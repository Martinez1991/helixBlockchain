# Helix Blockchain

Ledger **permissionado com consenso BFT** para garantir a **integridade** dos
dados dos brokers FIWARE Orion (Helix Sandbox Next Generation), no cenário de IoT.

[![CI](https://github.com/Martinez1991/helixBlockchain/actions/workflows/build.yml/badge.svg)](https://github.com/Martinez1991/helixBlockchain/actions/workflows/build.yml)

## Sobre

Esta blockchain opera em conjunto com o Helix Sandbox NG para garantir a
**integridade** dos dados armazenados nos brokers. Ela **não** cifra os dados —
portanto não garante confidencialidade. Vários nós validadores chegam a um
**consenso** sobre a veracidade de cada informação e registram o resultado numa
cadeia à prova de adulteração.

Se um agente malicioso inserir ou alterar dados diretamente nos brokers
**federados**, essa ação é identificada como ilegítima e — após ser **finalizada
por consenso** — a blockchain notifica qual dispositivo sofreu a adulteração.

> **v2 (reescrita 2026):** a versão original (TCC) era um encadeamento de hashes
> de nó único com Proof-of-Work. A v2 substitui isso por **consenso BFT real**
> (estilo IBFT/PBFT, com validadores e assinaturas Ed25519) e integridade por
> **árvore de Merkle**, alinhando a implementação à proposta de "vários nós em
> consenso". O código original está preservado em [`legacy/`](legacy/) como
> referência. Detalhes em [docs/architecture.md](docs/architecture.md).

## Como funciona

Cada processo `helix-node` é um validador que monitora o Orion, detecta
adulteração comparando brokers federados com o principal, e participa do
consenso para finalizar registros de integridade na cadeia compartilhada.

- Tolera até `f = (N−1)/3` validadores maliciosos (quórum `N − f`).
- Finalidade imediata (sem mineração/PoW).
- Veja o diagrama e o protocolo em [docs/architecture.md](docs/architecture.md).

## Início rápido (Docker)

Sobe MongoDB + Orion + 3 validadores:

```bash
docker compose up --build
```

Endpoints de cada nó (ex.: node-1 em `http://localhost:8001`):
`GET /health`, `GET /chain`, `GET /blocks/{i}`.

> As chaves no `docker-compose.yml` são **apenas para desenvolvimento**. Gere
> novas para produção: `python -m helix_blockchain.tools.keygen`.

## Início rápido (local)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Gere a identidade do validador e configure o .env
python -m helix_blockchain.tools.keygen node-1 127.0.0.1:8000
cp .env.example .env   # cole a chave privada e os peers

pytest            # roda a suíte de testes
helix-node        # inicia o nó
```

## Requisitos e instalação

- [Requisitos](docs/requirements.md)
- [Instalação](docs/installation.md)
- [Arquitetura](docs/architecture.md)

## Conheça o Helix Sandbox NG

<a href="https://gethelix.org">Helix</a> for a better world!
