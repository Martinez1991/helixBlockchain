# Documentação — Helix Blockchain

Índice da documentação da v0.3.0.

## Visão geral e arquitetura
- [architecture.md](architecture.md) — camadas, consenso BFT (IBFT/PBFT),
  round-change, mempool/gossip, membership dinâmico, descoberta de peers e
  segurança da camada P2P.

## Uso e operação
- [installation.md](installation.md) — instalação (Docker e manual).
- [requirements.md](requirements.md) — requisitos de hardware/software e portas.
- [configuration.md](configuration.md) — referência completa das variáveis `HELIX_*`.
- [api.md](api.md) — referência da API HTTP (P2P, leitura, prova Merkle, admin).
- [operations.md](operations.md) — persistência, backup, retenção e restore.
- [observability.md](observability.md) — métricas, alertas, dashboards e tracing.

## Segurança e governança
- [security.md](security.md) — modelo de segurança consolidado.
- [compliance/lgpd.md](compliance/lgpd.md) — mapeamento LGPD.
- [compliance/data-classification.md](compliance/data-classification.md) —
  classificação de dados e mapa ISO 27001 / NIST / SOC 2.

## Desenvolvimento
- [development.md](development.md) — ambiente, testes, lint, arquitetura e contribuição.
- [../CONTRIBUTING.md](../CONTRIBUTING.md) — como contribuir.
- [../SECURITY.md](../SECURITY.md) — política de segurança / reporte de vulnerabilidades.
- [../CHANGELOG.md](../CHANGELOG.md) — histórico de versões.

## Deploy e verificação
- [../deploy/helm/helix/README.md](../deploy/helm/helix/README.md) — chart Helm (HA).
- [../specs/README.md](../specs/README.md) — verificação formal (TLA+) e fuzzing.
- [../ops/](../ops/) — dashboard Grafana e regras de alerta Prometheus.

## Histórico
- [../legacy/README.md](../legacy/README.md) — código original do TCC (referência).
