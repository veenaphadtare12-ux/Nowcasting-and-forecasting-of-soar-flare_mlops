# Architecture and integration contract

*Written 2026-11-13, before any Phase 2–8 code. Every later change must keep these rules or update this file first.*

## 0. Frozen ML phase
- The champion models, thresholds and all evaluation numbers are **frozen** (`docs/FINAL_CHOICE.md`,
  `docs/FINAL_CHOICE_2.md`).
- Nothing in the product retrains a champion, re-tunes, re-scores an evaluation period, or reads holdout data.
- Data after the development end (2026-09-13) is locked (`src/ops/locks.py`).
- The product only **displays** frozen results and **replays** development days.

## 1. One source of truth for models: the registry alias `champion` → the model bundle

```
MLflow registry (mlflow.db, alias "champion")
        │  scripts/export_bundle.ps1  →  python -m src.serving.bundle export
        ▼
model_bundle/                                   (committed, < 50 MB, versioned)
  manifest.json      bundle version, git SHA, created_at, per model: registry name, version, run id, target,
                     learner, features, thresholds A/B/C, SHA-256 of the model file; replay days; results summary
  models/<target>.joblib      the champion estimator, exported from models:/<name>@champion
  model_card.json             headline metrics (test + holdout2, with intervals) from docs/MODEL_CARD.md sources
  replay/<day>/…              inputs + pipeline features + predictions + GOES flares + detector events
  drift/latest.json           copy of reports/drift/latest.json
  pipeline/status.json        DVC stages (frozen flags), tool status, last flow runs, registry (champion/challenger)
```

- The API, the Prefect flows and Kubernetes load models **only** from the bundle (`src/serving/bundle.py`). Each
  model file is checked against its SHA-256 in `manifest.json` on load.
- The registry → bundle export is the only path. A test checks that bundle versions equal the registry champion
  versions, when the local registry exists.
- Current champions: `flare-nowcast`, `flare-forecast-c30`, `flare-forecast-c60`, `flare-forecast-m30`,
  `flare-forecast-m60`, all version 1.
  - They were chosen by `docs/FINAL_CHOICE.md`.
  - Holdout2 was scored with the FINAL_CHOICE_2 refits (same recipes, more data), which were never registered.
  - Promoting them is a human decision and is not done here. The frontend labels which models produced which
    result.

## 2. One source of truth for features: the pipeline's feature code
- All feature math lives in `src/features.py` (`bin_counts`, `solexs_features`, `hel1os_channels`,
  `hel1os_features`) and `src/improve/features_extra.py` (extra blocks used by the c_30m champion).
- `src/serving/features.py` composes them for one day, exactly as `src/dataset.py::build_all` does:
  - previous-day warm-up of max window + 70 min;
  - right-closed 10-s bins;
  - row filter `rate` present and `valid_frac_5m ≥ 0.8`;
  - float32.
- The API imports `src/serving/features.py`; it never re-implements a feature.
- **Equality test** (`tests/test_serving_features.py`): for every bundle day, features recomputed by the API code from
  the bundle's raw inputs (1-s SoLEXS counts, HEL1OS channels) equal the pipeline's own dataset rows stored in the
  bundle, column by column. A data-marked variant compares against `data/processed/dataset` directly.

## 3. One config
- `params.yaml` holds all science/pipeline settings. `src/settings.py` (pydantic-settings) holds runtime/service
  settings: bundle path, predictions store, CORS origins, log level, replay speed limits, Prometheus.
- Services get settings **only** through environment variables (`FLARE_*`):
  - in Docker Compose: `docker-compose.yml` `environment:` / `.env`;
  - in Kubernetes: a ConfigMap (`k8s/configmap.yaml`) mapped to the same variables.

## 4. One data flow, end to end
```
                      (developer machine, DVC data)                            (any machine, bundle only)
Prefect daily_ingest ─► pandera checks ─► dvc repro (data stages only)
                                               │
                                     scripts/export_bundle ─► model_bundle/ ─────────────────────────┐
                                                                                                    ▼
Prefect score_replay (bundle day) ─► predictions store data/predictions/{*.parquet, predictions.db} ─► FastAPI ─► React
Prefect check_drift ─► reports/drift/latest.json ─► bundle drift/latest.json ─► FastAPI /drift/latest ─► React
FastAPI /metrics ─► Prometheus ─► Grafana (+ 1 alert rule)
Prefect retrain_candidate ─► MLflow alias "challenger" ─► bundle pipeline/status.json ─► /pipeline/status ─► React
                              (never auto-promoted)
```
- `score_replay` has two sources. `--source dvc` (developer, `data/processed`) and `--source bundle` (any machine;
  scores a bundle replay day with the bundle models). Both write the same validated `predictions` contract
  (`src/validation/schemas.py::PREDICTIONS`) to the same store.
- The API serves `/replay/{day}` from the predictions store when it has rows for that day, otherwise from the
  bundle's precomputed predictions. The response says which (`source`, `run_id`).

## 5. Images and deployment
- Two images: `flare-api` (python:3.12-slim, non-root, healthcheck; also runs the flows) and `flare-frontend` (nginx,
  static build).
- Tags: the git SHA (and `v*` on releases).
- The same images run in Docker Compose (local + the CI e2e job), in kind (Kubernetes) and, prepared only, on AWS.
- Compose services: `api`, `frontend`, `prometheus`, `grafana`; `worker` = the `flare-api` image running a flow
  (`docker compose run --rm worker python -m flows.score_replay …`).
- Kubernetes (kind): `api` (2 replicas, probes, limits), `frontend`, Services, NodePort, ConfigMap. The bundle is
  baked into the API image.

## 6. API surface (FastAPI, `src/serving/api.py`)
| Method | Path | Returns |
|---|---|---|
| GET | `/health` | status, bundle version, git SHA, models loaded |
| GET | `/models` | champion per target: version, learner, thresholds, features; challenger if any |
| GET | `/replay/days` | bundle replay days with flare counts and notes |
| GET | `/replay/{day}?until=` | light curves, predictions (all targets), GOES flares and detector events known by `until` |
| GET | `/replay/{day}/stream?speed=&start=` | server-sent events, one frame per 10-s step |
| POST | `/predict` | probabilities + alerts for feature rows, or for a raw SoLEXS 1-s window (features computed with the pipeline code) |
| GET | `/results` | frozen test and holdout2 results with 95% intervals, baselines, per month |
| GET | `/drift/latest` | latest Evidently summary |
| GET | `/pipeline/status` | DVC stages, Prefect runs, registry, tools |
| GET | `/metrics` | Prometheus metrics |

**Causality in the replay:** a GOES flare is shown only once its begin time ≤ the replay clock. A detector event is
shown only once its trigger time ≤ the clock, and its end only once that is known. Probabilities at t use features
built only from data ≤ t.

## 7. Honesty rules for the UI
- Every number shown comes from a committed source file; the source is named in the UI.
- Replay days are development days:
  - four are inside the champions' fit period ("in-sample demo");
  - 2026-05-16 is in the threshold month.
  - The UI says so, and replay is never presented as evaluation.
- M results on holdout2 are labelled UNDERPOWERED. The test results come from the one-time evaluation and are not
  recomputed.
