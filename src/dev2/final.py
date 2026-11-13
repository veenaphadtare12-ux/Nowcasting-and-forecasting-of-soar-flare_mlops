"""Freeze the FINAL_CHOICE_2 models (development data only; holdout2 is never read here).

    python -m src.dev2.final

Blocks (params `dev2.final`), from the task: train on development data up to the last two development months,
fit calibration on the earlier of those two months and choose thresholds on the later one; both months are excluded
from fitting and from each other (120-min purge before each block):
    fit        : 2025-04-09 .. 2026-08-01 minus purge
    calibration: 2026-08-01 .. 2026-09-01 minus purge       (isotonic, on the raw model score)
    thresholds : 2026-09-01 .. 2026-09-13 minus purge       (A max TSS; M targets also C FAR <= 0.80 and K cost 10)
Thresholds are set on the raw score (isotonic is monotone, so the alerts are the same; calibrated values are reported).
For every target two variants are frozen: `aditya` (SoLEXS/HEL1OS inputs only) and `with_goes` (+ the GOES-derived
blocks), so every holdout2 result can be shown with and without GOES. `choice` says which one is the champion.
R1 (early class prediction): per k and input variant, the learner chosen on development data, fit on detections known
before the calibration month; thresholds (max TSS) on the triggers of the last two development months.
"""
from __future__ import annotations

import json
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from src import config
from src import mlflow_utils as mu
from src.dev2 import early, protocol as pr
from src.dev2 import run as rn
from src.models import train

MODEL_DIR = config.PROJECT_ROOT / "models_final2"
REPORT = config.PROJECT_ROOT / "reports" / "dev2" / "final_freeze.json"


def F() -> dict:
    return config.load_params()["dev2"]["final"]


def _fresh(p):
    if p.exists():
        p.chmod(0o666)
        p.unlink()
    return p


def blocks(index: pd.DatetimeIndex) -> dict:
    f = F()
    purge = pd.Timedelta(minutes=pr.P()["purge_min"])
    c0, t0 = (pd.Timestamp(x, tz="UTC") for x in (f["calibration_start"], f["threshold_start"]))
    end = pr.dev_end()
    return {"fit": np.asarray(index < c0 - purge),
            "cal": np.asarray((index >= c0) & (index < t0 - purge)),
            "thr": np.asarray((index >= t0) & (index < end - purge))}


def thresholds(y, s, m_target: bool) -> dict:
    p = pr.P()
    out = {"A": pr.thr_max_tss(y, s)}
    if m_target:
        out["C"] = pr.thr_far_cap(y, s, p["far_cap"])
        for r in [p["cost_fn_fp"]] + list(p["cost_sensitivity"]):
            out[f"K{r}"] = pr.thr_cost(y, s, r)
    return out


def variant_blocks(target: str, variant: str) -> list[str]:
    spec = F()["targets"][target]
    return list(spec["blocks"]) + (list(spec["goes_blocks"]) if variant == "with_goes" else [])


def freeze_forecasts(log) -> dict:
    out = {}
    rule = config.load_params()["models"]["rule_feature"]
    frames = {}
    for target, spec in F()["targets"].items():
        y_col, ok_col = train.TARGETS[target]
        out[target] = {"choice": spec["choice"], "learner": spec["learner"], "variants": {}}
        for variant in ("aditya", "with_goes"):
            bl = variant_blocks(target, variant)
            key = tuple(bl)
            if key not in frames:
                frames[key] = rn.add_blocks(rn.base_frame(), bl)
            df, feats = frames[key]
            b = blocks(df.index)
            ok = df[ok_col].to_numpy().astype(bool)
            fit = df[b["fit"] & ok].iloc[:: pr.P()["train_stride"]]
            cal, thr = df[b["cal"] & ok], df[b["thr"] & ok]
            yf = fit[y_col].to_numpy().astype(int)
            mp = config.load_params()["models"]
            lr = train.make_logreg(mp["logreg"], pr.P()["seed"])
            xg = train.make_xgb(mp["xgb"], rn.xgb_params()[target], pr.P()["seed"], train._pos_weight(yf))
            if spec["learner"] == "ensemble":
                from sklearn.ensemble import VotingClassifier

                est = VotingClassifier([("logreg", lr), ("xgb", xg)], voting="soft")
            else:
                est = {"logreg": lr, "xgb": xg}[spec["learner"]]
            est.fit(fit[feats], yf)
            s_cal = est.predict_proba(cal[feats])[:, 1]
            s_thr = est.predict_proba(thr[feats])[:, 1]
            y_cal, y_thr = cal[y_col].to_numpy().astype(bool), thr[y_col].to_numpy().astype(bool)
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(s_cal, y_cal.astype(float))
            th = thresholds(y_thr, s_thr, target.startswith("m_"))
            base_thr = {"rule": thresholds(y_thr, thr[rule].fillna(0).to_numpy(), False),
                        "flux": thresholds(y_thr, thr["log_rate"].fillna(-9).to_numpy(), False),
                        "persistence": {"A": 0.5}, "climatology_rate": float(yf.mean())}
            joblib.dump({"estimator": est, "features": feats, "blocks": bl, "learner": spec["learner"], "isotonic": iso,
                         "thresholds": th, "baseline_thresholds": base_thr, "target": target, "variant": variant},
                        _fresh(MODEL_DIR / f"{target}_{variant}.joblib"))
            out[target]["variants"][variant] = {
                "blocks": bl, "n_features": len(feats), "fit_rows": int(len(fit)), "fit_pos": int(yf.sum()),
                "cal_rows": int(len(cal)), "cal_pos": int(y_cal.sum()), "thr_rows": int(len(thr)), "thr_pos": int(y_thr.sum()),
                "thresholds": th, "baseline_thresholds": base_thr,
                "thr_block_tss_A": pr.tss_of(pr.counts(y_thr, s_thr >= th["A"])),
                "brier_cal_raw": float(np.mean((s_cal - y_cal) ** 2)),
                "brier_thr_raw": float(np.mean((s_thr - y_thr) ** 2)),
                "brier_thr_isotonic": float(np.mean((iso.predict(s_thr) - y_thr) ** 2))}
            log(f"{target}-{variant}", est, feats, out[target]["variants"][variant])
            print(f"  {target:7s} {variant:9s} {len(feats):3d} feats, thr block {int(y_thr.sum())} pos, TSS_A "
                  f"{out[target]['variants'][variant]['thr_block_tss_A']:.3f}", flush=True)
    return out


def freeze_r1() -> dict:
    d = early.dev_inputs()
    det = d["det"].reset_index(drop=True)
    f = F()
    purge = pd.Timedelta(minutes=pr.P()["purge_min"])
    c0 = pd.Timestamp(f["calibration_start"], tz="UTC")
    known, trig = pd.DatetimeIndex(det["end_known_time"]), pd.DatetimeIndex(det["trigger_time"])
    fit = np.asarray(known < c0 - purge)
    thr = np.asarray((trig >= c0) & (trig < pr.dev_end()))
    out = {}
    for k in early.KS:
        X = early.features(det, k, d["minute"], d["spectral"], d["rows"], d["gx"])
        for var, cols in (("aditya", early.ADITYA), ("with_goes", early.ADITYA + early.GOESF)):
            kind = f["r1"][var]
            models, th = {}, {}
            for tgt in ("y_c", "y_m"):
                y = det[tgt].to_numpy()
                est = early.make(kind, y[fit], pr.P()["seed"]).fit(X.loc[fit, cols], y[fit].astype(int))
                s = est.predict_proba(X.loc[thr, cols])[:, 1]
                models[tgt], th[tgt] = est, pr.thr_max_tss(y[thr], s)
            th_flux = {tgt: pr.thr_max_tss(det[tgt].to_numpy()[thr], X.loc[thr, "f_log_m"].fillna(-9).to_numpy())
                       for tgt in ("y_c", "y_m")}
            joblib.dump({"models": models, "thresholds": th, "flux_thresholds": th_flux, "features": cols, "learner": kind, "k": k},
                        _fresh(MODEL_DIR / f"r1_k{k}_{var}.joblib"))
            out[f"k{k}_{var}"] = {"learner": kind, "thresholds": th, "flux_thresholds": th_flux,
                                  "fit_triggers": int(fit.sum()), "fit_m": int(det["y_m"][fit].sum()),
                                  "thr_triggers": int(thr.sum()), "thr_m": int(det["y_m"][thr].sum())}
    return out


def main() -> dict:
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow
    from mlflow.models import infer_signature

    MODEL_DIR.mkdir(exist_ok=True)
    mlflow.set_tracking_uri(config.mlflow_uri())
    mlflow.set_experiment("flare-final2")
    tags0 = mu.run_tags() | {"final_choice": "docs/FINAL_CHOICE_2.md"}

    def log(name, est, feats, info):
        with mlflow.start_run(run_name=f"final2-{name}"):
            mlflow.set_tags(tags0 | {"target": name.split("-")[0], "variant": name.split("-")[1],
                                     "blocks": ",".join(info["blocks"]) or "base", "seed": str(pr.P()["seed"]),
                                     "fit": f"< {F()['calibration_start']}", "calibration": F()["calibration_start"],
                                     "thresholds": F()["threshold_start"]})
            mlflow.log_params({"n_features": info["n_features"], "fit_rows": info["fit_rows"]})
            mlflow.log_metrics({"thr_block_tss_A": info["thr_block_tss_A"], "brier_thr_raw": info["brier_thr_raw"],
                                "brier_thr_isotonic": info["brier_thr_isotonic"]})
            mlflow.log_dict({"features": feats, "thresholds": info["thresholds"]}, "final2_spec.json")

    res = {"blocks": {k: F()[k] for k in ("calibration_start", "threshold_start")}, "forecasts": freeze_forecasts(log),
           "r1": freeze_r1()}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    _fresh(REPORT).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8", newline="\n")
    print(f"frozen -> {MODEL_DIR}")
    return res


if __name__ == "__main__":
    main()
