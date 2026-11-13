# Solar Flare Nowcasting/Forecasting with Aditya-L1 SoLEXS + HEL1OS Data

[![CI](https://github.com/veenaphadtare12-ux/Nowcasting-and-forecasting-of-soar-flare_mlops/actions/workflows/ci.yml/badge.svg)](https://github.com/veenaphadtare12-ux/Nowcasting-and-forecasting-of-soar-flare_mlops/actions/workflows/ci.yml)

This is an MLOps project that combines soft X-ray data from SoLEXS and hard X-ray data from HEL1OS, both instruments aboard India's Aditya-L1 mission, to detect and forecast solar flares. The project builds an end-to-end pipeline — from raw data ingestion and preprocessing through model training and evaluation — aimed at identifying flare onset in near real time (nowcasting) and predicting flare activity ahead of time (forecasting).

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
GitHub Actions (`.github/workflows/ci.yml`) runs ruff and `pytest -m "not data"` on Python 3.12 on every push and pull request.

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
