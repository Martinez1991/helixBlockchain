"""Application entrypoint: wire config -> node -> server + monitoring loop.

Run with ``helix-node`` (see ``[project.scripts]``) or
``python -m helix_blockchain.app``. Each process is one BFT validator that:

1. serves the P2P/read HTTP API (:mod:`helix_blockchain.network.server`),
2. polls FIWARE Orion for tampering and submits integrity records, and
3. participates in consensus to finalize them into the shared chain.
"""

from __future__ import annotations

import asyncio
import logging

import uvicorn

from helix_blockchain.clock import now_ms
from helix_blockchain.collectors.integrity import IntegrityChecker, RecordDeduper
from helix_blockchain.collectors.orion import MongoOrionGateway
from helix_blockchain.config import Settings, load_settings
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.network.node import Node
from helix_blockchain.network.server import create_app
from helix_blockchain.network.transport import HttpTransport
from helix_blockchain.notify.notifier import ConsoleNotifier
from helix_blockchain.storage.sql import SqlBlockRepository

log = logging.getLogger("helix.app")


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def build_node(settings: Settings) -> tuple[Node, HttpTransport]:
    if not settings.node.private_key_hex:
        raise SystemExit(
            "HELIX_NODE__PRIVATE_KEY_HEX is not set. "
            "Generate one with: python -m helix_blockchain.tools.keygen"
        )
    private_key = PrivateKey.from_hex(settings.node.private_key_hex)
    validators = ValidatorSet(
        [private_key.public, *(p.public_key for p in settings.consensus.peers)]
    )
    repo = SqlBlockRepository(settings.storage.url)
    transport = HttpTransport(settings.consensus.peers)
    notifier = ConsoleNotifier()
    node = Node(
        node_id=settings.node.node_id,
        private_key=private_key,
        validators=validators,
        repo=repo,
        transport=transport,
        now_ms=now_ms,
        on_commit=notifier.block_committed,
    )
    log.info(
        "node %s ready: %d validators, quorum %d, tip height %d",
        settings.node.node_id, validators.size, validators.quorum, node.height,
    )
    return node, transport


async def monitor_loop(node: Node, settings: Settings) -> None:
    """Poll Orion, detect tampering and feed records into consensus."""
    gateway = MongoOrionGateway(settings.orion)
    checker = IntegrityChecker(gateway, now_ms=now_ms)
    deduper = RecordDeduper()
    interval = settings.orion.poll_interval
    while True:
        try:
            records = await asyncio.to_thread(checker.check)
            fresh = deduper.filter_new(records)
            if fresh:
                log.info("submitting %d new integrity record(s)", len(fresh))
                await node.submit_records(fresh)
            await node.tick()
        except Exception:  # noqa: BLE001 — keep the loop alive on transient errors
            log.exception("monitor loop iteration failed")
        await asyncio.sleep(interval)


async def run(settings: Settings) -> None:
    node, transport = build_node(settings)
    api = create_app(node, debug_api=settings.debug_api)
    config = uvicorn.Config(
        api,
        host=settings.consensus.bind_host,
        port=settings.consensus.bind_port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    # Round-change fires if a height stalls for ~3x the block interval.
    round_timeout = max(2.0, settings.consensus.block_interval * 3)
    try:
        await asyncio.gather(
            server.serve(),
            node.inbound_worker(),
            monitor_loop(node, settings),
            node.round_timer_loop(round_timeout),
        )
    finally:
        await transport.aclose()


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
