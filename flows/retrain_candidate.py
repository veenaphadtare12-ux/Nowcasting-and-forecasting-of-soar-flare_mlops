"""Prefect flow: retrain the frozen recipe on a newer window and register it as alias "challenger" (never champion).

    python -m flows.retrain_candidate c_60m 2025-04-09 2026-09-13 2026-08-01

Arguments: target, window start, window end (exclusive), threshold-block start. Promotion to champion is a manual
decision after a fresh one-time evaluation; this flow can never move the champion alias.
"""

from __future__ import annotations

import sys

from prefect import flow, get_run_logger, task

from src.ops import retrain


@task(retries=1, retry_delay_seconds=60)
def fit_and_register(target: str, start: str, end: str, block_start: str) -> dict:
    return retrain.retrain(target, start, end, block_start)


@flow(name="retrain_candidate", log_prints=True)
def retrain_candidate(target: str, start: str, end: str, block_start: str) -> dict:
    log = get_run_logger()
    out = fit_and_register(target, start, end, block_start)
    log.info(
        "registered %s v%s as 'challenger' (champion unchanged); thresholds %s",
        out["registry"],
        out["challenger_version"],
        out["thresholds"],
    )
    return out


if __name__ == "__main__":
    retrain_candidate(*sys.argv[1:5])
