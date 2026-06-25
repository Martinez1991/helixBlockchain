# Arquitetura (v2)

## Visão geral

O Helix Blockchain é um **ledger permissionado com consenso BFT** que registra,
de forma à prova de adulteração e acordada por múltiplos nós, a integridade dos
dados dos brokers FIWARE Orion (Helix Sandbox NG). Ele **não** cifra dados —
garante *integridade*, não confidencialidade.

Cada processo (`helix-node`) é um **validador** que:

1. monitora o broker Orion principal e seus brokers federados,
2. detecta adulteração comparando os valores federados com o broker principal,
3. propõe/valida blocos via consenso BFT, e
4. notifica adulterações **somente após** o bloco ser finalizado por consenso.

## Camadas

```
collectors/  ── coleta Orion (MongoDB) + detecção de adulteração (lógica pura testável)
      │
      ▼
network/     ── nó orquestrador + transporte P2P (HTTP) + servidor FastAPI
      │
      ▼
consensus/   ── motor BFT (IBFT/PBFT): validadores, mensagens assinadas, quórum
      │
      ▼
domain/      ── primitivas puras: cripto (Ed25519/SHA-256), Merkle, bloco, registros
      │
      ▼
storage/     ── persistência (SQLAlchemy: SQLite/Postgres)
```

A regra de dependência aponta para baixo. `domain/` não tem I/O e é 100% testável.

## Modelo de consenso (IBFT/PBFT)

- Conjunto de **N validadores** conhecidos (permissionado). Tolera
  `f = (N−1)/3` validadores bizantinos; o **quórum** é `N − f`.
- O **proposer** de cada altura é escolhido por rodízio determinístico, então
  todos os nós honestos concordam sobre quem pode propor.
- Fluxo por altura `h` (caminho feliz):
  1. **PRE-PREPARE** — o proposer monta um bloco e o transmite.
  2. **PREPARE** — quem aceita a proposta transmite PREPARE; juntar `quórum`
     PREPAREs prova que um quórum viu a *mesma* proposta.
  3. **COMMIT** — ao atingir o quórum de PREPAREs, o validador trava o bloco e
     transmite COMMIT com seu *commit seal* (assinatura sobre o hash do bloco).
     Juntar `quórum` COMMITs **finaliza** o bloco.
- Os commit seals coletados viram o **certificado de finalidade** persistido no
  bloco — verificável de forma independente por `verify_finality()`.

### Por que BFT em vez de PoW (como na v1)?

Num cenário permissionado de IoT, Proof-of-Work só desperdiça CPU sem agregar
segurança (não há mineradores anônimos competindo). BFT dá **finalidade
imediata**, custo baixo e tolerância a nós maliciosos — o que blockchains
permissionadas reais usam (Hyperledger Besu IBFT, Quorum). A integridade do
conteúdo é garantida pela **árvore de Merkle** no cabeçalho do bloco.

## Detecção de adulteração

`IntegrityChecker` compara cada valor de atributo nos brokers federados com o
valor autoritativo do broker principal:

| Situação                                   | Veredito    |
|--------------------------------------------|-------------|
| valor federado == principal                | `OK`        |
| valor federado != principal (alterado)     | `TAMPERED`  |
| entidade/atributo só existe no federado     | `TAMPERED`  |

`RecordDeduper` evita registrar repetidamente observações idênticas (equivale ao
`monitora()` legado).

## Limitações conhecidas / trabalho futuro

- **Round-change não implementado.** O caminho feliz (segurança por certificado)
  está completo e testado. Se o *próximo proposer* estiver offline, o cluster
  não troca de rodada automaticamente e a altura corrente trava até ele voltar.
  Implementar o protocolo de ROUND_CHANGE (mensagem já modelada) é o próximo
  passo para liveness sob proposer faltante.
- **Mempool simples.** Registros pendentes são propostos pelo proposer da
  rodada; não há reconciliação de mempool entre nós (cada nó propõe o que
  coletou). Suficiente para o cenário, mas pode duplicar observações entre nós.
- **Sincronização de blocos** é sob demanda (ao ver mensagem de altura futura);
  não há gossip proativo de blocos.
- **TLS** entre validadores e com o MongoDB deve ser habilitado em produção
  (config `HELIX_ORION__TLS`; HTTPS via proxy reverso para o P2P).
