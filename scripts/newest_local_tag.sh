#!/usr/bin/env bash
# Print the newest image tag that exists locally for flare-api, flare-frontend AND flare-prefect-server (used by
# `scripts\up.ps1 -Local`, so a demo starts from images already on the machine). Prints nothing if there is none.
set -euo pipefail
REPO=ghcr.io/veenaphadtare12-ux
# docker lists images newest first
for t in $(docker images "$REPO/flare-api" --format '{{.Tag}}'); do
  if docker image inspect "$REPO/flare-frontend:$t" "$REPO/flare-prefect-server:$t" >/dev/null 2>&1; then
    echo "$t"
    exit 0
  fi
done
