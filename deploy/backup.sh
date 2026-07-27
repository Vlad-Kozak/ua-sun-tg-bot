#!/usr/bin/env bash
# Гарячий бекап SQLite. Просте копіювання файлу під час роботи бота може
# дати побитий знімок, тому використовуємо .backup / backup API.
#
# Cron щодня о 4:00:
#   0 4 * * * /app/ua-sun-tg-bot/deploy/backup.sh >> /var/log/ua-sun-backup.log 2>&1
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${DB_PATH:-$ROOT_DIR/data/bot.db}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"

if [[ ! -f "$DB_PATH" ]]; then
    echo "Немає файлу БД: $DB_PATH" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
TARGET="$BACKUP_DIR/bot-$STAMP.db"

if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB_PATH" ".backup '$TARGET'"
else
    python3 - "$DB_PATH" "$TARGET" <<'PY'
import sqlite3
import sys

source_path, target_path = sys.argv[1], sys.argv[2]
source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
target = sqlite3.connect(target_path)
with target:
    source.backup(target)
target.close()
source.close()
PY
fi

gzip -f "$TARGET"
echo "Бекап: $TARGET.gz"

find "$BACKUP_DIR" -name 'bot-*.db.gz' -type f -mtime "+$KEEP_DAYS" -delete
