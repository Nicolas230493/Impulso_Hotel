#!/usr/bin/env bash
# Backup diario de PostgreSQL con prueba de restauración. Programar con cron: 0 3 * * * /app/scripts/backup.sh
set -euo pipefail
DESTINO="${BACKUP_DIR:-/var/backups/impulso}"
FECHA="$(date +%F)"
mkdir -p "$DESTINO"
ARCHIVO="$DESTINO/impulso_$FECHA.dump"
export PGPASSWORD="${POSTGRES_PASSWORD:-impulso}"
CONN=(-h "${POSTGRES_HOST:-localhost}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-impulso}")
pg_dump "${CONN[@]}" -Fc "${POSTGRES_DB:-impulso}" -f "$ARCHIVO"
# Prueba de restauración en una base temporal
PRUEBA="impulso_restore_test"
dropdb "${CONN[@]}" --if-exists "$PRUEBA"
createdb "${CONN[@]}" "$PRUEBA"
pg_restore "${CONN[@]}" -d "$PRUEBA" "$ARCHIVO"
RESERVAS=$(psql "${CONN[@]}" -d "$PRUEBA" -tAc "select count(*) from reservas")
dropdb "${CONN[@]}" "$PRUEBA"
echo "$FECHA backup OK ($ARCHIVO), restauración verificada: $RESERVAS reservas"
find "$DESTINO" -name 'impulso_*.dump' -mtime +30 -delete
