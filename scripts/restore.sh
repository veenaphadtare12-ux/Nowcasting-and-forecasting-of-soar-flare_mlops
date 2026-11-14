#!/usr/bin/env bash
# Restore volumes from a backup folder made by scripts/backup.sh.
#   scripts/restore.sh <backup folder> [volume ...]              restore into the live volumes (stack must be stopped)
#   RESTORE_PREFIX=flare_restoretest scripts/restore.sh <folder>  restore into NEW volumes <prefix>_<name> (verification)
# Every archive's SHA-256 is checked against the manifest before anything is written. Live volumes are only replaced
# when the stack is stopped (scripts\down.ps1), so a running service never sees its files change underneath it.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC=${1:?backup folder}
shift || true
PREFIX=${RESTORE_PREFIX:-flare}
[ -f "$SRC/manifest.json" ] || { echo "no manifest.json in $SRC"; exit 1; }
vols=${*:-$(python3 -c "import json,sys; print(' '.join(json.load(open(sys.argv[1]))['volumes']))" "$SRC/manifest.json")}

if [ "$PREFIX" = "flare" ] && [ -n "$(docker compose ps --status running -q 2>/dev/null)" ]; then
  echo "stop the stack first (scripts\\down.ps1), or set RESTORE_PREFIX to restore into new volumes"; exit 1
fi

for v in $vols; do
  want=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['volumes'][sys.argv[2]]['sha256'])" "$SRC/manifest.json" "$v")
  have=$(sha256sum "$SRC/$v.tar.gz" | cut -d' ' -f1)
  [ "$want" = "$have" ] || { echo "CHECKSUM MISMATCH for $v.tar.gz: refusing to restore"; exit 1; }
done

for v in $vols; do
  vol="${PREFIX}_$v"
  docker volume create "$vol" >/dev/null
  docker run --rm -v "$vol":/dst -v "$SRC":/backup:ro alpine:3.22 \
    sh -c "find /dst -mindepth 1 -delete && tar xzf /backup/$v.tar.gz -C /dst && find /dst -type f | wc -l" \
    | { read -r n; echo "restored $vol: $n files"; }
done
echo "RESTORE OK ($PREFIX)"
