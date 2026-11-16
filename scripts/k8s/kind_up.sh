#!/usr/bin/env bash
# Local Kubernetes: create the kind cluster (if needed), load the images, deploy, smoke-test.
#
#   scripts/k8s/kind_up.sh <image tag>        e.g. the git SHA used by Docker Compose
#   scripts/k8s/kind_up.sh <image tag> --down delete the cluster afterwards
#
# Needs kind + kubectl + docker. URLs afterwards: website http://localhost:18080, API http://localhost:18000,
# Grafana :13000, Prometheus :19090, Prefect :14200, MLflow :15000.
set -euo pipefail
TAG=${1:?image tag}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"
REPO=ghcr.io/veenaphadtare12-ux

if ! kind get clusters 2>/dev/null | grep -qx flare; then
  kind create cluster --config k8s/kind/cluster.yaml --wait 120s
fi
kubectl config use-context kind-flare >/dev/null

# Our two images come from the local Docker engine; third-party images are pulled by the node.
kind load docker-image --name flare "$REPO/flare-api:$TAG" "$REPO/flare-frontend:$TAG" "$REPO/flare-prefect-server:$TAG"

bash scripts/k8s/deploy.sh kind "$TAG"
bash scripts/k8s/smoke.sh http://localhost:18080 http://localhost:18000

if [ "${2:-}" = "--down" ]; then kind delete cluster --name flare; fi
