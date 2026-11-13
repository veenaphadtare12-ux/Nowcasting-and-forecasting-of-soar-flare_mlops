"""Prefect flow: Evidently drift report, training features vs the last 30 days of development data.

    python -m flows.check_drift

Writes reports/drift/drift_<start>_<end>.{html,json}; logs a warning when drift is flagged.
"""

from __future__ import annotations

from prefect import flow, get_run_logger, task

from src.ops import drift, runs


@task
def run_report() -> dict:
    # developer machine (DVC dataset present): training block vs the last 30 development days;
    # containers: bundle reference sample vs the last 30 days of production features
    from src import config

    if (config.processed_dir() / "dataset" / "tune.parquet").exists():
        return drift.run_default()
    return drift.run_bundle()


@flow(name="check_drift", log_prints=True)
def check_drift() -> dict:
    log = get_run_logger()
    s = run_report()
    msg = f"drifted features: {len(s['drifted_features'])}/{s['features_checked']} (share {s['drifted_share']:.2f})"
    (log.warning if s["drift_flag"] else log.info)(("DRIFT FLAGGED - " if s["drift_flag"] else "no dataset drift - ") + msg)
    runs.record(
        "check_drift",
        "Completed",
        {"drifted_share": s["drifted_share"], "drift_flag": s["drift_flag"], "features_checked": s["features_checked"]},
    )
    return s


if __name__ == "__main__":
    check_drift()
