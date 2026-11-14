#!/usr/bin/env bash
# Demonstrates a zero-downtime rolling update and a rollback of a bad release on the running cluster.
#   scripts/k8s/rollout_demo.sh <API base URL>      e.g. http://localhost:18000
#
# 1. Rolling update: a config change creates a new ReplicaSet; maxUnavailable 0 + readiness probes keep the API
#    answering throughout (a background loop counts failed requests; it must stay 0).
# 2. Bad release: an image tag that does not exist. The new pod never becomes ready, the rollout times out, the old
#    pods keep serving, and `kubectl rollout undo` restores the previous revision (same as deploy.sh does in CD).
set -euo pipefail
API=${1:?API URL}
NS=flare

probe_loop() { # count failed requests while a rollout runs
  local fails=0 total=0
  while [ ! -f /tmp/flare_rollout_done ]; do
    total=$((total + 1))
    curl -fsS -m 3 "$API/health" >/dev/null 2>&1 || fails=$((fails + 1))
    sleep 0.3
  done
  echo "$total $fails" > /tmp/flare_rollout_counts
}

echo "== 1. rolling update (config change: FLARE_LOG_LEVEL=DEBUG)"
rm -f /tmp/flare_rollout_done /tmp/flare_rollout_counts
probe_loop &
kubectl -n $NS set env deploy/api FLARE_LOG_LEVEL=DEBUG
kubectl -n $NS annotate deploy/api kubernetes.io/change-cause="demo: log level DEBUG" --overwrite >/dev/null
kubectl -n $NS rollout status deploy/api --timeout=300s
touch /tmp/flare_rollout_done; wait
read -r total fails < /tmp/flare_rollout_counts
echo "requests during the rolling update: $total, failed: $fails"
[ "$fails" -eq 0 ] || { echo "FAIL: requests failed during the rolling update"; exit 1; }

echo "== 2. bad release (image tag that does not exist) -> rollout fails -> rollback"
GOOD=$(kubectl -n $NS get deploy api -o jsonpath='{.spec.template.spec.containers[0].image}')
kubectl -n $NS set image deploy/api api=ghcr.io/veenaphadtare12-ux/flare-api:does-not-exist
kubectl -n $NS annotate deploy/api kubernetes.io/change-cause="demo: bad image" --overwrite >/dev/null
if kubectl -n $NS rollout status deploy/api --timeout=60s; then
  echo "FAIL: the bad release should not become ready"; exit 1
fi
echo "rollout failed as expected; the old pods are still serving:"
curl -fsS -m 5 "$API/health" && echo
kubectl -n $NS get pods -l app=api
kubectl -n $NS rollout undo deploy/api
kubectl -n $NS rollout status deploy/api --timeout=300s
NOW=$(kubectl -n $NS get deploy api -o jsonpath='{.spec.template.spec.containers[0].image}')
[ "$NOW" = "$GOOD" ] || { echo "FAIL: image after rollback is $NOW, expected $GOOD"; exit 1; }
echo "rolled back to $NOW"

echo "== 3. back to the original configuration"
kubectl -n $NS set env deploy/api FLARE_LOG_LEVEL=INFO
kubectl -n $NS rollout status deploy/api --timeout=300s
kubectl -n $NS rollout history deploy/api
echo "ROLLOUT DEMO OK"
