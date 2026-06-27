# Contribuindo

Obrigado por contribuir com o Helix Blockchain!

## Fluxo

1. Crie uma branch a partir de `master`.
2. Faça as mudanças com **testes** (mantenha a suíte verde).
3. Garanta `ruff check src tests` e `pytest` limpos localmente.
4. Abra um PR — o CI roda testes+lint, Postgres, SonarQube e o workflow de
   segurança (SCA, secret scan, SAST, SBOM, IaC).

## Ambiente e padrões

Veja [docs/development.md](docs/development.md) para setup, arquitetura em
camadas e convenções (estilo `ruff`, `domain/` puro, Protocols, sem segredos no
código, serialização canônica).

## Mensagens de commit

Convencional: `feat(scope): …`, `fix(scope): …`, `docs: …`, `ci: …`, `test: …`.

## Segurança

Não abra issues públicas para vulnerabilidades — siga [SECURITY.md](SECURITY.md).

## Licença

Ao contribuir, você concorda em licenciar sua contribuição sob a licença **MIT**
do projeto.
