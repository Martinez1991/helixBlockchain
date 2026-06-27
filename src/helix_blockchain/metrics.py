"""Prometheus metrics for the node, exposed at ``/metrics``.

A distributed consensus system must be observable: silent liveness loss, a
lagging node, or a compromised broker should surface as metrics and alerts, not
be discovered by reading logs. Collectors are module-level singletons updated by
the node at the relevant moments; the HTTP server renders them for scraping.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

CHAIN_HEIGHT = Gauge("helix_chain_height", "Index of the chain tip block")
CONSENSUS_ROUND = Gauge("helix_consensus_round", "Current consensus round at the working height")
BLOCKS_COMMITTED = Counter("helix_blocks_committed_total", "Finalized blocks applied")
TAMPERING_DETECTED = Counter("helix_tampering_detected_total", "Tampered records committed")
MEMPOOL_PENDING = Gauge("helix_mempool_pending_records", "Records pending inclusion")
VALIDATORS_ACTIVE = Gauge("helix_validators_active", "Validators in the active set")
QUORUM = Gauge("helix_quorum", "Votes required to finalize a block")
IS_VALIDATOR = Gauge("helix_is_validator", "1 if this node is an active validator, else 0")
ROUND_TIMEOUTS = Counter("helix_round_timeouts_total", "Round-change timeouts fired")
INBOUND_QUEUE = Gauge("helix_inbound_queue_depth", "Queued inbound consensus messages")
RECORDS_DROPPED = Counter("helix_records_dropped_total", "Unsigned/invalid records dropped")


def observe_chain_state(
    *, height: int, validators: int, quorum: int, is_validator: bool, pending: int
) -> None:
    CHAIN_HEIGHT.set(height)
    VALIDATORS_ACTIVE.set(validators)
    QUORUM.set(quorum)
    IS_VALIDATOR.set(1 if is_validator else 0)
    MEMPOOL_PENDING.set(pending)


def observe_commit(tampered: int) -> None:
    BLOCKS_COMMITTED.inc()
    if tampered:
        TAMPERING_DETECTED.inc(tampered)


def observe_round(round_: int) -> None:
    CONSENSUS_ROUND.set(round_)


def observe_timeout() -> None:
    ROUND_TIMEOUTS.inc()


def observe_inbound(depth: int) -> None:
    INBOUND_QUEUE.set(depth)


def observe_records_dropped(n: int) -> None:
    if n:
        RECORDS_DROPPED.inc(n)


def render() -> tuple[bytes, str]:
    """Return ``(body, content_type)`` for the ``/metrics`` endpoint."""
    return generate_latest(), CONTENT_TYPE_LATEST
