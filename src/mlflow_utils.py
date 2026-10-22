"""Shared MLflow helpers: provenance tags and dataset inputs. The test period is never logged."""
from __future__ import annotations

import hashlib
import subprocess

import pandas as pd
import yaml

from src import config

R = config.PROJECT_ROOT
DATASET_DIR = "data/processed/dataset"
LOGGABLE_PERIODS = ("tune", "val")


def git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=R, text=True).strip()


def git_dirty() -> bool:
    out = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=R, text=True)
    return bool(out.strip())


def dvc_lock_md5() -> str:
    """md5 of dvc.lock as it was when the run started (the data versions the run read)."""
    p = R / "dvc.lock"
    return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else "none"


def dataset_md5() -> str:
    """DVC md5 of data/processed/dataset (directory hash from dvc.lock, without the '.dir' suffix)."""
    lock = yaml.safe_load((R / "dvc.lock").read_text(encoding="utf-8"))
    for stage in lock["stages"].values():
        for o in stage.get("outs", []):
            if o["path"] == DATASET_DIR:
                return o["md5"].removesuffix(".dir")
    raise KeyError(f"{DATASET_DIR} not found in dvc.lock outs")


def run_tags() -> dict[str, str]:
    return {"git_commit": git_commit(), "git_dirty": str(git_dirty()), "dvc_lock_md5": dvc_lock_md5(),
            "dataset_md5": dataset_md5()}


def horizon_min(target: str) -> int:
    """'now' -> 0; 'c_30m' -> 30."""
    return 0 if target == "now" else int(target.split("_")[1].removesuffix("m"))


def make_inputs(frames: dict[str, pd.DataFrame]) -> dict:
    """MLflow dataset objects for the tune and val frames. Digest = DVC md5 of the dataset directory, so a run can be
    traced back to the exact data version. Refuses any other period (the test set is never logged)."""
    import mlflow

    digest = dataset_md5()
    out = {}
    for period, df in frames.items():
        if period not in LOGGABLE_PERIODS:
            raise ValueError(f"refusing to log the '{period}' dataset")
        out[period] = mlflow.data.from_pandas(df, source=str(R / DATASET_DIR / f"{period}.parquet"),
                                              name=f"flare-dataset-{period}", digest=digest)
    return out


def log_inputs(ds: dict) -> None:
    import mlflow

    for period, d in ds.items():
        mlflow.log_input(d, context="training" if period == "tune" else "validation",
                         tags={"rows": str(d.profile["num_rows"]), "dvc_md5": d.digest})
