# Legacy (TCC v1)

Estes são os arquivos originais do TCC, mantidos **apenas como referência de
domínio** (estrutura das coleções FIWARE Orion `entities`/`csubs`, lógica de
detecção de adulteração e federação). **Não são executados** pela nova versão.

A implementação ativa fica em [`../src/helix_blockchain/`](../src/helix_blockchain).

Principais diferenças da v2:

| Aspecto            | v1 (legacy)                          | v2 (`src/`)                                  |
|--------------------|--------------------------------------|----------------------------------------------|
| Modelo             | Hash chain de nó único + PoW         | Blockchain permissionada BFT (IBFT/PBFT)     |
| Consenso           | Nenhum (mineração individual)        | Validadores + quórum 2/3, assinaturas Ed25519|
| Credenciais        | Hardcoded no código                  | Config via `.env`/pydantic-settings          |
| Persistência       | MySQL com SQL string                 | SQLAlchemy (SQLite/Postgres)                  |
| Testes             | Nenhum                               | pytest                                        |
| Python             | 3.6 (EOL)                            | 3.11+                                         |
