"""Dynamic peer registry for automatic peer discovery.

Static configuration lists the seed validators, but with dynamic membership a
validator can be added after others started — they would not know its address.
Each node therefore keeps a mutable registry of ``public key -> address`` that is
seeded from config, includes the node's own advertised address, and is exchanged
with peers over ``/peers``: a node announces itself and periodically pulls peers'
registries, so a newcomer's address propagates across the cluster.

The registry is keyed by public key (a validator's stable identity), so a peer
re-announcing a new address updates in place rather than duplicating.
"""

from __future__ import annotations

from helix_blockchain.config import Peer


class PeerRegistry:
    def __init__(self, self_pubkey_hex: str, self_peer: Peer | None = None) -> None:
        self._self = self_pubkey_hex
        self._self_peer = self_peer
        self._peers: dict[str, Peer] = {}

    def seed(self, peers: list[Peer]) -> None:
        for peer in peers:
            self._add(peer)

    def merge(self, peers: list[Peer]) -> int:
        """Add/refresh peers; returns how many were newly learned."""
        added = 0
        for peer in peers:
            if self._add(peer):
                added += 1
        return added

    def _add(self, peer: Peer) -> bool:
        key = peer.public_key.to_hex()
        if key == self._self:
            return False  # never store ourselves as a peer
        is_new = key not in self._peers
        self._peers[key] = peer
        return is_new

    def current(self) -> list[Peer]:
        """Peers to send to (excludes self)."""
        return list(self._peers.values())

    def specs(self) -> list[str]:
        """Shareable peer specs, including our own advertised address."""
        out = [self._spec(p) for p in self._peers.values()]
        if self._self_peer is not None:
            out.append(self._spec(self._self_peer))
        return out

    def self_spec(self) -> str | None:
        return self._spec(self._self_peer) if self._self_peer else None

    @staticmethod
    def _spec(peer: Peer) -> str:
        return f"{peer.node_id}@{peer.host}:{peer.port}|{peer.public_key.to_hex()}"
