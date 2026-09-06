#!/bin/bash
# Щоденний бекап бази тривог.
#
# Два принципи, обидва запозичені з ~/aurum/aurum-backup.sh:
#   1. Знімок робиться через VACUUM INTO, а не cat по файлу: база в режимі WAL
#      і пишеться збирачем щохвилини, тож проста копія може зловити її посеред транзакції.
#   2. Ротація виконується ТІЛЬКИ після валідного свіжого архіву — інакше серія
#      битих бекапів витіснила б справжні (так уже було з Aurum у серпні 2026).
set -euo pipefail

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

APP_DIR="${ALERTS_APP_DIR:-$HOME/air-alerts}"
DEST="${ALERTS_BACKUP_DIR:-$APP_DIR/backups}"
KEEP_DAYS="${ALERTS_KEEP_DAYS:-30}"
MIN_ROWS="${ALERTS_MIN_ROWS:-1000}"   # менше — вважаємо базу підозріло порожньою
LOG="$APP_DIR/backup.log"

mkdir -p "$DEST"
say() { echo "$(date '+%F %T') $*" >> "$LOG"; }
die() { say "ПОМИЛКА: $*"; echo "ПОМИЛКА: $*" >&2; exit 1; }

cd "$APP_DIR"

TMP="$(mktemp "$DEST/.tmp.XXXXXX")"
SNAP="/data/.backup-snapshot.db"
cleanup() {
    rm -f "$TMP"
    docker compose exec -T web sh -c "rm -f $SNAP" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Знімок + перевірка цілісності всередині контейнера. Назовні йде лише кількість рядків.
rows=$(docker compose exec -T web python - "$SNAP" "$MIN_ROWS" <<'PY'
import os, sqlite3, sys
snap, min_rows = sys.argv[1], int(sys.argv[2])
if os.path.exists(snap):
    os.remove(snap)
src = sqlite3.connect("/data/alerts.db", timeout=120)
src.execute("PRAGMA busy_timeout=120000")
src.execute("VACUUM INTO ?", (snap,))
src.close()
chk = sqlite3.connect(snap)
if chk.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
    sys.exit("integrity_check не пройдено")
n = chk.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
if n < min_rows:
    sys.exit(f"лише {n} тривог — менше порога {min_rows}")
if not chk.execute("SELECT COUNT(*) FROM regions").fetchone()[0]:
    sys.exit("порожній каталог регіонів")
chk.close()
print(n)
PY
) || die "знімок не пройшов перевірку: $rows"

rows="$(echo "$rows" | tr -d '\r')"

docker compose exec -T web sh -c "cat $SNAP" > "$TMP" || die "не вдалось вивантажити знімок"
[ -s "$TMP" ] || die "вивантажений знімок порожній"

OUT="$DEST/alerts-$(date +%F).db.gz"
gzip -c "$TMP" > "$OUT.part" && mv "$OUT.part" "$OUT"
chmod 600 "$OUT"
say "ok: $OUT, $rows тривог, $(stat -c%s "$OUT") байт"

# Ротація — лише тепер, коли свіжий архів перевірений.
find "$DEST" -maxdepth 1 -name 'alerts-*.db.gz' -mtime "+$KEEP_DAYS" -delete
say "ротація: лишилось $(find "$DEST" -maxdepth 1 -name 'alerts-*.db.gz' | wc -l) архівів"
