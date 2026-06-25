"""BFT consensus (IBFT/PBFT-style) for a permissioned validator set.

The :class:`~helix_blockchain.consensus.engine.ConsensusEngine` is a pure state
machine: it consumes signed :class:`~helix_blockchain.consensus.messages.ConsensusMessage`
objects and emits outgoing messages plus, on agreement, a finalized block. It has
no networking or storage dependencies, so the full agreement protocol is unit
testable with in-process validators.
"""

from helix_blockchain.consensus.messages import ConsensusMessage, MessageType
from helix_blockchain.consensus.validator_set import ValidatorSet

__all__ = ["ValidatorSet", "ConsensusMessage", "MessageType"]
