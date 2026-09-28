#!/usr/bin/env bash
# Nightly Postgres dump of the BlockID app database (blockid-app-postgres-1).
# Run by deploy/systemd/blockid-backup.{service,timer}. Keeps KEEP_DAYS days in
# BACKUP_DIR. Set GCS_BUCKET (gs://...) in /etc/blockid/backup.env to also copy
# each dump off the VM (needs a service account with storage write scope).
# Restore: gunzip -c FILE | docker exec -i blockid-app-postgres-1 psql -U blockid blockid
set -euo pipefail
BACKUP_DIR="${BACKUP_DIR:-/var/backups/blockid}"
KEEP_DAYS="${KEEP_DAYS:-14}"
CONTAINER="${CONTAINER:-blockid-app-postgres-1}"
GCS_BUCKET=""
# shellcheck disable=SC1091
[[ -r /etc/blockid/backup.env ]] && source /etc/blockid/backup.env

install -d -m 700 "$BACKUP_DIR"
out="$BACKUP_DIR/pg-blockid-$(date -u +%Y%m%dT%H%MZ).sql.gz"
tmp="$out.partial"
docker exec "$CONTAINER" pg_dump -U blockid --no-owner blockid | gzip -9 >"$tmp"
# refuse to keep an empty or truncated dump
gunzip -t "$tmp"
gunzip -c "$tmp" | tail -n 5 | grep -q "PostgreSQL database dump complete" \
  || { echo "backup: dump incomplete" >&2; rm -f "$tmp"; exit 1; }
mv "$tmp" "$out"; chmod 600 "$out"
echo "backup: wrote $out ($(du -h "$out" | cut -f1))"
if [[ -n "$GCS_BUCKET" ]]; then
  gcloud storage cp "$out" "$GCS_BUCKET/" && echo "backup: copied to $GCS_BUCKET"
fi
find "$BACKUP_DIR" -name 'pg-blockid-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
