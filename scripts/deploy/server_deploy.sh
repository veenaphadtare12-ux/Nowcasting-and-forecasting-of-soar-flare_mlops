#!/usr/bin/env bash
# Runs ON the server (/opt/flare): deploy one image tag of the Compose stack with automatic rollback.
#   bash scripts/deploy/server_deploy.sh <tag>          deploy <tag>; on failure go back to the previous tag
#   bash scripts/deploy/server_deploy.sh --rollback     go back to the previous tag now
# Images come from GHCR (public). /opt/flare/.env (written by CD, never in git) holds SITE_ADDRESS, API keys, SMTP...
# The current and previous tags are kept in .current_tag / .previous_tag; older flare images are removed after success.
set -euo pipefail
cd /opt/flare
REPO=ghcr.io/veenaphadtare12-ux
mkdir -p data/raw_empty data/solexs_production   # copy new SoLEXS L1 day folders into data/solexs_production
CUR=$(cat .current_tag 2>/dev/null || true)
PREV=$(cat .previous_tag 2>/dev/null || true)

healthy() {  # API and website answer locally (Caddy and HTTPS are checked from outside by CD)
  for _ in $(seq 1 60); do
    if curl -fsS -m 5 http://127.0.0.1:8000/health >/dev/null 2>&1 && curl -fsS -m 5 http://127.0.0.1:8080/ >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  return 1
}

start() {  # start the stack on one tag
  FLARE_TAG="$1" docker compose pull --quiet api frontend prefect-server
  FLARE_TAG="$1" docker compose up -d --no-build --pull missing --remove-orphans
}

if [ "${1:-}" = "--rollback" ]; then
  [ -n "$PREV" ] || { echo "no previous tag to roll back to"; exit 1; }
  echo "rolling back: $CUR -> $PREV"
  start "$PREV"
  healthy || { echo "ROLLBACK UNHEALTHY"; docker compose ps; exit 1; }
  echo "$PREV" > .current_tag; echo "$CUR" > .previous_tag
  echo "ROLLBACK OK ($PREV)"
  exit 0
fi

TAG=${1:?image tag}
echo "deploying $TAG (current: ${CUR:-none})"
if start "$TAG" && healthy; then
  if [ -n "$CUR" ] && [ "$CUR" != "$TAG" ]; then echo "$CUR" > .previous_tag; fi
  echo "$TAG" > .current_tag
  KEEP_PREV=$(cat .previous_tag 2>/dev/null || true)
  for img in flare-api flare-frontend flare-prefect-server; do
    docker images "$REPO/$img" --format '{{.Tag}}' | { grep -vxE "$TAG|${KEEP_PREV:-none}" || true; } | while read -r t; do
      docker rmi "$REPO/$img:$t" >/dev/null 2>&1 && echo "removed old image $img:$t" || true
    done
  done
  docker compose ps --format '{{.Service}} {{.Status}}'
  echo "DEPLOY OK ($TAG)"
else
  echo "DEPLOY FAILED for $TAG"
  docker compose ps || true
  docker compose logs --tail 40 api || true
  if [ -n "$CUR" ]; then
    echo "automatic rollback to $CUR"
    start "$CUR" && healthy && echo "ROLLED BACK to $CUR" || echo "ROLLBACK ALSO FAILED"
  fi
  exit 1
fi
