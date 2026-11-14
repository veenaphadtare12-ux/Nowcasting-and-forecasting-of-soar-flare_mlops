# Production readiness (v1.1.0, checked 2026-11-14)

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
| 17 | HTTPS | **PASS (local CA) / NOT RUN (public)** | `SITE_ADDRESS=localhost`: https://localhost → HTTP/2 200, issuer "Caddy Local Authority", http → 308 to https. A Let's Encrypt certificate needs a public domain: NOT RUN |
| 18 | Alert rules fire | **PASS** | `alert_drill.ps1 -Rule down` → FIRING after 135–180 s; `-Rule errors` → FIRING with error ratio 0.51 (screenshots `docs/screenshots/prometheus_alert_*.jpg`) |
| 19 | Alert delivery to Alertmanager | **PASS** | fake alert POSTed → state active, receiver `log-only`; real `FlareApiDown` reached Alertmanager ~140 s after the API stopped |
| 20 | Alert e-mail | **NOT RUN** | no SMTP account configured; set `SMTP_*` and `ALERT_EMAIL_TO` in `.env` / GitHub secrets |
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
| 31 | Public deployment | **NOT RUN** | no `DEPLOY_HOST` / `DEPLOY_USER` / `DEPLOY_SSH_KEY` secrets; exact steps in `docs/DEPLOY_STEPS.md`; dry run of the CD deploy script passed locally |
| 32 | Public rollback | **NOT RUN** | needs the deployment above; same sequence proven in CI (row 30) |
| 33 | Drift monitoring | **PASS** | `check_drift` flow Completed; `/drift/latest` drifted share 0.64, flag True (on development data: drift is real and expected) |
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
- **Not run:** public deployment and rollback on a server, a public Let's Encrypt certificate, alert e-mail.

## Release
v1.1.0: see the git tag message and the final CI run recorded in `docs/DEPLOY_PROGRESS.md`.
