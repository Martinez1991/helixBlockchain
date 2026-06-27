# Observabilidade

Métricas Prometheus, dashboards Grafana, regras de alerta e tracing distribuído.
Artefatos em [`../ops/`](https://github.com/Martinez1991/helixBlockchain/tree/master/ops).

## Métricas (`GET /metrics`)

Sempre ativo (sem configuração). Coletores expostos:

| Métrica | Tipo | Significado |
|---|---|---|
| `helix_chain_height` | gauge | Índice do bloco no topo |
| `helix_consensus_round` | gauge | Rodada de consenso na altura corrente |
| `helix_blocks_committed_total` | counter | Blocos finalizados aplicados |
| `helix_tampering_detected_total` | counter | Registros de adulteração commitados |
| `helix_mempool_pending_records` | gauge | Registros pendentes de inclusão |
| `helix_validators_active` / `helix_quorum` | gauge | Tamanho do conjunto / quórum |
| `helix_is_validator` | gauge | 1 se este nó é validador ativo |
| `helix_round_timeouts_total` | counter | Timeouts de round-change |
| `helix_inbound_queue_depth` | gauge | Mensagens de consenso enfileiradas |
| `helix_records_dropped_total` | counter | Registros não assinados/inválidos descartados |

Configure o Prometheus para *scrape* da porta do nó em `/metrics`. Com o
Prometheus Operator, o chart Helm expõe um `ServiceMonitor`
(`serviceMonitor.enabled=true`).

## Alertas

[`../ops/prometheus/alerts.yml`](https://github.com/Martinez1991/helixBlockchain/blob/master/ops/prometheus/alerts.yml) define regras:

- **HelixChainStalled** (crítico) — sem novos blocos em 5 min com pendências.
- **HelixRoundChangeStorm** (aviso) — muitos timeouts (proposer faltante/partição).
- **HelixNodeLagging** (aviso) — nó atrasado > 2 blocos do cluster.
- **HelixTamperingDetected** (crítico) — adulteração commitada.
- **HelixInboundBacklog** (aviso) — fila de inbound acumulando.
- **HelixRecordsDropped** (aviso) — muitos registros descartados (injeção/misconfig).

## Dashboard

[`../ops/grafana/helix-dashboard.json`](https://github.com/Martinez1991/helixBlockchain/blob/master/ops/grafana/helix-dashboard.json) —
altura por nó, blocos/s, validadores/quórum, adulterações, rodada, timeouts,
mempool/fila e descartes. Importe no Grafana (datasource Prometheus).

## Tracing (OpenTelemetry)

No-op por padrão; ative com `HELIX_OTEL__ENABLED=true` e um endpoint OTLP/HTTP
(`HELIX_OTEL__ENDPOINT`, ex.: Jaeger/Tempo). Spans cobrem o processamento de
mensagens (`consensus.handle`, com `type/height/round`) e um evento
`block.committed`, correlacionados entre nós pelo contexto de trace.

Instale o SDK/exportador: `pip install -e ".[otel]"`.

## Logs

`helix.audit` (acessos) e os logs da aplicação (`HELIX_LOG_LEVEL`). Encaminhe ao
seu stack (Loki/ELK/SIEM). Ver [security.md](security.md).
