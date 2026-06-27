# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
versionamento [SemVer](https://semver.org/lang/pt-BR/).

## [0.4.0] — 2026-06-27 — Console web + confidencialidade

### Added
- **Console web read-only** em `GET /ui` (SPA estática, sem build): board do
  cluster (altura/round/lag/validador por nó), explorer de blocos com drill-down,
  feed de adulterações, **aba Validadores** (evolução do conjunto com gráfico),
  **aba Ações** (com token: submeter registros OK/TAMPERED, add/remove validador)
  e **verificador de prova de Merkle no navegador**.
- **Confidencialidade alvo**:
  - `value_hash` como **commitment com chave** `HMAC(HELIX_COMMIT_KEY, valor)`
    — bloqueia força-bruta de valores de baixa entropia; fallback SHA-256 sem chave.
  - **Pseudonimização** opcional de `entity_id` (`HELIX_PSEUDONYMIZE_ENTITIES`)
    → `pid:HMAC(chave, id)`, suportando *crypto-shredding* (LGPD).
- `/admin/submit` aceita `verdict=OK|TAMPERED` (exercita o pipeline de adulteração).
- `/chain` expõe `round`; CORS para o console cruzar nós.
- Documentação at-rest/in-transit; chave de commit no compose/Helm/`gen_dev_secrets`.

### Changed
- Detecção continua nos valores brutos; só os campos **armazenados** ficam
  confidenciais (commitment determinístico → validadores ainda concordam).

## [0.3.0] — 2026-06-27 — Production hardening

Implementa todas as 15 issues da auditoria (#3–#17). 183 testes; CI verde.

### Added
- **WAL de votos de consenso** para crash-recovery seguro (anti-equivocação) (#3).
- **Assinatura Ed25519 de registros** de integridade; ingestão descarta não
  assinados/inválidos (anti-injeção no mempool) (#4).
- **Observabilidade**: `/metrics` Prometheus, dashboard Grafana e regras de
  alerta (#5); **tracing OpenTelemetry** no consenso (#11).
- **Segredos via arquivo** (`*_FILE`, Vault/KMS) e **rotação de token** (#6).
- **Coleta event-driven** via Mongo Change Streams + índices (#7).
- **Pipeline DevSecOps**: pip-audit, gitleaks, bandit, CodeQL, SBOM, Trivy +
  Dependabot (#8).
- **Rate limiting** (429), limite de payload (413) e **backpressure** (503) (#9).
- **Postgres testado em CI** + script de backup/retenção (#10).
- **Notificações** webhook/Slack/SIEM (#12).
- **Prova de inclusão Merkle** (`GET /proof/{h}/{i}`), verificável offline (#13).
- **Chart Helm** com HA (StatefulSet, PDB, probes, anti-affinity) (#14).
- **Spec TLA+** de safety + **fuzzing** (Hypothesis) (#15).
- **Bootstrap de genesis** a partir de um peer (#16).
- **Trilha de auditoria de acesso** + dossiê **LGPD**/classificação de dados (#17).

### Changed
- Imagem Docker roda como usuário **non-root** + healthcheck.
- `build_node` assíncrono; conjunto de validadores deduplica o próprio nó.

### Fixed
- `verify_signature`/`verify_finality`/`_valid_commit_seal` não lançam mais em
  hex malformado (bug encontrado pelo fuzzing).

## [0.2.0] — 2026-06-26 — Reescrita BFT

### Added
- **Consenso BFT** estilo IBFT/PBFT (proposer em rodízio, quórum `N−f`),
  **round-change** Bizantino-seguro com certificados.
- Integridade por **Ed25519** + **árvore de Merkle** + certificado de finalidade.
- Detecção de adulteração entre broker principal e federados (FIWARE Orion).
- **Membership dinâmico on-chain**, genesis auto-descritivo, mempool gossip,
  descoberta de peers.
- Arquitetura em camadas; config via pydantic-settings; Docker Compose.

### Changed
- Substitui o hash-chain de nó único + PoW do TCC por consenso multi-nó.
- Migração de MySQL para **SQLAlchemy** (SQLite/Postgres); Python 3.6 → 3.11+.

## [0.1.0] — TCC (legado)

Encadeamento de hashes de nó único com Proof-of-Work, integrado ao Helix
Sandbox NG. Preservado em [`legacy/`](legacy/).
