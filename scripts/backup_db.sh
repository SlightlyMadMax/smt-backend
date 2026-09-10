#!/bin/bash
set -euo pipefail

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

export PGPASSWORD="$POSTGRES_PASSWORD"
export PGHOST="${PGHOST:-db}"

INTERVAL="${BACKUP_INTERVAL_SECONDS:-21600}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
DIR="${BACKUP_DIR:-/backups}"

mkdir -p "$DIR"
echo "Backing up $POSTGRES_DB every ${INTERVAL}s into $DIR, keeping ${KEEP_DAYS} days."

while true; do
    target="$DIR/${POSTGRES_DB}-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"

    if pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists | gzip >"$target.part"; then
        mv "$target.part" "$target"
        echo "$(date -u +%FT%TZ) wrote $target, $(stat -c %s "$target") bytes"
        find "$DIR" -name "${POSTGRES_DB}-*.sql.gz" -mtime "+$KEEP_DAYS" -delete
    else
        rm -f "$target.part"
        echo "$(date -u +%FT%TZ) pg_dump failed, keeping the previous backups" >&2
    fi

    sleep "$INTERVAL"
done
