import pytest

from helix_blockchain.config import ConsensusSettings, Peer
from helix_blockchain.domain.crypto import PrivateKey


def test_peer_parse_roundtrip():
    pub = PrivateKey.generate().public
    spec = f"node-2@10.0.0.2:8000|{pub.to_hex()}"
    peer = Peer.parse(spec)
    assert peer.node_id == "node-2"
    assert peer.host == "10.0.0.2"
    assert peer.port == 8000
    assert peer.public_key == pub
    assert peer.base_url == "http://10.0.0.2:8000"


def test_peer_parse_rejects_malformed():
    with pytest.raises(ValueError):
        Peer.parse("garbage-without-delimiters")


def test_consensus_settings_parses_peer_csv():
    a = PrivateKey.generate().public
    b = PrivateKey.generate().public
    spec = f"n1@h1:1|{a.to_hex()},n2@h2:2|{b.to_hex()}"
    settings = ConsensusSettings(peers=spec)
    assert [p.node_id for p in settings.peers] == ["n1", "n2"]


def test_consensus_settings_empty_peers():
    assert ConsensusSettings(peers="").peers == []
