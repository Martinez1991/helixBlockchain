"""Notify operators when a committed block records tampering.

The original TCC printed ``"Divice X foi adulterado"`` to the prompt. Here the
same alert fires only for records that are *finalized by consensus*, so an alert
reflects agreement across the validator set rather than one node's view.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Protocol, runtime_checkable

import httpx

from helix_blockchain.domain.block import Block
from helix_blockchain.domain.records import IntegrityRecord, Verdict

log = logging.getLogger("helix.alert")


def _tampered(block: Block) -> list[IntegrityRecord]:
    return [r for r in block.records if r.verdict is Verdict.TAMPERED]


@runtime_checkable
class Notifier(Protocol):
    def block_committed(self, block: Block) -> None:
        """Called with each finalized block; implementations surface tampering."""


class ConsoleNotifier:
    """Prints a prominent alert for every tampered record in a block."""

    def block_committed(self, block: Block) -> None:
        for record in _tampered(block):
            banner = (
                f"\n{'~' * 60}\n"
                f"  TAMPERING DETECTED — block #{block.index}\n"
                f"  device  : {record.entity_id}\n"
                f"  attribute: {record.attribute}\n"
                f"  broker  : {record.source_broker}\n"
                f"  observed: {record.observed_at}\n"
                f"{'~' * 60}"
            )
            log.warning(banner)

    def __call__(self, block: Block) -> None:  # convenience as a commit hook
        self.block_committed(block)


class CompositeNotifier:
    """Fans a commit out to several notifiers."""

    def __init__(self, notifiers: list[Notifier]) -> None:
        self._notifiers = notifiers

    def block_committed(self, block: Block) -> None:
        for n in self._notifiers:
            with contextlib.suppress(Exception):
                n.block_committed(block)


class WebhookNotifier:
    """Posts tampering alerts to a webhook (Slack-compatible / generic SIEM).

    ``block_committed`` runs inside the node's lock, so it only *enqueues*; the
    :meth:`run` task drains the queue and performs the HTTP POST off the hot path.
    The payload carries both a Slack-style ``text`` and structured fields so it
    fits Slack incoming webhooks and SIEM ingestion alike."""

    def __init__(self, url: str, *, maxsize: int = 1000) -> None:
        self.url = url
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)

    def block_committed(self, block: Block) -> None:
        tampered = _tampered(block)
        if not tampered:
            return
        with contextlib.suppress(asyncio.QueueFull):
            self._queue.put_nowait(self._payload(block, tampered))

    @staticmethod
    def _payload(block: Block, tampered: list[IntegrityRecord]) -> dict[str, Any]:
        devices = ", ".join(sorted({r.entity_id for r in tampered}))
        return {
            "text": (
                f":rotating_light: Helix: tampering detected in block "
                f"#{block.index} — device(s): {devices}"
            ),
            "event": "tampering_detected",
            "severity": "critical",
            "block_index": block.index,
            "block_hash": block.hash,
            "records": [
                {
                    "entity_id": r.entity_id,
                    "attribute": r.attribute,
                    "source_broker": r.source_broker,
                    "observed_at": r.observed_at,
                }
                for r in tampered
            ],
        }

    async def run(self, client: httpx.AsyncClient | None = None) -> None:
        """Drain the queue, POSTing each alert. Runs as a background task."""
        owns = client is None
        client = client or httpx.AsyncClient(timeout=5.0)
        try:
            while True:
                payload = await self._queue.get()
                with contextlib.suppress(httpx.HTTPError):
                    await client.post(self.url, json=payload)
        finally:
            if owns:
                await client.aclose()

    def pending(self) -> asyncio.Queue[dict[str, Any]]:
        return self._queue
