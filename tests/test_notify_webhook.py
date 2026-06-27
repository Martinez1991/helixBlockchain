"""Webhook/SIEM tamper notification + composite fan-out (#12)."""

from __future__ import annotations

import asyncio

import httpx

from helix_blockchain.domain.block import Block
from helix_blockchain.domain.records import IntegrityRecord, Verdict
from helix_blockchain.notify.notifier import (
    CompositeNotifier,
    WebhookNotifier,
)


def record(entity: str, verdict: Verdict) -> IntegrityRecord:
    return IntegrityRecord(
        entity_id=entity, attribute="temperature",
        value_hash=IntegrityRecord.hash_value(1), source_broker="fed-a",
        verdict=verdict, observed_at=1000,
    )


def block_with(*verdicts_entities) -> Block:
    recs = [record(e, v) for e, v in verdicts_entities]
    return Block.create(7, "0" * 64, 1000, "proposer", recs)


def test_webhook_enqueues_only_for_tampering():
    wh = WebhookNotifier("http://hook")
    wh.block_committed(block_with(("S:1", Verdict.OK)))
    assert wh.pending().qsize() == 0
    wh.block_committed(block_with(("S:bad", Verdict.TAMPERED)))
    assert wh.pending().qsize() == 1


def test_webhook_payload_shape():
    wh = WebhookNotifier("http://hook")
    wh.block_committed(block_with(("S:bad", Verdict.TAMPERED), ("S:ok", Verdict.OK)))
    payload = wh.pending().get_nowait()
    assert payload["event"] == "tampering_detected"
    assert payload["block_index"] == 7
    assert "S:bad" in payload["text"]
    assert [r["entity_id"] for r in payload["records"]] == ["S:bad"]


def test_webhook_run_posts_payload():
    posted = []

    async def handler(request: httpx.Request) -> httpx.Response:
        posted.append(httpx.Response(200, request=request))
        import json
        posted[-1] = json.loads(request.content)
        return httpx.Response(200)

    async def drive():
        wh = WebhookNotifier("http://hook")
        wh.block_committed(block_with(("S:bad", Verdict.TAMPERED)))
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            task = asyncio.create_task(wh.run(client))
            await asyncio.sleep(0.05)  # let the worker drain
            task.cancel()

    asyncio.run(drive())
    assert posted and posted[0]["event"] == "tampering_detected"


def test_composite_fans_out_and_isolates_failures():
    seen = []

    class Good:
        def block_committed(self, block):
            seen.append(block.index)

    class Bad:
        def block_committed(self, block):
            raise RuntimeError("boom")

    comp = CompositeNotifier([Bad(), Good()])
    comp.block_committed(block_with(("S:bad", Verdict.TAMPERED)))
    assert seen == [7]  # Good ran despite Bad raising
