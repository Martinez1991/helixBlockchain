"""MongoDB-backed :class:`OrionGateway` for FIWARE Orion.

FIWARE Orion stores context in MongoDB. Relevant collections:

* ``entities`` — one document per entity; ``_id.id`` is the entity id and
  ``attrs`` maps attribute name -> ``{"value": ..., "type": ..., ...}``.
* ``csubs`` — subscriptions; ``reference`` holds the notification URL of a
  federated broker (e.g. ``http://10.0.0.5:1026/v2/op/notify``), from which we
  derive the federated broker hosts.

This module performs network/database I/O and is therefore not unit-tested in
isolation; the comparison logic it feeds lives in the pure
:class:`~helix_blockchain.collectors.integrity.IntegrityChecker`.
"""

from __future__ import annotations

from urllib.parse import urlparse

from pymongo import MongoClient

from helix_blockchain.collectors.integrity import EntityObservation
from helix_blockchain.config import OrionSettings


class MongoOrionGateway:
    """Reads entity/subscription data from Orion's MongoDB, main + federated."""

    def __init__(self, settings: OrionSettings) -> None:
        self._settings = settings
        self._clients: dict[str, MongoClient] = {}

    # ── connection management ──────────────────────────────────────────
    def _client_for(self, host: str) -> MongoClient:
        if host not in self._clients:
            kwargs: dict = {"tls": self._settings.tls, "serverSelectionTimeoutMS": 3000}
            if self._settings.tls and self._settings.tls_ca_file:
                kwargs["tlsCAFile"] = self._settings.tls_ca_file
            # Only authenticate when credentials are configured; the demo Mongo
            # runs without auth, and passing empty credentials would fail SCRAM.
            if self._settings.password:
                kwargs["username"] = self._settings.username
                kwargs["password"] = self._settings.password
            self._clients[host] = MongoClient(host, self._settings.port, **kwargs)
        return self._clients[host]

    def _entities_collection(self, host: str):
        return self._client_for(host)[self._settings.database]["entities"]

    def _csubs_collection(self, host: str):
        return self._client_for(host)[self._settings.database]["csubs"]

    # ── OrionGateway protocol ──────────────────────────────────────────
    def main_broker(self) -> str:
        return self._settings.host

    def federated_brokers(self) -> list[str]:
        refs = self._csubs_collection(self.main_broker()).distinct("reference")
        hosts: list[str] = []
        for ref in refs:
            host = self._host_from_reference(str(ref))
            if host and host != self.main_broker() and host not in hosts:
                hosts.append(host)
        return hosts

    def observations(self, broker: str | None = None) -> list[EntityObservation]:
        host = broker or self.main_broker()
        collection = self._entities_collection(host)
        observations: list[EntityObservation] = []
        for doc in collection.find():
            entity_id = self._entity_id(doc)
            if entity_id is None:
                continue
            for attr_name, attr_body in (doc.get("attrs") or {}).items():
                value = attr_body.get("value") if isinstance(attr_body, dict) else attr_body
                observations.append(
                    EntityObservation(
                        entity_id=entity_id,
                        attribute=attr_name,
                        value=value,
                        broker=host,
                    )
                )
        return observations

    def ensure_indexes(self) -> None:
        """Create helpful indexes on the watched collections (idempotent).

        ``entities._id.id`` and ``csubs.reference`` back the lookups done every
        cycle; without them large brokers force collection scans."""
        entities = self._entities_collection(self.main_broker())
        csubs = self._csubs_collection(self.main_broker())
        entities.create_index("_id.id", name="helix_entity_id")
        csubs.create_index("reference", name="helix_csub_reference")

    def watch_entities(self, broker: str | None = None):
        """Yield change events for the entities collection via a Mongo Change
        Stream (requires a replica set). Each event signals which entity changed,
        so the checker can re-verify just that entity instead of full-scanning.

        Returns the pymongo change-stream cursor (an iterator of change docs)."""
        host = broker or self.main_broker()
        return self._entities_collection(host).watch(
            full_document="updateLookup"
        )

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
        self._clients.clear()

    # ── parsing helpers ────────────────────────────────────────────────
    @staticmethod
    def _entity_id(doc: dict) -> str | None:
        raw_id = doc.get("_id")
        if isinstance(raw_id, dict):
            return raw_id.get("id")
        return None

    @staticmethod
    def entity_id_from_change(change: dict) -> str | None:
        """Extract the changed entity id from a Mongo change-stream document.

        Orion entity ids live under ``documentKey._id.id`` (or, for full-document
        events, ``fullDocument._id.id``)."""
        key = change.get("documentKey") or {}
        raw = key.get("_id")
        if isinstance(raw, dict) and raw.get("id"):
            return raw["id"]
        full = change.get("fullDocument") or {}
        raw = full.get("_id")
        if isinstance(raw, dict):
            return raw.get("id")
        return None

    @staticmethod
    def _host_from_reference(reference: str) -> str | None:
        """Extract the host from a subscription ``reference`` URL."""
        parsed = urlparse(reference)
        if parsed.hostname:
            return parsed.hostname
        # Fallback for bare ``host:port/...`` forms without a scheme.
        return urlparse(f"//{reference}").hostname
