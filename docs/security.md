# Modelo de segurança

O Helix garante **integridade** (não confidencialidade) dos dados de IoT. Esta
página consolida os controles. Reporte de vulnerabilidades: [../SECURITY.md](https://github.com/Martinez1991/helixBlockchain/blob/master/SECURITY.md).

## Superfície e identidades

- Cada validador tem uma identidade **Ed25519**. Mensagens de consenso são
  **assinadas** por nó — um nó bizantino não forja votos de um nó honesto.
- A rede é **permissionada**: o conjunto de validadores é conhecido e acordado
  on-chain (ver [architecture.md](architecture.md)).

## Autenticação dos endpoints

- Endpoints mutáveis (`/consensus`, `/mempool`, `/membership`, `/block`,
  `/peers`, `/admin/*`) exigem um **token de cluster** (Bearer), comparado em
  **tempo constante**. Endpoints de leitura ficam abertos (blocos
  auto-verificáveis).
- **Rotação:** `HELIX_CLUSTER_TOKEN` aceita uma lista separada por vírgula
  (`novo,antigo`); o servidor aceita qualquer um, o transporte envia o primeiro.

## Integridade dos registros (anti-injeção)

- Cada `IntegrityRecord` carrega `observer` (pubkey) + assinatura **Ed25519**
  sobre o conteúdo da observação. Na ingestão (`/mempool` e local), registros
  **não assinados por um validador atual são descartados** — posse do token não
  basta para injetar relatos falsos.
- A cadeia armazena `value_hash` (não o valor bruto) → minimização de dados.

## Segurança do consenso

- **Finalidade** por quórum de *commit seals* (assinaturas sobre o hash do
  bloco), verificável de forma independente (`verify_finality`).
- **Crash-recovery seguro (WAL):** votos e o *lock* (prepared) são persistidos
  antes de transmitir; após restart o nó **recusa votos conflitantes** e restaura
  o lock — sem equivocação.
- **Round-change** preserva safety via certificados de *prepared*/*round-change*.
- **Robustez:** parsing de mensagens nunca lança em entrada malformada (validado
  por **fuzzing** — ver [../specs/README.md](https://github.com/Martinez1991/helixBlockchain/blob/master/specs/README.md)).

## Transporte (TLS / mTLS)

- P2P pode rodar sobre **HTTPS** (`HELIX_TLS__*`), com **mTLS** opcional (cada
  validador apresenta e exige certificado de cliente, verificado contra a CA).
- MongoDB do Orion aceita CA própria (`HELIX_ORION__TLS_CA_FILE`).
- Gere certs de dev: `python -m helix_blockchain.tools.gen_certs ./certs node-1 …`.

## Gestão de segredos

- Chave privada e token via **arquivo** (`*_FILE`) — Docker/k8s secret,
  Vault/KMS, External Secrets — **nunca** inline em produção.
- O repositório **não versiona segredos**; o demo gera `.env` (gitignored) com
  `scripts/gen_dev_secrets.py`.

## Disponibilidade / abuso

- **Rate limiting** por origem (token-bucket → 429), **limite de payload**
  (→ 413) e **backpressure** na fila de inbound (→ 503).

## Auditoria

- Logger **`helix.audit`**: uma entrada por acesso a endpoint sensível
  (method, path, client, authenticated, status). Encaminhe ao SIEM.

## Pipeline DevSecOps (CI)

`.github/workflows/security.yml`: **SCA** (pip-audit), **secret scan**
(gitleaks), **SAST** (bandit + CodeQL), **SBOM** (CycloneDX), **IaC/container
scan** (Trivy); **Dependabot** semanal.

## Limitações conhecidas

- Token de cluster é **compartilhado** (não identidade por nó no HTTP); o
  consenso já é assinado por nó. Considere mTLS para identidade de transporte.
- A cadeia é append-only: para o "direito ao esquecimento", use pseudonimização
  + *crypto-shredding* (ver [compliance/lgpd.md](compliance/lgpd.md)).
