"""FastAPI HTTP server exposing a node's P2P and read endpoints.

Endpoints:

* ``POST /consensus`` — receive a consensus message from a peer.
* ``GET  /blocks/{index}`` — serve a finalized block (used for catch-up sync).
* ``GET  /chain`` — chain height + latest hash.
* ``GET  /health`` — liveness probe.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from helix_blockchain.consensus.messages import ConsensusMessage
from helix_blockchain.network.node import Node


def create_app(node: Node) -> FastAPI:
    app = FastAPI(title="Helix Blockchain Node", version="0.2.0")

    @app.post("/consensus")
    async def consensus(payload: dict[str, Any]) -> dict[str, str]:
        try:
            message = ConsensusMessage.from_dict(payload)
        except (KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail=f"malformed message: {exc}"
            ) from exc
        await node.on_message(message)
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

    return app
