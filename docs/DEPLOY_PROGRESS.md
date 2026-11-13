# Deployment progress (resume here)

Contract: `docs/ARCHITECTURE.md`. ML phase frozen. Repo:
https://github.com/veenaphadtare12-ux/Nowcasting-and-forecasting-of-soar-flare_mlops

| Phase | Status |
|---|---|
| Ops-1: CI, contracts, flows, push | **done**: CI green on GitHub |
| 2: bundle, API, Docker | **code done, tested; Docker images NOT built (blocked, see below)** |
| 3: frontend | not started |
| 4: monitoring | not started |
| 5: e2e | not started |
| 6: Kubernetes (kind) | not started |
| 7: CD + Terraform | not started |
| 8: submission docs, v1.0.0 | not started |

## Phase 2: what exists
- **`model_bundle/`** (22.1 MB, committed). It holds the 5 champion models exported from the registry alias
  `champion` (all v1), thresholds, `model_card.json` (frozen test + holdout2 results), `drift/latest.json`,
  `pipeline/status.json`, and 5 replay days, all from tune/val:
  - 2026-04-24: X day, HEL1OS;
  - 2025-04-13: 10 M, HEL1OS;
  - 2025-11-04: X day;
  - 2026-05-16: threshold month;
  - 2026-02-21: quiet day.
  - Rebuild with `python -m src.serving.bundle export`; check with `python -m src.serving.bundle verify`.
- **`src/serving/features.py`:** the pipeline's feature code for one day. Test: API features == pipeline dataset
  rows, exactly, on all 5 days (`tests/test_serving_features.py`).
- **`src/serving/api.py`** (FastAPI): `/health`, `/models`, `/replay/days`, `/replay/{day}?until=`,
  `/replay/{day}/stream` (SSE), `POST /predict` (feature rows or raw 1-s counts), `/results`, `/drift/latest`,
  `/pipeline/status`, `/metrics`. Tests: `tests/test_api.py` (10).
- `src/settings.py` (`FLARE_*` env vars). `flows/score_replay.py --day <d>` scores a bundle day into the
  predictions store, and the API then serves it with `source: store`.
- `docker/api.Dockerfile`, `.dockerignore`, `docker-compose.yml` (api + worker), `scripts/up.ps1`, `down.ps1`,
  `smoke_test.ps1`, `requirements-serve.txt`, `requirements-worker.txt`.
- Checks: 128 tests pass (1 skipped), ruff clean, `dvc status` clean.

## How to run (without Docker, works now)
```
.venv\Scripts\Activate.ps1
uvicorn src.serving.api:app --port 8000          # then: .\scripts\smoke_test.ps1
```

## BLOCKER (2026-11-13): Docker Desktop engine does not start
- Docker Desktop 4.89.0 on Windows 10.0.26300 fails at startup:
  `initializing Ingest server: listening on unix://…/Docker/run/sailor-ingest.sock: rename … .stale: The file cannot
  be accessed by the system`. The WSL distro `docker-desktop` stays Stopped.
- **Attempts (3, then stopped per the rules):**
  1. Deleting the stale socket files from 2026-09-12: Windows refuses ("cannot be accessed by the system").
  2. Moved `%LOCALAPPDATA%\Docker\run` → `run.stale-20261113` (reversible). Docker then failed on the same kind of
     file in `%LOCALAPPDATA%\docker-secrets-engine`, which was moved to `docker-secrets-engine.stale-20261113`.
  3. Restart: Docker fails again on the socket it had *just created*. So it isn't leftover files: this Windows
     build cannot rename AF_UNIX socket files that Docker Desktop creates.
- **Needs the user:** see the options in the chat message. Both renamed folders can be restored by renaming them
  back (they only contain empty socket files).
