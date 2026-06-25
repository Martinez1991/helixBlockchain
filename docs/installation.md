## Instalação

A blockchain v2 roda como um conjunto de **nós validadores**. Você pode subir
tudo com Docker (recomendado para testar) ou instalar manualmente em cada
servidor.

### Opção A — Docker Compose (demo: Orion + Mongo + 3 nós)

```bash
git clone https://github.com/Martinez1991/helixBlockchain.git
cd helixBlockchain
docker compose up --build
```

Isso sobe MongoDB, FIWARE Orion e 3 validadores. As chaves no `docker-compose.yml`
são **apenas de desenvolvimento** — gere novas para qualquer uso real.

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
HELIX_NODE__PRIVATE_KEY_HEX=<chave privada deste nó>

# Broker Orion a monitorar (MongoDB)
HELIX_ORION__HOST=<ip-do-orion>
HELIX_ORION__PORT=27017
HELIX_ORION__USERNAME=helix
HELIX_ORION__PASSWORD=<senha-do-mongo>
HELIX_ORION__DATABASE=orion

# Demais validadores (peer specs gerados no passo 1, separados por vírgula)
HELIX_CONSENSUS__PEERS=node-2@10.0.0.2:8000|<pub2>,node-3@10.0.0.3:8000|<pub3>
HELIX_CONSENSUS__BIND_PORT=8000

# Persistência (SQLite para começar; Postgres em produção)
HELIX_STORAGE__URL=sqlite:///data/helix_chain.db
```

> **Segurança:** ao contrário da v1, **nenhuma credencial fica no código**.
> Nunca faça commit do `.env`. Em produção, habilite TLS
> (`HELIX_ORION__TLS=true`) e exponha o P2P via HTTPS.

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
