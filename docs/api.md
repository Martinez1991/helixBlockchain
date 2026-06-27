# API HTTP

Cada `helix-node` expõe uma API HTTP (FastAPI) na porta `HELIX_CONSENSUS__BIND_PORT`
(default 8000). Endpoints **mutáveis** exigem o token de cluster quando
`HELIX_CLUSTER_TOKEN` está definido; endpoints de **leitura** ficam abertos (os
blocos são auto-verificáveis pelo certificado de finalidade e prova de Merkle).

Autenticação: cabeçalho `Authorization: Bearer <token>`.

## Peer-to-peer (mutáveis, autenticados)

| Método | Caminho | Descrição |
|---|---|---|
| POST | `/consensus` | Recebe uma mensagem de consenso assinada (enfileira; 503 se cheio) |
| POST | `/mempool` | Recebe registros de integridade gossipados (`{"records": [...]}`) |
| POST | `/membership` | Recebe mudanças de validador gossipadas (`{"changes": [...]}`) |
| POST | `/block` | Recebe um bloco finalizado empurrado por um peer |
| POST | `/peers` | Mescla specs de peers no registro (`{"peers": ["id@host:port\|pub"]}`) |

Sujeitos a **rate limiting** (429), **limite de payload** (413) e **backpressure**.

## Leitura (abertos)

### `GET /health`
Liveness. `{"status": "ok"}`.

### `GET /chain`
Estado da cadeia e do conjunto de validadores ativo:
```json
{ "node_id": "node-1", "height": 12, "latest_hash": "…",
  "validators": 4, "quorum": 3, "is_validator": true, "validator_keys": ["…"] }
```

### `GET /blocks/{index}`
Bloco finalizado (JSON completo: header, records, commit_signatures,
validator_changes). `404` se inexistente. Usado também para catch-up sync.

### `GET /peers`
Specs de peers conhecidos (registro de descoberta). *Autenticado.*

### `GET /metrics`
Métricas no formato Prometheus (ver [observability.md](observability.md)).

### `GET /ui`
**Console web read-only** (SPA): board do cluster (altura/round/lag/validadores
por nó), explorer de blocos com drill-down de registros, feed de adulterações e
**verificador de prova de Merkle no navegador**. Consome apenas os endpoints de
leitura; consulta nós irmãos via CORS. Complementa (não substitui) o Grafana.

### `GET /proof/{height}/{index}`
**Prova de inclusão Merkle** de `records[index]` no bloco `height` — verificável
**offline** contra a raiz de Merkle, sem confiar no nó:
```json
{ "height": 1, "index": 0, "merkle_root": "…", "block_hash": "…",
  "record": { … }, "proof": [ {"sibling": "…", "right": true}, … ] }
```
Verificação (Python):
```python
from helix_blockchain.domain.merkle import ProofStep, verify_proof
from helix_blockchain.domain.records import IntegrityRecord
rec = IntegrityRecord.from_dict(body["record"])
steps = [ProofStep(bytes.fromhex(s["sibling"]), s["right"]) for s in body["proof"]]
assert verify_proof(rec.canonical(), steps, bytes.fromhex(body["merkle_root"]))
```

## Admin (apenas com `HELIX_DEBUG_API=true`, autenticados)

| Método | Caminho | Descrição |
|---|---|---|
| POST | `/admin/submit?count=N` | Injeta `N` registros sintéticos (dispara consenso; demo/teste) |
| POST | `/admin/validator` | Propõe mudança de validador (`{"action":"ADD\|REMOVE","validator":"<pub>"}`) |

## Códigos de status

| Código | Significado |
|---|---|
| 200 | OK |
| 400 | Payload malformado |
| 401 | Token ausente/ inválido |
| 404 | Bloco/registro inexistente |
| 413 | Payload acima de `MAX_BODY_BYTES` |
| 429 | Rate limit excedido |
| 503 | Fila de inbound cheia (backpressure) |

## Auditoria

Acessos aos endpoints sensíveis são registrados no logger `helix.audit`
(method, path, client, authenticated, status) — encaminhe ao SIEM.
Ver [security.md](security.md) e [compliance/](compliance/lgpd.md).
