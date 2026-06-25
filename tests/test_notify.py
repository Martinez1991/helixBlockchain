import logging

from helix_blockchain.domain.block import Block
from helix_blockchain.domain.records import IntegrityRecord, Verdict
from helix_blockchain.notify.notifier import ConsoleNotifier, Notifier


def record(verdict: Verdict, entity: str = "S:1") -> IntegrityRecord:
    return IntegrityRecord(
        entity_id=entity,
        attribute="temperature",
        value_hash="h",
        source_broker="fed-a",
        verdict=verdict,
        observed_at=1000,
    )


def test_satisfies_notifier_protocol():
    assert isinstance(ConsoleNotifier(), Notifier)


def test_alerts_only_for_tampered(caplog):
    block = Block.create(
        1, "0" * 64, 1000, "proposer",
        [record(Verdict.OK, "S:1"), record(Verdict.TAMPERED, "S:rogue")],
    )
    with caplog.at_level(logging.WARNING, logger="helix.alert"):
        ConsoleNotifier().block_committed(block)
    assert "S:rogue" in caplog.text
    assert "TAMPERING DETECTED" in caplog.text
    assert "S:1" not in caplog.text  # the OK record is not alerted


def test_no_alert_when_all_ok(caplog):
    block = Block.create(1, "0" * 64, 1000, "proposer", [record(Verdict.OK)])
    with caplog.at_level(logging.WARNING, logger="helix.alert"):
        ConsoleNotifier().block_committed(block)
    assert caplog.text == ""
