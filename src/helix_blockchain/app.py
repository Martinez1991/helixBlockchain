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

from helix_blockchain import tracing
from helix_blockchain.clock import now_ms
from helix_blockchain.collectors.integrity import IntegrityChecker, RecordDeduper
from helix_blockchain.collectors.orion import MongoOrionGateway
from helix_blockchain.config import Peer, Settings, load_settings
from helix_blockchain.consensus.journal import SqlConsensusJournalStore
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.network.discovery import PeerRegistry
from helix_blockchain.network.node import Node
from helix_blockchain.network.server import create_app
from helix_blockchain.network.transport import HttpTransport
from helix_blockchain.notify.notifier import (
    CompositeNotifier,
    ConsoleNotifier,
    WebhookNotifier,
)
from helix_blockchain.storage.sql import SqlBlockRepository
from helix_blockchain.tls import uvicorn_ssl_kwargs

log = logging.getLogger("helix.app")


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def _advertise_peer(settings: Settings, private_key: PrivateKey) -> Peer | None:
    """This node's own peer entry from HELIX_CONSENSUS__ADVERTISE, for discovery."""
    advertise = settings.consensus.advertise
    if not advertise:
        return None
    host, port = advertise.rsplit(":", 1)
    return Peer(
        node_id=settings.node.node_id,
        host=host,
        port=int(port),
        public_key=private_key.public,
    )


def build_node(settings: Settings) -> tuple[Node, HttpTransport, WebhookNotifier | None]:
    private_key_hex = settings.resolved_private_key_hex()
    if not private_key_hex:
        raise SystemExit(
            "No private key configured. Set HELIX_NODE__PRIVATE_KEY_HEX or "
            "HELIX_NODE__PRIVATE_KEY_FILE (Docker/k8s/Vault secret). "
            "Generate one with: python -m helix_blockchain.tools.keygen"
        )
    private_key = PrivateKey.from_hex(private_key_hex)
    cluster_token = settings.resolved_cluster_token()
    # Dedup by public key so a peer list that includes this node (common in k8s,
    # where every pod gets the same full list) is tolerated.
    keys = {private_key.public.to_hex(): private_key.public}
    for p in settings.consensus.peers:
        keys[p.public_key.to_hex()] = p.public_key
    validators = ValidatorSet(list(keys.values()))
    registry = PeerRegistry(
        private_key.public.to_hex(),
        self_peer=_advertise_peer(settings, private_key),
    )
    registry.seed(settings.consensus.peers)
    repo = SqlBlockRepository(settings.storage.url)
    journal_store = SqlConsensusJournalStore(settings.storage.url)
    transport = HttpTransport(
        registry,
        cluster_token=cluster_token,
        tls=settings.tls,
    )
    notifiers: list = [ConsoleNotifier()]
    webhook = None
    if settings.notify.webhook_url:
        webhook = WebhookNotifier(settings.notify.webhook_url)
        notifiers.append(webhook)
    notifier = CompositeNotifier(notifiers)
    node = Node(
        node_id=settings.node.node_id,
        private_key=private_key,
        validators=validators,
        repo=repo,
        transport=transport,
        now_ms=now_ms,
        on_commit=notifier.block_committed,
        peer_registry=registry,
        journal_store=journal_store,
        max_inbox=settings.consensus.max_inbox,
    )
    log.info(
        "node %s ready: %d validators, quorum %d, tip height %d",
        settings.node.node_id, validators.size, validators.quorum, node.height,
    )
    return node, transport, webhook


async def monitor_loop(node: Node, settings: Settings) -> None:
    """Detect tampering and feed records into consensus.

    Uses Mongo Change Streams (event-driven, low latency, no idle scans) when
    ``use_change_streams`` is set, otherwise timed polling."""
    gateway = MongoOrionGateway(settings.orion)
    checker = IntegrityChecker(gateway, now_ms=now_ms)
    deduper = RecordDeduper()
    try:
        await asyncio.to_thread(gateway.ensure_indexes)
    except Exception:  # noqa: BLE001 — indexing is best-effort
        log.exception("could not ensure Orion indexes")

    async def run_check() -> None:
        records = await asyncio.to_thread(checker.check)
        fresh = deduper.filter_new(records)
        if fresh:
            log.info("submitting %d new integrity record(s)", len(fresh))
            await node.submit_records(fresh)
        await node.tick()

    if settings.orion.use_change_streams:
        await _change_stream_loop(gateway, run_check)
    else:
        await _polling_loop(run_check, settings.orion.poll_interval)


async def _polling_loop(run_check, interval: float) -> None:
    while True:
        try:
            await run_check()
        except Exception:  # noqa: BLE001 — keep the loop alive on transient errors
            log.exception("monitor poll failed")
        await asyncio.sleep(interval)


async def _change_stream_loop(gateway: MongoOrionGateway, run_check) -> None:
    """Re-verify integrity whenever the entities collection changes."""
    queue: asyncio.Queue[bool] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def watch() -> None:  # runs in a worker thread (blocking cursor)
        try:
            for _change in gateway.watch_entities():
                loop.call_soon_threadsafe(queue.put_nowait, True)
        except Exception:  # noqa: BLE001
            log.exception("change stream ended; falling back to a final check")
            loop.call_soon_threadsafe(queue.put_nowait, True)

    watcher = asyncio.create_task(asyncio.to_thread(watch))
    await run_check()  # initial baseline
    try:
        while True:
            await queue.get()
            try:
                await run_check()
            except Exception:  # noqa: BLE001
                log.exception("monitor change check failed")
    finally:
        watcher.cancel()


async def run(settings: Settings) -> None:
    node, transport, webhook = build_node(settings)
    api = create_app(
        node, debug_api=settings.debug_api,
        cluster_token=settings.resolved_cluster_token(),
        rate_limit_rps=settings.consensus.rate_limit_rps,
        rate_limit_burst=settings.consensus.rate_limit_burst,
        max_body_bytes=settings.consensus.max_body_bytes,
    )
    config = uvicorn.Config(
        api,
        host=settings.consensus.bind_host,
        port=settings.consensus.bind_port,
        log_level=settings.log_level.lower(),
        **uvicorn_ssl_kwargs(settings.tls),
    )
    server = uvicorn.Server(config)
    # Round-change fires if a height stalls for ~3x the block interval.
    round_timeout = max(2.0, settings.consensus.block_interval * 3)
    tasks = [
        server.serve(),
        node.inbound_worker(),
        monitor_loop(node, settings),
        node.round_timer_loop(round_timeout),
        node.discovery_loop(max(5.0, settings.consensus.block_interval * 2)),
    ]
    if webhook is not None:
        tasks.append(webhook.run())
    try:
        await asyncio.gather(*tasks)
    finally:
        await transport.aclose()


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    tracing.configure(
        enabled=settings.otel.enabled,
        endpoint=settings.otel.endpoint,
        service_name=settings.otel.service_name,
    )
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
