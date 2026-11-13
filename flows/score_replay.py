"""Prefect flow: score a past window with the registered champion models and store the predictions (Parquet + SQLite).

    python -m flows.score_replay 2026-04-01 2026-04-08            # tune/val windows only

Writes data/predictions/replay_<start>_<end>.parquet and data/predictions/predictions.db (table `predictions`).
"""

from __future__ import annotations

import sys

from prefect import flow, get_run_logger, task

from src.ops import replay


@task(retries=1, retry_delay_seconds=30)
def score(start: str, end: str, targets: list[str] | None, alias: str):
    return replay.score(start, end, targets, alias=alias)


@task
def store(pred) -> dict:
    return replay.store(pred)


@flow(name="score_replay", log_prints=True)
def score_replay(start: str, end: str, targets: list[str] | None = None, alias: str = "champion") -> dict:
    log = get_run_logger()
    pred = score(start, end, targets, alias)
    out = store(pred)
    log.info("stored %d predictions: %s", out["rows"], out["parquet"])
    return out


if __name__ == "__main__":
    score_replay(sys.argv[1], sys.argv[2])
