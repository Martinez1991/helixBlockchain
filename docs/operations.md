# Operações: persistência, backup e retenção

## Backend de persistência

`HELIX_STORAGE__URL` (SQLAlchemy) define onde a cadeia e o **journal de consenso**
(WAL) são gravados — ambos no mesmo banco:

- **SQLite** (`sqlite:///data/helix_chain.db`) — dev/single-node.
- **Postgres** (`postgresql+psycopg://user:pass@host:5432/helix`) — produção/HA.

O suporte a Postgres é exercitado no CI (job *Storage tests on Postgres*) via
`HELIX_TEST_DB_URL`, garantindo paridade de comportamento com o SQLite.

## Backup

A cadeia é **append-only e tamper-evident**, então um dump lógico é um backup
completo e verificável:

```bash
DATABASE_URL=postgresql://helix:pass@host:5432/helix ./scripts/backup.sh ./backups
```

Agende via cron ou `CronJob` do Kubernetes. Para **PITR** (point-in-time
recovery), combine com WAL archiving (WAL-G / pgBackRest).

## Retenção

- **Backups:** `RETENTION_DAYS` (default 14) no `backup.sh` poda dumps antigos.
- **Journal de consenso:** podado automaticamente — ao finalizar a altura `h`, o
  WAL de votos daquela altura é descartado (só o estado em-voo importa).
- **Cadeia:** cresce indefinidamente (append-only). Para horizontes longos,
  considere *checkpointing* (snapshot de estado + arquivamento de blocos antigos
  em armazenamento frio), preservando o último hash para continuidade da
  verificação. Não há expurgo de blocos por padrão — é uma decisão de governança
  (ver `docs/compliance/`).

## Restore

```bash
gunzip -c backups/helix-<stamp>.sql.gz | psql "$DATABASE_URL"
```

Após restaurar, valide a finalidade de cada bloco (`verify_finality`) ao recarregar.
