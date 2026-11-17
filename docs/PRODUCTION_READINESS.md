# Production readiness (v1.2.0: live on AWS 2026-11-16; v1.1.0 checks 2026-11-14)

Every row was run on 2026-11-14 on the development PC (Windows 11, Docker Engine in WSL Ubuntu) or in GitHub Actions,
unless it says **NOT RUN**. Nothing is marked PASS from memory.

## Summary
| # | Item | Result | Proof (command → result) |
|---|---|---|---|
| 1 | Git state | **PASS** | `git status` → clean before work started |
| 2 | Pipeline (DVC) | **PASS** | `dvc status` → "Data and pipelines are up to date" (37 stages, 24 frozen) |
| 3 | Unit and integration tests | **PASS** | `pytest -q` → 145 passed, 1 skipped (146 tests); `ruff check .` → clean |
| 4 | Full stack up | **PASS** | `.\scripts\up.ps1` → 9 services healthy (caddy, frontend, api, worker, prefect-server, mlflow, prometheus, alertmanager, grafana) |
| 5 | Smoke test | **PASS** | `.\scripts\smoke_test.ps1` → all checks passed (12 checks incl. `POST /predict` with key, 401 without) |
| 6 | End-to-end | **PASS** | `.\scripts\e2e.ps1 -Tag e48339fa084f` → "E2E PASSED": inbox day → Prefect `daily_ingest` deployment → contracts → features → champions → store → API → website; replay, drift, Prometheus, Grafana |
| 7 | Prefect flows | **PASS** | `daily_ingest`, `score_replay`, `check_drift` → Completed (in e2e); `retrain_candidate c_60m 2025-04-09 2026-06-01 2026-05-01` → Completed, challenger v4, champion still v1 |
| 8 | Challenger-only retraining | **PASS** | MLflow aliases after the run: `flare-forecast-c60` champion=1, challenger=4; project `mlflow.db` untouched (767 runs, all champions v1, no challenger) |
| 9 | API health, predict, metrics | **PASS** | `/health` 200, `POST /predict` p=0.131 thr=0.440 with key, `/metrics` exposes `flare_api_requests_total` |
| 10 | Website | **PASS** | http://localhost:8080 → 200; http://localhost (Caddy) → 200 |
| 11 | MLflow registry | **PASS** | 5 registered models with alias `champion` |
| 12 | Monitoring | **PASS** | Prometheus targets `flare-api`, `prometheus`, `alertmanager` all UP; Grafana dashboard "Solar flare API" (9 panels) returns data through its Prometheus datasource |
| 13 | CI | **PASS** | GitHub Actions run 43570488801: test, compose-e2e, kind, terraform, security → 5/5 success (final release run: see "Release" below) |
| 14 | API key | **PASS** | `tests/test_api.py`: 401 without / with wrong key, 200 with key, old+new key both valid, 401 when no key configured |
| 15 | Rate limit | **PASS** | test: 5 requests 200 then 429 with `Retry-After`; `/health`, `/metrics` never limited; k6 at 200 users: 3,055 × 429 from one key |
| 16 | Request size limit, CORS | **PASS** | tests: 413 above the limit; evil origin gets no `Access-Control-Allow-Origin`; wildcard ignored |
| 17 | HTTPS | **PASS (public)** | 2026-11-16: Caddy obtained a **Let's Encrypt** certificate for veena-flare.duckdns.org (log: `certificate obtained successfully`, issuer acme-v02.api.letsencrypt.org); https → 200, http → 308 to https; security headers present |
| 18 | Alert rules fire | **PASS** | `alert_drill.ps1 -Rule down` → FIRING after 135–180 s; `-Rule errors` → FIRING with error ratio 0.51 (screenshots `docs/screenshots/prometheus_alert_*.jpg`) |
| 19 | Alert delivery to Alertmanager | **PASS** | fake alert POSTed → state active, receiver `log-only`; real `FlareApiDown` reached Alertmanager ~140 s after the API stopped |
| 20 | Alert e-mail | **PASS** | 2026-11-16 on the server: Alertmanager receiver `email` (Gmail SMTP with an App Password); test alert `FlareEmailDeliveryTest` → `alertmanager_notifications_total{integration="email"} 1`, failed 0. **Received in the owner's Gmail inbox at 12:44 on 2026-11-16** |
| 21 | Backup | **PASS** | `.\scripts\backup.ps1` → 8 volumes, 29 MB, `D:\backups\flare\20261114T075117Z` with SHA-256 manifest |
| 22 | Restore | **PASS** | `restore.ps1 -Prefix flare_restoretest` → checksums verified, file counts equal; MLflow DB `integrity_check` ok, same 5 models, aliases, 8 versions; predictions 68,933 rows; MLflow, predictions, drift byte-identical |
| 23 | Load test vs SLOs | **PASS** | `.\scripts\loadtest.ps1` (50 users, 2 min): 5,950 requests, 49 req/s, 0 % errors, p50 2.2 ms, p95 8.3 ms, p99 20.5 ms (SLO p95 < 300 ms, errors < 1 %) |
| 24 | Load test (first attempt) | **FAIL → fixed** | before the fix: 60-s timeouts and `/health` starved; fixed by caching prepared replay days and async probes; responses byte-identical |
| 25 | Dependency scans | **PASS (1 accepted risk)** | pip-audit image deps: none; npm audit: 0; pip-audit CI deps: 3 MLflow 3.16.1 CVEs accepted (`docs/SECURITY.md`) |
| 26 | Image scans | **PASS** | trivy, CRITICAL, fixed-only, both images → 0 (CI job fails otherwise) |
| 27 | Container hardening | **PASS** | `docker inspect`: non-root api/worker (app), frontend (101), grafana (472), prometheus/alertmanager (nobody); memory limits and `unless-stopped` on all; healthchecks on all; pinned image versions |
| 28 | Kubernetes deploy | **PASS (CI)** | CI `kind` job: `DEPLOY OK`, smoke 5/5 |
| 29 | Rolling update | **PASS (CI)** | 67 requests during the update, 0 failed |
| 30 | Rollback | **PASS (CI)** | bad image never became ready, old pods kept serving, `rollout undo` restored the good image |
| 31 | Public deployment | **PASS** | **https://veena-flare.duckdns.org** on AWS EC2 (m7i-flex.large, Sydney, Elastic IP 54.79.250.93). CD run 43821987129: publish → SSH deploy `65843c2962eb` over `d4a22dc870f3` → public smoke 6/6 (website, health, `/api/models`, replay days, metrics not public) |
| 32 | Public rollback | **PASS** | broken release (tag `does-not-exist`) refused before touching the stack: 7 public requests, 0 failed, still serving `65843c2962eb`; manual `server_deploy.sh --rollback` → `ROLLBACK OK (d4a22dc870f3)`, roll forward → `DEPLOY OK (65843c2962eb)`. Compose recreates containers, so a switch costs a few seconds (9 of 27 probe requests failed); the zero-downtime rolling update is the Kubernetes path (row 29) |
| 33 | Drift monitoring | **PASS** | `check_drift` flow Completed; `/drift/latest` drifted share 0.64, flag True (on development data: drift is real and expected) |
| 37 | Scheduled Prefect runs | **PASS (fixed 2026-11-16)** | 2026-11-16: the official Prefect 3.8.7 image ships SQLAlchemy 2.1.1; its scheduler failed on every pass (`Can't evaluate bulk DML statement`), so the server had 0 flow runs. Fix: `docker/prefect-server.Dockerfile` (same Prefect, SQLAlchemy 2.0.57), used by Compose, Kubernetes, CI and CD; guarded by `tests/test_deploy_config.py`. Local proof: 0 scheduler errors, 6 runs scheduled (02:15 and 03:30 UTC for 3 nights), a run scheduled 1 minute ahead was executed by the worker and Completed. AWS (CD run 43950207588, image `bfe0fa8ebe2a`): 0 scheduler errors, nightly runs scheduled (first: daily_ingest 2026-11-17 02:15 UTC) |
| 38 | First production days (new data) | **PASS** | 2026-11-17: SoLEXS 2026-11-13 and 2026-11-14 (after every evaluation period) scored by `daily_ingest` through Prefect, locally and on AWS; public `/latest` shows 2026-11-14 with 100 % coverage, 6 GOES flares, alerts for 3 targets |
| 39 | Website after an API-only restart | **PASS (fixed)** | 2026-11-17: nginx now re-resolves the API every 10 s; with the API forced onto a new IP the site recovered in about 3 s (before: 502 until the frontend restarted) |
| 34 | CD image publishing | **PASS** | CD runs publish `ghcr.io/veenaphadtare12-ux/flare-{api,frontend}:<sha>` + `master` / `vX.Y.Z`; packages public (anonymous pull token 200) |
| 35 | Terraform | **PASS (validate) / NOT APPLIED** | CI `terraform fmt -check` + `validate`; applying creates billable resources, by decision |
| 36 | Docs consistency | **PASS** | README, REPORT, RUNBOOK, DEMO, INTERVIEW_PREP, ARCHITECTURE updated to these numbers; dated documents carry a current-state banner |

## Bugs found by this check (all fixed, with tests)
1. `retrain_candidate` crashed on the real UTC-indexed dataset (timezone-naive block start); `tests/test_ops.py::test_retrain_accepts_date_strings_on_a_utc_index`.
2. A Prefect test passed only while the developer's Prefect profile pointed at a running server; `tests/conftest.py` isolates it.
3. Under 50 users `/replay/{day}` starved the API, including `/health`; cache + async probes, `test_replay_cache_key_follows_the_store`.
4. `/metrics` was reachable publicly through the website; nginx now returns 404 and `smoke.sh` checks it.
5. `up.ps1` never deleted old image tags (`wsl.exe` expanded `$img` early); moved into `scripts/prune_old_images.sh`.
6. `api.Dockerfile` declared the git SHA above the apt/pip layers, so every rebuild re-downloaded ~2 GB (the cause of the
   repeated disk stops); the SHA now comes after them.

## Commands used
```
git status; dvc status; pytest -q; ruff check .
.\scripts\up.ps1 ; .\scripts\smoke_test.ps1 ; .\scripts\e2e.ps1
$env:MLFLOW_TRACKING_URI="http://localhost:5000"; $env:PYTHONUTF8=1; python -m flows.retrain_candidate c_60m 2025-04-09 2026-06-01 2026-05-01
.\scripts\alert_drill.ps1 -Rule down ; .\scripts\alert_drill.ps1 -Rule errors
.\scripts\backup.ps1 ; .\scripts\restore.ps1 -From D:\backups\flare\<time> -Prefix flare_restoretest
.\scripts\loadtest.ps1 ; .\scripts\loadtest.ps1 -Vus 200 -Duration 1m
gh secret list ; gh run list
```

## Known limits
- **Manual data download:** new SoLEXS L1 days come from ISRO PRADAN, which needs a personal login; they are downloaded by
  hand into the raw folder (or inbox) and then scored automatically. No production day after 2026-11-13 exists yet, so
  the "Latest" page correctly shows "no production day yet".
- **Single node:** Compose on one machine or k3s on one server; ReadWriteOnce volumes; SQLite for MLflow and Prefect.
- **HEL1OS coverage:** hard X-rays overlap usable SoLEXS data only about 5 % of the time (4.7 %), so HEL1OS stays optional
  and production does not use it yet.
- **What the forecasts learn:** they mostly read the current solar activity level; on holdout2 a one-number current-flux
  baseline does almost as well for C forecasts.
- **Small M-class sample:** holdout2 had 7 M flares, so M results there are underpowered and no claim is made.
- **Research system:** NOAA SWPC issues official alerts; M alerts have many false alarms.
- **Rate limits are per process** (one API worker per container; each Kubernetes replica counts separately).
- **Cloud account:** the AWS free plan's organisation SCP denies EC2/Lightsail API calls with access keys, so the server
  was launched in the console; Terraform describes it but cannot be applied from this account.
- **Single server, Compose:** a release switch costs a few seconds of downtime (Kubernetes path is zero-downtime, CI).
- **Cost:** the server uses the AWS credit (~USD 0.12/h); stop it between demos (`docs/DEPLOY_STEPS.md`).

## Release
v1.1.0 (tag on the commit after `e6f0f3b`): CI run 43578152118 on `e6f0f3b` → test, compose-e2e, kind, terraform,
security: 5/5 success. Local on image `e6f0f3b7f1f3`: smoke test passed, `e2e.ps1` → E2E PASSED, `smoke.sh http://localhost`
→ SMOKE OK (incl. "metrics not public").
