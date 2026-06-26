"""BFT consensus (IBFT/PBFT-style) for a permissioned validator set.

The :class:`~helix_blockchain.consensus.engine.ConsensusEngine` is a pure state
machine: it consumes signed :class:`~helix_blockchain.consensus.messages.ConsensusMessage`
objects and emits outgoing messages plus, on agreement, a finalized block. It has
no networking or storage dependencies, so the full agreement protocol is unit
testable with in-process validators.

Import from the submodules directly (``consensus.engine``, ``consensus.messages``,
``consensus.validator_set``). This package ``__init__`` deliberately performs no
eager imports so that ``consensus.validator_set`` — depended on by the domain
layer — can be imported without pulling in ``messages`` (which imports
``domain.block``) and creating an import cycle.
"""
