"""FastAPI HTTP server exposing a node's P2P and read endpoints.

Endpoints:

* ``POST /consensus`` — receive a consensus message from a peer.
* ``POST /mempool`` — receive integrity records gossiped by a peer.
* ``POST /block`` — receive a finalized block pushed by a peer.
* ``GET  /blocks/{index}`` — serve a finalized block (used for catch-up sync).
* ``GET  /chain`` — chain height + latest hash.
* ``GET  /health`` — liveness probe.
* ``POST /admin/submit`` — (debug only) inject synthetic integrity records to
  drive a consensus round without a live FIWARE federation.

The mutating peer-to-peer endpoints (``/consensus``, ``/mempool``, ``/block``)
and ``/admin/submit`` are guarded by a shared bearer token when ``cluster_token``
is configured. Read endpoints stay open (blocks are self-verifying via their
finality certificates). ``/mempool`` is the main reason auth matters: gossiped
records are not individually signed, so an unauthenticated peer could otherwise
inject bogus tampering reports.
"""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException

from helix_blockchain.consensus.messages import ConsensusMessage
from helix_blockchain.domain.block import Block
from helix_blockchain.domain.records import IntegrityRecord, Verdict
from helix_blockchain.network.node import Node


def create_app(
    node: Node, *, debug_api: bool = False, cluster_token: str = ""
) -> FastAPI:
    app = FastAPI(title="Helix Blockchain Node", version="0.2.0")

    async def require_token(authorization: str = Header(default="")) -> None:
        if not cluster_token:
            return  # auth disabled
        expected = f"Bearer {cluster_token}"
        # Constant-time comparison avoids leaking the token via timing.
        if not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="invalid or missing token")

    auth = [Depends(require_token)]

    @app.post("/consensus", dependencies=auth)
    async def consensus(payload: dict[str, Any]) -> dict[str, str]:
        try:
            message = ConsensusMessage.from_dict(payload)
        except (KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail=f"malformed message: {exc}"
            ) from exc
        # Queue and return immediately so the sender's broadcast never blocks on
        # our processing (avoids re-entrant consensus deadlock).
        node.enqueue_inbound(message)
        return {"status": "accepted"}

    @app.post("/mempool", dependencies=auth)
    async def mempool(payload: dict[str, Any]) -> dict[str, str]:
        try:
            records = [IntegrityRecord.from_dict(r) for r in payload["records"]]
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"malformed records: {exc}"
            ) from exc
        await node.receive_records(records)
        return {"status": "accepted"}

    @app.post("/block", dependencies=auth)
    async def push_block(payload: dict[str, Any]) -> dict[str, str]:
        try:
            block = Block.from_dict(payload)
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"malformed block: {exc}"
            ) from exc
        await node.ingest_block(block)
        return {"status": "accepted"}

    @app.get("/blocks/{index}")
    async def get_block(index: int) -> dict[str, Any]:
        block = node.repo.get(index)
        if block is None:
            raise HTTPException(status_code=404, detail="block not found")
        return block.to_dict()

    @app.get("/chain")
    async def chain() -> dict[str, Any]:
        latest = node.repo.latest()
        return {
            "node_id": node.node_id,
            "height": node.height,
            "latest_hash": latest.hash if latest else None,
            "validators": node.validators.size,
            "quorum": node.validators.quorum,
        }

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    if debug_api:

        @app.post("/admin/submit", dependencies=auth)
        async def admin_submit(count: int = 1) -> dict[str, Any]:
            """Inject ``count`` synthetic integrity records (testing hook)."""
            ts = node.now_ms()
            records = [
                IntegrityRecord(
                    entity_id=f"Demo:{ts}:{i}",
                    attribute="temperature",
                    value_hash=IntegrityRecord.hash_value(20 + i),
                    source_broker="demo",
                    verdict=Verdict.OK,
                    observed_at=ts,
                )
                for i in range(count)
            ]
            await node.submit_records(records)
            return {"submitted": count, "height": node.height}

    return app
