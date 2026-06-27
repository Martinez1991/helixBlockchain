"""FastAPI HTTP server exposing a node's P2P and read endpoints.

Endpoints:

* ``POST /consensus`` — receive a consensus message from a peer.
* ``POST /mempool`` — receive integrity records gossiped by a peer.
* ``POST /membership`` — receive validator-set changes gossiped by a peer.
* ``POST /block`` — receive a finalized block pushed by a peer.
* ``GET  /peers`` / ``POST /peers`` — exchange the peer registry (discovery).
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
import logging
from importlib import resources
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from helix_blockchain import metrics
from helix_blockchain.config import Peer
from helix_blockchain.consensus.messages import ConsensusMessage
from helix_blockchain.domain.block import Block
from helix_blockchain.domain.membership import ValidatorChange
from helix_blockchain.domain.records import IntegrityRecord, Verdict
from helix_blockchain.network.node import Node
from helix_blockchain.network.ratelimit import RateLimiter

audit_log = logging.getLogger("helix.audit")

# Mutating endpoints subject to rate limiting and body-size limits.
_PROTECTED_PREFIXES = ("/consensus", "/mempool", "/membership", "/block", "/peers", "/admin")


def create_app(
    node: Node,
    *,
    debug_api: bool = False,
    cluster_token: str = "",
    rate_limit_rps: float = 0.0,
    rate_limit_burst: int = 200,
    max_body_bytes: int = 1_048_576,
) -> FastAPI:
    app = FastAPI(title="Helix Blockchain Node", version="0.3.0")
    limiter = RateLimiter(rate_limit_rps, rate_limit_burst)

    # The read-only web console (/ui) polls sibling nodes from the browser, so
    # allow cross-origin GETs (read endpoints are already public; mutating ones
    # remain token-protected — CORS does not bypass auth).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        client = request.client.host if request.client else "unknown"
        if request.method == "POST" and request.url.path.startswith(_PROTECTED_PREFIXES):
            length = request.headers.get("content-length")
            if length is not None and int(length) > max_body_bytes:
                return JSONResponse({"detail": "payload too large"}, status_code=413)
            if not limiter.allow(client):
                return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
        response = await call_next(request)
        # Access audit trail (ISO 27001 A.12.4 / LGPD accountability): who did
        # what, when, with what outcome. Ship this logger to your SIEM.
        if request.url.path.startswith(_PROTECTED_PREFIXES):
            audit_log.info(
                "access method=%s path=%s client=%s authenticated=%s status=%s",
                request.method, request.url.path, client,
                bool(request.headers.get("authorization")), response.status_code,
            )
        return response

    accepted = [t.strip() for t in cluster_token.split(",") if t.strip()]

    async def require_token(authorization: str = Header(default="")) -> None:
        if not accepted:
            return  # auth disabled
        # Constant-time comparison against each accepted token (supports rotation).
        if not any(
            hmac.compare_digest(authorization, f"Bearer {t}") for t in accepted
        ):
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
        if not node.enqueue_inbound(message):
            raise HTTPException(status_code=503, detail="inbox full, retry later")
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

    @app.post("/membership", dependencies=auth)
    async def membership(payload: dict[str, Any]) -> dict[str, str]:
        try:
            changes = [ValidatorChange.from_dict(c) for c in payload["changes"]]
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"malformed changes: {exc}"
            ) from exc
        await node.receive_validator_changes(changes)
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

    @app.get("/peers", dependencies=auth)
    async def get_peers() -> dict[str, Any]:
        return {"peers": node.peer_registry.specs()}

    @app.post("/peers", dependencies=auth)
    async def post_peers(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            peers = [Peer.parse(s) for s in payload["peers"]]
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"malformed peers: {exc}"
            ) from exc
        added = node.peer_registry.merge(peers)
        return {"added": added}

    @app.get("/blocks/{index}")
    async def get_block(index: int) -> dict[str, Any]:
        block = node.repo.get(index)
        if block is None:
            raise HTTPException(status_code=404, detail="block not found")
        return block.to_dict()

    @app.get("/proof/{height}/{index}")
    async def inclusion_proof(height: int, index: int) -> dict[str, Any]:
        """Merkle inclusion proof that ``records[index]`` is in finalized block
        ``height`` — verifiable offline against the block's Merkle root."""
        block = node.repo.get(height)
        if block is None:
            raise HTTPException(status_code=404, detail="block not found")
        if not 0 <= index < len(block.records):
            raise HTTPException(status_code=404, detail="record index out of range")
        steps = block.proof_for_record(index)
        return {
            "height": height,
            "index": index,
            "merkle_root": block.header.merkle_root,
            "block_hash": block.hash,
            "record": block.records[index].to_dict(),
            "proof": [
                {"sibling": s.sibling.hex(), "right": s.sibling_on_right}
                for s in steps
            ],
        }

    @app.get("/chain")
    async def chain() -> dict[str, Any]:
        latest = node.repo.latest()
        return {
            "node_id": node.node_id,
            "height": node.height,
            "round": node.round,
            "latest_hash": latest.hash if latest else None,
            "validators": node.validators.size,
            "quorum": node.validators.quorum,
            "is_validator": node.is_validator,
            "validator_keys": [v.to_hex() for v in node.validators],
        }

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ui", response_class=HTMLResponse)
    async def ui() -> str:
        """Read-only web console: cluster board, block explorer, tampering feed
        and in-browser Merkle proof verifier."""
        return resources.files("helix_blockchain.static").joinpath("index.html").read_text(
            encoding="utf-8"
        )

    @app.get("/metrics")
    async def prometheus_metrics() -> Response:
        body, content_type = metrics.render()
        return Response(content=body, media_type=content_type)

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

        @app.post("/admin/validator", dependencies=auth)
        async def admin_validator(payload: dict[str, Any]) -> dict[str, Any]:
            """Queue a validator add/remove (testing/ops hook)."""
            try:
                change = ValidatorChange.from_dict(payload)
            except (KeyError, ValueError) as exc:
                raise HTTPException(
                    status_code=400, detail=f"malformed change: {exc}"
                ) from exc
            await node.submit_validator_change(change)
            return {"queued": change.to_dict(), "height": node.height}

    return app
