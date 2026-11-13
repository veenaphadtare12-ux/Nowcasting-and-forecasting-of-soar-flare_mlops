"""Long-running Prefect worker process: registers the deployments with the Prefect server and runs them on schedule.

    PREFECT_API_URL=http://prefect-server:4200/api  python -m flows.serve      (Docker Compose service "worker")

Schedules (UTC): daily_ingest every day 02:15, check_drift every day 03:30. score_replay is deployed without a schedule
(run it from the Prefect UI). retrain_candidate is not deployed here: it needs the DVC data and the MLflow registry
of the developer machine, and only ever registers a challenger.
"""

from __future__ import annotations

import os

from prefect import serve

from flows.check_drift import check_drift
from flows.daily_ingest import daily_ingest
from flows.score_replay import score_replay

INGEST_CRON = os.environ.get("FLARE_INGEST_CRON", "15 2 * * *")
DRIFT_CRON = os.environ.get("FLARE_DRIFT_CRON", "30 3 * * *")

if __name__ == "__main__":
    serve(
        daily_ingest.to_deployment(name="daily", cron=INGEST_CRON, tags=["production"]),
        check_drift.to_deployment(name="daily", cron=DRIFT_CRON, tags=["monitoring"]),
        score_replay.to_deployment(name="on-demand", tags=["replay"], parameters={"day": "2026-04-24"}),
    )
