"""Generate a development CA and per-node TLS certificates for the validators.

Usage::

    python -m helix_blockchain.tools.gen_certs <out_dir> node-1 node-2 node-3

Writes ``<out_dir>/ca.crt`` plus ``<node>.crt`` / ``<node>.key`` for each node.
Each node certificate carries both ``serverAuth`` and ``clientAuth`` so the same
pair works for inbound (server) and outbound (mTLS client) connections, and
includes the node name plus ``localhost``/``127.0.0.1`` as subject alternative
names. For production, use your own PKI; this is a convenience for demos/tests.
"""

from __future__ import annotations

import datetime
import ipaddress
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

_DAY = datetime.timedelta(days=1)


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _san(name: str) -> x509.GeneralName:
    try:
        return x509.IPAddress(ipaddress.ip_address(name))
    except ValueError:
        return x509.DNSName(name)


def generate_ca(common_name: str = "Helix Dev CA"):
    """Return a self-signed CA ``(certificate, private_key)``."""
    key = _key()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _DAY)
        .not_valid_after(now + 3650 * _DAY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert, key


def generate_cert(ca_cert, ca_key, common_name: str, sans: list[str]):
    """Return a ``(certificate, private_key)`` signed by the CA, valid for both
    server and client authentication."""
    key = _key()
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _DAY)
        .not_valid_after(now + 825 * _DAY)
        .add_extension(
            x509.SubjectAlternativeName([_san(s) for s in sans]), critical=False
        )
        .add_extension(
            x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return cert, key


def _write_cert(path: Path, cert) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _write_key(path: Path, key) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print("usage: gen_certs <out_dir> <node-name> [<node-name> ...]")
        return 1
    out_dir = Path(argv[0])
    out_dir.mkdir(parents=True, exist_ok=True)
    ca_cert, ca_key = generate_ca()
    _write_cert(out_dir / "ca.crt", ca_cert)
    _write_key(out_dir / "ca.key", ca_key)
    for node in argv[1:]:
        cert, key = generate_cert(ca_cert, ca_key, node, [node, "localhost", "127.0.0.1"])
        _write_cert(out_dir / f"{node}.crt", cert)
        _write_key(out_dir / f"{node}.key", key)
        print(f"wrote {node}.crt / {node}.key")
    print(f"CA written to {out_dir / 'ca.crt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
