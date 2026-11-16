# Solar Flare Nowcasting/Forecasting with Aditya-L1 SoLEXS + HEL1OS Data

[![CI](https://github.com/veenaphadtare12-ux/Nowcasting-and-forecasting-of-soar-flare_mlops/actions/workflows/ci.yml/badge.svg)](https://github.com/veenaphadtare12-ux/Nowcasting-and-forecasting-of-soar-flare_mlops/actions/workflows/ci.yml)
[![CD](https://github.com/veenaphadtare12-ux/Nowcasting-and-forecasting-of-soar-flare_mlops/actions/workflows/cd.yml/badge.svg)](https://github.com/veenaphadtare12-ux/Nowcasting-and-forecasting-of-soar-flare_mlops/actions/workflows/cd.yml)

This is an MLOps project that combines soft X-ray data from SoLEXS and hard X-ray data from HEL1OS, both instruments aboard India's Aditya-L1 mission, to detect and forecast solar flares. The project builds an end-to-end pipeline — from raw data ingestion and preprocessing through model training and evaluation — aimed at identifying flare onset in near real time (nowcasting) and predicting flare activity ahead of time (forecasting).

**Live:** https://veena-flare.duckdns.org (AWS EC2, HTTPS by Caddy + Let's Encrypt, deployed by GitHub Actions CD).

## Run the product (3 commands, Windows PowerShell)
```
.\scripts\up.ps1            # build the images (tagged with the git SHA) and start the whole stack in Docker
.\scripts\smoke_test.ps1    # check every service
.\scripts\e2e.ps1           # raw day -> Prefect -> data contracts -> features -> champions -> store -> API -> website
```
| URL | What |
|---|---|
| http://localhost | the public entry through Caddy (HTTPS automatically when `SITE_ADDRESS` is a domain) |
| http://localhost:8080 | website: 3D landing page and the console (latest day, replay, performance, models, drift) |
| http://localhost:8000/docs | FastAPI (frozen champion models) |
| http://localhost:4200 | Prefect (daily ingest 02:15 UTC, drift check 03:30 UTC, replay on demand) |
| http://localhost:5000 | MLflow model registry |
| http://localhost:9090 / :9093 / :3000 | Prometheus (2 alert rules) / Alertmanager / Grafana dashboard |

`POST /predict` needs the header `X-API-Key`; `up.ps1` creates a local key in the git-ignored `.env` (`FLARE_API_KEYS`).

Kubernetes: `.\scripts\k8s_kind.ps1 -Demo` (kind cluster, rolling update and rollback). Deployment: GitHub Actions CD to
GHCR and a k3s server (`docs/RUNBOOK.md`). Docker Engine runs in WSL Ubuntu; the scripts call it themselves.

| Document | For |
|---|---|
| `docs/REPORT.md` | the project report: problem, data, method, results, MLOps, limitations |
| `docs/DEMO.md` | a 10-minute live demo script |
| `docs/RUNBOOK.md` | start/stop, alerts, HTTPS, API-key rotation, backup/restore, rollback, Kubernetes, CD, Terraform |
| `docs/PRODUCTION_READINESS.md` | PASS / FAIL / NOT RUN for every production item, with proof |
| `docs/SECURITY.md`, `docs/SLO.md` | security controls, scans, accepted risks; load-test results against the SLOs |
| `docs/DEPLOY_STEPS.md` | exactly what is needed for the public deployment |
| `docs/VIVA_CHEATSHEET.md` | one page for the viva |
| `docs/INTERVIEW_PREP.md` | questions and answers about every design choice |
| `docs/ARCHITECTURE.md` | the system contract |
| `docs/DEPLOY_PROGRESS.md` | what was built and verified, with dates and disk log |

Results and decisions: `docs/MODEL_CARD.md`, `docs/FINAL_CHOICE.md`, `docs/FINAL_CHOICE_2.md`, `docs/IMPROVEMENTS.md`.
Plain-language overview: `docs/WHAT_WE_DID.md`. Lessons: `docs/learn/INDEX.md`.

## Layout
| Path | What |
|---|---|
| `src/` | pipeline code (ingest, detector, features, labels, models, evaluation) |
| `src/validation/` | pandera data contracts, run inside the DVC data stages |
| `src/ops/` + `flows/` | operational logic + Prefect flows (ingest, replay, drift, challenger retraining) |
| `dvc.yaml`, `dvc.lock`, `params.yaml` | the pipeline, its data versions, all settings |
| `tests/` | pytest; `tests/fixtures/` = small committed sample tables for CI |
| `models_final/`, `mlflow.db`, `mlruns/`, `data/` | local only (DVC / MLflow), not in git |

## Setup
```
python -m venv .venv
.venv\Scripts\Activate.ps1            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt       # full pinned dev environment (Windows freeze)
pre-commit install                    # ruff + ruff-format + basic checks on every commit
```
Other environments: `requirements-ci.txt` (what CI installs, Linux) and `requirements-serve.txt` (serving the models).
`Makefile` shortcuts: `make setup | test | test-ci | lint | repro | status | ingest | drift | replay | retrain | serve`
(on Windows use `mingw32-make`, or run the command shown in the Makefile).

## Tests and CI
```
pytest -q                     # everything (needs the local DVC data)
pytest -q -m "not data"       # what CI runs: uses tests/fixtures only
ruff check .
```
GitHub Actions on every push and pull request (`.github/workflows/ci.yml`):
- `test`: ruff and `pytest -m "not data"` on Python 3.12;
- `compose-e2e`: builds the images and runs `scripts/e2e.sh` against the full Docker Compose stack;
- `kind`: deploys `k8s/` to a kind cluster (automatic rollback on failure), smoke test, rolling update and rollback demo;
- `terraform`: `terraform fmt -check` and `terraform validate` for `infra/terraform` (never applied);
- `security`: pip-audit, npm audit, trivy on both images (fails on CRITICAL).

`.github/workflows/cd.yml` publishes the images to GHCR (git SHA + version tag) after CI passes on master or on a `v*` tag,
and deploys to the k3s server over SSH when the secrets `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` exist.

## Data contracts (pandera)
`src/validation/schemas.py` defines contracts for the SoLEXS minute series, HEL1OS sessions, GOES events, the 10-s feature
dataset and model predictions. The DVC stages `solexs_clean`, `hel1os_index`, `match_goes` and `build_dataset` run
`python -m src.validation.check <table>` after producing their output, so a broken table stops `dvc repro` with a message like

```
Data contract 'solexs_minute' broken in solexs_minute.parquet: 1 failure(s)
  - column m: greater_than_or_equal_to(0)  (e.g. -5.0)
```

## Prefect flows
All flows keep their state in a project-local Prefect home (`.prefect/`, not in git).
```
$env:PREFECT_HOME = "$PWD\.prefect"     # PowerShell   (bash: export PREFECT_HOME=$PWD/.prefect)
prefect server start                    # optional UI at http://127.0.0.1:4200 (then, in a 2nd terminal:
$env:PREFECT_API_URL = "http://127.0.0.1:4200/api"    #  point the flows at it; without a server they run in a temporary local one)

python -m flows.daily_ingest                                          # new local days, GOES reports, validate, dvc repro (data stages only)
python -m flows.check_drift                                           # Evidently: training features vs last 30 dev days -> reports/drift/
python -m flows.score_replay 2026-04-01 2026-04-08                    # champions -> data/predictions/*.parquet + predictions.db
python -m flows.retrain_candidate c_60m 2025-04-09 2026-09-13 2026-08-01   # registers alias "challenger" only
```
Safety rules built into the flows (`src/ops/locks.py`):
- no flow reads data after the development end (2026-09-13): holdout2 and any newer days are locked for the next
  one-time evaluation; `daily_ingest` only lists them by name;
- `score_replay` only scores tune + val (the old test period is never re-scored);
- `retrain_candidate` registers a **challenger** and asserts that the **champion** alias did not move — promotion is a
  manual decision after a fresh one-time evaluation;
- all model and evaluation DVC stages are `frozen`; `daily_ingest` re-runs only data stages.

## Serving a champion model
```
make serve MODEL=flare-nowcast          # MLflow REST endpoint on http://127.0.0.1:5001/invocations
```
Input: the model's feature columns (see its signature in MLflow); output: `[P(no flare), P(flare)]`; alert when
P(flare) ≥ the version tag `thr_A`.
