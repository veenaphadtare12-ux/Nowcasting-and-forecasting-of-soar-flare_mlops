"""score_replay logic: score a past window (tune + val only) with the registered champion models; store predictions.

Predictions are validated against the PREDICTIONS data contract and written to Parquet and SQLite for the API/frontend.
Nothing is evaluated (no labels are read or reported) and the model threshold comes from the registry tag `thr_A`.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pandas as pd

from src import config
from src.ops.locks import check_window
from src.validation import schemas as S

REGISTRY = {
    "now": "flare-nowcast",
    "c_30m": "flare-forecast-c30",
    "c_60m": "flare-forecast-c60",
    "m_30m": "flare-forecast-m30",
    "m_60m": "flare-forecast-m60",
}
OUT_DIR = config.PROJECT_ROOT / "data" / "predictions"


def load_champion(name: str, alias: str, tracking_uri: str | None):
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    from mlflow import MlflowClient

    from src.models.load_production import load_production

    uri = tracking_uri or config.mlflow_uri()
    mv = MlflowClient(tracking_uri=uri).get_model_version_by_alias(name, alias)
    return load_production(name, alias=alias, tracking_uri=uri), mv


def feature_frame(start: pd.Timestamp, end: pd.Timestamp, ideas: list[str]) -> pd.DataFrame:
    """Base features (tune/val dataset files) plus the extra idea features the champion needs."""
    from src.final import features as ff
    from src.models.train import load_period

    d = pd.concat([load_period(p) for p in ("tune", "val")]).sort_index()  # load_period refuses the test period
    d = d[(d.index >= start - pd.Timedelta(days=8)) & (d.index < end)]  # 8-day margin: drift/long-context windows
    if ideas:
        d = ff.build(d, ideas)[0]
    return d[(d.index >= start) & (d.index < end)]


def score(
    start,
    end,
    targets: list[str] | None = None,
    alias: str = "champion",
    tracking_uri: str | None = None,
    frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    s, e = check_window(start, end, kind="score")
    rows = []
    for target in targets or list(REGISTRY):
        model, mv = load_champion(REGISTRY[target], alias, tracking_uri)
        cols = model.metadata.get_input_schema().input_names()
        ideas = [x for x in (mv.tags.get("ideas") or "none").split(",") if x and x != "none"]
        X = frame if frame is not None else feature_frame(s, e, ideas)
        X = X[(X.index >= s) & (X.index < e)]
        p = model.predict(X[cols])
        p1 = p.iloc[:, 1].to_numpy() if hasattr(p, "iloc") else p[:, 1]
        thr = float(mv.tags["thr_A"])
        rows.append(
            pd.DataFrame(
                {
                    "time": X.index,
                    "target": target,
                    "model": REGISTRY[target],
                    "model_version": str(mv.version),
                    "p_flare": p1.astype(float),
                    "threshold": thr,
                    "alert": p1 >= thr,
                }
            )
        )
    out = pd.concat(rows, ignore_index=True)
    return S.validate(out, S.PREDICTIONS, "score_replay")


def store(pred: pd.DataFrame, out_dir: Path | None = None, tag: str = "") -> dict:
    out_dir = Path(out_dir) if out_dir else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    t0, t1 = pred["time"].min(), pred["time"].max()
    pq = out_dir / f"replay_{t0:%Y%m%d}_{t1:%Y%m%d}{tag}.parquet"
    pred.to_parquet(pq)
    db = out_dir / "predictions.db"
    with sqlite3.connect(db) as con:
        p = pred.assign(time=pred["time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
        p.to_sql("predictions_staging", con, if_exists="replace", index=False)
        con.execute(
            "CREATE TABLE IF NOT EXISTS predictions (time TEXT, target TEXT, model TEXT, model_version TEXT, "
            "p_flare REAL, threshold REAL, alert INTEGER, PRIMARY KEY (time, target, model, model_version))"
        )
        con.execute(
            "INSERT OR REPLACE INTO predictions SELECT time, target, model, model_version, p_flare, threshold, alert "
            "FROM predictions_staging"
        )
        con.execute("DROP TABLE predictions_staging")
    return {"parquet": str(pq), "sqlite": str(db), "rows": int(len(pred))}


def score_bundle_day(day: str, bundle_dir: Path | None = None, targets: list[str] | None = None) -> pd.DataFrame:
    """Score one bundle replay day with the bundle's champion models and the bundle's stored model inputs (the
    pipeline's features). Works on any machine: no DVC data, no MLflow registry."""
    from src.serving import bundle as B

    b = B.load(str(bundle_dir) if bundle_dir else None)
    d0 = pd.Timestamp(day, tz="UTC")
    check_window(d0, d0 + pd.Timedelta(days=1), kind="score")
    rows = []
    for target in targets or list(b.manifest["models"]):
        m = b.model_meta(target)
        X = b.model_input(day, target)
        p1 = b.model(target).predict_proba(X)[:, 1].astype(float)
        thr = float(m["thresholds"]["A"])
        rows.append(
            pd.DataFrame(
                {
                    "time": X.index,
                    "target": target,
                    "model": m["registry_name"],
                    "model_version": m["version"],
                    "p_flare": p1.clip(0, 1),
                    "threshold": thr,
                    "alert": p1 >= thr,
                }
            )
        )
    return S.validate(pd.concat(rows, ignore_index=True), S.PREDICTIONS, f"score_replay bundle day {day}")


def read_store(day: str, out_dir: Path | None = None) -> pd.DataFrame | None:
    """Predictions for one UTC day from the SQLite store (None if the store has none)."""
    db = (Path(out_dir) if out_dir else OUT_DIR) / "predictions.db"
    if not db.exists():
        return None
    a = f"{day}T00:00:00Z"
    b = (pd.Timestamp(day) + pd.Timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with sqlite3.connect(db) as con:
        q = "SELECT * FROM predictions WHERE time > ? AND time <= ? ORDER BY target, time"
        df = pd.read_sql_query(q, con, params=(a, b))
    if df.empty:
        return None
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["alert"] = df["alert"].astype(bool)
    return df
