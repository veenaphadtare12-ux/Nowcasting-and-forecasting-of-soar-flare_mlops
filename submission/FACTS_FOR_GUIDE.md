# FACTS FOR THE GUIDE AND SLIDES (read-only check)

Checked on **2026-11-16, about 19:40–20:15 UTC** (server clock; this PC's clock is about 5 h 30 min behind real UTC, see
section 7). Nothing in the code, data, models, server or configuration was changed for this report. No model was
retrained, re-tuned or re-scored; no holdout data was read (only committed result files). Secrets are named, never shown.

Legend: **CHECKED NOW** = command run or page opened during this check · *file* = copied from the named committed file ·
**NOT CHECKED** = could not be verified.

---

## 1. Release and repository

| Fact | Value | Source |
|---|---|---|
| Latest tag | **v1.2.0** on commit `2b0c36a` (commit 2026-11-16 12:47:54 +0530; tag created 2026-11-16 12:57:13 +0530) | `git describe`, `git for-each-ref` (CHECKED NOW) |
| Commits after the tag | 2 documentation-only commits: `416cbc2` (demo start command), `54c55ab` (alert e-mail received) | `git log v1.2.0..HEAD` |
| Total commits on `master` | **84** | `git rev-list --count HEAD` |
| Working tree | clean (only the untracked tool folder `.claude/`; this report and the screenshots are new, not committed) | `git status` |
| Repository | https://github.com/veenaphadtare12-ux/Nowcasting-and-forecasting-of-soar-flare_mlops, **public**, default branch `master` | `gh repo view` |

**CI on tag v1.2.0**: run 43823967906, overall **success**
https://github.com/veenaphadtare12-ux/Nowcasting-and-forecasting-of-soar-flare_mlops/actions/runs/43823967906

| Job | Result |
|---|---|
| test (ruff + pytest on fixtures) | PASS |
| compose-e2e (whole Docker Compose stack, end to end) | PASS |
| kind (Kubernetes deploy, smoke, rolling update + rollback) | PASS |
| terraform (fmt + validate: EC2 and Lightsail code) | PASS |
| security (pip-audit, npm audit, trivy) | PASS |

**CD on tag v1.2.0**: run 43823967895, overall **success**
https://github.com/veenaphadtare12-ux/Nowcasting-and-forecasting-of-soar-flare_mlops/actions/runs/43823967895

| Job | Result |
|---|---|
| publish (images to GHCR, tags `2b0c36aab42c` and `v1.2.0`) | PASS |
| deploy (SSH → Docker Compose on EC2 → public HTTPS smoke test) | PASS |

Latest runs on `master` (after the tag): CI 43826246111 and 43827170695 success; CD 43827395139 and 43828391510 success.

**Tests** (CHECKED NOW, full suite on this PC): `145 passed, 1 skipped, 283 warnings in 94.19s` (146 tests).
CI runs the 140 data-free ones. **Ruff**: `All checks passed!`

---

## 2. Live deployment

**Public URL: https://veena-flare.duckdns.org**: loads now (CHECKED NOW)

| Check | Result |
|---|---|
| `GET https://veena-flare.duckdns.org/` | **200** (1.0 s from this PC) |
| `GET http://veena-flare.duckdns.org/` | **308** → `https://veena-flare.duckdns.org/` |
| Certificate | subject `veena-flare.duckdns.org`, issuer **Let's Encrypt (YE1)**, valid **2026-11-16 06:09:28 GMT → 2027-02-14 06:09:27 GMT**, verified against the system CA store. Caddy renews it automatically |
| `/api/health` | `ok`, image `54c55abb1927`, bundle `2026.11.13-1719`, environment `compose`, 5 models loaded |

The site runs image `54c55abb1927` (the latest `master`; app contents identical to v1.2.0, the two later commits are
docs only). CD redeploys automatically after every green CI run on `master`, so the site stays current without manual steps.

**Server** (CHECKED NOW, from the instance metadata service and the OS, over SSH)

| Item | Value |
|---|---|
| Cloud | AWS, free-plan account |
| Region / zone | **ap-southeast-2 (Sydney)**, ap-southeast-2a |
| Instance type | **m7i-flex.large**: 2 vCPU, 7.6 GiB RAM (+ 2 GiB swap) |
| Disk | 29 GB root (gp3 30 GiB), 18 GB used, 11 GB free |
| Image | Ubuntu 24.04.5 LTS (AMI `ami-081307e05c61a3854`), Docker 29.1.3, Compose 2.40.3 |
| Public IP | **54.79.250.93, an Elastic IP: yes** (allocated and associated in the console on 2026-11-16; the API cannot confirm it, see Terraform row) |
| State | **running** (uptime 13 h 25 min at the check) |
| Deployed tag / previous tag | `54c55abb1927` / `416cbc224270` (kept for rollback) |
| DNS | `veena-flare.duckdns.org` → 54.79.250.93 |

**Terraform: no resources were created by Terraform; there is no apply date.** The AWS free plan's organisation
service control policy denies EC2 and Lightsail API calls made with access keys (`explicit deny in a service control
policy`, tested in 4 regions on 2026-11-16). The server was therefore created **by hand in the AWS console on
2026-11-16**: EC2 instance `flare`, key pair `flare-deploy` (imported public key), a security group with SSH 22 / HTTP 80 /
HTTPS 443 (its name: NOT CHECKED), an Elastic IP. `infra/terraform` (EC2) and `infra/lightsail` (Lightsail) describe the
same server as code and pass `terraform validate` in CI, but were never applied.

**Access table** (CHECKED NOW from this PC)

| Page / endpoint | Public? | Result now |
|---|---|---|
| `/`, `/latest`, `/replay`, `/performance`, `/models`, `/data`, `/about` (website) | public | 200 |
| `/api/health`, `/api/models`, `/api/replay/days`, `/api/results`, `/api/drift/latest`, `/api/pipeline/status`, `/api/docs` | public (read-only) | 200 |
| `POST /api/predict` | **needs API key** (`X-API-Key`) | no key 401, wrong key 401, valid key 200 |
| `/api/metrics` | blocked publicly (Prometheus scrapes it internally) | 404 |
| Grafana :3000, Prometheus :9090, Alertmanager :9093, Prefect :4200, MLflow :5000, API :8000, nginx :8080 | **not public**: bound to 127.0.0.1 on the server and not open in the security group; reachable only via an SSH tunnel | all ports closed from outside |
| Grafana admin | needs the admin password (secret `GRAFANA_ADMIN_PASSWORD`); anonymous users are read-only viewers | admin API without login: 403 |

**Memory and services** (CHECKED NOW; peak = cgroup `memory.peak` since each container started)

| Service | Now | Peak | Limit |
|---|---|---|---|
| mlflow | 1.58 GiB | 1,629 MiB | 2 GiB |
| api | 239 MiB | 273 MiB | 1.5 GiB |
| prefect-server | 229 MiB | 246 MiB | 1 GiB |
| worker | 131 MiB | 154 MiB | 2 GiB |
| grafana | 101 MiB | 155 MiB | 512 MiB |
| prometheus | 47 MiB | 100 MiB | 512 MiB |
| alertmanager | 27 MiB | 31 MiB | 128 MiB |
| caddy | 13 MiB | 128 MiB | 128 MiB |
| frontend | 3.5 MiB | 62 MiB | 128 MiB |

Host: 3,132 MiB used of 7,776 MiB. **9 services running, all healthy.**

**Cost**

| Item | Value | Source |
|---|---|---|
| Instance | USD 0.1197 per hour → **USD 2.87 per day** | AWS Price List API, ap-southeast-2, 2026-11-16 |
| Public IPv4 (Elastic IP) | USD 0.005 per hour → USD 0.12 per day | AWS standard rate (not looked up from the API) |
| Disk 30 GiB gp3 | about USD 0.10 per day (USD 0.096 per GB-month is the Singapore price; Sydney price NOT CHECKED) | estimate |
| **Total while running** | **≈ USD 3.1 per day** (≈ USD 7 per month while stopped: disk + IP) | estimate |
| Credit used so far | ≈ USD 1.7 (≈ 13.5 h × USD 0.13/h): estimate only; actual NOT CHECKED | estimate |
| Credit remaining | **NOT CHECKED now** (AWS rejected the request because this PC's clock is 5.5 h off). Last read: **USD 120.00**, plan FREE, expires 2027-05-14 (CLI, 2026-11-16 before the server was launched) | `aws freetier get-account-plan-state` |

---

## 3. Proof table

| Item | Result | Date | Proof |
|---|---|---|---|
| HTTPS | **PASS** | 2026-11-16 (now) | 200 over TLS; Let's Encrypt cert valid to 2027-02-14 |
| HTTP → HTTPS redirect | **PASS** | 2026-11-16 (now) | `http://…/` → 308 to `https://…/` |
| `/health` | **PASS** | 2026-11-16 (now) | `ok`, 5 models, image `54c55abb1927` |
| `/predict` without key = 401 | **PASS** | 2026-11-16 (now) | 401 (and 401 with a wrong key) |
| `/predict` with key = 200 | **PASS** | 2026-11-16 (now) | 200, p_flare 0.039, threshold 0.324 (key read from the server's `.env`, never printed) |
| Admin UIs locked | **PASS** | 2026-11-16 (now) | ports 3000, 4200, 5000, 8000, 8080, 9090, 9093 closed from outside; Grafana admin API 403 without login |
| Grafana data | **PASS** | 2026-11-16 (now) | Grafana → Prometheus datasource: `sum(flare_api_requests_total)` = 7158 on the server; dashboard "Solar flare API", 9 panels |
| Prometheus targets | **PASS** | 2026-11-16 (now) | `flare-api` up, `prometheus` up, `alertmanager` up |
| All 4 Prefect flows **on the server** | **FAIL** | 2026-11-16 (now) | **0 flow runs** on the server. Deployments `daily_ingest/daily` (02:15 UTC), `check_drift/daily` (03:30 UTC) and `score_replay/on-demand` exist and are not paused, but the Prefect server's scheduler fails on every pass: `sqlalchemy.exc.InvalidRequestError: Can't evaluate bulk DML statement` in `schedule_deployments`. `retrain_candidate` is not deployed on the server (NOT RUN there). **Fixed afterwards (2026-11-16/17):** patched Prefect server image with SQLAlchemy 2.0.57; see the update at the end of this file. |
| All 4 Prefect flows (local stack) | **PASS** | 2026-11-14 | `daily_ingest`, `score_replay`, `check_drift` in `scripts\e2e.ps1`; `retrain_candidate` run by hand → challenger v4, champion v1 (*docs/PRODUCTION_READINESS.md*) |
| Champion alias unchanged | **PASS** | 2026-11-16 (now) | server MLflow: 5 models, `champion` = v1, no challenger; project registry `mlflow.db`: 5 champions v1, no challenger; local stack MLflow: champions v1, challenger only on `flare-forecast-c60` (v4) |
| Alert e-mail sent and resolved | **PASS (sent + resolved sent)** | 2026-11-16 | server Alertmanager: `alertmanager_notifications_total{integration="email"} 2`, failed 0 (firing + resolved); no alert active now. Firing e-mail **received in Gmail at 12:44 IST** (owner). Arrival of the resolved e-mail: NOT CHECKED |
| Public rollback | **PASS** | 2026-11-16 | broken tag `does-not-exist` refused: 7 public requests, 0 failed; `--rollback` → `ROLLBACK OK (d4a22dc870f3)`; roll forward → `DEPLOY OK (65843c2962eb)`; 9 of 27 probe requests failed during the two Compose switches (*docs/PRODUCTION_READINESS.md* row 32) |
| **Public load test** | **errors PASS / p95 SLO FAIL** | 2026-11-16 (now) | k6 from this PC (India) to Sydney: **50 users, 2 min, 4,091 requests, 33.1 req/s, errors 0 %, p50 268.8 ms, p95 1,335.7 ms, p99 1,869.3 ms**, max 5,043.8 ms. Server-side API time in the same window (Prometheus): **p50 3.0 ms, p95 9.1 ms, p99 21.4 ms**. A single request from this PC spends 0.49 s connecting and 0.78 s in TLS: the public p95 is network distance, not server load |
| Load test (local, SLO) | **PASS** | 2026-11-14 | 50 users, 2 min, 5,950 requests, 49 req/s, 0 % errors, p50 2.2 ms, p95 8.3 ms, p99 20.5 ms (*docs/SLO.md*, `reports/loadtest/baseline.json`) |
| Backup + restore | **PASS (local)** / NOT RUN on the server | 2026-11-14 | 8 volumes, 29 MB, SHA-256 manifest; restored registry, aliases, 8 versions and 68,933 prediction rows identical, SQLite integrity ok (*docs/PRODUCTION_READINESS.md* rows 21–22) |
| Security scans | **PASS** | 2026-11-16 (CI on v1.2.0) | job `security` success: pip-audit image dependencies clean, CI dependencies 3 accepted MLflow CVEs; npm audit 0; trivy 0 CRITICAL in both images (*docs/SECURITY.md*) |
| Local e2e | **PASS** | 2026-11-14 | `E2E PASSED (e6f0f3b7f1f3)`; also `compose-e2e` PASS in CI on v1.2.0 (2026-11-16). Local smoke test re-run today: all 11 checks passed |

---

## 4. Pipeline and MLOps numbers

**DVC: 37 stages, 24 frozen; `dvc status`: "Data and pipelines are up to date"** (CHECKED NOW, `dvc.yaml`)

| Step | Stages |
|---|---|
| Data and detection (13) | fetch_goes, solexs_clean, detect_events, legacy_events, match_goes, evaluate_detector, build_dataset, hel1os_index, solexs_spectral, goes_xrs_fetch, goes_xrs_minute, srs_fetch, r3_fetch |
| Baseline training (1) | train |
| Improvement experiments (7) | improve_reference, improve_E2, improve_E3, improve_E4, improve_E5, improve_E6, improve_final |
| Final models and one-time test (6) | final_models, solexs_spectral_test, goes_xrs_test_fetch, goes_xrs_test_minute, evaluate_test, test_analysis |
| Development protocol 2 (9) | dev2_ref, dev2_e6, dev2_r2a, dev2_r2b, dev2_champ, dev2_r1, dev2_r3_mapping, dev2_r3, dev2_final |
| Holdout2 (1) | evaluate_holdout2 |

**MLflow (project registry `mlflow.db`, read-only): 767 runs**: detector-tuning 410, flare-models-v2 170, flare-models
105, flare-improve 54, flare-final2 14, flare-final 6, flare-dev2 6, flare-holdout2 1, eda 1, Default 0.

**Registered models**

| Model | Project registry (`mlflow.db`) | Server MLflow (AWS) | Local stack MLflow |
|---|---|---|---|
| flare-nowcast | champion v1 | champion v1 | champion v1 |
| flare-forecast-c30 | champion v1 | champion v1 | champion v1 |
| flare-forecast-c60 | champion v1 | champion v1 | champion v1, **challenger v4** (retrain drill 2026-11-14) |
| flare-forecast-m30 | champion v1 | champion v1 | champion v1 |
| flare-forecast-m60 | champion v1 | champion v1 | champion v1 |

**Prefect flows** (`flows/`): daily_ingest, score_replay, check_drift, retrain_candidate. Last run state:
- **Server:** no runs at all (scheduler error, see section 3).
- **Local stack:** daily_ingest, score_replay and check_drift Completed (2026-11-14); retrain_candidate Completed (2026-11-14). Two earlier failed retrain attempts are visible in the local Prefect UI; both causes (timezone, Windows encoding) were fixed.

**Grafana**: 1 dashboard, **9 panels** (*monitoring/grafana/dashboards/flare-api.json*; CHECKED on the server).

**Prometheus alert rules** (*monitoring/prometheus/alerts.yml*; CHECKED on the server)

| Rule | Condition | For | Severity |
|---|---|---|---|
| FlareApiHighErrorRate | `sum(rate(flare_api_requests_total{status=~"5.."}[5m])) / clamp_min(sum(rate(flare_api_requests_total[5m])), 1e-9) > 0.05` | 5 min | warning |
| FlareApiDown | `up{job="flare-api"} == 0` | 2 min | critical |

**Docker Compose services (10)**: caddy, frontend, api, worker, prefect-server, mlflow, mlflow-seed (one-off), prometheus,
alertmanager, grafana; plus `tools` (profile, one-off flows).

**Docker image sizes** (CHECKED NOW, on the server)

| Image | Size |
|---|---|
| ghcr.io/veenaphadtare12-ux/flare-api | 2.36 GB |
| ghcr.io/veenaphadtare12-ux/flare-frontend | 121 MB |
| ghcr.io/mlflow/mlflow:v3.16.1 | 1.28 GB |
| prefecthq/prefect:3.8.7-python3.12 | 1.14 GB |
| grafana/grafana:12.1.1 | 961 MB |
| prom/prometheus:v3.5.0 | 440 MB |
| prom/alertmanager:v0.28.1 | 110 MB |
| caddy:2.10.2-alpine | 83.2 MB |

**Kubernetes**: 16 YAML files in `k8s/` (kustomize base + overlays `kind` and `prod`, kind cluster config), **26 objects**:
8 Deployments, 7 Services, 7 PersistentVolumeClaims, 1 ConfigMap, 1 Job, 1 Namespace, 1 Ingress (Secrets and monitoring
ConfigMaps are created by `scripts/k8s/deploy.sh`, not stored in git).

Other counts: 2 GitHub workflows (CI with 5 jobs, CD with 2 jobs); 10 PowerShell and 9 bash scripts; 22 numbered lessons in
`docs/learn/`.

---

## 5. ML results (committed files only)

**Data** (*docs/PRESENTATION_FACTS.md* section A, from `data/processed/solexs_qc.csv`, `reports/data_inventory.csv`,
`data/processed/hel1os/coverage.csv`, `data/processed/dataset/`)
- SoLEXS usable days (≥ 50 % valid): **424** of 452 day folders, **2025-04-09 … 2026-09-12** (1-s light curves, SDD2).
- HEL1OS: **124** unique sessions on disk, **98** after the newest-version rule; date range 2024-07-01 … 2026-11-11.
- Rows with HEL1OS available: **4.7 %** overall (tune 4.0 %, validation 6.3 %).

**Detector validation** (*docs/PRESENTATION_FACTS.md* section B, from `reports/detection_metrics.json`; final setting)

| Metric | Tune | Validation |
|---|---|---|
| Onset error, median | 1.00 min | **1.00 min** |
| Onset error, p90 | 10.00 min | 9.00 min |
| Recall C | 0.85 | **0.88** |
| Recall M | 0.96 | **0.93** |
| Recall X | 1.00 | 1.00 |

**Final one-time test (2026-06-01 … 2026-09-12), 5 champions, operating point A** (threshold with maximum TSS on the
threshold block, chosen before the test) (*docs/MODEL_CARD.md*, from `reports/final/test_metrics.json`)

| Target | Model | TSS [95 % CI] | HSS | POD | FAR | Best baseline TSS |
|---|---|---|---|---|---|---|
| now | XGBoost | **0.758** [0.74, 0.78] | 0.457 | 0.87 | 0.64 | persistence 0.668 |
| c_30m | LogReg + XGBoost ensemble | **0.358** [0.29, 0.42] | 0.177 | 0.69 | 0.79 | persistence 0.017 |
| c_60m | XGBoost | **0.304** [0.23, 0.37] | 0.196 | 0.74 | 0.70 | rule 0.027 |
| m_30m | Logistic regression | **0.518** [0.34, 0.63] | 0.070 | 0.76 | 0.95 | rule 0.055 |
| m_60m | Logistic regression | **0.494** [0.33, 0.60] | 0.103 | 0.78 | 0.91 | persistence 0.080 |

**Holdout2 (2026-09-13 … 2026-11-12), 11 usable days, GOES flares B 33 · C 118 · M 7** (M underpowered: 7 < 15)
(*reports/holdout2/metrics.json*; flare counts *docs/PRESENTATION_FACTS.md* section M from `reports/holdout2/ingest.json`).
TSS, interval, POD, FAR and threshold are stored in the file; **HSS was computed here from the stored contingency counts**
(the computed POD and FAR match the stored ones exactly). Operating point A.

| Target | TSS [95 % CI] | HSS* | POD | FAR | Threshold (A) | Best baseline TSS |
|---|---|---|---|---|---|---|
| now | **0.760** [0.69, 0.81] | 0.555 | 0.88 | 0.52 | 0.280 | persistence 0.661 |
| c_30m | **0.486** [0.22, 0.67] | 0.285 | 0.98 | 0.66 | 0.286 | current flux 0.493 |
| c_60m | **0.603** [0.33, 0.78] | 0.506 | 0.98 | 0.44 | 0.291 | current flux 0.596 |
| m_30m (UNDERPOWERED) | 0.307 [−0.47, 0.50] | 0.012 | 1.00 | 0.98 | 0.039 | current flux 0.350 |
| m_60m (UNDERPOWERED) | 0.332 [−0.43, 0.54] | 0.026 | 1.00 | 0.96 | 0.054 | current flux 0.392 |

**Top 10 features by permutation importance** (drop in average precision; ≥C-within-60-min logistic regression,
seed 42, Dec 2025–Jan 2026 calibration rows, 5 shuffles per feature) (*reports/presentation_figures.json*
`importance_top15`; caveats in *docs/presentation_figures/FIGURE_NOTES.md*)

| # | Feature | Importance |
|---|---|---|
| 1 | bg_60m | 0.0852 |
| 2 | std_15m | 0.0637 |
| 3 | mean_15m | 0.0474 |
| 4 | mean_60m | 0.0422 |
| 5 | max_15m | 0.0307 |
| 6 | max_60m | 0.0284 |
| 7 | ratio_5m_60m | 0.0265 |
| 8 | max_5m | 0.0254 |
| 9 | std_5m | 0.0254 |
| 10 | mean_5m | 0.0241 |

No HEL1OS feature appears because no HEL1OS session falls in Dec–Jan; this says nothing about HEL1OS value.

**Ablation: soft only / hard only / combined** (rows with HEL1OS; validation; *docs/PRESENTATION_FACTS.md* section F)
- now, TSS at A: logreg soft 0.68 [0.65, 0.71], hard 0.66 [0.63, 0.69], combined 0.67 [0.65, 0.69]; xgb soft 0.63,
  hard 0.64, combined 0.65 (intervals overlap).
- c_30m: logreg soft 0.14, hard 0.00, combined 0.15; c_60m: logreg soft 0.21, hard 0.02, combined 0.16.
- Only visible gain: quiet-start nowcast with logreg, combined 0.45 [0.42, 0.48] vs soft 0.37 [0.31, 0.43].
- **Not conclusive**: hard X-rays alone carry about no skill for ≥C forecasts and adding them does not beat SoLEXS alone;
  c_120m and all M targets have too few positive episodes (< 30) to judge.

---

## 6. Problems and fixes since v1.1.0 (AWS deployment)

1. An AWS access key was pasted into a chat → treated as exposed and replaced; the CLI profile now uses a new key (deleting the old key in IAM was the owner's step).
2. `aws configure` kept showing the old masked key → explained that pasting at the prompt overwrites it; profile replaced.
3. The IAM user had no permissions → inline policy `flare-deploy` (EC2 limited to one region, Lightsail, read-only pricing/budget/free-tier).
4. **EC2 and Lightsail API calls are denied by the free plan's organisation SCP in every region** → server launched in the console; Terraform kept as validated code, not applied. (An early reading that Lightsail was allowed was wrong and was corrected.)
5. AWS CLI and Terraform were not installed, and `unzip` was missing → installed in the user's WSL home with Python's zip module; Terraform verified against HashiCorp's SHA-256 sums.
6. The instance was launched in Sydney, not Mumbai (console region) → kept; about USD 13/month more.
7. The security group lacked HTTP/HTTPS → Let's Encrypt could not reach port 80 and Caddy's fallback (ZeroSSL) got stuck → rules added, `docker compose restart caddy`, certificate issued within seconds.
8. The first CD deploy's public smoke test failed with no previous release to roll back to → after the fix, a second deploy created the previous tag that rollback needs.
9. Gmail needs an App Password, not the account password → the secrets script checks for 16 characters.
10. A misread log line suggested alerts were "log-only" → verified the `email` receiver and the delivery counters.
11. Compose release switches cost a few seconds (9 of 27 probe requests failed) → documented; zero-downtime updates are the Kubernetes path (CI).
12. The demo start command `up.ps1 -NoBuild` would download 2.4 GB → docs changed to `up.ps1 -Tag 7f03392ed044`.
13. Found in this check: Prefect scheduler error (no scheduled runs) → **fixed** with a patched Prefect server image (SQLAlchemy 2.0.57), see the update at the end. This PC's clock was 5.5 h behind real UTC (AWS CLI signatures rejected) → the owner fixes the time zone in Windows.

---

## 7. Limits and honest caveats

**Not run / failing**
- Scheduled Prefect runs on the server: **FAIL** (scheduler error; 0 runs). The "scored every night at 02:15 UTC" claim is true only in design until this is fixed; on the server `daily_ingest` and `check_drift` have never run. The same Prefect version runs in the local stack and is probably affected too (its runs were triggered by hand).
- `score_replay` and `retrain_candidate` on the server: NOT RUN (retrain is not deployed there).
- Backup and restore on the server: NOT RUN (proven on the local stack only).
- Terraform apply: NOT RUN (blocked by the SCP; the server was made by hand).
- Public p95 < 300 ms: **FAIL from India** (1,336 ms) because of distance to Sydney; the server itself answers in p95 9 ms.
- Credit remaining and credit used: NOT CHECKED (PC clock); arrival of the "resolved" alert e-mail: NOT CHECKED.

**Operational risks**
- One server, one Availability Zone, SQLite for MLflow and Prefect; a release switch costs a few seconds.
- SSH (22) is open to the internet, key-only login; GitHub-hosted runners need it.
- The running server spends credit, about USD 3.1/day; stop it between demos.
- Free services: DuckDNS for the name, Let's Encrypt for the certificate (auto-renewed by Caddy before 2027-02-14).
- 3 MLflow 3.16.1 CVEs accepted (internal-only server); Caddy, Prefect server and MLflow containers run as root (upstream images).
- Every documentation commit to `master` triggers a redeploy (new image tag, same app).

**Scientific limits** (*docs/PRESENTATION_FACTS.md*, *docs/MODEL_CARD.md*)
- New SoLEXS days must be downloaded by hand from ISRO PRADAN (personal login); no production day has been scored yet.
- HEL1OS overlaps usable SoLEXS rows only about 5 % (4.7 %) of the time, so hard X-rays stay optional and the ablation is underpowered.
- The forecasts mostly read the current activity level; on holdout2 a one-number current-flux baseline is about as good for C forecasts.
- M-class: only 7 M flares in holdout2 (underpowered); on the test, M alerts have FAR 0.91–0.95 at operating point A.
- Validation was used for model comparisons; the one-time test and holdout2 are the unbiased scores.
- Research system: NOAA SWPC issues official alerts.

---

## 8. Screenshots for the slides (`submission/slides_shots/`, PNG, device scale factor 2)

| File | Size | Pixels | Source and notes |
|---|---|---|---|
| 01_live_site.png | 1.46 MB | 2048 × 1280 | **live public URL** https://veena-flare.duckdns.org/. Viewport 1024 × 640 at scale 2 and a 256-colour palette to stay under 1.5 MB (the 3D Sun and star field do not compress). **The browser padlock is not visible**: a page screenshot contains only the page, not the address bar; certificate facts are in section 2 |
| 02_console_latest.png | 0.34 MB | 2880 × 1800 | live public URL `/latest` (shows "no run yet" for daily_ingest, consistent with the scheduler finding) |
| 03_console_replay.png | 0.66 MB | 2880 × 1800 | live public URL `/replay`, X-class day 2026-04-24 replayed to 13:50 UTC (alerts on) |
| 04_grafana.png | 0.26 MB | 2880 × 1800 | **local stack** Grafana (same images and dashboard), last 15 min after 90 s of local traffic; the server's Grafana is not public and an SSH tunnel for screenshots was not allowed |
| 05_mlflow_registry.png | 0.31 MB | 2880 × 1800 | **local stack** MLflow: 5 champions v1 and challenger v4 on c60 |
| 06_prefect_runs.png | 0.25 MB | 2880 × 1800 | **local stack** Prefect: 12 runs from the drills of 2026-11-14 (2 failed retrain attempts, causes fixed) |
| 07_github_actions.png | 0.32 MB | 2880 × 1800 | public GitHub Actions page (CI and CD runs, all green) |
| 08_architecture.png | — | — | **not created**: no diagram exists in `submission/` (the architecture is described in text in `docs/ARCHITECTURE.md` and `docs/REPORT.md`) |

No key, password or token is visible in any screenshot.

---

## 9. Viva-day facts

**The 5 commands** (Windows PowerShell)
```
cd D:\projects\solar-flare-project
.\scripts\up.ps1 -Local              # start the full local stack from the newest images on this PC
.\scripts\smoke_test.ps1               # must end with "all checks passed"
.\scripts\e2e.ps1 -SkipBuild         # optional, ~5 min: raw day -> Prefect -> contracts -> champions -> store -> API -> website
.\scripts\down.ps1                     # stop everything (data volumes are kept)
```

**EC2 instance** (AWS console, region **Asia Pacific (Sydney)**): EC2 → Instances → `flare` →
**Instance state → Start** (wait about 3 minutes, then open the public URL; the stack starts by itself) or **Stop** after the
demo (keeps disk, Elastic IP and data; about USD 7/month while stopped).

**The 3 links to open first**
1. https://veena-flare.duckdns.org (live on AWS, HTTPS)
2. http://localhost/replay (local console after `up.ps1`; replay the X-class day)
3. https://github.com/veenaphadtare12-ux/Nowcasting-and-forecasting-of-soar-flare_mlops/actions (CI 5 jobs + CD to AWS)

Before the viva: fix this PC's clock (Windows Settings → Time & language → Date & time → set the time zone to
"(UTC+05:30) Chennai, Kolkata, Mumbai, New Delhi" and "Sync now"), so that AWS CLI checks work again.

---

## Update after the check: Prefect scheduler fixed (2026-11-16 UTC)

- **Cause:** the official `prefecthq/prefect:3.8.7-python3.12` image ships SQLAlchemy 2.1.1; Prefect 3.8.7's scheduler
  (`_insert_scheduled_flow_runs`) fails with it on every pass, so scheduled deployments never created runs.
- **Fix:** `docker/prefect-server.Dockerfile` = the same Prefect 3.8.7 server with SQLAlchemy **2.0.57**, published as
  `ghcr.io/veenaphadtare12-ux/flare-prefect-server:<git sha>` and used by Docker Compose, Kubernetes, CI and CD;
  `tests/test_deploy_config.py` (3 tests) keeps it that way. Commit `bfe0fa8`.
- **Proof, local:** 0 scheduler errors; 6 runs scheduled (02:15 and 03:30 UTC for 3 nights); a `check_drift` run scheduled
  1 minute ahead was picked up by the worker and finished **Completed**.
- **Proof, CI:** run 43948566960: test, compose-e2e, kind, terraform, security, all success.
- **Proof, AWS:** CD run 43950207588 deployed `bfe0fa8ebe2a` over `54c55abb1927` (`DEPLOY OK`, `SMOKE OK`). On the server:
  Prefect image `flare-prefect-server:bfe0fa8ebe2a`, **0 scheduler errors since restart**, next runs scheduled:
  daily_ingest 2026-11-17 02:15 UTC, check_drift 2026-11-17 03:30 UTC, then every night.
- **Still true:** no production day can be scored until a SoLEXS L1 day from 2026-11-13 or later is downloaded from
  ISRO PRADAN and placed where the server reads raw days; until then `daily_ingest` runs and reports "nothing waiting".
