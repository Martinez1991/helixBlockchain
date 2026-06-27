## Instalação

A blockchain v2 roda como um conjunto de **nós validadores**. Você pode subir
tudo com Docker (recomendado para testar) ou instalar manualmente em cada
servidor.

### Opção A — Docker Compose (demo: Orion + Mongo + 3 nós)

```bash
git clone https://github.com/Martinez1991/helixBlockchain.git
cd helixBlockchain
python scripts/gen_dev_secrets.py     # gera .env (gitignored) com chaves+token de DEV
docker compose up --build
```

Isso sobe MongoDB, FIWARE Orion e 3 validadores. **Nenhum segredo é versionado**:
o compose lê chaves/token do `.env` gerado pelo script (apenas para
desenvolvimento). Para Kubernetes/HA, use o chart em
[`deploy/helm/helix`](https://github.com/Martinez1991/helixBlockchain/blob/master/deploy/helm/helix/README.md).

### Opção C — Ingressar numa rede existente

Um nó novo pode **buscar o genesis de um peer** em vez de tê-lo na config:
defina `HELIX_CONSENSUS__BOOTSTRAP_GENESIS=true` e ao menos um peer.

### Opção B — Instalação manual (por nó)

Requisitos: **Python 3.11+** e acesso ao MongoDB do broker Orion.

```bash
git clone https://github.com/Martinez1991/helixBlockchain.git
cd helixBlockchain
python3 -m venv .venv && source .venv/bin/activate
pip install .                      # ou: pip install -e ".[dev]" para desenvolver
```

#### 1. Gere a identidade do validador

```bash
python -m helix_blockchain.tools.keygen node-1 <IP_DESTE_NO>:8000
```

Isso imprime:
- a **chave privada** (vai no `.env` deste nó);
- o **peer spec** público `id@host:port|pubkey` (compartilhe com os outros nós).

#### 2. Configure o `.env`

```bash
cp .env.example .env
```

Edite e preencha:

```dotenv
HELIX_NODE__NODE_ID=node-1
# Em produção, prefira um arquivo de segredo (Vault/KMS/k8s):
HELIX_NODE__PRIVATE_KEY_FILE=/run/secrets/helix_private_key
# (ou inline, só para dev): HELIX_NODE__PRIVATE_KEY_HEX=<chave>

# Broker Orion a monitorar (MongoDB)
HELIX_ORION__HOST=<ip-do-orion>
HELIX_ORION__PASSWORD=<senha-do-mongo>
HELIX_ORION__DATABASE=orion

# Demais validadores (peer specs gerados no passo 1, separados por vírgula)
HELIX_CONSENSUS__PEERS=node-2@10.0.0.2:8000|<pub2>,node-3@10.0.0.3:8000|<pub3>
HELIX_CONSENSUS__ADVERTISE=node-1:8000
HELIX_CONSENSUS__BIND_PORT=8000

# Token de cluster (mesmo em todos; prefira arquivo em produção)
HELIX_CLUSTER_TOKEN_FILE=/run/secrets/helix_cluster_token

# Persistência (SQLite para começar; Postgres em produção)
HELIX_STORAGE__URL=sqlite:///data/helix_chain.db
```

> **Segurança:** nenhuma credencial fica no código. Nunca faça commit do `.env`.
> Em produção, use **segredos via arquivo** (`*_FILE`), habilite **TLS/mTLS**
> (`HELIX_TLS__*`, `HELIX_ORION__TLS`) e considere rate limiting
> (`HELIX_CONSENSUS__RATE_LIMIT_RPS`). Referência completa em
> [configuration.md](configuration.md) e [security.md](security.md).

#### 3. Execute

```bash
helix-node
```

Repita os passos em cada servidor validador, ajustando `NODE_ID`,
`PRIVATE_KEY_HEX` e a lista de `PEERS`. Para tolerância bizantina (`f=1`) use
**4 validadores**.

### Verificação

```bash
curl http://<ip-do-no>:8000/chain     # altura da cadeia e quórum
curl http://<ip-do-no>:8000/health
```
