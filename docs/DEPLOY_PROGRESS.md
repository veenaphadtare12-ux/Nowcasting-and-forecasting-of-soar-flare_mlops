# Deployment progress (resume here)

Contract: `docs/ARCHITECTURE.md`. ML phase frozen. Repo:
https://github.com/veenaphadtare12-ux/Nowcasting-and-forecasting-of-soar-flare_mlops

| Phase | Status |
|---|---|
| Ops-1: CI, contracts, flows, push | **done**: CI green on GitHub |
| 2: model bundle, API, Docker | **done** |
| 2b: full Compose stack + smoke test + e2e | **done**: `scripts\up.ps1`, `scripts\smoke_test.ps1`, `scripts\e2e.ps1` all pass (re-verified 2026-11-14) |
| 3: frontend | **done**: dashboard (6 pages + pipeline panel) and the cinematic landing page at `/` (2026-11-14) |
| 4: monitoring | **done** (2026-11-14): both alert rules proven firing by drills, screenshots in `docs/screenshots/` |
| 5: CI with full Compose + kind | **done**: CI jobs `test`, `compose-e2e`, `kind`, `terraform` |
| 6: Kubernetes | **done**: `k8s/` (kustomize base + kind/prod overlays), `scripts\k8s_kind.ps1`, rolling update + rollback demonstrated in the CI `kind` job |
| 7: CD + Terraform | **done (deploy waits for secrets)**: images to GHCR (git SHA + version); SSH deploy to k3s with automatic rollback needs DEPLOY_HOST / DEPLOY_USER / DEPLOY_SSH_KEY; Terraform validated, not applied |
| 8: submission docs, v1.0.0 | **done**: README, RUNBOOK, REPORT, DEMO, INTERVIEW_PREP, lesson 21, fresh-clone check, tag `v1.0.0` |
| 9: release readiness v1.1.0 | **done** (2026-11-14): health check, hardening, load test, backups, docs; public deploy waits for secrets (`docs/DEPLOY_STEPS.md`). Table: `docs/PRODUCTION_READINESS.md` |

## How to run
Docker Engine runs inside WSL Ubuntu (Docker Desktop is not used, see "Docker history" below). The scripts call
`wsl -d Ubuntu` themselves and start a hidden keep-alive so the WSL VM does not stop.
```
.\scripts\up.ps1            # build (git-SHA tag) + start the stack
.\scripts\smoke_test.ps1    # health, models, replay, predict, metrics, frontend
.\scripts\e2e.ps1           # inbox -> Prefect daily_ingest -> contracts -> champions -> store -> API -> frontend
.\scripts\down.ps1
```
| URL | What |
|---|---|
| http://localhost:8080 | Website: landing page `/`, console `/latest`, `/replay`, `/performance`, `/models`, `/data`, `/about` |
| http://localhost:8000/docs | FastAPI |
| http://localhost:4200 | Prefect UI (deployments `daily_ingest/daily` 02:15 UTC, `check_drift/daily` 03:30 UTC, `score_replay/on-demand`) |
| http://localhost:5000 | MLflow (registry seeded from the model bundle; the API only reads it) |
| http://localhost:9090 | Prometheus |
| http://localhost:3000 | Grafana (anonymous viewer; admin password from `GRAFANA_ADMIN_PASSWORD`) |

Frontend development without rebuilding the image: `cd frontend; npm run dev` → http://localhost:5173 (proxies
`/api` to :8000).

## Phase 2b: what was verified (e2e, 2026-11-13)
- A raw SoLEXS day dropped into the inbox is picked up by the Prefect deployment `daily_ingest`, which the worker
  container runs: pandera contracts → features → 5 champions → predictions store. `/production/latest` serves it.
  On 2026-02-21 the production path reproduces the bundle predictions exactly.
- `score_replay` writes to the store and the API switches to `source: store`; `check_drift` (bundle mode) writes
  `latest.json`; the frontend's `/api` proxy works; Prometheus has the API metrics and Grafana is healthy.
- With no data on or after the production start (2026-11-13), `/production/latest` correctly reports `no_data`.

## Phase 3: frontend
- **Dashboard** (`frontend/src/pages/`): React 19 + TypeScript + Tailwind 4 + ECharts 6, served by
  nginx-unprivileged (`docker/frontend.Dockerfile`, SSE location without buffering).
- **Landing page** (`frontend/src/landing/`, lazy-loaded at `/`):
  - **3D scene (three.js):** a rotating procedural Sun (GLSL noise granulation, sunspots, limb darkening), corona, flowing magnetic loops, flare flashes with shock rings, and solar-wind particles. Aditya-L1 is modelled with a gold bus and solar wing, plus Earth and Moon.
  - **Scroll:** a camera path driven by GSAP ScrollTrigger and Lenis.
  - **Sections, all on live API data:** the X-class day (scroll = time; light curve, three model probabilities with thresholds, alerts, counts jar), live pipeline badges, and holdout2 results beside the best baseline.
  - **Design and lesson:** design inspiration from The Reef Line and Rainy Day (Claude Website Library); see lesson `docs/learn/20-cinematic-landing-threejs-gsap.md`.
- **Checks (2026-11-14):**
  - `npm run build` passes (typecheck included);
  - no console errors or warnings on the landing page or dashboard;
  - checked at 1366×768, 1920×1080 and 390×844;
  - `prefers-reduced-motion` respected.
- **Screenshots:** `docs/screenshots/landing_*.jpg`.
- **OpenArt:** one image was generated (free plan, 10 credits), but it carries a large OpenArt watermark, so it is **not used**. The Sun is drawn procedurally instead. A paid plan would allow un-watermarked art.

## Problems met (and fixes)
- **Docker Desktop failed to start** on this Windows build: it could not rename its AF_UNIX socket files. After 3 attempts, the user installed Docker Engine inside WSL Ubuntu instead.
- **Git Bash mangles `$vars` and `/mnt/...` paths** in `wsl` calls: helper scripts go to `D:/tmp/wsl/*.sh` and run with `MSYS_NO_PATHCONV=1`. The PowerShell scripts use `_common.ps1` (`Invoke-Bash`, `Get-WslPath`).
- **The WSL VM stops** a few seconds after the last `wsl.exe` exits, taking Docker with it: a hidden `wsl ... sleep infinity` keep-alive (`Start-WslKeepAlive`).
- **Port 5000 was held** by the leftover Docker Desktop backend, which was stopped.
- **CI:**
  - the Prefect server needs FastAPI 0.142, so it is pinned in `requirements-ci.txt`;
  - one HEL1OS feature (`hx_cdte_lo_d5m`) differs by float32 rounding between Windows and Linux, so that test uses `rtol=1e-5`.
- **Python text mode on Windows writes CRLF:** the LF test caught it, and files were rewritten in binary mode.
- **RAM:** with the Docker VM and browsers running, the full-data tests can hit `MemoryError` (about 1 GB free of 15.7 GB). Rerunning them alone passes.

## Disk log
Rule: after every image build run `docker builder prune -f`; log C: and D: free space after every phase.
The WSL disk was moved to `D:\WSL\Ubuntu\ext4.vhdx` (17.6 GB file, about 13 GB used inside, **not sparse**, so space
freed inside WSL is not returned to D: until the disk is compacted or made sparse).

| Date | Point | C: free | D: free | Notes |
|---|---|---|---|---|
| 2026-11-14 | pre-flight before phase 4 | 39.0 GB | 9.69 GB | **STOP: D: below 15 GB.** Build cache 0 B, no dangling images. 4.69 GB is held by old, non-dangling image tags (`flare-api:6dbb958be90b`, `flare-api:7c9b20e183ef-dirty` and their frontends), which the prune rule does not cover. |
| 2026-11-14 | after deleting 2 old image tags + diskpart compact | 39.0 GB | 17.02 GB | VHDX 17.6 -> 10.3 GB. Sparse mode refused by WSL ("disabled due to potential data corruption"); not forced. |
| 2026-11-14 | after step 1 (up.ps1 rebuild, pytest, e2e) | 38.9 GB | 11.43 GB | **STOP: D: below 15 GB.** VHDX grew 10.3 -> 14.0 GB from the image rebuild (build cache pruned afterwards, 2.2 GB, but a non-sparse VHDX never shrinks by itself). |

## Step 1 re-verification (2026-11-14)
- `scripts\up.ps1` rebuilt images `6dfe4acc700e`; all services healthy: site :8080, API :8000, Prometheus :9090,
  Grafana :3000, Prefect :4200, MLflow :5000 (all HTTP 200). Cause of the earlier outage: WSL had been shut down
  for the disk compaction; nothing was broken.
- `scripts\smoke_test.ps1`: all checks passed. `ruff check .`: clean. `pytest`: 136 passed, 1 skipped (105 s).
- `scripts\e2e.ps1`: **E2E PASSED (6dfe4acc700e)**.
| 2026-11-14 | after phase 4 (one rebuild, drills, screenshots) | 38.9 GB | 12.08 GB | build cache pruned by `up.ps1`; limit lowered to 10 GB for D: by the user (option chosen 2026-11-14), old tag `9d36afd2b402` deleted with approval |
| 2026-11-14 | after phases 5-8 (no local images built; CI builds on GitHub) | 38.8 GB | 12.0 GB | kind is exercised in CI, not locally, to keep the WSL disk from growing by about 6 GB |

| 2026-11-14 | after the v1.0.1 fix rebuild | 38.5 GB | **8.33 GB** | **STOP: D: below 10 GB.** Each rebuild after a cache prune re-creates the 2 GB pip layer; three flare-api tags are kept (`e48339fa084f` running, `f6d346f773a4`, `6dfe4acc700e`). Proposed rule change: keep the build cache, delete older flare tags after a successful start. |

| 2026-11-14 | v1.1.0: before work | 38.4 GB | 8.33 GB | approved: old tags `f6d346f773a4`, `6dfe4acc700e` deleted, compaction by the user |
| 2026-11-14 | after compaction 1 | 38.6 GB | 14.92 GB | VHDX 17.08 -> 12.36 GB |
| 2026-11-14 | after hardening build | 38.7 GB | 9.73 GB | **stop**; tag `e48339fa084f` deleted; compaction 2 -> 13.54 GB |
| 2026-11-14 | after perf-fix build | 38.6 GB | 8.07 GB | **stop**; root cause: GIT_SHA above the apt/pip layers (0 cached steps); fixed, stale cache (6.9 GB) pruned once; compaction 3 -> 16.47 GB |
| 2026-11-14 | before the v1.1.0 build | 38.5 GB | 14.57 GB | backups on D: 29 MB |

## Phase 4: monitoring (2026-11-14)
- `scripts\alert_drill.ps1 -Rule down`: API container stopped; `FlareApiDown` pending after 15 s, **firing after 135 s**
  (`for: 2m`), API restarted and healthy. Screenshot `docs/screenshots/prometheus_alert_api_down_firing.jpg`.
- `scripts\alert_drill.ps1 -Rule errors`: `FLARE_FAULT_INJECT_RATE=0.5` plus 4 requests/s; `FlareApiHighErrorRate`
  **firing after 480 s with an error ratio of 0.51** (`> 0.05` for 5 m), then restored (rate 0, `/models` 200).
  Screenshot `docs/screenshots/prometheus_alert_error_rate_firing.jpg`.
- Fault injection (`src/settings.py` `fault_inject_rate`, `src/serving/api.py` `_inject_fault`): off by default, ignored in
  `production`, never on `/health` or `/metrics`; test `test_fault_injection_is_off_by_default_and_counted_when_on`.
- Grafana stat panels got thresholds (error rate green < 1 % < orange < 5 % < red; API up shows UP/DOWN).
- Screenshots: `grafana_flare_api_dashboard.jpg` (both drills visible), `prefect_flow_runs.jpg`, `mlflow_registry.jpg`,
  `landing_hero_1440.jpg`, `landing_mobile_390.jpg`. Headless capture returned a stale frame for WebGL pages until the page
  was repainted (a 2-px scroll); recorded so the next capture is quick.
- Found: `scripts/e2e.sh` ran `docker compose down --volumes` (deleted named volumes) and left the test production start
  active. Now volumes are only wiped with `E2E_FRESH=1` (CI), and the real production start is restored at the end.

## Phases 5-7: CI, Kubernetes, CD, Terraform (2026-11-14)
- CI (`.github/workflows/ci.yml`): `test` (ruff + pytest), `compose-e2e` (build + `scripts/e2e.sh` with fresh volumes on the
  runner: **passed**), `kind` (build, kind cluster from `k8s/kind/cluster.yaml`, `scripts/k8s/kind_up.sh`: deploy with
  automatic rollback + smoke test, then `scripts/k8s/rollout_demo.sh`), `terraform` (fmt + validate: **passed**).
- Kubernetes (`k8s/base`): Deployments for api (2 replicas, maxSurge 1 / maxUnavailable 0, startup/readiness/liveness probes,
  preStop sleep, non-root, limits), worker (Recreate), frontend (2 replicas), prefect-server, mlflow (+ seed Job that copies
  the bundle from the API image), prometheus, grafana; 7 PVCs; ConfigMap `flare-config`; ConfigMaps for Prometheus/Grafana
  and the Secret `grafana-admin` are created by `scripts/k8s/deploy.sh` (never committed). Overlays: `kind` (NodePorts on
  host ports 18080/18000/13000/19090/14200/15000) and `prod` (Ingress, `FLARE_ENVIRONMENT=production`).
- kind fixes found by CI: kustomize refuses absolute resource paths (temporary overlay now inside `k8s/`); 2 of 29
  requests failed during the first rolling update (fixed with a preStop sleep, grace period and minReadySeconds); MLflow
  measured 2.1 GiB with 4 workers in Compose, so Kubernetes runs it with `--workers=1` and a 2 Gi limit.
- **CI run 43561999582 (commit dd12a63): all 4 jobs green.** kind job: `DEPLOY OK (kind, tag dd12a633d5b8)`, smoke test
  5/5 OK, rolling update **67 requests, 0 failed**, bad image release: rollout failed as expected while the old pods kept
  serving, `rollout undo` restored `flare-api:dd12a633d5b8`, `ROLLOUT DEMO OK`.
- **CD run 43562573972: success.** Published `ghcr.io/veenaphadtare12-ux/flare-api:dd12a633d5b8` and `:master` (same for
  flare-frontend). Deploy job: "Deploy skipped: repository secrets missing: DEPLOY_HOST DEPLOY_USER DEPLOY_SSH_KEY".
- Local kind: `scripts\k8s_kind.ps1 [-Demo] [-Down]`. Not run on this PC: kind/kubectl are not installed in WSL (installing
  needs the user's approval for downloads) and the kind node would add about 6 GB to the WSL disk on D:. CI runs the same
  scripts on every push.
- CD (`.github/workflows/cd.yml`): after CI succeeds on master, on a `v*.*.*` tag, or by hand: push
  `ghcr.io/veenaphadtare12-ux/flare-{api,frontend}:<sha>` and `:master` / `:vX.Y.Z`; deploy job checks DEPLOY_HOST,
  DEPLOY_USER, DEPLOY_SSH_KEY (not set yet, so it prints a notice), copies `k8s/ scripts/k8s monitoring/` over SSH and runs
  `deploy.sh prod <sha>` (rollout undo on failure), then smoke-tests `http://<host>/`.
- Terraform (`infra/terraform`): AWS ap-south-1, t3.large, Ubuntu 24.04, 40 GB gp3 encrypted, IMDSv2, security group
  22/80/443, Elastic IP, cloud-init installs k3s + `deploy` user. Not applied.

## Phase 8: docs and release (2026-11-14)
- `README.md` (3 start commands, URLs, CI/CD), `docs/RUNBOOK.md`, `docs/REPORT.md`, `docs/DEMO.md`,
  `docs/INTERVIEW_PREP.md`, lesson `docs/learn/21-alerts-kubernetes-cd-terraform.md`.
- Fresh-clone check: `git clone` into `D:\tmp\fresh` (37 MB without .git): `pytest -m "not data"` 126 passed, 6 skipped;
  `docker compose config` valid. The CI `compose-e2e` job is the full fresh-clone build and end-to-end run.

## v1.0.1 (2026-11-14)
- Found after v1.0.0: `/production/latest` served 2026-02-21 (the day the end-to-end test scores with a temporary
  production start) as the latest production day. `production.scored_days()` now applies the production start, like
  `available_days()`; test `test_days_before_the_production_start_are_never_reported`. Local stack rebuilt
  (`e48339fa084f`): `/production/latest` = `no_data`, smoke test passed.

## v1.1.0: release readiness and hardening (2026-11-14)
Full PASS / FAIL / NOT RUN table with proof: `docs/PRODUCTION_READINESS.md`. Highlights:
- Health check: git clean, DVC up to date, pytest 145 passed / 1 skipped, stack + smoke + e2e passed, all four Prefect
  flows ran (retrain only created challenger v4 in the stack's MLflow; project registry untouched), Prometheus targets
  UP, Grafana data, CI green.
- Fixed: retrain tz bug, Prefect test isolation, replay starvation under load, public `/metrics`, old-image cleanup,
  Docker layer-cache order.
- Hardening: API key / rate limit / size limit / CORS (5 new API tests), Caddy (HTTP + auto-HTTPS, local-CA test),
  Alertmanager (fake + real alert delivered; e-mail NOT RUN), backup -> restore -> identical, k6 50 users p95 8.3 ms 0 %
  errors, CI `security` job (pip-audit, npm audit, trivy 0 CRITICAL), Compose hardening (non-root, limits, healthchecks,
  restart, no-new-privileges, localhost-only ports, pinned images), k8s Alertmanager + API-key Secret, CD secrets on stdin.
- Deploy: secrets absent -> `docs/DEPLOY_STEPS.md`; GHCR packages public; CD deploy script dry run passed locally.
- Docs: SECURITY, SLO, DEPLOY_STEPS, PRODUCTION_READINESS, VIVA_CHEATSHEET, RUNBOOK sections, lesson 22, current-state
  banners on dated documents.
- Release check: CI run 43578152118 (commit e6f0f3b) 5/5 green; local image e6f0f3b7f1f3: smoke, e2e and public smoke passed.
