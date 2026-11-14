# Lesson 21: Alert drills, Kubernetes (kind, k3s), continuous deployment and Terraform

## What we built
- **Alert drills** (`scripts/alert_drill.ps1`): break the API on purpose, watch the Prometheus alert go
  inactive → pending → firing, then restore. Both rules were proven on 2026-11-14.
- **Kubernetes manifests** (`k8s/`): the whole product (API, worker, website, Prefect, MLflow, Prometheus, Grafana) as
  Deployments, Services, PersistentVolumeClaims, a ConfigMap and a seed Job, organised with **kustomize** (a `base` plus
  overlays for `kind` and `prod`).
- **Deploy with automatic rollback** (`scripts/k8s/deploy.sh`) and a **rolling update + rollback demo**
  (`scripts/k8s/rollout_demo.sh`), run in CI on a **kind** cluster on every push.
- **CI** now has four jobs: tests, the full Compose stack end to end, kind, Terraform validate.
- **CD** (`.github/workflows/cd.yml`): images pushed to **GHCR** tagged with the version and the git SHA, then deployed over
  SSH to a **k3s** server, with automatic rollback.
- **Terraform** (`infra/terraform`): one AWS VM with k3s, written and validated, not applied.

## Why it matters
A fire alarm that has never been tested is a hope, not a safety system. Fire drills prove it rings. Kubernetes is like a
restaurant manager who keeps the right number of cooks working, replaces one who faints, and brings in new cooks one at a
time so the kitchen never closes. CD is the delivery van that takes each approved dish to the restaurant, and brings the
old dish back if customers complain. Terraform is the architect's plan for the building, so it can be rebuilt identically.

## Concepts
- **Alert states:** an alert rule is *inactive* while its expression is false, *pending* while true but for less than
  `for:`, *firing* once it has been true for the whole `for:` duration. `for:` prevents alerts on one bad scrape.
- **`up` metric:** Prometheus sets `up{job=...}` to 1 when a scrape works, 0 when it fails. "API down" is `up == 0`.
- **Error ratio:** `rate(5xx requests) / rate(all requests)` over 5 minutes. With 50 % injected 503s it measured 0.51.
- **Fault injection:** a switch that makes some requests fail deliberately (`FLARE_FAULT_INJECT_RATE`). Off by default,
  impossible in production, never on `/health` or `/metrics` (the probes must keep telling the truth).
- **Pod, Deployment, ReplicaSet:** a pod runs containers; a Deployment says "keep N pods of this template"; each template
  change creates a new ReplicaSet (a *revision*), which is what makes rollback possible.
- **Service:** a stable name and port (`api:8000`) in front of changing pods, so nginx and Prometheus never need pod IPs.
- **Probes:** *startup* (give the API up to 3 minutes to load the models), *readiness* (send traffic only when `/health`
  answers), *liveness* (restart a pod that stops answering).
- **Requests and limits:** requests reserve CPU/memory for scheduling; limits cap them (memory over the limit = restart).
- **ConfigMap and Secret:** settings and secrets injected as environment variables or files. Our ConfigMaps for Prometheus
  and Grafana are built from `monitoring/` by the deploy script, so Compose and Kubernetes share one source. The Grafana
  password Secret is created at deploy time and never committed.
- **PVC:** a request for disk that survives pod restarts (predictions store, Prefect and MLflow databases, Prometheus data).
- **Rolling update:** `maxSurge: 1, maxUnavailable: 0`: start one new pod, wait until it is ready, then stop one old pod.
- **Rollback:** `kubectl rollout undo` switches back to the previous ReplicaSet.
- **kustomize:** plain YAML plus overlays that patch it (NodePorts for kind, an Ingress and `production` for the server).
- **kind:** Kubernetes nodes running as Docker containers: a real cluster on a laptop or a CI runner.
- **k3s:** a small, complete Kubernetes for one server, with the Traefik ingress built in.
- **GHCR:** GitHub's container registry. Images are tagged twice: the git SHA (exact code) and a version (`v1.0.0`).
- **Terraform:** declare infrastructure in `.tf` files; `plan` shows changes, `apply` makes them, the state file remembers.

## Tools used
| Tool | What it did here | Most useful commands |
|---|---|---|
| Prometheus alerts | proved both rules fire | `curl localhost:9090/api/v1/alerts` |
| kubectl | talks to any cluster | `get pods`, `describe pod`, `logs deploy/api`, `rollout status/history/undo`, `set image`, `port-forward` |
| kustomize (inside kubectl) | builds the manifests | `kubectl kustomize k8s/overlays/kind`, `kubectl apply -k ...` |
| kind | local and CI cluster | `kind create cluster --config k8s/kind/cluster.yaml`, `kind load docker-image ...`, `kind delete cluster --name flare` |
| GitHub Actions | CI and CD | `gh run list`, `gh run view <id> --log-failed` |
| Terraform | server as code | `terraform fmt`, `init`, `validate`, `plan`, `apply`, `destroy` |

## Code walkthrough
- `src/serving/api.py` `_inject_fault`: returns True for a random share of requests only if the rate is above 0, the
  environment is not `production`, and the path is not `/health` or `/metrics`. The middleware then answers 503 and still
  counts the request, so the error ratio is real.
- `scripts/alert_drill.ps1`: reuses the running image tag (so Compose never rebuilds mid-drill), polls
  `/api/v1/alerts` every 15 s, holds the fault for screenshots with `-HoldSec`, and always restores.
- `k8s/base/api.yaml`: 2 replicas, the rolling-update strategy, the three probes, `runAsNonRoot` with uid 10001, dropped
  Linux capabilities, `envFrom: flare-config`.
- `k8s/base/mlflow.yaml`: the seed Job copies the model bundle out of the API image with an init container, so the
  registry is filled from the same files the API serves.
- `scripts/k8s/deploy.sh`: creates ConfigMaps/Secrets, pins the image tag in a temporary overlay, records each
  deployment's revision, applies, waits for every rollout and runs `rollout undo` for any that fail, then exits 1.
- `scripts/k8s/rollout_demo.sh`: a background loop calls `/health` every 0.3 s during an update (must be 0 failures),
  then deploys a tag that does not exist, sees the rollout time out while the old pods still answer, and rolls back.
- `.github/workflows/cd.yml`: `publish` (build, tag SHA + version, push) then `deploy` (checks the three secrets; SSH,
  copy, `deploy.sh prod <sha>`, smoke test of the public URL).
- `infra/terraform/main.tf`: Ubuntu 24.04 AMI lookup, key pair, security group (22/80/443), the instance with
  `cloud-init.yaml.tftpl` installing k3s and a `deploy` user, and an Elastic IP.

## Hands-on
1. Run the API-down drill: `.\scripts\alert_drill.ps1 -Rule down`. Expected: `pending` after about 15 s, `OK FlareApiDown
   is FIRING after ~135 s`, then "API healthy again".
2. Read the alert in the API yourself while it fires:
   `curl.exe -s localhost:9090/api/v1/alerts`. Expected: `"alertname":"FlareApiDown"` and `"state":"firing"`.
3. Build the manifests without a cluster (needs kubectl in WSL):
   `wsl -d Ubuntu -- bash -lc "cd /mnt/d/projects/solar-flare-project && kubectl kustomize k8s/overlays/kind | grep -c '^kind:'"`.
   Expected: a count of about 25 objects.
4. Find the rolling-update settings: open `k8s/base/api.yaml` and explain `maxSurge` and `maxUnavailable` in your words.
5. Read a CI kind job log: on GitHub open Actions → CI → the latest run → `kind` → "Rolling update and rollback demo".
   Expected lines: `requests during the rolling update: N, failed: 0`, `rollout failed as expected`, `ROLLOUT DEMO OK`.
6. Terraform without spending money: `cd infra\terraform; terraform init -backend=false; terraform validate`.
   Expected: `Success! The configuration is valid.`

## Break it on purpose
Set the alert threshold impossibly high so the error drill never fires: in `monitoring/prometheus/alerts.yml` change
`> 0.05` to `> 0.95`, restart Prometheus (`docker compose restart prometheus`), run
`.\scripts\alert_drill.ps1 -Rule errors -TimeoutSec 480`. Expected: `FAIL FlareApiHighErrorRate did not fire`. This
shows why drills matter: a wrong threshold is silent. Undo: `git checkout monitoring/prometheus/alerts.yml` and restart
Prometheus again.

## Check yourself
1. What is the difference between a *pending* and a *firing* alert?
2. Why must fault injection never touch `/health`?
3. With 2 replicas, `maxSurge 1` and `maxUnavailable 0`, how many API pods exist at most during an update?
4. Why does a release with a non-existent image tag not cause downtime?
5. Why are the images tagged with the git SHA as well as the version?

## Questions to discuss with my tutor
- Should CD deploy every master commit, or only version tags, for a research system?
- Is SSH from GitHub-hosted runners (changing IPs, port 22 open) acceptable, or should we use a self-hosted runner?
- When would ReadWriteOnce volumes stop being enough?

## Key numbers to remember
FlareApiDown: `for: 2m`, fired after 135 s · FlareApiHighErrorRate: `> 5 %` for 5 min, fired at a 0.51 ratio · API: 2
replicas, 512 Mi request, 1.5 Gi limit, startup probe up to 3 min · kind host ports 18080 (website) and 18000 (API) ·
CI: 4 jobs · Terraform: t3.large, 40 GB.

---
Answers: 1. Pending = the expression is true but not yet for the whole `for:` duration; firing = true for all of it.
2. The probes would see failures and Kubernetes would restart healthy pods, and the drill would test the wrong thing.
3. Three (2 + 1 surge). 4. The new pod never becomes ready, so the old pods are never stopped and keep serving.
5. The SHA identifies the exact code and models in the image (and never changes); the version is the human-friendly name.
