# RUNBOOK: operating Flare Watch

How to start, check, fix and deploy the product. Every command is for Windows PowerShell in the repo root unless it says
otherwise. Docker Engine runs inside WSL Ubuntu; the scripts call `wsl -d Ubuntu` themselves.

## Start, check, stop (Docker Compose)

```
.\scripts\up.ps1            # build images tagged with the git SHA, start everything, prune the build cache
.\scripts\smoke_test.ps1    # every API endpoint + frontend + metrics
.\scripts\e2e.ps1           # full chain: inbox -> Prefect daily_ingest -> contracts -> champions -> store -> API -> frontend
.\scripts\down.ps1          # stop (named volumes are kept)
.\scripts\up.ps1 -NoBuild   # restart the existing images without building
```

| URL | Service | Health |
|---|---|---|
| http://localhost:8080 | website (landing `/`, console `/latest` ...) | `/healthz` |
| http://localhost:8000/docs | FastAPI | `/health` |
| http://localhost:4200 | Prefect UI | `/api/health` |
| http://localhost:5000 | MLflow registry (read-only for the API) | `/health` |
| http://localhost:9090 | Prometheus (alerts at `/alerts`) | `/-/ready` |
| http://localhost:3000 | Grafana, dashboard "Solar flare API" | `/api/health` |

Scheduled work (Prefect worker): `daily_ingest` 02:15 UTC, `check_drift` 03:30 UTC, `score_replay` on demand.

## Alerts

Both rules live in `monitoring/prometheus/alerts.yml` and are evaluated every 15 s.

### api-down
`FlareApiDown`: Prometheus could not scrape `api:8000/metrics` for 2 minutes (severity critical).
1. `wsl -d Ubuntu -- bash -lc "cd /mnt/d/projects/solar-flare-project && docker compose ps api && docker compose logs --tail 100 api"`
2. Container exited: look for the Python traceback (a broken model bundle or a missing env var are the usual causes).
   Restart with `.\scripts\up.ps1 -NoBuild`.
3. Container running but unhealthy: `curl http://localhost:8000/health`. Out of memory shows as exit code 137 in `docker
   compose ps`; free RAM (close browsers) or lower other services.
4. Kubernetes: `kubectl -n flare get pods -l app=api`, `kubectl -n flare describe pod <pod>`, `kubectl -n flare logs deploy/api`.
   A bad release is rolled back with `kubectl -n flare rollout undo deploy/api` (CD does this automatically).

### api-errors
`FlareApiHighErrorRate`: more than 5 % of API responses were 5xx for 5 minutes (severity warning).
1. Grafana panel "Errors per second by route" shows which route fails.
2. `docker compose logs --tail 200 api | grep -- "-> 5"` shows the failing requests with their latency.
3. Check that fault injection is off: `docker compose exec api env | grep FAULT` must show `FLARE_FAULT_INJECT_RATE=0`.
4. Errors only on `/production/*` or `/drift/*`: the volume data is broken; rerun the flow
   (`docker compose run --rm tools python -m flows.check_drift`).

### alert-drills
Proves that each alert really fires (done on 2026-11-14, screenshots in `docs/screenshots/prometheus_alert_*.jpg`).
```
.\scripts\alert_drill.ps1 -Rule down               # stops the API; FlareApiDown fires after about 2.5 min; restarts it
.\scripts\alert_drill.ps1 -Rule errors             # 50 % of requests answer 503; FlareApiHighErrorRate fires after about 6-8 min
.\scripts\alert_drill.ps1 -Rule errors -HoldSec 120   # keep it firing 2 minutes (screenshots), then restore
.\scripts\alert_drill.ps1 -Restore                 # emergency restore: fault injection off, API running
```
The error drill uses `FLARE_FAULT_INJECT_RATE` (src/settings.py): off by default, ignored when `FLARE_ENVIRONMENT=production`,
never applied to `/health` or `/metrics`, and covered by `tests/test_api.py`.

Measured on 2026-11-14: FlareApiDown pending after 15 s, firing after 135 s; FlareApiHighErrorRate firing after 480 s with
an error ratio of 0.51.

## Disk (Windows)

The WSL disk is `D:\WSL\Ubuntu\ext4.vhdx`. It grows with every image build and never shrinks by itself (sparse mode is
refused by WSL on this machine). Limits used during the build: C: 10 GB, D: 10 GB.
- `up.ps1` prunes the build cache after each build. Old image tags: `docker images | grep flare`, then
  `docker rmi <repo>:<old tag>` (never `docker volume rm`, never `docker system prune --volumes`).
- To give the space back to D: (admin PowerShell): `wsl --shutdown`, then `diskpart` with
  `select vdisk file="D:\WSL\Ubuntu\ext4.vhdx"`, `attach vdisk readonly`, `compact vdisk`, `detach vdisk`.

## Kubernetes (kind)

The same images and the manifests in `k8s/` (kustomize base + overlays `kind` and `prod`).
Install the tools once inside WSL Ubuntu (official release binaries):
```
wsl -d Ubuntu -- bash -lc "curl -Lo /tmp/kind https://kind.sigs.k8s.io/dl/v0.30.0/kind-linux-amd64 && sudo install /tmp/kind /usr/local/bin/kind"
wsl -d Ubuntu -- bash -lc "curl -Lo /tmp/kubectl https://dl.k8s.io/release/v1.34.1/bin/linux/amd64/kubectl && sudo install /tmp/kubectl /usr/local/bin/kubectl"
```
Then:
```
.\scripts\k8s_kind.ps1          # cluster + load images + deploy (automatic rollback) + smoke test
.\scripts\k8s_kind.ps1 -Demo    # ... plus a zero-downtime rolling update and the rollback of a bad release
.\scripts\k8s_kind.ps1 -Down    # delete the cluster
```
URLs: website http://localhost:18080, API :18000, Grafana :13000, Prometheus :19090, Prefect :14200, MLflow :15000.
Disk: the kind node keeps its own copy of the images (about 6 GB in the WSL disk); delete the cluster when done.
CI runs exactly these scripts in the `kind` job on every push, so the manifests are tested even without a local cluster.

Useful commands:
```
kubectl -n flare get pods,svc,pvc
kubectl -n flare rollout history deploy/api
kubectl -n flare rollout undo deploy/api
kubectl -n flare logs deploy/api --tail 100
kubectl -n flare get secret grafana-admin -o jsonpath='{.data.password}' | base64 -d
```

## Continuous deployment

Workflow `.github/workflows/cd.yml`:
1. After CI passes on `master` (or on a tag `vX.Y.Z`, or by hand): build both images and push them to GHCR as
   `ghcr.io/veenaphadtare12-ux/flare-api:<git sha>` plus `:master` or `:vX.Y.Z` (same for `flare-frontend`).
2. If the deploy secrets exist: copy `k8s/`, `scripts/k8s/` and `monitoring/` to the server over SSH and run
   `scripts/k8s/deploy.sh prod <git sha>`. It waits for every rollout; if one fails it runs `kubectl rollout undo` for the
   failed deployments and the job fails. Then `scripts/k8s/smoke.sh http://<server>` checks the public site.

### Repository secrets (Settings -> Secrets and variables -> Actions)
| Secret | Value |
|---|---|
| `DEPLOY_HOST` | server IP or DNS name (Terraform output `public_ip`) |
| `DEPLOY_USER` | SSH user that has `~/.kube/config` for k3s (`deploy` with the Terraform cloud-init) |
| `DEPLOY_SSH_KEY` | the PRIVATE key (whole file, including the BEGIN/END lines) whose public key is on the server |
| `GRAFANA_ADMIN_PASSWORD` | optional: Grafana admin password (otherwise a random one is generated once) |
| `GHCR_PULL_TOKEN` | optional: only if the GHCR packages stay private; a token with `read:packages` |

Without the three DEPLOY_* secrets the deploy job prints a notice and stops; images are still published.
Make the packages public (GitHub -> Packages -> flare-api / flare-frontend -> Package settings -> Change visibility) or set
`GHCR_PULL_TOKEN`.

### Server preparation (if you do not use Terraform)
```
curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 600
sudo mkdir -p /home/<user>/.kube && sudo cp /etc/rancher/k3s/k3s.yaml /home/<user>/.kube/config && sudo chown -R <user> /home/<user>/.kube
```
Open ports 22 and 80. The website is then `http://<server>/`; Grafana and Prometheus stay internal:
`kubectl -n flare port-forward svc/grafana 3000:3000`.

### Manual rollback on the server
```
kubectl -n flare rollout undo deploy/api deploy/frontend deploy/worker
```
or rerun CD for an older commit (Actions -> CD -> Run workflow on that commit).

## Terraform (written, not applied)
`infra/terraform`: one AWS VM (t3.large, Ubuntu 24.04, 40 GB) with k3s installed by cloud-init, security group (22, 80,
443), Elastic IP. CI runs `terraform fmt -check` and `terraform validate`.
```
cd infra\terraform
copy terraform.tfvars.example terraform.tfvars   # fill in your public SSH key
terraform init
terraform plan
terraform apply      # creates billable resources: only when you decide to
```

## Machine learning is frozen
Never retrain, re-tune or re-score from the running system. Holdout data is never read. The API serves only the frozen
champions in `model_bundle/`; `flows/retrain_candidate.py` can register a challenger in MLflow but never moves the champion.
