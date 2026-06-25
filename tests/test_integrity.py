from helix_blockchain.collectors.integrity import (
    EntityObservation,
    IntegrityChecker,
    OrionGateway,
    RecordDeduper,
)
from helix_blockchain.domain.records import IntegrityRecord, Verdict


class FakeGateway:
    """In-memory OrionGateway: ``data[broker] = list[EntityObservation]``."""

    def __init__(self, main: str, data: dict[str, list[EntityObservation]]):
        self._main = main
        self._data = data

    def main_broker(self) -> str:
        return self._main

    def federated_brokers(self) -> list[str]:
        return [b for b in self._data if b != self._main]

    def observations(self, broker=None):
        return self._data.get(broker or self._main, [])


def obs(entity, attr, value, broker):
    return EntityObservation(entity_id=entity, attribute=attr, value=value, broker=broker)


def test_satisfies_gateway_protocol():
    gw = FakeGateway("main", {"main": []})
    assert isinstance(gw, OrionGateway)


def test_matching_value_is_ok():
    gw = FakeGateway(
        "main",
        {
            "main": [obs("S:1", "temperature", 21.5, "main")],
            "fed-a": [obs("S:1", "temperature", 21.5, "fed-a")],
        },
    )
    records = IntegrityChecker(gw, now_ms=lambda: 1000).check()
    assert len(records) == 1
    assert records[0].verdict is Verdict.OK
    assert records[0].source_broker == "fed-a"


def test_altered_value_is_tampered():
    gw = FakeGateway(
        "main",
        {
            "main": [obs("S:1", "temperature", 21.5, "main")],
            "fed-a": [obs("S:1", "temperature", 99.9, "fed-a")],  # altered
        },
    )
    records = IntegrityChecker(gw, now_ms=lambda: 1000).check()
    assert records[0].verdict is Verdict.TAMPERED


def test_injected_entity_is_tampered():
    gw = FakeGateway(
        "main",
        {
            "main": [obs("S:1", "temperature", 21.5, "main")],
            "fed-a": [obs("S:rogue", "temperature", 5.0, "fed-a")],  # not in main
        },
    )
    records = IntegrityChecker(gw, now_ms=lambda: 1000).check()
    assert records[0].entity_id == "S:rogue"
    assert records[0].verdict is Verdict.TAMPERED


def test_multiple_brokers_and_attrs():
    gw = FakeGateway(
        "main",
        {
            "main": [
                obs("S:1", "temperature", 21.5, "main"),
                obs("S:1", "humidity", 60, "main"),
            ],
            "fed-a": [obs("S:1", "temperature", 21.5, "fed-a")],
            "fed-b": [obs("S:1", "humidity", 61, "fed-b")],  # tampered
        },
    )
    records = IntegrityChecker(gw, now_ms=lambda: 1000).check()
    by_broker = {(r.source_broker, r.attribute): r.verdict for r in records}
    assert by_broker[("fed-a", "temperature")] is Verdict.OK
    assert by_broker[("fed-b", "humidity")] is Verdict.TAMPERED


def make_record(value_hash="h", verdict=Verdict.OK, ts=1000):
    return IntegrityRecord(
        entity_id="S:1",
        attribute="temperature",
        value_hash=value_hash,
        source_broker="fed-a",
        verdict=verdict,
        observed_at=ts,
    )


def test_deduper_suppresses_identical_observations():
    deduper = RecordDeduper()
    first = deduper.filter_new([make_record(ts=1000)])
    second = deduper.filter_new([make_record(ts=2000)])  # same content, later time
    assert len(first) == 1
    assert second == []  # duplicate content, suppressed


def test_deduper_passes_changed_value():
    deduper = RecordDeduper()
    deduper.filter_new([make_record(value_hash="h1")])
    changed = deduper.filter_new([make_record(value_hash="h2")])
    assert len(changed) == 1


def test_deduper_passes_changed_verdict():
    deduper = RecordDeduper()
    deduper.filter_new([make_record(verdict=Verdict.OK)])
    changed = deduper.filter_new([make_record(verdict=Verdict.TAMPERED)])
    assert len(changed) == 1
