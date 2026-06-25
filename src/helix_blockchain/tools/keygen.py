"""Generate an Ed25519 validator keypair.

Usage::

    python -m helix_blockchain.tools.keygen [node-id] [host:port]

Prints the private seed (to put in this node's ``.env`` as
``HELIX_NODE__PRIVATE_KEY_HEX``) and the peer spec (to share with other nodes
for their ``HELIX_CONSENSUS__PEERS`` list).
"""

from __future__ import annotations

import sys

from helix_blockchain.domain.crypto import PrivateKey


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    node_id = argv[0] if len(argv) > 0 else "node-1"
    hostport = argv[1] if len(argv) > 1 else "HOST:PORT"

    key = PrivateKey.generate()
    pub_hex = key.public.to_hex()

    print("# Private (keep secret — this node's .env):")
    print(f"HELIX_NODE__PRIVATE_KEY_HEX={key.to_hex()}")
    print()
    print("# Public peer spec (share with other validators):")
    print(f"{node_id}@{hostport}|{pub_hex}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
