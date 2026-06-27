"""Typed configuration loaded from environment / ``.env`` (no hardcoded secrets).

All settings are namespaced under ``HELIX_`` with ``__`` separating nested
sections, e.g. ``HELIX_ORION__HOST``. See ``.env.example`` for the full list.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from helix_blockchain.domain.crypto import PublicKey


def _read_secret(inline: str, file: str) -> str:
    """Resolve a secret, preferring a file (Docker/k8s/Vault-agent ``*_FILE``
    convention) over an inline value so secrets never need to live in env/code."""
    if file:
        return Path(file).read_text(encoding="utf-8").strip()
    return inline


@dataclass(frozen=True)
class Peer:
    """A remote validator: identity, network location and public key."""

    node_id: str
    host: str
    port: int
    public_key: PublicKey

    @classmethod
    def parse(cls, spec: str) -> Peer:
        """Parse ``id@host:port|pubkey_hex``."""
        try:
            ident, rest = spec.split("@", 1)
            hostport, pubkey_hex = rest.split("|", 1)
            host, port = hostport.rsplit(":", 1)
            return cls(
                node_id=ident.strip(),
                host=host.strip(),
                port=int(port),
                public_key=PublicKey.from_hex(pubkey_hex.strip()),
            )
        except (ValueError, KeyError) as exc:
            raise ValueError(
                f"invalid peer spec {spec!r}; expected 'id@host:port|pubkey_hex'"
            ) from exc

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


class NodeSettings(BaseSettings):
    node_id: str = "node-1"
    private_key_hex: str = ""
    # Read the private key from this file instead (Docker/k8s secret mount).
    private_key_file: str = ""


class OrionSettings(BaseSettings):
    host: str = "localhost"
    port: int = 27017
    username: str = "helix"
    password: str = ""
    database: str = "orion"
    tls: bool = False
    tls_ca_file: str = ""  # CA bundle verifying the MongoDB server certificate
    poll_interval: float = 5.0
    # Event-driven collection via Mongo Change Streams (requires a replica set).
    # When false, falls back to timed polling every poll_interval seconds.
    use_change_streams: bool = False


class TlsSettings(BaseSettings):
    """TLS / mutual TLS for the validator peer-to-peer HTTP layer."""

    enabled: bool = False
    cert_file: str = ""  # this node's server certificate (PEM)
    key_file: str = ""   # this node's private key (PEM)
    ca_file: str = ""    # CA bundle used to verify peer certificates
    mutual: bool = False  # require client certificates (mTLS)
    # This node's client certificate for outbound mTLS; defaults to the server pair.
    client_cert_file: str = ""
    client_key_file: str = ""

    @property
    def effective_client_cert(self) -> str:
        return self.client_cert_file or self.cert_file

    @property
    def effective_client_key(self) -> str:
        return self.client_key_file or self.key_file


class ConsensusSettings(BaseSettings):
    # NoDecode stops pydantic-settings from JSON-decoding the env value, so the
    # validator below receives the raw "id@host:port|pubkey,..." string.
    peers: Annotated[list[Peer], NoDecode] = Field(default_factory=list)
    bind_host: str = "0.0.0.0"
    bind_port: int = 8000
    block_interval: float = 5.0
    # This node's address as peers should reach it (e.g. "node-1:8000"). Used to
    # announce itself for peer discovery; empty disables self-announcement.
    advertise: str = ""
    # Per-source rate limit for P2P/admin endpoints (requests/sec; 0 = disabled)
    # and burst size. Plus request body cap and inbound queue bound (backpressure).
    rate_limit_rps: float = 0.0
    rate_limit_burst: int = 200
    max_body_bytes: int = 1_048_576
    max_inbox: int = 10_000

    @field_validator("peers", mode="before")
    @classmethod
    def _split_peers(cls, value: object) -> object:
        if isinstance(value, str):
            return [Peer.parse(s) for s in value.split(",") if s.strip()]
        return value


class StorageSettings(BaseSettings):
    url: str = "sqlite:///data/helix_chain.db"


class OtelSettings(BaseSettings):
    """Distributed tracing (OpenTelemetry). No-op unless enabled."""

    enabled: bool = False
    endpoint: str = ""  # OTLP/HTTP endpoint, e.g. http://otel-collector:4318/v1/traces
    service_name: str = "helix-node"


class NotifySettings(BaseSettings):
    """Tamper-alert delivery. Console is always on; webhook is optional."""

    webhook_url: str = ""  # Slack incoming webhook or generic SIEM endpoint


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HELIX_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    node: NodeSettings = Field(default_factory=NodeSettings)
    orion: OrionSettings = Field(default_factory=OrionSettings)
    consensus: ConsensusSettings = Field(default_factory=ConsensusSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    tls: TlsSettings = Field(default_factory=TlsSettings)
    otel: OtelSettings = Field(default_factory=OtelSettings)
    notify: NotifySettings = Field(default_factory=NotifySettings)
    log_level: str = "INFO"
    # Enables the /admin/submit test hook. Demo/testing only.
    debug_api: bool = False
    # Shared bearer token(s) authenticating peer-to-peer endpoints. Comma-separate
    # to accept several during rotation (the first is used for outbound requests).
    # When empty, authentication is disabled (dev only).
    cluster_token: str = ""
    # Read the token(s) from this file instead (secret mount).
    cluster_token_file: str = ""

    def resolved_private_key_hex(self) -> str:
        return _read_secret(self.node.private_key_hex, self.node.private_key_file)

    def resolved_cluster_token(self) -> str:
        return _read_secret(self.cluster_token, self.cluster_token_file)


def load_settings() -> Settings:
    return Settings()
