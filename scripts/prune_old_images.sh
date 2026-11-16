#!/usr/bin/env bash
# Delete every flare-api / flare-frontend image tag except the one given (called by scripts\up.ps1 only after the new
# stack started and the smoke test passed). Never touches volumes, other images or the build cache.
#   scripts/prune_old_images.sh <tag to keep>
set -euo pipefail
KEEP=${1:?tag to keep}
REPO=ghcr.io/veenaphadtare12-ux
for img in flare-api flare-frontend flare-prefect-server; do
  docker images "$REPO/$img" --format '{{.Tag}}' | { grep -vx "$KEEP" || true; } | while read -r t; do
    docker rmi "$REPO/$img:$t" >/dev/null && echo "removed $REPO/$img:$t"
  done
done
