"""Adversarial fuzzing of the consensus engine (#15).

Run a normal cluster to capture the full multiset of valid messages, then replay
them to fresh engines in Hypothesis-chosen random orders, interleaved with
malformed/garbage messages. BFT must be order-insensitive and ignore garbage, so
the safety invariants must always hold:

  * agreement  — engines never commit two different blocks at one height;
  * finality   — any committed block carries a valid finality certificate;
  * robustness — malformed messages never crash the engine.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from helix_blockchain.consensus.engine import ConsensusEngine, verify_finality
from helix_blockchain.consensus.journal import NullVoteJournal
from helix_blockchain.consensus.messages import ConsensusMessage, MessageType
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.block import ZERO_HASH, genesis_block
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.domain.records import IntegrityRecord, Verdict

N = 4


def _records(n):
    return [
        IntegrityRecord(
            entity_id=f"S:{i}", attribute="t", value_hash=IntegrityRecord.hash_value(i),
            source_broker="b", verdict=Verdict.OK, observed_at=1,
        )
        for i in range(n)
    ]


def _engines(keys, vs):
    prev = genesis_block(vs).hash
    return {
        k.public.to_hex(): ConsensusEngine(
            validators=vs, private_key=k, height=1, previous_hash=prev,
            now_ms=lambda: 1000, journal=NullVoteJournal(),
        )
        for k in keys
    }


def _capture(keys, vs):
    """Run a normal round, returning every valid message exchanged."""
    engines = _engines(keys, vs)
    proposer_id = vs.proposer(1, 0).to_hex()
    bus = list(engines[proposer_id].propose(_records(3)).broadcast)
    captured = list(bus)
    while bus:
        msg = bus.pop(0)
        for nid, eng in engines.items():
            if nid == msg.sender:
                continue
            out = eng.handle(msg).broadcast
            bus.extend(out)
            captured.extend(out)
    return captured


def _garbage_strategy(validator_hexes):
    return st.builds(
        ConsensusMessage,
        type=st.sampled_from(list(MessageType)),
        height=st.integers(min_value=0, max_value=3),
        round=st.integers(min_value=0, max_value=3),
        block_hash=st.text(alphabet="0123456789abcdef", min_size=0, max_size=64),
        sender=st.sampled_from(validator_hexes)
        | st.text(alphabet="0123456789abcdef", max_size=70),
        signature=st.text(alphabet="0123456789abcdef", max_size=128),
    )


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(data=st.data())
def test_agreement_under_random_delivery_and_garbage(data):
    keys = [PrivateKey.generate() for _ in range(N)]
    vs = ValidatorSet([k.public for k in keys])
    valid = _capture(keys, vs)

    order = data.draw(st.permutations(valid))
    garbage = data.draw(st.lists(_garbage_strategy([v.to_hex() for v in vs]), max_size=10))
    stream = list(order)
    for g in garbage:
        stream.insert(data.draw(st.integers(0, len(stream))), g)

    engines = _engines(keys, vs)
    committed = {}
    for msg in stream:
        for nid, eng in engines.items():
            res = eng.handle(msg)  # must never raise, even on garbage
            if res.committed is not None:
                committed.setdefault(nid, res.committed)

    hashes = {b.hash for b in committed.values()}
    assert len(hashes) <= 1, "agreement broken: validators committed different blocks"
    for b in committed.values():
        assert verify_finality(b, vs)


@settings(max_examples=300, deadline=None)
@given(
    block_hash=st.text(alphabet="0123456789abcdef", max_size=64),
    sender=st.text(max_size=70),
    signature=st.text(alphabet="0123456789abcdef", max_size=130),
    mtype=st.sampled_from(list(MessageType)),
    height=st.integers(min_value=0, max_value=5),
    round=st.integers(min_value=0, max_value=5),
)
def test_garbage_messages_never_crash_or_commit(
    block_hash, sender, signature, mtype, height, round
):
    key = PrivateKey.generate()
    vs = ValidatorSet([key.public, *(PrivateKey.generate().public for _ in range(3))])
    engine = ConsensusEngine(
        validators=vs, private_key=key, height=1, previous_hash=ZERO_HASH,
        now_ms=lambda: 1, journal=NullVoteJournal(),
    )
    msg = ConsensusMessage(
        type=mtype, height=height, round=round, block_hash=block_hash,
        sender=sender, signature=signature,
    )
    assert engine.handle(msg).committed is None  # garbage can never finalize
