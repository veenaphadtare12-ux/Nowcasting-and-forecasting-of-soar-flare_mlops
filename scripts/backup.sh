#!/usr/bin/env bash
# Back up the product's state: every named Docker volume -> one .tar.gz each + manifest (SHA-256, file counts).
#   scripts/backup.sh [backup root]          default root: /mnt/d/backups/flare  (D:\backups\flare on Windows)
# Consistency: the services that write (api, worker, mlflow, prefect-server, prometheus, grafana, alertmanager) are
# frozen with `docker compose pause` while the archives are written (a few seconds), then resumed. SQLite databases
# (MLflow, Prefect, Grafana, predictions) are therefore never copied half-written. Prints the backup folder.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=${1:-/mnt/d/backups/flare}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DEST="$ROOT/$STAMP"
PROJECT=flare
VOLUMES="mlflow predictions drift inbox prefect grafana prometheus alertmanager"
WRITERS="api worker mlflow prefect-server prometheus grafana alertmanager"
mkdir -p "$DEST"

running=$(docker compose ps --status running --services 2>/dev/null | tr '\n' ' ')
to_pause=""
for s in $WRITERS; do case " $running " in *" $s "*) to_pause="$to_pause $s" ;; esac; done
resume() { [ -n "$to_pause" ] && docker compose unpause $to_pause >/dev/null 2>&1 || true; }
trap resume EXIT
[ -n "$to_pause" ] && docker compose pause $to_pause >/dev/null

echo "{" > "$DEST/manifest.json"
echo "  \"created_utc\": \"$STAMP\", \"git_sha\": \"$(git rev-parse --short=12 HEAD 2>/dev/null || echo unknown)\"," >> "$DEST/manifest.json"
echo "  \"volumes\": {" >> "$DEST/manifest.json"
first=1
for v in $VOLUMES; do
  vol="${PROJECT}_$v"
  if ! docker volume inspect "$vol" >/dev/null 2>&1; then echo "skip $vol (does not exist)"; continue; fi
  docker run --rm -v "$vol":/src:ro -v "$DEST":/backup alpine:3.22 \
    sh -c "cd /src && tar czf /backup/$v.tar.gz . && find . -type f | wc -l > /backup/$v.files"
  sum=$(sha256sum "$DEST/$v.tar.gz" | cut -d' ' -f1)
  files=$(cat "$DEST/$v.files"); rm -f "$DEST/$v.files"
  size=$(stat -c %s "$DEST/$v.tar.gz")
  [ $first -eq 1 ] || echo "," >> "$DEST/manifest.json"
  printf '    "%s": {"archive": "%s.tar.gz", "sha256": "%s", "files": %s, "bytes": %s}' "$v" "$v" "$sum" "$files" "$size" >> "$DEST/manifest.json"
  first=0
  echo "backed up $vol: $files files, $size bytes"
done
printf '\n  }\n}\n' >> "$DEST/manifest.json"
resume; trap - EXIT
echo "BACKUP OK $DEST"
