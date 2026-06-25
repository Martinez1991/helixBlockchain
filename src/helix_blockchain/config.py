"""Typed configuration loaded from environment / ``.env`` (no hardcoded secrets).

All settings are namespaced under ``HELIX_`` with ``__`` separating nested
sections, e.g. ``HELIX_ORION__HOST``. See ``.env.example`` for the full list.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from helix_blockchain.domain.crypto import PublicKey


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


class OrionSettings(BaseSettings):
    host: str = "localhost"
    port: int = 27017
    username: str = "helix"
    password: str = ""
    database: str = "orion"
    tls: bool = False
    poll_interval: float = 5.0


class ConsensusSettings(BaseSettings):
    peers: list[Peer] = Field(default_factory=list)
    bind_host: str = "0.0.0.0"
    bind_port: int = 8000
    block_interval: float = 5.0

    @field_validator("peers", mode="before")
    @classmethod
    def _split_peers(cls, value: object) -> object:
        if isinstance(value, str):
            return [Peer.parse(s) for s in value.split(",") if s.strip()]
        return value


class StorageSettings(BaseSettings):
    url: str = "sqlite:///data/helix_chain.db"


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
    log_level: str = "INFO"


def load_settings() -> Settings:
    return Settings()
