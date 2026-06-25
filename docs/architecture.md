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

### Round change (liveness sob proposer faltante)

Se uma altura não fecha a tempo, cada nó chama `on_timeout()` e transmite uma
mensagem **ROUND_CHANGE** para a próxima rodada, escolhendo um novo proposer por
rodízio. Dois limiares governam a transição:

- **f+1 ROUND_CHANGE** para uma rodada maior → o nó "acelera" enviando o seu
  próprio (garante que nós atrasados avancem).
- **quórum ROUND_CHANGE** → o nó adota a nova rodada; seu proposer assume.

**Segurança preservada por certificados.** Cada ROUND_CHANGE carrega um
*prepared certificate* — um quórum de mensagens PREPARE provando qual valor o
remetente travou (se travou). O novo proposer **re-propõe o valor travado de
maior rodada** entre o quórum de ROUND_CHANGE (ou um bloco novo, se nada estava
travado), e anexa esse *round-change certificate* ao PRE_PREPARE para que todos
verifiquem. Sem o prepared certificate, um nó bizantino poderia mentir sobre um
valor travado e sequestrar a próxima proposta — por isso a prova é obrigatória.

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

### Mempool e gossip

- **Reconciliação de mempool (gossip de registros).** Cada nó coleta do seu
  próprio Orion. Ao observar registros novos, ele os compartilha com os peers
  (`POST /mempool`). Assim, uma adulteração detectada por um nó que **não** é o
  proposer da rodada ainda chega a quem vai propor, e entra na cadeia. Um
  conjunto `mempool_seen` (por id de registro) impede laços de gossip e
  re-inclusão de registros já commitados.
- **Gossip proativo de blocos.** Ao finalizar um bloco, o nó o **empurra** aos
  peers (`POST /block`), além do pull sob demanda (`fetch_block`). Um nó que
  perdeu as rodadas de consenso recebe o bloco imediatamente; lacunas maiores
  ainda são preenchidas pelo pull-sync.

## Limitações conhecidas / trabalho futuro

- **TLS** entre validadores e com o MongoDB deve ser habilitado em produção
  (config `HELIX_ORION__TLS`; HTTPS via proxy reverso para o P2P).
- **Autenticação dos endpoints de gossip.** `/mempool` e `/block` aceitam
  payloads de qualquer origem alcançável; em produção, restrinja a rede dos
  validadores e/ou exija mTLS. Mensagens de consenso já são assinadas por nó.
- **Conjunto de validadores estático.** Adição/remoção de validadores exige
  reconfiguração e reinício; não há mudança dinâmica de membership on-chain.
