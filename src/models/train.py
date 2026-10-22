"""Train, compare and score flare models. Every training run is logged to MLflow.

Models per target: climatology, persistence, one-feature rule, logistic regression, XGBoost.

Data discipline (CLAUDE.md):
* Only the tune and val dataset files are read; `load_period` refuses the test period.
* Tune is split IN TIME at `models.inner_split`:
  - fit part (before the split, minus a purge gap): model fitting, and rolling-origin CV for XGBoost settings;
  - calibration part (Dec-Jan): threshold selection only (operating points A = max TSS, B = max HSS).
* Val is used to compare models (model selection). Nothing is fitted or tuned on it.
* Rows are used only where the target's `ok` flag is True.
* Every number is reported for all rows and for quiet-start rows (no flare in progress at t, causal flag).
* Logistic regression and XGBoost are fitted with 3 seeds; scores are mean +- std over seeds, with a 95 % interval
  from a bootstrap over validation days.
"""
from __future__ import annotations

import itertools
import json
import os
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
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
MODELS = ("climatology", "persistence", "rule", "logreg", "xgb")
FLAG = "flare_in_progress_at_t"
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
    return df[df.index < cut - pd.Timedelta(minutes=purge_min)], df[df.index >= cut]


def cv_folds(df: pd.DataFrame, fold_months: list[str], purge_min: int) -> list[tuple[pd.DataFrame, pd.DataFrame, str]]:
    """Rolling-origin folds: for each month m, train on everything before m (minus a purge gap), score on m."""
    folds = []
    for m in fold_months:
        lo = pd.Timestamp(m + "-01", tz="UTC")
        hi = lo + pd.offsets.MonthBegin(1)
        folds.append((df[df.index < lo - pd.Timedelta(minutes=purge_min)], df[(df.index >= lo) & (df.index < hi)], m))
    return folds


def _rows(df: pd.DataFrame, target: str, stride: int = 1) -> pd.DataFrame:
    _, ok_col = TARGETS[target]
    d = df[df[ok_col].astype(bool)]
    return d.iloc[::stride] if stride > 1 else d


def _y(d: pd.DataFrame, target: str) -> np.ndarray:
    return d[TARGETS[target][0]].to_numpy().astype(int)


def make_logreg(cfg: dict, seed: int) -> Pipeline:
    return Pipeline([
        # median imputation + an explicit missing-value indicator per feature, fitted on training rows only
        # (HEL1OS features are missing outside sessions)
        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", QuantileTransformer(n_quantiles=1000, output_distribution="normal", subsample=200_000, random_state=seed)),
        ("clf", LogisticRegression(C=cfg["C"], max_iter=cfg["max_iter"], class_weight="balanced")),
    ])


def make_xgb(base: dict, params: dict, seed: int, pos_weight: float) -> XGBClassifier:
    return XGBClassifier(**base, **params, eval_metric="aucpr", tree_method="hist", scale_pos_weight=pos_weight,
                         random_state=seed, n_jobs=-1)


def _pos_weight(y: np.ndarray) -> float:
    return float((y == 0).sum() / max((y == 1).sum(), 1))


# ---------------------------------------------------------------- rolling-origin CV for XGBoost
def xgb_cv(fit_df: pd.DataFrame, target: str, feats: list[str], P: dict) -> tuple[dict, pd.DataFrame]:
    """Choose n_estimators and regularisation by mean aucpr over monthly rolling-origin folds (fit part only).

    One model with the largest n_estimators is trained per (setting, fold); smaller tree counts are scored from
    the same model with `iteration_range`, so trying 3 tree counts costs one fit.
    """
    mp = P["models"]
    cv = mp["cv"]
    grid = [dict(zip(("max_depth", "min_child_weight", "reg_lambda"), v))
            for v in itertools.product(cv["max_depth"], cv["min_child_weight"], cv["reg_lambda"])]
    n_list, n_max = sorted(cv["n_estimators"]), max(cv["n_estimators"])
    rows = []
    for tr_df, va_df, month in cv_folds(fit_df, cv["fold_months"], mp["purge_min"]):
        tr, va = _rows(tr_df, target, cv["stride"]), _rows(va_df, target)
        ytr, yva = _y(tr, target), _y(va, target)
        if yva.sum() == 0 or ytr.sum() == 0:
            continue  # aucpr undefined without positives in this month
        for g in grid:
            m = make_xgb(mp["xgb"], {**g, "n_estimators": n_max}, mp["seeds"][0], _pos_weight(ytr)).fit(tr[feats], ytr)
            for n in n_list:
                p = m.predict_proba(va[feats], iteration_range=(0, n))[:, 1]
                rows.append({**g, "n_estimators": n, "fold": month, "aucpr": average_precision_score(yva, p),
                             "fold_pos": int(yva.sum())})
    table = pd.DataFrame(rows)
    keys = ["max_depth", "min_child_weight", "reg_lambda", "n_estimators"]
    summary = table.groupby(keys)["aucpr"].agg(["mean", "std", "count"]).reset_index().sort_values("mean", ascending=False)
    best = {k: (int(v) if k != "reg_lambda" else float(v)) for k, v in summary.iloc[0][keys].items()}
    return best, summary


# ---------------------------------------------------------------- scoring
def _score_block(y_cal, s_cal, y_val, s_val, quiet, day_codes, n_days, op_metrics: dict, fixed_threshold=None) -> dict:
    """Thresholds from calibration (one per operating point), metrics on val (all rows and quiet-start rows)."""
    out = {}
    for op, met in op_metrics.items():
        thr = fixed_threshold if fixed_threshold is not None else metrics.best_threshold(y_cal, s_cal, met)[0]
        r = {"threshold": float(thr), "cal": metrics.evaluate(y_cal, s_cal, thr, proba=False)}
        for subset, mask in (("all", np.ones(len(y_val), bool)), ("quiet", quiet)):
            ev = metrics.evaluate(y_val[mask], s_val[mask], thr, proba=False)
            ev["day_counts"] = metrics.daily_counts(y_val[mask], s_val[mask] >= thr, day_codes[mask], n_days)
            r[subset] = ev
        out[op] = r
    return out


def train_target(target: str, fit_df, cal_df, val_df, feats: list[str], P: dict, xgb_params: dict, days) -> dict:
    """Fit every model for one target. Returns {model: [per-seed result]} where each result holds
    calibration/validation metrics for each operating point."""
    mp = P["models"]
    ops = mp["operating_points"]
    fit = _rows(fit_df, target, mp["train_stride"])
    cal, val = _rows(cal_df, target), _rows(val_df, target)
    yf, yc, yv = _y(fit, target), _y(cal, target), _y(val, target)
    quiet = val[FLAG].to_numpy() == 0
    day_codes = days.get_indexer(val.index.floor("D"))
    n_days = len(days)
    blk = lambda sc, sv, fixed=None: _score_block(yc, sc, yv, sv, quiet, day_codes, n_days, ops, fixed)  # noqa: E731
    res: dict = {}

    # climatology: always the training positive rate. A constant forecast has no skill (TSS 0) by construction.
    rate = float(yf.mean())
    res["climatology"] = [{"seed": None, "params": {"rate": rate},
                           **blk(np.full(len(yc), rate), np.full(len(yv), rate), fixed=rate + 1e-12)}]
    # persistence: "yes" while a flare is in progress at t (causal flag); no threshold to choose
    res["persistence"] = [{"seed": None, "params": {"flag": FLAG},
                           **blk(cal[FLAG].to_numpy().astype(float), val[FLAG].to_numpy().astype(float), fixed=0.5)}]
    # one-feature rule
    rf = mp["rule_feature"]
    res["rule"] = [{"seed": None, "params": {"feature": rf},
                    **blk(cal[rf].fillna(0).to_numpy(), val[rf].fillna(0).to_numpy())}]
    # logistic regression and XGBoost, one fit per seed
    res["logreg"], res["xgb"] = [], []
    for seed in mp["seeds"]:
        t0 = time.time()
        lr = make_logreg(mp["logreg"], seed).fit(fit[feats], yf)
        res["logreg"].append({"seed": seed, "params": mp["logreg"], "fit_seconds": time.time() - t0, "estimator": lr,
                              **blk(lr.predict_proba(cal[feats])[:, 1], lr.predict_proba(val[feats])[:, 1])})
        t0 = time.time()
        xg = make_xgb(mp["xgb"], xgb_params, seed, _pos_weight(yf)).fit(fit[feats], yf)
        imp = pd.Series(xg.get_booster().get_score(importance_type="gain")).reindex(feats).fillna(0)
        res["xgb"].append({"seed": seed, "params": {**mp["xgb"], **xgb_params}, "fit_seconds": time.time() - t0,
                           "estimator": xg, "importance": (imp / imp.sum()).sort_values(ascending=False).round(4).to_dict(),
                           **blk(xg.predict_proba(cal[feats])[:, 1], xg.predict_proba(val[feats])[:, 1])})
    return res


def aggregate(runs: list[dict], ops: dict, boot_idx: np.ndarray, level: float) -> dict:
    """Mean +- std over seeds and a day-bootstrap interval for TSS, per operating point and subset."""
    out = {}
    for op in ops:
        out[op] = {"threshold_mean": float(np.mean([r[op]["threshold"] for r in runs]))}
        for subset in ("all", "quiet"):
            vals = {k: [r[op][subset][k] for r in runs] for k in ("tss", "hss", "pod", "far")}
            agg = {f"{k}_mean": float(np.mean(v)) for k, v in vals.items()}
            agg |= {f"{k}_std": float(np.std(v)) for k, v in vals.items()}
            lo, hi = metrics.bootstrap_mean_tss([r[op][subset]["day_counts"] for r in runs], boot_idx, level)
            agg |= {"tss_ci_low": lo, "tss_ci_high": hi, "n": runs[0][op][subset]["n"],
                    "pos_rate": runs[0][op][subset]["pos_rate"], "n_seeds": len(runs)}
            out[op][subset] = agg
    return out


def _fresh(path: Path) -> Path:
    if path.exists():
        path.chmod(0o666)
        path.unlink()
    return path


def _strip(r: dict) -> dict:
    """Per-seed result without numpy arrays/estimators, for JSON."""
    out = {k: v for k, v in r.items() if k not in ("estimator",)}
    for op in ("A", "B"):
        if op in out:
            out[op] = {k: ({kk: vv for kk, vv in v.items() if kk != "day_counts"} if isinstance(v, dict) else v)
                       for k, v in out[op].items()}
    return out


def _log_seed_run(mlflow, mu, r: dict, target: str, model: str, ttags: dict, inputs: dict, ops: dict,
                  example: pd.DataFrame) -> None:
    """One nested run per seed: that seed's validation metrics. The first seed's model (the one saved in models/) is
    also logged as an MLflow model with a signature and a 5-row input example."""
    from mlflow.models import infer_signature

    seed = r["seed"]
    with mlflow.start_run(run_name=f"{target}-{model}-seed{seed}", nested=True):
        mlflow.set_tags(ttags | {"model": model, "seed": str(seed)})
        mu.log_inputs(inputs)
        for op in ops:
            mlflow.log_metric(f"{op}_threshold", float(r[op]["threshold"]))
            for subset in ("all", "quiet"):
                mlflow.log_metrics({f"{op}_{subset}_{k}": float(v) for k, v in r[op][subset].items()
                                    if k in ("tss", "hss", "pod", "far", "roc_auc", "avg_precision")})
        if seed == config.load_params()["models"]["seeds"][0]:
            import sklearn
            import xgboost

            est = r["estimator"]
            sig = infer_signature(example, est.predict_proba(example))
            mlflow.sklearn.log_model(
                est, name="model", signature=sig, input_example=example, serialization_format="cloudpickle",
                pyfunc_predict_fn="predict_proba",
                pip_requirements=[f"scikit-learn=={sklearn.__version__}", f"xgboost=={xgboost.__version__}",
                                  f"pandas=={pd.__version__}", f"numpy=={np.__version__}"])
            mlflow.set_tag("saved_model", "models/" + (f"{target}_xgb.json" if model == "xgb" else f"{target}_logreg.joblib"))


def run() -> dict:
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow

    from src.models import plots, report

    P = config.load_params()
    mp = P["models"]
    ops = mp["operating_points"]
    tune, val = load_period("tune"), load_period("val")
    feats = dataset.feature_columns(tune)
    fit_df, cal_df = split_tune(tune, mp["inner_split"], mp["purge_min"])
    days = pd.DatetimeIndex(sorted(val.index.floor("D").unique()))
    bs = mp["bootstrap"]
    boot_idx = metrics.bootstrap_indices(len(days), bs["n"], bs["seed"])
    MODEL_DIR.mkdir(exist_ok=True)
    for old in MODEL_DIR.glob("*"):
        _fresh(old)

    from src import mlflow_utils as mu

    mlflow.set_tracking_uri(config.mlflow_uri())
    mlflow.set_experiment("flare-models-v2")
    base_tags = mu.run_tags()
    inputs = mu.make_inputs({"tune": tune, "val": val})  # the test set is never logged
    example = fit_df.loc[fit_df["hel1os_available"] == 1, feats].dropna().head(5)  # all 44 features filled in
    if len(example) < 5:
        example = fit_df[feats].head(5)
    summary: dict = {
        "features": feats, "val_days": len(days),
        "split": {"fit_end": str(fit_df.index.max()), "cal_start": str(cal_df.index.min()), "cal_end": str(cal_df.index.max()),
                  "val_start": str(val.index.min()), "val_end": str(val.index.max())},
        "targets": {},
    }
    thresholds: dict = {}
    cv_tables = []
    for target in mp["targets"]:
        t0 = time.time()
        xgb_params, cv_table = xgb_cv(fit_df, target, feats, P)
        cv_tables.append(cv_table.assign(target=target))
        res = train_target(target, fit_df, cal_df, val, feats, P, xgb_params, days)
        agg = {m: aggregate(res[m], ops, boot_idx, bs["level"]) for m in MODELS}
        candidates = ("rule", "logreg", "xgb")
        selected = max(candidates, key=lambda m: agg[m]["A"]["all"]["tss_mean"])
        summary["targets"][target] = {"selected": selected, "xgb_cv_best": xgb_params,
                                      "models": {m: {"summary": agg[m], "runs": [_strip(r) for r in res[m]]} for m in MODELS}}
        thresholds[target] = {m: {op: agg[m][op]["threshold_mean"] for op in ops} for m in MODELS} | {"selected": selected}
        for name in ("logreg", "xgb"):  # keep the first seed's fitted model of each learner
            est = res[name][0]["estimator"]
            if name == "xgb":
                est.save_model(_fresh(MODEL_DIR / f"{target}_xgb.json"))
            else:
                joblib.dump(est, _fresh(MODEL_DIR / f"{target}_logreg.joblib"))
        ttags = base_tags | {"target": target, "horizon_min": str(mu.horizon_min(target))}
        seeds_str = ",".join(str(s) for s in mp["seeds"])
        with mlflow.start_run(run_name=f"{target}"):
            mlflow.set_tags(ttags | {"model": "all", "seed": seeds_str, "selected": selected,
                                     "periods": "fit+cv+cal=tune, eval=val"})
            mu.log_inputs(inputs)
            mlflow.log_params({f"xgb_{k}": v for k, v in xgb_params.items()} | {"seeds": str(mp["seeds"]),
                              "n_features": len(feats), "cv_folds": str(mp["cv"]["fold_months"]),
                              "rows_tune": len(tune), "rows_val": len(val)})
            mlflow.log_text(cv_table.to_csv(index=False, lineterminator="\n"), "xgb_cv.csv")
            for m in MODELS:
                learner = m in ("logreg", "xgb")
                with mlflow.start_run(run_name=f"{target}-{m}", nested=True):
                    mlflow.set_tags(ttags | {"model": m, "seed": seeds_str if learner else "none",
                                             "aggregate": "mean over seeds" if learner else "deterministic"})
                    mu.log_inputs(inputs)
                    for op in ops:
                        for subset in ("all", "quiet"):
                            mlflow.log_metrics({f"{op}_{subset}_{k}": v for k, v in agg[m][op][subset].items()
                                                if isinstance(v, (int, float))})
                    if learner:
                        for r in res[m]:
                            _log_seed_run(mlflow, mu, r, target, m, ttags, inputs, ops, example)
            for name in ("logreg", "xgb"):
                path = MODEL_DIR / (f"{target}_xgb.json" if name == "xgb" else f"{target}_logreg.joblib")
                mlflow.log_artifact(str(path))
        a = agg[selected]["A"]["all"]
        print(f"{target:7s} selected {selected:6s} TSS {a['tss_mean']:.3f}±{a['tss_std']:.3f} "
              f"[{a['tss_ci_low']:.3f}, {a['tss_ci_high']:.3f}]  xgb {xgb_params}  ({time.time() - t0:.0f}s)", flush=True)

    from src.models import ablation

    ab = ablation.run_ablation(tune, val, feats, P, {t: summary["targets"][t]["xgb_cv_best"] for t in mp["targets"]})
    summary["ablation"] = ab
    with mlflow.start_run(run_name="hel1os-ablation"):
        mlflow.set_tags(base_tags | {"kind": "ablation", "rows": "hel1os_available == 1", "target": "all",
                                     "model": "logreg,xgb", "horizon_min": "all", "seed": seeds_str})
        mu.log_inputs(inputs)
        mlflow.log_dict(ab, "ablation.json")
    _fresh(MODEL_DIR / "thresholds.json").write_text(json.dumps(thresholds, indent=2), newline="\n")
    pd.concat(cv_tables).to_csv(_fresh(REPORTS / "xgb_cv.csv"), index=False, lineterminator="\n")
    _fresh(REPORTS / "model_metrics.json").write_text(json.dumps(summary, indent=2, default=str), newline="\n")
    report.write_tables(summary)
    plots.skill_figure()
    return summary


if __name__ == "__main__":
    run()
