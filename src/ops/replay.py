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
