#!/usr/bin/env bash
# Deploy the manifests with a given image tag and roll back automatically if any rollout fails.
# Used by the kind script, the CI kind job and the CD workflow (on the k3s server).
#
#   scripts/k8s/deploy.sh <overlay: kind|prod> <image tag>
#
# Needs: kubectl pointed at the cluster. Optional env: GRAFANA_ADMIN_PASSWORD (else a random one is generated once),
# ROLLOUT_TIMEOUT (default 300s).
set -euo pipefail
OVERLAY=${1:?overlay (kind|prod)}
TAG=${2:?image tag}
NS=flare
TIMEOUT=${ROLLOUT_TIMEOUT:-300s}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"
DEPLOYS="mlflow prefect-server prometheus alertmanager grafana api worker frontend"

kubectl apply -f k8s/base/namespace.yaml

# Private GHCR packages: a pull secret from GHCR_PULL_TOKEN (a GitHub token with read:packages), never committed.
if [ -n "${GHCR_PULL_TOKEN:-}" ]; then
  kubectl -n $NS create secret docker-registry ghcr-pull --docker-server=ghcr.io \
    --docker-username="${GHCR_USER:-veenaphadtare12-ux}" --docker-password="$GHCR_PULL_TOKEN" --dry-run=client -o yaml | kubectl apply -f -
  kubectl -n $NS patch serviceaccount default -p '{"imagePullSecrets":[{"name":"ghcr-pull"}]}'
fi

# ConfigMaps from monitoring/ (one source of truth with Docker Compose) and the Grafana admin Secret (never in git).
kubectl -n $NS create configmap prometheus-config --from-file=monitoring/prometheus --dry-run=client -o yaml | kubectl apply -f -
kubectl -n $NS create configmap grafana-datasources --from-file=monitoring/grafana/provisioning/datasources --dry-run=client -o yaml | kubectl apply -f -
kubectl -n $NS create configmap grafana-dashboard-provider --from-file=monitoring/grafana/provisioning/dashboards --dry-run=client -o yaml | kubectl apply -f -
kubectl -n $NS create configmap alertmanager-config --from-file=monitoring/alertmanager --dry-run=client -o yaml | kubectl apply -f -
kubectl -n $NS create configmap grafana-dashboards --from-file=monitoring/grafana/dashboards --dry-run=client -o yaml | kubectl apply -f -
if [ -n "${GRAFANA_ADMIN_PASSWORD:-}" ]; then
  kubectl -n $NS create secret generic grafana-admin --from-literal=password="$GRAFANA_ADMIN_PASSWORD" --dry-run=client -o yaml | kubectl apply -f -
elif ! kubectl -n $NS get secret grafana-admin >/dev/null 2>&1; then
  kubectl -n $NS create secret generic grafana-admin --from-literal=password="$(head -c 18 /dev/urandom | base64 | tr -d '/+=')"
  echo "created Secret grafana-admin with a random password (read it: kubectl -n $NS get secret grafana-admin -o jsonpath='{.data.password}' | base64 -d)"
fi

# API keys for POST /predict (GitHub secret FLARE_API_KEYS in CD); without it /predict refuses every call (fail closed).
if [ -n "${FLARE_API_KEYS:-}" ]; then
  kubectl -n $NS create secret generic flare-api-keys --from-literal=FLARE_API_KEYS="$FLARE_API_KEYS" --dry-run=client -o yaml | kubectl apply -f -
fi
# Optional SMTP settings for Alertmanager (GitHub secrets SMTP_*, ALERT_EMAIL_TO).
if [ -n "${SMTP_SMARTHOST:-}" ]; then
  kubectl -n $NS create secret generic alertmanager-smtp --from-literal=SMTP_SMARTHOST="$SMTP_SMARTHOST"     --from-literal=SMTP_FROM="${SMTP_FROM:-}" --from-literal=SMTP_USERNAME="${SMTP_USERNAME:-}"     --from-literal=SMTP_PASSWORD="${SMTP_PASSWORD:-}" --from-literal=ALERT_EMAIL_TO="${ALERT_EMAIL_TO:-}"     --dry-run=client -o yaml | kubectl apply -f -
fi

# Temporary overlay that pins the image tag (the committed overlays stay tag-free).
BUILD=$(mktemp -d "$ROOT/k8s/.build.XXXXXX")   # inside k8s/: kustomize only accepts relative resource paths
trap 'rm -rf "$BUILD"' EXIT
cat > "$BUILD/kustomization.yaml" <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../overlays/$OVERLAY
images:
  - name: ghcr.io/veenaphadtare12-ux/flare-api
    newTag: "$TAG"
  - name: ghcr.io/veenaphadtare12-ux/flare-frontend
    newTag: "$TAG"
  - name: ghcr.io/veenaphadtare12-ux/flare-prefect-server
    newTag: "$TAG"
EOF

# Remember the current revision of every deployment (for the rollback message).
declare -A BEFORE
for d in $DEPLOYS; do
  BEFORE[$d]=$(kubectl -n $NS get deploy "$d" -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}' 2>/dev/null || echo none)
done

# The seed Job is immutable once created: replace it on every deploy.
kubectl -n $NS delete job mlflow-seed --ignore-not-found
kubectl kustomize "$BUILD" | kubectl apply -f -
kubectl -n $NS annotate deploy api frontend worker kubernetes.io/change-cause="deploy $TAG" --overwrite >/dev/null

failed=""
for d in $DEPLOYS; do
  if ! kubectl -n $NS rollout status deploy/"$d" --timeout="$TIMEOUT"; then
    failed="$failed $d"
  fi
done

if [ -n "$failed" ]; then
  echo "ROLLOUT FAILED:$failed -> automatic rollback"
  kubectl -n $NS get pods -o wide || true
  for d in $failed; do
    kubectl -n $NS describe deploy "$d" | tail -20 || true
    if [ "${BEFORE[$d]}" != "none" ]; then
      kubectl -n $NS rollout undo deploy/"$d"
      kubectl -n $NS rollout status deploy/"$d" --timeout="$TIMEOUT" || true
      echo "rolled back $d to the previous revision (was revision ${BEFORE[$d]})"
    else
      echo "$d had no previous revision: nothing to roll back to"
    fi
  done
  exit 1
fi

kubectl -n $NS wait --for=condition=complete job/mlflow-seed --timeout="$TIMEOUT" || echo "warning: mlflow-seed job not complete yet"
kubectl -n $NS get deploy,svc,pvc
echo "DEPLOY OK ($OVERLAY, tag $TAG)"
