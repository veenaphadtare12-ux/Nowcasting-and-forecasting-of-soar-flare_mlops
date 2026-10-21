"""Train and compare flare models: one-feature rule, logistic regression, XGBoost. Every run is logged to MLflow.

Data discipline (CLAUDE.md):
* Only the tune and val dataset files are read. The test file is never opened here (`load_period` refuses it).
* Tune is split IN TIME: fit on rows before `models.inner_split` (minus a purge gap so no fit row's label window
  reaches the calibration part), calibrate on rows after it. Early stopping and the alert threshold are chosen on
  the calibration part only.
* Val is used once per model, with the frozen threshold, to compare models (model selection). Nothing is fitted on it.
* Rows are used only where the target's `ok` flag is True.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import QuantileTransformer
from xgboost import XGBClassifier

from src import config, dataset
from src.models import metrics

TARGETS = {
    "now": ("y_now", "ok_now"),
    "c_30m": ("y_c_30m", "ok_30m"), "c_60m": ("y_c_60m", "ok_60m"), "c_120m": ("y_c_120m", "ok_120m"),
    "m_30m": ("y_m_30m", "ok_30m"), "m_60m": ("y_m_60m", "ok_60m"), "m_120m": ("y_m_120m", "ok_120m"),
}
MODEL_DIR = config.PROJECT_ROOT / "models"
REPORTS = config.PROJECT_ROOT / "reports"
ALLOWED_PERIODS = ("tune", "val")


def load_period(name: str) -> pd.DataFrame:
    """Read one period's dataset file. The test period is refused: it is reserved for the final evaluation."""
    if name not in ALLOWED_PERIODS:
        raise ValueError(f"training code may not read the '{name}' period")
    return pd.read_parquet(config.processed_dir() / "dataset" / f"{name}.parquet")


def split_tune(df: pd.DataFrame, split: str, purge_min: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chronological split of the tune period with a purge gap before the calibration part."""
    cut = pd.Timestamp(split, tz="UTC")
    fit = df[df.index < cut - pd.Timedelta(minutes=purge_min)]
    cal = df[df.index >= cut]
    return fit, cal


def _rows(df: pd.DataFrame, target: str, stride: int = 1) -> tuple[pd.DataFrame, np.ndarray]:
    y_col, ok_col = TARGETS[target]
    d = df[df[ok_col].astype(bool)]
    if stride > 1:
        d = d.iloc[::stride]
    return d, d[y_col].to_numpy().astype(int)


def make_logreg(cfg: dict, seed: int) -> Pipeline:
    return Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", QuantileTransformer(n_quantiles=1000, output_distribution="normal", subsample=200_000, random_state=seed)),
        ("clf", LogisticRegression(C=cfg["C"], max_iter=cfg["max_iter"], class_weight="balanced")),
    ])


def make_xgb(cfg: dict, seed: int, pos_weight: float) -> XGBClassifier:
    return XGBClassifier(
        n_estimators=cfg["n_estimators"], learning_rate=cfg["learning_rate"], max_depth=cfg["max_depth"],
        min_child_weight=cfg["min_child_weight"], subsample=cfg["subsample"], colsample_bytree=cfg["colsample_bytree"],
        early_stopping_rounds=cfg["early_stopping_rounds"], eval_metric="aucpr", tree_method="hist",
        scale_pos_weight=pos_weight, random_state=seed, n_jobs=-1,
    )


def train_target(target: str, fit_df, cal_df, val_df, feats: list[str], P: dict) -> list[dict]:
    """Fit the three models for one target; return one result dict per model (calibration + validation metrics)."""
    mp = P["models"]
    Xf_df, yf = _rows(fit_df, target, mp["train_stride"])
    Xc_df, yc = _rows(cal_df, target)
    Xv_df, yv = _rows(val_df, target)
    Xf, Xc, Xv = Xf_df[feats], Xc_df[feats], Xv_df[feats]
    results = []

    # 1) one-feature rule: alert when the chosen feature exceeds a threshold (chosen on calibration)
    rf = mp["rule_feature"]
    sc, sv = Xc[rf].fillna(0).to_numpy(), Xv[rf].fillna(0).to_numpy()
    thr, _ = metrics.best_threshold(yc, sc)
    results.append({"model": "rule", "estimator": None, "threshold": thr,
                    "cal": metrics.evaluate(yc, sc, thr, proba=False), "val": metrics.evaluate(yv, sv, thr, proba=False),
                    "params": {"feature": rf}, "fit_rows": 0})

    # 2) logistic regression
    t0 = time.time()
    lr = make_logreg(mp["logreg"], mp["random_state"]).fit(Xf, yf)
    pc, pv = lr.predict_proba(Xc)[:, 1], lr.predict_proba(Xv)[:, 1]
    thr, _ = metrics.best_threshold(yc, pc)
    results.append({"model": "logreg", "estimator": lr, "threshold": thr, "cal": metrics.evaluate(yc, pc, thr),
                    "val": metrics.evaluate(yv, pv, thr), "params": mp["logreg"], "fit_rows": len(yf),
                    "fit_seconds": time.time() - t0})

    # 3) XGBoost, early-stopped on the calibration part
    t0 = time.time()
    pos_weight = float((yf == 0).sum() / max((yf == 1).sum(), 1))
    xgb = make_xgb(mp["xgb"], mp["random_state"], pos_weight)
    xgb.fit(Xf, yf, eval_set=[(Xc, yc)], verbose=False)
    pc, pv = xgb.predict_proba(Xc)[:, 1], xgb.predict_proba(Xv)[:, 1]
    thr, _ = metrics.best_threshold(yc, pc)
    imp = pd.Series(xgb.get_booster().get_score(importance_type="gain")).reindex(feats).fillna(0)
    results.append({"model": "xgb", "estimator": xgb, "threshold": thr, "cal": metrics.evaluate(yc, pc, thr),
                    "val": metrics.evaluate(yv, pv, thr), "params": {**mp["xgb"], "scale_pos_weight": pos_weight},
                    "fit_rows": len(yf), "fit_seconds": time.time() - t0, "best_iteration": int(xgb.best_iteration),
                    "importance": (imp / imp.sum()).sort_values(ascending=False).round(4).to_dict()})
    return results


def _fresh(path: Path) -> Path:
    if path.exists():
        path.chmod(0o666)
        path.unlink()
    return path


def run() -> dict:
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow

    from src.models import plots

    P = config.load_params()
    mp = P["models"]
    tune, val = load_period("tune"), load_period("val")
    feats = dataset.feature_columns(tune)
    fit_df, cal_df = split_tune(tune, mp["inner_split"], mp["purge_min"])
    MODEL_DIR.mkdir(exist_ok=True)
    for old in MODEL_DIR.glob("*"):
        _fresh(old)

    mlflow.set_tracking_uri(config.mlflow_uri())
    mlflow.set_experiment("flare-models")
    summary: dict = {"features": feats, "split": {"fit_end": str(fit_df.index.max()), "cal_start": str(cal_df.index.min()),
                     "cal_end": str(cal_df.index.max()), "val_start": str(val.index.min()), "val_end": str(val.index.max())},
                     "targets": {}}
    for target in mp["targets"]:
        res = train_target(target, fit_df, cal_df, val, feats, P)
        summary["targets"][target] = {}
        for r in res:
            name = r["model"]
            with mlflow.start_run(run_name=f"{target}-{name}"):
                mlflow.set_tags({"target": target, "model": name, "periods": "fit+cal=tune, eval=val"})
                mlflow.log_params({"target": target, "model": name, "threshold": r["threshold"], "fit_rows": r["fit_rows"],
                                   "n_features": len(feats), **{f"p_{k}": v for k, v in r["params"].items()}})
                for part in ("cal", "val"):
                    mlflow.log_metrics({f"{part}_{k}": float(v) for k, v in r[part].items() if isinstance(v, (int, float))})
                if r["estimator"] is not None:
                    path = MODEL_DIR / (f"{target}_xgb.json" if name == "xgb" else f"{target}_{name}.joblib")
                    if name == "xgb":
                        r["estimator"].save_model(_fresh(path))
                    else:
                        joblib.dump(r["estimator"], _fresh(path))
                    mlflow.log_artifact(str(path))
                if "importance" in r:
                    mlflow.log_dict(r["importance"], "feature_importance.json")
            summary["targets"][target][name] = {k: v for k, v in r.items() if k != "estimator"}
        best = max(res, key=lambda r: r["val"]["tss"])
        summary["targets"][target]["selected"] = best["model"]
        print(f"{target:7s} " + "  ".join(f"{r['model']}: val TSS {r['val']['tss']:.3f} HSS {r['val']['hss']:.3f}" for r in res)
              + f"  -> {best['model']}")
    (MODEL_DIR / "thresholds.json").write_text(json.dumps(
        {t: {m: summary["targets"][t][m]["threshold"] for m in ("rule", "logreg", "xgb")} | {"selected": summary["targets"][t]["selected"]}
         for t in mp["targets"]}, indent=2), newline="\n")
    REPORTS.mkdir(exist_ok=True)
    _fresh(REPORTS / "model_metrics.json").write_text(json.dumps(summary, indent=2, default=str), newline="\n")
    plots.skill_figure()
    return summary


if __name__ == "__main__":
    run()
