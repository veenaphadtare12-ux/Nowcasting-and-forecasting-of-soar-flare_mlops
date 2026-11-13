# Developer shortcuts.  Windows: `mingw32-make <target>` (MSYS2) or run the command shown after each target by hand.
# Linux / CI: `make <target>`.
ifeq ($(OS),Windows_NT)
  BIN := .venv/Scripts/
else
  BIN := .venv/bin/
endif
PY := $(BIN)python
export MLFLOW_DISABLE_AGENT_HINT := 1
export PREFECT_HOME := $(CURDIR)/.prefect   # project-local Prefect DB/profile (independent of ~/.prefect)

.PHONY: help setup setup-ci test test-ci lint format repro status flows-server ingest drift replay retrain serve

help:
	@echo "setup | setup-ci | test | test-ci | lint | format | repro | status | flows-server | ingest | drift | replay | retrain | serve"

setup:                ## dev environment (full pinned freeze) + git hooks
	python -m venv .venv
	$(PY) -m pip install -r requirements.txt
	$(BIN)pre-commit install

setup-ci:             ## small test environment (what CI installs)
	$(PY) -m pip install -r requirements-ci.txt

test:                 ## all tests (needs the local DVC data)
	$(PY) -m pytest -q

test-ci:              ## what CI runs: no DVC data needed
	$(PY) -m pytest -q -m "not data"

lint:
	$(BIN)ruff check .

format:               ## formats only the new code (see .pre-commit-config.yaml for why)
	$(BIN)ruff format flows src/validation src/ops tests/fixtures tests/test_validation.py tests/test_ops.py

repro:                ## re-run data stages that changed; model/evaluation stages are frozen
	$(BIN)dvc repro

status:
	$(BIN)dvc status

flows-server:         ## Prefect UI at http://127.0.0.1:4200
	$(BIN)prefect server start

ingest:
	$(PY) -m flows.daily_ingest

drift:
	$(PY) -m flows.check_drift

replay:               ## e.g. make replay START=2026-04-01 END=2026-04-08
	$(PY) -m flows.score_replay $(START) $(END)

retrain:              ## e.g. make retrain TARGET=c_60m START=2025-04-09 END=2026-09-13 BLOCK=2026-08-01  (registers a challenger only)
	$(PY) -m flows.retrain_candidate $(TARGET) $(START) $(END) $(BLOCK)

serve:                ## REST endpoint for one champion: POST http://127.0.0.1:5001/invocations
	MLFLOW_TRACKING_URI=sqlite:///mlflow.db $(BIN)mlflow models serve -m "models:/$(or $(MODEL),flare-nowcast)@champion" --env-manager local -p 5001
