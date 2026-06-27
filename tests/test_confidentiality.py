"""Targeted confidentiality: keyed value commitments + entity pseudonymization."""

from __future__ import annotations

import hashlib

from helix_blockchain.collectors.integrity import (
    EntityObservation,
    IntegrityChecker,
)
from helix_blockchain.domain.canonical import canonical_bytes
from helix_blockchain.domain.confidentiality import Confidentiality
from helix_blockchain.domain.records import IntegrityRecord, Verdict

KEY = bytes.fromhex("ab" * 32)


# ── value commitment ───────────────────────────────────────────────────
def test_no_key_falls_back_to_plain_sha256():
    c = Confidentiality()
    assert c.enabled is False
    assert c.commit_value(21.5) == hashlib.sha256(canonical_bytes(21.5)).hexdigest()
    # ...and matches the domain's plain helper (backward compatible).
    assert c.commit_value(21.5) == IntegrityRecord.hash_value(21.5)


def test_keyed_commitment_differs_from_plain_and_hides_low_entropy():
    c = Confidentiality(KEY)
    assert c.enabled
    plain = IntegrityRecord.hash_value(True)
    keyed = c.commit_value(True)
    assert keyed != plain
    # A reader without the key cannot reproduce the commitment for a guessed value.
    assert hashlib.sha256(canonical_bytes(True)).hexdigest() != keyed


def test_commitment_is_deterministic_per_key():
    a, b = Confidentiality(KEY), Confidentiality(KEY)
    assert a.commit_value(42) == b.commit_value(42)  # validators agree


def test_different_keys_give_different_commitments():
    k2 = bytes.fromhex("cd" * 32)
    assert Confidentiality(KEY).commit_value(42) != Confidentiality(k2).commit_value(42)


# ── entity pseudonymization ────────────────────────────────────────────
def test_entity_raw_by_default():
    assert Confidentiality(KEY).entity_ref("Sensor:1") == "Sensor:1"  # flag off


def test_entity_pseudonymized_when_enabled():
    c = Confidentiality(KEY, pseudonymize_entities=True)
    ref = c.entity_ref("Sensor:1")
    assert ref.startswith("pid:") and "Sensor:1" not in ref
    assert ref == c.entity_ref("Sensor:1")  # deterministic
    assert ref != c.entity_ref("Sensor:2")  # distinct entities distinct


# ── integrity checker preserves detection under confidentiality ─────────
class FakeGateway:
    def __init__(self, data):
        self._data = data

    def main_broker(self):
        return "main"

    def federated_brokers(self):
        return [b for b in self._data if b != "main"]

    def observations(self, broker=None):
        return self._data.get(broker or "main", [])


def obs(e, a, v, b):
    return EntityObservation(entity_id=e, attribute=a, value=v, broker=b)


def test_checker_keys_value_and_pseudonymizes_but_still_detects():
    gw = FakeGateway({
        "main": [obs("S:1", "t", 21.5, "main")],
        "fed-a": [obs("S:1", "t", 99.9, "fed-a")],  # tampered
    })
    conf = Confidentiality(KEY, pseudonymize_entities=True)
    recs = IntegrityChecker(gw, now_ms=lambda: 1, confidentiality=conf).check()
    assert len(recs) == 1
    r = recs[0]
    # Detection still works on raw values:
    assert r.verdict is Verdict.TAMPERED
    # ...but stored fields are confidential:
    assert r.entity_id.startswith("pid:")
    assert r.value_hash == conf.commit_value(99.9)
    assert r.value_hash != IntegrityRecord.hash_value(99.9)


def test_checker_without_key_is_unchanged():
    gw = FakeGateway({
        "main": [obs("S:1", "t", 21.5, "main")],
        "fed-a": [obs("S:1", "t", 21.5, "fed-a")],
    })
    recs = IntegrityChecker(gw, now_ms=lambda: 1).check()
    assert recs[0].entity_id == "S:1"
    assert recs[0].value_hash == IntegrityRecord.hash_value(21.5)
    assert recs[0].verdict is Verdict.OK
