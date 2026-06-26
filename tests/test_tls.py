"""TLS/mTLS: settings -> kwargs mapping, and a real in-memory mTLS handshake."""

from __future__ import annotations

import contextlib
import ssl

import pytest

from helix_blockchain.config import TlsSettings
from helix_blockchain.tls import httpx_tls_kwargs, scheme, uvicorn_ssl_kwargs
from helix_blockchain.tools import gen_certs


# ── settings -> kwargs ─────────────────────────────────────────────────
def test_scheme_follows_enabled():
    assert scheme(TlsSettings(enabled=False)) == "http"
    assert scheme(TlsSettings(enabled=True, cert_file="c", key_file="k")) == "https"


def test_kwargs_empty_when_disabled():
    assert uvicorn_ssl_kwargs(TlsSettings(enabled=False)) == {}
    assert httpx_tls_kwargs(TlsSettings(enabled=False)) == {}


def test_uvicorn_kwargs_basic_tls():
    tls = TlsSettings(enabled=True, cert_file="s.crt", key_file="s.key", ca_file="ca.crt")
    kw = uvicorn_ssl_kwargs(tls)
    assert kw["ssl_certfile"] == "s.crt"
    assert kw["ssl_keyfile"] == "s.key"
    assert kw["ssl_ca_certs"] == "ca.crt"
    assert "ssl_cert_reqs" not in kw  # not mutual


def test_uvicorn_kwargs_mutual_requires_client_cert():
    tls = TlsSettings(enabled=True, cert_file="s.crt", key_file="s.key", mutual=True)
    assert uvicorn_ssl_kwargs(tls)["ssl_cert_reqs"] == ssl.CERT_REQUIRED


def test_uvicorn_kwargs_missing_cert_raises():
    with pytest.raises(ValueError):
        uvicorn_ssl_kwargs(TlsSettings(enabled=True))


def test_httpx_kwargs_mutual_uses_client_pair_default_to_server():
    tls = TlsSettings(enabled=True, cert_file="s.crt", key_file="s.key",
                      ca_file="ca.crt", mutual=True)
    kw = httpx_tls_kwargs(tls)
    assert kw["verify"] == "ca.crt"
    assert kw["cert"] == ("s.crt", "s.key")  # falls back to the server pair


# ── real mutual-TLS handshake using generated certs ────────────────────
def _handshake(server_ctx: ssl.SSLContext, client_ctx: ssl.SSLContext) -> None:
    """Drive a full TLS handshake over in-memory BIOs (no sockets)."""
    s_in, s_out = ssl.MemoryBIO(), ssl.MemoryBIO()
    c_in, c_out = ssl.MemoryBIO(), ssl.MemoryBIO()
    s = server_ctx.wrap_bio(s_in, s_out, server_side=True)
    c = client_ctx.wrap_bio(c_in, c_out, server_hostname="localhost")

    for _ in range(20):
        for obj, src, dst in ((c, c_out, s_in), (s, s_out, c_in)):
            with contextlib.suppress(ssl.SSLWantReadError):
                obj.do_handshake()
            data = src.read()
            if data:
                dst.write(data)
        if c.cipher() and s.cipher():
            return
    raise AssertionError("handshake did not complete")


def _server_ctx(tmp_path):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(tmp_path / "node-1.crt"), str(tmp_path / "node-1.key"))
    ctx.load_verify_locations(str(tmp_path / "ca.crt"))
    ctx.verify_mode = ssl.CERT_REQUIRED  # mTLS: require a client cert
    return ctx


def _client_ctx(tmp_path, cert_prefix="node-2"):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(str(tmp_path / "ca.crt"))
    ctx.load_cert_chain(str(tmp_path / f"{cert_prefix}.crt"), str(tmp_path / f"{cert_prefix}.key"))
    return ctx


def test_generated_certs_enable_mutual_tls(tmp_path):
    gen_certs.main([str(tmp_path), "node-1", "node-2"])
    _handshake(_server_ctx(tmp_path), _client_ctx(tmp_path, "node-2"))  # no raise


def test_client_without_ca_signed_cert_is_rejected(tmp_path):
    gen_certs.main([str(tmp_path), "node-1"])
    # A second, independent CA whose client cert the server must NOT trust.
    rogue_ca, rogue_key = gen_certs.generate_ca("Rogue CA")
    rogue_cert, rogue_ckey = gen_certs.generate_cert(rogue_ca, rogue_key, "rogue", ["localhost"])
    gen_certs._write_cert(tmp_path / "rogue.crt", rogue_cert)
    gen_certs._write_key(tmp_path / "rogue.key", rogue_ckey)

    with pytest.raises(ssl.SSLError):
        _handshake(_server_ctx(tmp_path), _client_ctx(tmp_path, "rogue"))
