"""Prefect flow: discover new local SoLEXS days, fetch GOES reports, validate the tables, re-run changed DATA stages.

    python -m flows.daily_ingest            # one run now (ephemeral Prefect API if no server is running)

Days after the development end are only listed by name (locked for the next one-time evaluation). Model and evaluation
stages are frozen and never re-run here.
"""

from __future__ import annotations

from prefect import flow, get_run_logger, task

from src.ops import ingest
from src.validation import check


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
def daily_ingest(dry_run: bool = False) -> dict:
    log = get_run_logger()
    found = discover()
    log.info("new development days: %s", found["new_in_development"] or "none")
    if found["locked_after_development_end"]:
        log.warning(
            "%d day(s) after the development end (%s) are locked and were not read: %s ...",
            len(found["locked_after_development_end"]),
            found["development_end"],
            found["locked_after_development_end"][:3],
        )
    todo = ingest.stages_to_run(ingest.changed_stages(), ingest.frozen_stages())
    log.info("data stages to re-run: %s", todo or "none (pipeline up to date)")
    if not dry_run:
        for s in todo:
            repro_stage(s)
        validate(["solexs_minute", "hel1os", "goes_events", "dataset"])
    return {"discovered": found, "stages": todo, "dry_run": dry_run}


if __name__ == "__main__":
    daily_ingest()
