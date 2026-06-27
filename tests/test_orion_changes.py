"""Event-driven Orion collection: change extraction + index creation (#7)."""

from __future__ import annotations

from helix_blockchain.collectors.orion import MongoOrionGateway
from helix_blockchain.config import OrionSettings


def test_entity_id_from_documentkey():
    change = {"operationType": "update", "documentKey": {"_id": {"id": "Sensor:1"}}}
    assert MongoOrionGateway.entity_id_from_change(change) == "Sensor:1"


def test_entity_id_from_full_document():
    change = {"operationType": "insert", "fullDocument": {"_id": {"id": "Sensor:2"}}}
    assert MongoOrionGateway.entity_id_from_change(change) == "Sensor:2"


def test_entity_id_missing_returns_none():
    assert MongoOrionGateway.entity_id_from_change({"operationType": "drop"}) is None


# ── ensure_indexes against a fake collection ───────────────────────────
class _FakeCollection:
    def __init__(self):
        self.indexes = []

    def create_index(self, key, name=None):
        self.indexes.append((key, name))


class _FakeGateway(MongoOrionGateway):
    def __init__(self):
        self.entities = _FakeCollection()
        self.csubs = _FakeCollection()
        self._settings = OrionSettings(host="main")

    def _entities_collection(self, host):
        return self.entities

    def _csubs_collection(self, host):
        return self.csubs


def test_ensure_indexes_creates_expected_indexes():
    gw = _FakeGateway()
    gw.ensure_indexes()
    assert ("_id.id", "helix_entity_id") in gw.entities.indexes
    assert ("reference", "helix_csub_reference") in gw.csubs.indexes


def test_use_change_streams_flag_defaults_off():
    assert OrionSettings().use_change_streams is False
    assert OrionSettings(use_change_streams=True).use_change_streams is True
