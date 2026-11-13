"""Prefect flow: score a past window with the registered champion models and store the predictions (Parquet + SQLite).

    python -m flows.score_replay 2026-04-01 2026-04-08     # tune/val window from the DVC data (developer machine)
    python -m flows.score_replay --day 2026-04-24          # one model-bundle day (any machine, Docker, CI, k8s)

Writes data/predictions/replay_<start>_<end>.parquet and data/predictions/predictions.db (table `predictions`).
"""

from __future__ import annotations

import sys

from prefect import flow, get_run_logger, task

from src.ops import replay, runs
from src.settings import get_settings


@task(retries=1, retry_delay_seconds=30)
def score(start: str | None, end: str | None, targets: list[str] | None, alias: str, day: str | None):
    if day:  # bundle source: any machine, bundle models + bundle features
        return replay.score_bundle_day(day, targets=targets)
    return replay.score(start, end, targets, alias=alias)


@task
def store(pred) -> dict:
    return replay.store(pred, get_settings().predictions_dir)


@flow(name="score_replay", log_prints=True)
def score_replay(
    start: str | None = None,
    end: str | None = None,
    targets: list[str] | None = None,
    alias: str = "champion",
    day: str | None = None,
) -> dict:
    """Either a tune/val window from the DVC data (start, end) or one model-bundle day (day=YYYY-MM-DD)."""
    log = get_run_logger()
    pred = score(start, end, targets, alias, day)
    out = store(pred)
    out["source"] = "bundle" if day else "dvc"
    log.info("stored %d predictions: %s", out["rows"], out["parquet"])
    runs.record("score_replay", "Completed", out)
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--day":
        score_replay(day=a[1])
    else:
        score_replay(a[0], a[1])
