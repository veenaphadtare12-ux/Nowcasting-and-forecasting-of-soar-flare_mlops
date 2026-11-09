"""Stage final_models: fit the frozen final models (docs/FINAL_CHOICE.md), choose thresholds, register them.

    python -m src.final.freeze

Reads tune + val only (never the test period):
    fit        = 2025-04-09 .. final.fit_end minus purge, ok rows, every 6th row, seed 42
    thresholds = final.threshold_block minus purge at its end (May 2026): A max TSS, B max HSS, C lowest thr with FAR <= cap
Writes models_final/<target>_{chosen,runner_up,isotonic}.joblib, models_final/thresholds.json, reports/final/freeze.json,
and registers each chosen model in the MLflow registry with alias `champion`.
"""
from __future__ import annotations

import json
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import VotingClassifier
from sklearn.isotonic import IsotonicRegression

from src import config
from src import mlflow_utils as mu
from src.final import features as ff
from src.improve import protocol as pr
from src.models import metrics, train

MODEL_DIR = config.PROJECT_ROOT / "models_final"
REPORT = config.PROJECT_ROOT / "reports" / "final"
FLAG = train.FLAG


def _fresh(p):
    if p.exists():
        p.chmod(0o666)
        p.unlink()
    return p


def xgb_params() -> dict:
    mm = json.loads((config.PROJECT_ROOT / "reports" / "model_metrics.json").read_text(encoding="utf-8"))
    return {t: mm["targets"][t]["xgb_cv_best"] for t in mm["targets"]}


def make_model(kind: str, target: str, yf: np.ndarray, seed: int):
    mp = config.load_params()["models"]
    lr = train.make_logreg(mp["logreg"], seed)
    xg = train.make_xgb(mp["xgb"], xgb_params()[target], seed, train._pos_weight(yf))
    return {"logreg": lr, "xgb": xg, "ensemble": VotingClassifier([("logreg", lr), ("xgb", xg)], voting="soft")}[kind]


def thresholds(y: np.ndarray, s: np.ndarray, far_cap: float) -> dict:
    y = np.asarray(y).astype(bool)
    return {"A": pr.thr_max_tss(y, s), "B": float(metrics.best_threshold(y, s, "hss")[0]) if y.any() else np.inf,
            "C": pr.thr_far_cap(y, s, far_cap)}


def ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error with equal-width probability bins."""
    p = np.clip(p, 0, 1)
    k = np.minimum((p * bins).astype(int), bins - 1)
    tot = 0.0
    for b in range(bins):
        m = k == b
        if m.any():
            tot += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(tot)


def blocks(index: pd.DatetimeIndex) -> dict:
    F = config.load_params()["final"]
    purge = pd.Timedelta(minutes=F["purge_min"])
    fit_end = pd.Timestamp(F["fit_end"], tz="UTC")
    b0, b1 = (pd.Timestamp(x, tz="UTC") for x in F["threshold_block"])
    return {"fit": np.asarray(index < fit_end - purge), "block": np.asarray((index >= b0) & (index < b1 - purge)),
            "dates": {"fit": [str(index.min()), str(fit_end - purge)], "threshold_block": [str(b0), str(b1 - purge)]}}


def main() -> dict:
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow
    import sklearn
    import xgboost
    from mlflow import MlflowClient
    from mlflow.models import infer_signature

    P = config.load_params()
    F, mp = P["final"], P["models"]
    MODEL_DIR.mkdir(exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    base = pr.load(ff.base_features() + ff.label_columns() + [FLAG])   # tune + val only
    mlflow.set_tracking_uri(config.mlflow_uri())
    mlflow.set_experiment("flare-final")
    client = MlflowClient()
    tags0 = mu.run_tags()
    out = {"targets": {}}
    thr_all = {}
    frames = {}
    for target, spec in F["targets"].items():
        y_col, ok_col = train.TARGETS[target]
        res = {"registry": spec["registry"], "model": spec["model"], "ideas": spec["ideas"]}
        thr_all[target] = {}
        for role, s in (("chosen", spec), ("runner_up", spec["runner_up"])):
            key = tuple(sorted(s["ideas"]))
            if key not in frames:
                frames[key] = ff.build(base, list(s["ideas"]))
            df, feats = frames[key]
            bk = blocks(df.index)
            ok = df[ok_col].to_numpy().astype(bool)
            fit = df[bk["fit"] & ok].iloc[::F["train_stride"]]
            blk = df[bk["block"] & ok]
            yf, yb = fit[y_col].to_numpy().astype(int), blk[y_col].to_numpy().astype(bool)
            est = make_model(s["model"], target, yf, F["seed"]).fit(fit[feats], yf)
            sb = est.predict_proba(blk[feats])[:, 1]
            thr = thresholds(yb, sb, F["far_cap"])
            joblib.dump({"estimator": est, "features": feats, "model": s["model"], "ideas": list(s["ideas"])},
                        _fresh(MODEL_DIR / f"{target}_{role}.joblib"))
            thr_all[target][role] = thr
            res[role] = {"model": s["model"], "ideas": list(s["ideas"]), "n_features": len(feats),
                         "fit_rows": len(fit), "fit_positive_rate": float(yf.mean()), "block_rows": len(blk),
                         "block_positives": int(yb.sum()), "thresholds": thr,
                         "block_tss_A": float(metrics.tss(metrics.contingency(yb, sb >= thr["A"])))}
            if role == "chosen":
                iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(sb, yb.astype(float))
                joblib.dump(iso, _fresh(MODEL_DIR / f"{target}_isotonic.joblib"))
                res["calibration_block"] = {"ece_raw": ece(yb, sb), "brier_raw": float(np.mean((sb - yb) ** 2)),
                                            "badly_calibrated": bool(ece(yb, sb) > 0.05)}
                # baselines: thresholds from the same block
                rule = blk[mp["rule_feature"]].fillna(0).to_numpy()
                thr_all[target]["rule"] = thresholds(yb, rule, F["far_cap"])
                thr_all[target]["persistence"] = {"A": 0.5, "B": 0.5, "C": 0.5}
                thr_all[target]["climatology"] = {"rate": float(yf.mean())}
                res["dates"] = bk["dates"]
                chosen_est, chosen_feats, chosen_blk, chosen_fit = est, feats, blk, fit
        # ---- MLflow: log + register the chosen model
        ex = chosen_fit[chosen_feats].dropna().head(5)    # fully filled rows (HEL1OS sessions lie in the fit block)
        if len(ex) < 5:
            ex = chosen_fit[chosen_feats].head(5)
        thr = thr_all[target]["chosen"]
        ttags = tags0 | {"target": target, "horizon_min": str(mu.horizon_min(target)), "model": spec["model"],
                         "seed": str(F["seed"]), "ideas": ",".join(spec["ideas"]) or "none",
                         "fit_dates": " .. ".join(res["dates"]["fit"]),
                         "threshold_block": " .. ".join(res["dates"]["threshold_block"]),
                         "thr_A": f"{thr['A']:.6g}", "thr_B": f"{thr['B']:.6g}", "thr_C": f"{thr['C']:.6g}",
                         "final_choice": "docs/FINAL_CHOICE.md"}
        with mlflow.start_run(run_name=f"final-{target}"):
            mlflow.set_tags(ttags)
            mlflow.log_params({"n_features": len(chosen_feats), "fit_rows": res["chosen"]["fit_rows"],
                               "block_rows": res["chosen"]["block_rows"], "registry": spec["registry"]})
            mlflow.log_metrics({"block_tss_A": res["chosen"]["block_tss_A"], "block_ece_raw": res["calibration_block"]["ece_raw"]})
            mlflow.log_dict({"features": chosen_feats, "thresholds": thr_all[target]}, "final_spec.json")
            info = mlflow.sklearn.log_model(
                chosen_est, name="model", signature=infer_signature(ex, chosen_est.predict_proba(ex)), input_example=ex,
                serialization_format="cloudpickle", pyfunc_predict_fn="predict_proba", registered_model_name=spec["registry"],
                pip_requirements=[f"scikit-learn=={sklearn.__version__}", f"xgboost=={xgboost.__version__}",
                                  f"pandas=={pd.__version__}", f"numpy=={np.__version__}"])
        v = info.registered_model_version
        client.set_registered_model_alias(spec["registry"], F["registry_alias"], v)
        for k, val in ttags.items():
            client.set_model_version_tag(spec["registry"], v, k, val)
        client.update_registered_model(spec["registry"], description=(
            f"Solar flare model for target '{target}' ({spec['model']}, ideas {spec['ideas'] or 'none'}). "
            "Input: the feature columns of the DVC pipeline (src/features.py, src/final/features.py). "
            "Output: [P(no), P(yes)]. Alert when P(yes) >= thr_A (or thr_B/thr_C) tag. See docs/MODEL_CARD.md."))
        res["registry_version"] = int(v)
        out["targets"][target] = res
        print(f"{target:6s} {spec['model']:8s} feats {len(chosen_feats):3d}  block TSS_A {res['chosen']['block_tss_A']:.3f}  "
              f"v{v}  ECE {res['calibration_block']['ece_raw']:.3f}", flush=True)
    _fresh(MODEL_DIR / "thresholds.json").write_text(json.dumps(thr_all, indent=2), encoding="utf-8", newline="\n")
    _fresh(REPORT / "freeze.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8", newline="\n")
    return out


if __name__ == "__main__":
    main()
