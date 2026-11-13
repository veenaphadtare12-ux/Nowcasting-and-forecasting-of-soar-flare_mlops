"""Prefect flow: the daily production pipeline (docs/ARCHITECTURE.md section 4).

    python -m flows.daily_ingest            # one run now
    (scheduled daily by flows/serve.py in Docker Compose / Kubernetes)

1. Production: every new day since FLARE_PRODUCTION_START (raw SoLEXS folder or inbox) -> pandera -> features (pipeline
   code) -> champion models (model bundle) -> pandera -> predictions store. Holdout2 and evaluation periods are locked.
2. Developer machine only (FLARE_INGEST_DVC=true): list new development days, re-run changed DVC DATA stages
   (model and evaluation stages are frozen) and re-check the data contracts.
"""

from __future__ import annotations

from prefect import flow, get_run_logger, task

from src.ops import ingest, production, runs
from src.settings import get_settings
from src.validation import check


@task(retries=2, retry_delay_seconds=[60, 300])
def score_production_day(day: str) -> dict:
    return production.run_day(day)


@task(retries=2, retry_delay_seconds=60)
def discover() -> dict:
    return ingest.discover_days()


@task(retries=3, retry_delay_seconds=[60, 300, 900])
def repro_stage(stage: str) -> str:
    ingest.repro(stage)  # fetch_goes downloads NOAA reports: network errors are retried
    return stage


@task
def validate(tables: list[str]) -> None:
    if check.main(tables) != 0:
        raise RuntimeError(f"data contract broken in {tables}; see the log above")


@flow(name="daily_ingest", log_prints=True)
def daily_ingest(dry_run: bool = False, dvc: bool | None = None) -> dict:
    log = get_run_logger()
    pending = production.pending_days()
    log.info("production start %s; new days to score: %s", production.start().date(), pending or "none")
    scored = []
    if not dry_run:
        for d in pending:
            s = score_production_day(d)
            alerts = {t: v["alerts"] for t, v in s["targets"].items()}
            log.info("scored %s: %d rows, alerts %s, GOES list: %s", d, s["rows"], alerts, s["goes"]["status"])
            scored.append(d)
    fresh = production.freshness()
    out = {"production": {"scored_now": scored, **fresh}, "dry_run": dry_run}

    if dvc if dvc is not None else get_settings().ingest_dvc:
        found = discover()
        log.info("new development days: %s", found["new_in_development"] or "none")
        if found["locked_after_development_end"]:
            log.warning(
                "%d day(s) after the development end are locked and were not read", len(found["locked_after_development_end"])
            )
        todo = ingest.stages_to_run(ingest.changed_stages(), ingest.frozen_stages())
        log.info("data stages to re-run: %s", todo or "none (pipeline up to date)")
        if not dry_run:
            for s in todo:
                repro_stage(s)
            validate(["solexs_minute", "hel1os", "goes_events", "dataset"])
        out["dvc"] = {"discovered": found, "stages": todo}

    runs.record(
        "daily_ingest",
        "Completed",
        {
            "production_scored": scored,
            "latest_scored_day": fresh["latest_scored_day"],
            "pending": fresh["pending_days"],
            "dry_run": dry_run,
        },
    )
    return out


if __name__ == "__main__":
    daily_ingest()
