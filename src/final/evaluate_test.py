"""Stage evaluate_test: score the frozen models ONCE on the test period (the only code allowed to read test.parquet).

    python -m src.final.evaluate_test

Everything is frozen beforehand (docs/FINAL_CHOICE.md, models_final/, thresholds from May 2026). Nothing here is fitted
on test rows. Writes reports/final/test_metrics.json and data/processed/final/test_scores.parquet (per-row scores,
labels and flags for the later analysis; no further reads of test.parquet are needed).
"""
from __future__ import annotations

import json
import os

import joblib
import numpy as np
import pandas as pd

from src import config
from src.final import features as ff
from src.final.freeze import MODEL_DIR, REPORT, _fresh
from src.improve import protocol as pr
from src.models import metrics, train

FLAG = train.FLAG
TEST_FILE = "test.parquet"


def load_all(columns: list[str]) -> pd.DataFrame:
    """tune + val (trailing context for long-window and drift features) + test."""
    d = config.processed_dir() / "dataset"
    parts = [pd.read_parquet(d / f"{p}.parquet", columns=columns) for p in ("tune", "val")]
    parts.append(pd.read_parquet(d / TEST_FILE, columns=columns))
    return pd.concat(parts).sort_index()


def block_metrics(y, yhat, day_codes, n_days, idx, level) -> dict:
    """TSS/HSS/POD/FAR + 95 % day-bootstrap interval for TSS; also the bootstrap TSS draws (for paired tests)."""
    c = metrics.contingency(y, yhat)
    dc = metrics.daily_counts(y, yhat, day_codes, n_days)
    boot = metrics.tss_from_counts(dc[idx].sum(axis=1))
    a = (1 - level) / 2
    return {"tss": float(metrics.tss(c)), "hss": float(metrics.hss(c)), "pod": c["tp"] / max(c["tp"] + c["fn"], 1),
            "far": c["fp"] / max(c["tp"] + c["fp"], 1), "tp": int(c["tp"]), "fp": int(c["fp"]), "fn": int(c["fn"]),
            "tn": int(c["tn"]), "n": int(len(y)), "pos": int(np.sum(y)), "alerts": int(np.sum(yhat)),
            "ci_low": float(np.quantile(boot, a)), "ci_high": float(np.quantile(boot, 1 - a))}, boot


def shap_nowcast(est, X: pd.DataFrame, n: int = 30000, seed: int = 0) -> dict:
    """Exact tree SHAP values from XGBoost (pred_contribs) on a random sample of test rows."""
    import xgboost as xgb

    rs = np.random.default_rng(seed)
    Xs = X.iloc[np.sort(rs.choice(len(X), size=min(n, len(X)), replace=False))]
    contrib = est.get_booster().predict(xgb.DMatrix(Xs, missing=np.nan), pred_contribs=True)[:, :-1]
    mean_abs = pd.Series(np.abs(contrib).mean(axis=0), index=X.columns).sort_values(ascending=False)
    top = list(mean_abs.index[:15])
    sample = pd.DataFrame({"feature": np.repeat(top, len(Xs)),
                           "value": np.concatenate([Xs[f].to_numpy() for f in top]),
                           "shap": np.concatenate([contrib[:, X.columns.get_loc(f)] for f in top])})
    p = _fresh(config.processed_dir() / "final" / "shap_nowcast_sample.parquet")
    sample.astype({"value": "float32", "shap": "float32"}).to_parquet(p)
    return {"n_rows": len(Xs), "mean_abs_shap": {k: float(v) for k, v in mean_abs.items()}}


def main() -> dict:
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    P = config.load_params()
    F, mp = P["final"], P["models"]
    bs = F["bootstrap"]
    thr = json.loads((MODEL_DIR / "thresholds.json").read_text(encoding="utf-8"))
    t0, t1 = config.period_bounds("test")
    base = load_all(ff.base_features() + ff.label_columns() + [FLAG])
    is_test = np.asarray((base.index >= t0) & (base.index < t1))
    frames, out, scores = {}, {"targets": {}}, pd.DataFrame(index=base.index[is_test])
    scores["quiet"] = base.loc[is_test, FLAG].to_numpy() == 0
    scores["persistence"] = base.loc[is_test, FLAG].to_numpy().astype("float32")
    scores["rule"] = base.loc[is_test, mp["rule_feature"]].fillna(0).to_numpy().astype("float32")
    days_all = pd.DatetimeIndex(sorted(scores.index.floor("D").unique()))
    idx = metrics.bootstrap_indices(len(days_all), bs["n"], bs["seed"])
    shap = None
    for target, spec in F["targets"].items():
        y_col, ok_col = train.TARGETS[target]
        scores[f"y_{target}"] = base.loc[is_test, y_col].to_numpy().astype("int8")
        scores[f"ok_{target}"] = base.loc[is_test, ok_col].to_numpy().astype(bool)
        for role in ("chosen", "runner_up"):
            m = joblib.load(MODEL_DIR / f"{target}_{role}.joblib")
            key = tuple(sorted(m["ideas"]))
            if key not in frames:
                frames[key] = ff.build(base, m["ideas"], end=t1, include_test=True)[0]
            X = frames[key].loc[is_test, m["features"]]
            scores[f"s_{target}_{role}"] = m["estimator"].predict_proba(X)[:, 1].astype("float32")
            if target == "now" and role == "chosen" and m["model"] == "xgb":
                shap = shap_nowcast(m["estimator"], X)
        iso = joblib.load(MODEL_DIR / f"{target}_isotonic.joblib")
        scores[f"s_{target}_calibrated"] = iso.predict(scores[f"s_{target}_chosen"].to_numpy()).astype("float32")
        # ---- metrics on ok rows
        ok = scores[f"ok_{target}"].to_numpy()
        sub = scores[ok]
        y = sub[f"y_{target}"].to_numpy().astype(bool)
        codes = days_all.get_indexer(sub.index.floor("D"))
        res, boots = {}, {}
        models = {"chosen": (f"s_{target}_chosen", thr[target]["chosen"]), "runner_up": (f"s_{target}_runner_up", thr[target]["runner_up"]),
                  "rule": ("rule", thr[target]["rule"]), "persistence": ("persistence", thr[target]["persistence"])}
        for name, (col, th) in models.items():
            res[name] = {}
            for op in ("A", "B", "C"):
                res[name][op] = {}
                for subset, mask in (("all", np.ones(len(sub), bool)), ("quiet", sub["quiet"].to_numpy())):
                    r, b = block_metrics(y[mask], sub[col].to_numpy()[mask] >= th[op], codes[mask], len(days_all), idx, bs["level"])
                    r["threshold"] = th[op]
                    res[name][op][subset] = r
                    if op == "A" and subset == "all":
                        boots[name] = b
        res["climatology"] = {"A": {"all": {"tss": 0.0, "note": "constant forecast: TSS 0 by construction"}}}
        # ---- paired day-bootstrap tests (TSS at A, all rows); one-sided p = share of draws where chosen is not better
        best_base = max(("rule", "persistence"), key=lambda k: res[k]["A"]["all"]["tss"])
        paired = {}
        for other in (best_base, "runner_up"):
            d = boots["chosen"] - boots[other]
            paired[f"vs_{other}"] = {"tss_diff": res["chosen"]["A"]["all"]["tss"] - res[other]["A"]["all"]["tss"],
                                     "ci_low": float(np.quantile(d, 0.025)), "ci_high": float(np.quantile(d, 0.975)),
                                     "p_one_sided": float((np.sum(d <= 0) + 1) / (len(d) + 1))}
        # ---- calibration (Brier raw vs isotonic fitted on the threshold block)
        s_raw, s_cal = sub[f"s_{target}_chosen"].to_numpy(), sub[f"s_{target}_calibrated"].to_numpy()
        cal = {"brier_raw": float(np.mean((s_raw - y) ** 2)), "brier_isotonic": float(np.mean((s_cal - y) ** 2)),
               "brier_climatology": float(np.mean((thr[target]["climatology"]["rate"] - y) ** 2)),
               "test_positive_rate": float(y.mean())}
        out["targets"][target] = {"registry": spec["registry"], "model": spec["model"], "ideas": spec["ideas"],
                                  "metrics": res, "best_baseline": best_base, "paired": paired, "calibration": cal,
                                  "n_test_rows": int(len(sub)), "test_days": len(days_all)}
        a = res["chosen"]["A"]["all"]
        print(f"{target:6s} TSS_A {a['tss']:.3f} [{a['ci_low']:.2f},{a['ci_high']:.2f}]  runner-up "
              f"{res['runner_up']['A']['all']['tss']:.3f}  {best_base} {res[best_base]['A']['all']['tss']:.3f}", flush=True)
    out["shap_nowcast"] = shap
    out["test_period"] = [str(t0), str(t1)]
    _fresh(REPORT / "test_metrics.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8", newline="\n")
    scores.to_parquet(_fresh(config.processed_dir() / "final" / "test_scores.parquet"))
    _log_mlflow(out)
    return out


def _log_mlflow(out: dict) -> None:
    import mlflow
    from mlflow import MlflowClient

    from src import mlflow_utils as mu

    F = config.load_params()["final"]
    mlflow.set_tracking_uri(config.mlflow_uri())
    mlflow.set_experiment("flare-final")
    client = MlflowClient()
    with mlflow.start_run(run_name="test-evaluation"):
        mlflow.set_tags(mu.run_tags() | {"kind": "one-time test evaluation", "test_period": " .. ".join(out["test_period"]),
                                         "target": "all", "model": "champions", "horizon_min": "all", "seed": str(F["seed"])})
        for t, r in out["targets"].items():
            for op in ("A", "B", "C"):
                for sub in ("all", "quiet"):
                    m = r["metrics"]["chosen"][op][sub]
                    mlflow.log_metrics({f"{t}_{op}_{sub}_tss": m["tss"], f"{t}_{op}_{sub}_far": m["far"], f"{t}_{op}_{sub}_pod": m["pod"]})
            mlflow.log_metrics({f"{t}_brier_raw": r["calibration"]["brier_raw"], f"{t}_brier_isotonic": r["calibration"]["brier_isotonic"]})
            v = client.get_model_version_by_alias(r["registry"], F["registry_alias"]).version
            a = r["metrics"]["chosen"]["A"]["all"]
            client.set_model_version_tag(r["registry"], v, "test_tss_A", f"{a['tss']:.4f} [{a['ci_low']:.3f}, {a['ci_high']:.3f}]")
        mlflow.log_dict(out, "test_metrics.json")


if __name__ == "__main__":
    main()
