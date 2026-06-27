#!/usr/bin/env bash
# Back up the Helix chain + consensus journal (Postgres).
#
# Usage:
#   DATABASE_URL=postgresql://helix:pass@host:5432/helix ./scripts/backup.sh [out_dir]
#
# The chain is append-only and tamper-evident, so a logical dump is a complete,
# verifiable backup. Schedule via cron/k8s CronJob. For point-in-time recovery
# use WAL archiving (e.g. WAL-G / pgBackRest) in addition to these dumps.
set -euo pipefail

OUT_DIR="${1:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
mkdir -p "$OUT_DIR"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$OUT_DIR/helix-${STAMP}.sql.gz"

echo "Dumping chain to $FILE ..."
pg_dump "${DATABASE_URL:?set DATABASE_URL}" --no-owner --clean --if-exists \
  | gzip -9 > "$FILE"

echo "Pruning backups older than ${RETENTION_DAYS} days ..."
find "$OUT_DIR" -name 'helix-*.sql.gz' -type f -mtime "+${RETENTION_DAYS}" -delete

echo "Done. Current backups:"
ls -lh "$OUT_DIR"/helix-*.sql.gz
