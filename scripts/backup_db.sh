#!/usr/bin/env bash
# Back up the PostgreSQL database to a compressed file and delete old backups.
#
#   scripts/backup_db.sh [backup_dir]
#
# Run it from the project folder on the server (where docker-compose.yml is),
# for example every night from cron:
#   0 3 * * * cd /srv/peligrosa && scripts/backup_db.sh /srv/backups >> /var/log/peligrosa-backup.log 2>&1
#
# Settings (environment):
#   BACKUP_DIR        where to write (default ./backups; the argument wins)
#   BACKUP_KEEP_DAYS  delete backups older than this many days (default 14)
#   DUMP_COMMAND      command that prints the SQL dump
#                     (default: docker compose exec -T db pg_dump -U peligrosa peligrosa)
#
# Safe by design: the file is written under a temporary name, checked, and only
# then renamed; old backups are deleted only after a NEW good backup exists, so
# a failing dump can never leave you with fewer backups. Files are readable by
# the owner only (they contain users' chats). Copy them off this machine too.
set -euo pipefail

BACKUP_DIR="${1:-${BACKUP_DIR:-./backups}}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
DUMP_COMMAND="${DUMP_COMMAND:-docker compose exec -T db pg_dump -U peligrosa peligrosa}"

case "$KEEP_DAYS" in
  ''|*[!0-9]*) echo "BACKUP_KEEP_DAYS must be a whole number." >&2; exit 2 ;;
esac

umask 077
mkdir -p "$BACKUP_DIR"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
raw="$BACKUP_DIR/.peligrosa-$stamp.sql.part"
tmp="$BACKUP_DIR/.peligrosa-$stamp.sql.gz.part"
final="$BACKUP_DIR/peligrosa-$stamp.sql.gz"
trap 'rm -f "$raw" "$tmp"' EXIT

# shellcheck disable=SC2086  # DUMP_COMMAND is meant to be split into words
$DUMP_COMMAND > "$raw"

if [ ! -s "$raw" ]; then
  echo "The dump is empty: no backup was made and nothing was deleted." >&2
  exit 1
fi

gzip -c "$raw" > "$tmp"
gzip -t "$tmp"
mv "$tmp" "$final"

find "$BACKUP_DIR" -maxdepth 1 -type f -name 'peligrosa-*.sql.gz' -mtime +"$KEEP_DAYS" -delete

echo "Backup written: $final"
