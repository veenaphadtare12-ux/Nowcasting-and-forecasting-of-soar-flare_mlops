#!/usr/bin/env bash
# End-to-end test of the whole product (docs/ARCHITECTURE.md section 4). Used by CI and by scripts/e2e.ps1.
#   scripts/e2e.sh            build images, start the stack, run every check, leave the stack running
#   E2E_DOWN=1 scripts/e2e.sh stop the stack (and delete its volumes) at the end
#   E2E_FRESH=1 scripts/e2e.sh start from empty volumes (CI). Locally the named volumes are kept (never deleted).
# Production path: inbox day -> Prefect deployment daily_ingest (run by the worker) -> pandera -> features -> champions
# -> predictions store -> API /production/latest -> frontend. Replay path: score_replay -> store -> API /replay (source=store).
set -euo pipefail
cd "$(dirname "$0")/.."
export FLARE_TAG="${FLARE_TAG:-$(git rev-parse --short=12 HEAD)}"
export FLARE_PRODUCTION_START=2026-02-21      # TEST ONLY: lets a development day stand in for a new production day
DAY=2026-02-21                                # quiet development day from the model bundle (tune period)
REPLAY_DAY=2026-04-24
API=${API:-http://localhost:8000}
FRONTEND=${FRONTEND:-http://localhost:8080}
PROM=${PROM:-http://localhost:9090}
step() { printf '\n== %s\n' "$*"; }
fail() { printf 'E2E FAILED: %s\n' "$*" >&2; docker compose ps >&2 || true; docker compose logs --tail 60 api worker >&2 || true; exit 1; }
wait_for() {  # url, seconds
  for _ in $(seq 1 "$2"); do curl -fsS -m 5 "$1" >/dev/null 2>&1 && return 0; sleep 1; done; fail "timeout waiting for $1"
}
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1]))" "$1"; }

step "build images (tag $FLARE_TAG)"
if [ "${E2E_SKIP_BUILD:-0}" != "1" ]; then docker compose build api frontend prefect-server; fi

step "start the stack (production start overridden to $DAY for the test)"
if [ "${E2E_FRESH:-0}" = "1" ]; then
  docker compose down --volumes --remove-orphans >/dev/null 2>&1 || true
else
  docker compose down --remove-orphans >/dev/null 2>&1 || true
fi
docker compose up -d
wait_for "$API/health" 240
wait_for "$FRONTEND/" 60
docker compose wait mlflow-seed >/dev/null || fail "mlflow-seed failed"

step "smoke test every API endpoint"
curl -fsS "$API/health" | json "d['status']" | grep -q ok || fail "/health"
[ "$(curl -fsS "$API/models" | json 'len(d)')" = "5" ] || fail "/models"
[ "$(curl -fsS "$API/replay/days" | json 'len(d)')" = "5" ] || fail "/replay/days"
curl -fsS "$API/replay/$REPLAY_DAY?until=${REPLAY_DAY}T09:00:00Z&step=6" | json "len(d['predictions']['now']['p_flare'])>10" | grep -q True || fail "/replay"
curl -fsS -N -m 60 "$API/replay/$DAY/stream?speed=600&step=60&start=${DAY}T23:00:00Z" | grep -q "event: end" || fail "/replay/stream"
curl -fsS "$API/results" | json "d['test']['targets']['now']['tss']>0" | grep -q True || fail "/results"
curl -fsS "$API/drift/latest" | json "'drifted_share' in d" | grep -q True || fail "/drift/latest"
curl -fsS "$API/pipeline/status" | json "d['mlflow']['models']['flare-nowcast']['champion']" | grep -q 1 || fail "MLflow champion not visible"
curl -fsS "$API/pipeline/status" | json "len(d['prefect']['deployments'])>=3" | grep -q True || fail "Prefect deployments missing"
curl -fsS "$API/metrics" | grep -q flare_api_requests_total || fail "/metrics"
if [ "${E2E_FRESH:-0}" = "1" ]; then
  [ "$(curl -fsS "$API/production/latest" | json "d['status']")" = "no_data" ] || fail "production should start empty"
fi

step "production: put a new day into the inbox and run the daily_ingest deployment through Prefect"
docker compose run --rm -T tools python -c "
from src.serving import bundle as B
b = B.load()
b.table('$DAY', 'inputs_solexs_1s').astype('float64').to_parquet('/data/inbox/$DAY.parquet')
print('inbox ready')"
docker compose run --rm -T tools prefect deployment run daily_ingest/daily --watch --watch-timeout 600 || fail "daily_ingest deployment run failed"
r=$(curl -fsS "$API/production/latest")
[ "$(echo "$r" | json "d['status']")" = "ok" ] || fail "production day not served"
[ "$(echo "$r" | json "d['day']")" = "$DAY" ] || fail "wrong production day"
echo "$r" | json "sorted(d['predictions'])" | grep -q "c_60m" || fail "production predictions missing"
echo "production: $(echo "$r" | json "{t: v['alerts'] for t, v in d['summary']['targets'].items()}") alerts on $DAY"

step "replay: score_replay writes the store, the API serves it (source=store)"
docker compose run --rm -T tools python -m flows.score_replay --day "$REPLAY_DAY" >/dev/null || fail "score_replay"
[ "$(curl -fsS "$API/replay/$REPLAY_DAY?until=${REPLAY_DAY}T06:00:00Z" | json "d['source']")" = "store" ] || fail "store predictions not served"

step "drift: check_drift writes the summary the API serves"
docker compose run --rm -T tools python -m flows.check_drift >/dev/null || fail "check_drift"
curl -fsS "$API/drift/latest" | json "d.get('mode')" | grep -q bundle || fail "drift summary not from the flow"

step "frontend and monitoring"
curl -fsS "$FRONTEND/" | grep -q '<div id="root">' || fail "frontend index"
curl -fsS "$FRONTEND/api/health" | json "d['status']" | grep -q ok || fail "frontend -> API proxy"
for _ in $(seq 1 30); do
  n=$(curl -fsS "$PROM/api/v1/query?query=flare_api_requests_total" | json "len(d['data']['result'])" || echo 0)
  [ "$n" -gt 0 ] && break; sleep 3
done
[ "$n" -gt 0 ] || fail "Prometheus has no API metrics"
curl -fsS "http://localhost:3000/api/health" | json "d['database']" | grep -q ok || fail "Grafana"

if [ "${E2E_DOWN:-0}" = "1" ]; then
  docker compose down --volumes
else
  step "restore the real production start (the test override must not stay active)"
  env -u FLARE_PRODUCTION_START docker compose up -d api worker >/dev/null
  wait_for "$API/health" 240
fi
printf '\nE2E PASSED (%s)\n' "$FLARE_TAG"
