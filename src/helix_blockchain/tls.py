"""TLS / mTLS wiring for the validator peer-to-peer HTTP layer.

The actual TLS is handled by uvicorn (server) and httpx (client); this module
only translates :class:`TlsSettings` into the keyword arguments each expects, so
the mapping is small and unit-testable. With ``mutual`` enabled, the server
requires a client certificate and each node presents its own — mutual TLS.
"""

from __future__ import annotations

import ssl
from typing import Any

from helix_blockchain.config import TlsSettings


def scheme(tls: TlsSettings) -> str:
    return "https" if tls.enabled else "http"


def uvicorn_ssl_kwargs(tls: TlsSettings) -> dict[str, Any]:
    """Keyword args for ``uvicorn.Config`` to serve HTTPS (and require client
    certs under mTLS). Empty when TLS is disabled."""
    if not tls.enabled:
        return {}
    if not tls.cert_file or not tls.key_file:
        raise ValueError("TLS enabled but cert_file/key_file are not set")
    kwargs: dict[str, Any] = {
        "ssl_certfile": tls.cert_file,
        "ssl_keyfile": tls.key_file,
    }
    if tls.ca_file:
        kwargs["ssl_ca_certs"] = tls.ca_file
    if tls.mutual:
        kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED
    return kwargs


def httpx_tls_kwargs(tls: TlsSettings) -> dict[str, Any]:
    """Keyword args for ``httpx.AsyncClient``: verify the peer with our CA and,
    under mTLS, present this node's client certificate."""
    if not tls.enabled:
        return {}
    kwargs: dict[str, Any] = {"verify": tls.ca_file or True}
    if tls.mutual:
        cert, key = tls.effective_client_cert, tls.effective_client_key
        if not cert or not key:
            raise ValueError("mTLS enabled but client certificate/key are not set")
        kwargs["cert"] = (cert, key)
    return kwargs
