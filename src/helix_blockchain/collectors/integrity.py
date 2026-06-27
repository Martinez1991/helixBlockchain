"""Tamper detection across the main and federated FIWARE Orion brokers.

This is the cleaned-up reimplementation of the legacy ``Funcoes.py`` logic. The
threat model (from the original TCC): an attacker injects or alters data directly
in a *federated* broker, bypassing the main broker. We detect this by comparing
each federated broker's entity attribute values against the authoritative value
held by the main broker:

* value matches the main broker            -> :data:`Verdict.OK`
* value differs from the main broker        -> :data:`Verdict.TAMPERED` (altered)
* entity/attr exists only at the federated  -> :data:`Verdict.TAMPERED` (injected)

The comparison logic lives in :class:`IntegrityChecker` and depends only on the
:class:`OrionGateway` protocol, so it is fully unit-testable with a fake gateway
(no MongoDB required). The concrete Mongo-backed gateway is in
:mod:`helix_blockchain.collectors.orion`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from helix_blockchain.domain.confidentiality import Confidentiality
from helix_blockchain.domain.records import IntegrityRecord, Verdict


@dataclass(frozen=True)
class EntityObservation:
    """One observed attribute value of an entity at a specific broker."""

    entity_id: str
    attribute: str
    value: Any
    broker: str


@runtime_checkable
class OrionGateway(Protocol):
    """Read access to the FIWARE Orion brokers under watch."""

    def main_broker(self) -> str:
        """Identifier (host) of the authoritative main broker."""

    def federated_brokers(self) -> list[str]:
        """Identifiers of the federated brokers referenced by subscriptions."""

    def observations(self, broker: str | None = None) -> list[EntityObservation]:
        """All entity attribute observations at ``broker`` (main if ``None``)."""


class IntegrityChecker:
    """Compares federated brokers against the main broker to flag tampering.

    Tamper detection runs on the *raw* values (which this node sees in both
    brokers); confidentiality only changes what is *stored* on the chain — the
    keyed value commitment and the (optional) entity pseudonym."""

    def __init__(
        self,
        gateway: OrionGateway,
        now_ms: Callable[[], int],
        confidentiality: Confidentiality | None = None,
    ) -> None:
        self._gateway = gateway
        self._now_ms = now_ms
        self._conf = confidentiality or Confidentiality()

    def check(self) -> list[IntegrityRecord]:
        main_index = {
            (o.entity_id, o.attribute): o.value
            for o in self._gateway.observations()
        }
        observed_at = self._now_ms()
        records: list[IntegrityRecord] = []
        for broker in self._gateway.federated_brokers():
            for obs in self._gateway.observations(broker):
                expected = main_index.get((obs.entity_id, obs.attribute), _MISSING)
                if expected is _MISSING or expected != obs.value:
                    verdict = Verdict.TAMPERED
                else:
                    verdict = Verdict.OK
                records.append(
                    IntegrityRecord(
                        entity_id=self._conf.entity_ref(obs.entity_id),
                        attribute=obs.attribute,
                        value_hash=self._conf.commit_value(obs.value),
                        source_broker=broker,
                        verdict=verdict,
                        observed_at=observed_at,
                    )
                )
        return records


class RecordDeduper:
    """Suppresses re-recording observations that have not changed.

    Mirrors the legacy ``monitora()`` behaviour: only records whose content
    differs from what was already committed are forwarded to the blockchain,
    keeping the chain free of redundant identical observations. Two records with
    the same content but different ``observed_at`` are considered duplicates.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    @staticmethod
    def _key(record: IntegrityRecord) -> str:
        # Content identity excluding the timestamp.
        return IntegrityRecord(
            entity_id=record.entity_id,
            attribute=record.attribute,
            value_hash=record.value_hash,
            source_broker=record.source_broker,
            verdict=record.verdict,
            observed_at=0,
        ).id

    def filter_new(self, records: list[IntegrityRecord]) -> list[IntegrityRecord]:
        fresh: list[IntegrityRecord] = []
        for record in records:
            key = self._key(record)
            if key not in self._seen:
                self._seen.add(key)
                fresh.append(record)
        return fresh


_MISSING = object()
