# Configuração

Toda a configuração vem de variáveis de ambiente (ou de um arquivo `.env`),
namespaceadas com `HELIX_` e `__` separando seções aninhadas — ex.:
`HELIX_ORION__HOST`. Veja [`.env.example`](../.env.example) para um modelo.

> **Segredos** (chave privada, token) devem vir de **arquivo** (`*_FILE`) em
> produção — Docker/k8s secret, Vault/KMS — nunca inline. Ver [security.md](security.md).

## Nó (`HELIX_NODE__*`)

| Variável | Default | Descrição |
|---|---|---|
| `HELIX_NODE__NODE_ID` | `node-1` | Identificador deste validador |
| `HELIX_NODE__PRIVATE_KEY_HEX` | — | Seed Ed25519 (64 hex). Gere com `keygen` |
| `HELIX_NODE__PRIVATE_KEY_FILE` | — | Lê a chave de um arquivo (preferido; precede o inline) |

## Consenso / rede (`HELIX_CONSENSUS__*`)

| Variável | Default | Descrição |
|---|---|---|
| `HELIX_CONSENSUS__PEERS` | — | Lista `id@host:port\|pubkey_hex`, separada por vírgula |
| `HELIX_CONSENSUS__BIND_HOST` | `0.0.0.0` | Host do servidor HTTP P2P/API |
| `HELIX_CONSENSUS__BIND_PORT` | `8000` | Porta do servidor |
| `HELIX_CONSENSUS__ADVERTISE` | — | Endereço alcançável (ex.: `node-1:8000`) p/ descoberta |
| `HELIX_CONSENSUS__BLOCK_INTERVAL` | `5.0` | Intervalo-alvo de bloco (s); base do timeout de round-change |
| `HELIX_CONSENSUS__RATE_LIMIT_RPS` | `0` | Rate limit por origem (req/s; `0` = desligado) |
| `HELIX_CONSENSUS__RATE_LIMIT_BURST` | `200` | Burst do token-bucket |
| `HELIX_CONSENSUS__MAX_BODY_BYTES` | `1048576` | Tamanho máximo de payload (413 acima) |
| `HELIX_CONSENSUS__MAX_INBOX` | `10000` | Limite da fila de inbound (backpressure → 503) |
| `HELIX_CONSENSUS__BOOTSTRAP_GENESIS` | `false` | Busca o genesis de um peer (nó ingressante) |

## FIWARE Orion / MongoDB (`HELIX_ORION__*`)

| Variável | Default | Descrição |
|---|---|---|
| `HELIX_ORION__HOST` | `localhost` | Host do MongoDB do Orion |
| `HELIX_ORION__PORT` | `27017` | Porta do MongoDB |
| `HELIX_ORION__USERNAME` | `helix` | Usuário (ignorado se sem senha) |
| `HELIX_ORION__PASSWORD` | — | Senha; vazio = sem auth (Mongo de demo) |
| `HELIX_ORION__DATABASE` | `orion` | Database |
| `HELIX_ORION__TLS` | `false` | TLS na conexão Mongo |
| `HELIX_ORION__TLS_CA_FILE` | — | CA que verifica o certificado do Mongo |
| `HELIX_ORION__POLL_INTERVAL` | `5.0` | Intervalo de polling (s) |
| `HELIX_ORION__USE_CHANGE_STREAMS` | `false` | Coleta event-driven (exige replica set) |

## Armazenamento (`HELIX_STORAGE__*`)

| Variável | Default | Descrição |
|---|---|---|
| `HELIX_STORAGE__URL` | `sqlite:///data/helix_chain.db` | URL SQLAlchemy (SQLite/Postgres). Guarda cadeia + WAL de consenso |

## TLS / mTLS do P2P (`HELIX_TLS__*`)

| Variável | Default | Descrição |
|---|---|---|
| `HELIX_TLS__ENABLED` | `false` | HTTPS entre validadores |
| `HELIX_TLS__CERT_FILE` / `KEY_FILE` | — | Certificado/chave do servidor (PEM) |
| `HELIX_TLS__CA_FILE` | — | CA que verifica os peers |
| `HELIX_TLS__MUTUAL` | `false` | Exige certificado de cliente (mTLS) |
| `HELIX_TLS__CLIENT_CERT_FILE` / `CLIENT_KEY_FILE` | = server | Cert de cliente p/ mTLS de saída |

## Observabilidade (`HELIX_OTEL__*`)

| Variável | Default | Descrição |
|---|---|---|
| `HELIX_OTEL__ENABLED` | `false` | Habilita tracing OpenTelemetry |
| `HELIX_OTEL__ENDPOINT` | — | Endpoint OTLP/HTTP (Jaeger/Tempo) |
| `HELIX_OTEL__SERVICE_NAME` | `helix-node` | Nome do serviço nos traces |

Métricas Prometheus em `GET /metrics` (sempre ativo, sem config).

## Notificação (`HELIX_NOTIFY__*`)

| Variável | Default | Descrição |
|---|---|---|
| `HELIX_NOTIFY__WEBHOOK_URL` | — | Webhook Slack/SIEM p/ alertas de adulteração |

## Segurança e gerais (top-level)

| Variável | Default | Descrição |
|---|---|---|
| `HELIX_CLUSTER_TOKEN` | — | Token(s) Bearer dos endpoints P2P; vírgula = rotação; vazio = sem auth |
| `HELIX_CLUSTER_TOKEN_FILE` | — | Lê o token de um arquivo (preferido) |
| `HELIX_DEBUG_API` | `false` | Habilita `/admin/*` (demo/testes) |
| `HELIX_LOG_LEVEL` | `INFO` | Nível de log |

## Notas

- **Quórum:** com `N` validadores, `f = (N-1)//3` e quórum `N - f`. Use **4** nós
  para tolerar 1 bizantino (`f=1`).
- **Validadores:** o conjunto inicial vem dos peers + chave própria (deduplicada);
  mudanças são acordadas on-chain (ver [architecture.md](architecture.md)).
