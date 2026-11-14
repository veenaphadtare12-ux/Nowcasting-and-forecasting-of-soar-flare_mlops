#!/usr/bin/env bash
# Smoke test against a running deployment (kind or server).
#   scripts/k8s/smoke.sh <website base URL> [API base URL]
set -euo pipefail
WEB=${1:?website URL}
API=${2:-$WEB/api}

check() { # name url jq-like grep
  local name=$1 url=$2 want=$3 body
  for _ in $(seq 1 30); do
    if body=$(curl -fsS -m 10 "$url" 2>/dev/null) && grep -q "$want" <<<"$body"; then
      echo "OK    $name"; return 0
    fi
    sleep 4
  done
  echo "FAIL  $name ($url)"; return 1
}

check "website"            "$WEB/"               "<div id=\"root\""
check "api health"         "$API/health"         '"status":"ok"'
check "api via website"    "$WEB/api/models"     '"target"'
check "replay days"        "$API/replay/days"    '2026-04-24'
check "metrics"            "$API/metrics"        'flare_api_requests_total'
echo "SMOKE OK"
