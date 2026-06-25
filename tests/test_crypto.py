from helix_blockchain.domain.crypto import PrivateKey, PublicKey, sha256_hex


def test_sha256_hex_known_vector():
    # SHA-256 of empty string.
    assert sha256_hex(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_private_key_roundtrip_hex():
    key = PrivateKey.generate()
    restored = PrivateKey.from_hex(key.to_hex())
    assert restored.to_hex() == key.to_hex()
    assert restored.public == key.public


def test_public_key_roundtrip_hex():
    pub = PrivateKey.generate().public
    restored = PublicKey.from_hex(pub.to_hex())
    assert restored == pub
    assert hash(restored) == hash(pub)


def test_sign_and_verify():
    key = PrivateKey.generate()
    msg = b"helix integrity"
    sig = key.sign(msg)
    assert key.public.verify(sig, msg) is True


def test_verify_rejects_tampered_message():
    key = PrivateKey.generate()
    sig = key.sign(b"original")
    assert key.public.verify(sig, b"tampered") is False


def test_verify_rejects_wrong_key():
    sig = PrivateKey.generate().sign(b"msg")
    other = PrivateKey.generate().public
    assert other.verify(sig, b"msg") is False


def test_from_hex_rejects_bad_length():
    import pytest

    with pytest.raises(ValueError):
        PrivateKey.from_hex("abcd")
