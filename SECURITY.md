# Política de segurança

## Versões suportadas

| Versão | Suporte |
|---|---|
| 0.3.x | ✅ |
| 0.2.x | ⚠️ correções críticas |
| 0.1.x (TCC/legacy) | ❌ |

## Reportar uma vulnerabilidade

**Não** abra uma issue pública. Use os **GitHub Security Advisories**
(*Security → Report a vulnerability*) deste repositório, ou contate o mantenedor
de forma privada.

Inclua: descrição, impacto, passos de reprodução e versão/commit afetados.
Faremos a triagem e responderemos com um prazo de correção.

## Escopo e modelo

O Helix garante **integridade** (não confidencialidade). Controles e limitações
estão em [docs/security.md](docs/security.md). Relevante:

- Consenso e registros são **assinados (Ed25519)**; finalidade por quórum.
- Endpoints P2P/admin exigem **token de cluster**; suporte a **TLS/mTLS**.
- Segredos devem vir de **arquivo/Vault/KMS** — nunca commitados.
- A cadeia é **append-only**: para dados pessoais, ver
  [docs/compliance/lgpd.md](docs/compliance/lgpd.md) (pseudonimização /
  crypto-shredding).

## Pipeline de segurança

CI executa SCA (pip-audit), secret scan (gitleaks), SAST (bandit/CodeQL), SBOM
(CycloneDX) e IaC scan (Trivy); Dependabot semanal. Ver
[.github/workflows/security.yml](.github/workflows/security.yml).
