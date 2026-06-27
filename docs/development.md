# Desenvolvimento

## Ambiente

Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Extras opcionais: `.[postgres]` (driver psycopg), `.[otel]` (SDK OpenTelemetry).

## Testes, lint e segurança

```bash
pytest                         # suíte (183 testes)
pytest --cov=helix_blockchain  # com cobertura
ruff check src tests           # lint
bandit -c pyproject.toml -r src -ll   # SAST
```

Testes contra **Postgres**: defina `HELIX_TEST_DB_URL` (ver
[operations.md](operations.md)); senão, `tests/test_postgres.py` é pulado.

## Arquitetura em camadas

A regra de dependência aponta para baixo; `domain/` não tem I/O e é 100% testável.

```
collectors/  coleta Orion (MongoDB) + detecção de adulteração (lógica pura)
network/     nó orquestrador, transporte P2P, servidor FastAPI, discovery, bootstrap
consensus/   motor BFT, mensagens assinadas, validador, journal (WAL)
domain/      cripto (Ed25519/SHA-256), merkle, block, records, membership, canonical
storage/     persistência (SQLAlchemy: SQLite/Postgres)
notify/      console / webhook / SIEM
metrics.py · tracing.py · config.py · app.py · clock.py
```

Princípios:
- **`domain/` puro** (sem rede/disco) — injete relógio/transporte para testar.
- **Protocols** desacoplam (`Transport`, `BlockRepository`, `OrionGateway`,
  `VoteJournal`, `Notifier`) — implementações reais e *fakes* intercambiáveis.
- O **motor de consenso é uma máquina de estados pura**: consome mensagens,
  retorna `StepResult` (broadcast + commit); o `Node` faz I/O.

## Convenções

- Estilo: `ruff` (ver `[tool.ruff]` no `pyproject.toml`), linha ≤ 100.
- Serialização determinística para hash/assinatura via `domain/canonical.py`.
- Não introduzir credenciais no código; segredos via `*_FILE`.
- Mensagens de commit: convencional (`feat(scope): …`), com `Co-Authored-By`.

## Rodando o cluster localmente (Docker)

```bash
python scripts/gen_dev_secrets.py   # gera .env de DEV (gitignored)
docker compose up --build           # Mongo + Orion + 3 validadores
```

## Verificação formal e fuzzing

`specs/Helix.tla` (TLA+, safety) e `tests/test_fuzz_consensus.py` (Hypothesis).
Ver [../specs/README.md](../specs/README.md).

## Contribuindo

Ver [../CONTRIBUTING.md](../CONTRIBUTING.md). PRs disparam CI (testes+lint,
Postgres, SonarQube) e o workflow de segurança.
