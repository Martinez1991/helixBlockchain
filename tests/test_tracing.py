"""OpenTelemetry tracing of the consensus path (#11)."""

from __future__ import annotations

import asyncio

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from helix_blockchain import tracing
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.domain.records import IntegrityRecord, Verdict
from helix_blockchain.network.node import Node
from helix_blockchain.storage.sql import SqlBlockRepository


class NullTransport:
    async def broadcast(self, m): ...
    async def fetch_block(self, i): return None
    async def gossip_records(self, r): ...
    async def gossip_changes(self, c): ...
    async def gossip_block(self, b): ...
    async def fetch_peers(self): return []
    async def announce(self, s): ...


@pytest.fixture
def exporter(monkeypatch):
    provider = TracerProvider()
    exp = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    # Point the module tracer at our in-memory provider for the test.
    monkeypatch.setattr(tracing, "_TRACER", provider.get_tracer("test"))
    return exp


def test_tracer_is_noop_without_sdk_configuration():
    # The default module tracer never raises even with no SDK provider set.
    with tracing.tracer().start_as_current_span("x") as span:
        span.set_attribute("k", "v")  # no exception


def test_on_message_emits_span(exporter):
    key = PrivateKey.generate()
    node = Node(
        node_id="n", private_key=key, validators=ValidatorSet([key.public]),
        repo=SqlBlockRepository("sqlite:///:memory:"), transport=NullTransport(),
        now_ms=lambda: 1,
    )
    from helix_blockchain.consensus.messages import ConsensusMessage, MessageType

    msg = ConsensusMessage.create(
        type=MessageType.PREPARE, height=1, round=0, block_hash="ab" * 32, signer=key,
    )
    asyncio.run(node.on_message(msg))

    spans = exporter.get_finished_spans()
    handle = [s for s in spans if s.name == "consensus.handle"]
    assert handle, "no consensus.handle span recorded"
    attrs = handle[0].attributes
    assert attrs["helix.msg_type"] == "PREPARE"
    assert attrs["helix.height"] == 1


def test_commit_adds_block_committed_event(exporter):
    key = PrivateKey.generate()
    node = Node(
        node_id="n", private_key=key, validators=ValidatorSet([key.public]),
        repo=SqlBlockRepository("sqlite:///:memory:"), transport=NullTransport(),
        now_ms=lambda: 1,
    )
    rec = IntegrityRecord(
        entity_id="S:1", attribute="t", value_hash=IntegrityRecord.hash_value(1),
        source_broker="b", verdict=Verdict.OK, observed_at=1,
    )

    # Wrap the commit-driving call in a span so the commit event has a parent.
    async def drive():
        with tracing.tracer().start_as_current_span("submit"):
            await node.submit_records([rec])

    asyncio.run(drive())

    events = [e for s in exporter.get_finished_spans() for e in s.events]
    assert any(e.name == "block.committed" for e in events)
