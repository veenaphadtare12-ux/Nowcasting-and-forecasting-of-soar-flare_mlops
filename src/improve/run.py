"""Improvement experiments with the rolling monthly protocol (tune + val only; the test period is never read).

    python -m src.improve.run reference      # current features/models -> reports/improve/reference.json (+ E1, E7)
    python -m src.improve.run E2             # one feature experiment, compared with the reference
    python -m src.improve.run final          # combination of the KEPT ideas (+ original validation block)
    python -m src.improve.run all            # everything, in order (used by the DVC stage)

E1 (adaptive thresholds) and E7 (ensemble) reuse the reference models' scores, so they need no refit.
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from src import config
from src import mlflow_utils as mu
from src.improve import features_extra as fx
from src.improve import protocol as pr
from src.models import train

OUT = config.PROJECT_ROOT / "reports" / "improve"
LEARNERS = ("logreg", "xgb")
FLAG = train.FLAG
FEATURE_EXPERIMENTS = {
    "E2": {"extra": ["long"], "desc": "long-context features (3-24 h light curve, causal detector events)"},
    "E3": {"drift": True, "desc": "drift-robust features (divided by trailing 7-day median)"},
    "E4": {"prune": True, "desc": "feature pruning (|r| > 0.95 on fit rows, keep the simpler)"},
    "E5": {"extra": ["spectral"], "desc": "SoLEXS spectral band features (temperature proxy, HOPE flag)"},
    "E6": {"extra": ["goes"], "desc": "GOES XRS 1-min flux features (ablation: with vs without GOES)"},
}
DERIVED = {"E1": "adaptive thresholds (previous 30 days) + operating point C (FAR <= 0.80)",
           "E7": "ensemble: mean of LogReg and XGBoost probabilities"}


def base_features() -> list[str]:
    return json.loads((config.PROJECT_ROOT / "reports" / "model_metrics.json").read_text(encoding="utf-8"))["features"]


def xgb_params() -> dict:
    mm = json.loads((config.PROJECT_ROOT / "reports" / "model_metrics.json").read_text(encoding="utf-8"))
    return {t: mm["targets"][t]["xgb_cv_best"] for t in mm["targets"]}


def load_frame(cfg: dict) -> tuple[pd.DataFrame, list[str]]:
    feats = base_features()
    labels = sorted({c for t in pr.P()["targets"] for c in train.TARGETS[t]})
    df = pr.load(feats + labels + [FLAG])
    for k in cfg.get("extra", []):
        ex = fx.extra_block(k, df.index)
        df = pd.concat([df, ex], axis=1)
        feats = feats + list(ex.columns)
    if cfg.get("drift"):
        df = fx.drift_normalise(df, pr.P()["drift_days"])
    return df, feats


def prune(df: pd.DataFrame, feats: list[str], r_max: float) -> list[str]:
    """Drop the later feature of every pair with |r| > r_max (feature order = simplest first)."""
    c = df[feats].iloc[::30].corr().abs().to_numpy()
    keep = []
    for i, f in enumerate(feats):
        if not any(c[i, feats.index(k)] > r_max for k in keep if np.isfinite(c[i, feats.index(k)])):
            keep.append(f)
    return keep


# ---------------------------------------------------------------- one fold
def run_fold(df: pd.DataFrame, feats: list[str], target: str, mk: dict, score_start: pd.Timestamp, cfg: dict,
             xgbp: dict) -> dict:
    """Fit on mk['fit'] rows, score mk['cal'] (threshold block) and mk['score'] rows."""
    p = pr.P()
    mp = config.load_params()["models"]
    y_col, ok_col = train.TARGETS[target]
    ok = df[ok_col].to_numpy().astype(bool)
    fit = df[mk["fit"] & ok].iloc[::p["train_stride"]]
    cs = df[(mk["cal"] | mk["score"]) & ok]           # threshold block + scored block (E1 needs both)
    in_cal = np.asarray(cs.index < score_start)
    fts = prune(fit, feats, p["prune_r"]) if cfg.get("prune") else feats
    yf = fit[y_col].to_numpy().astype(int)
    scores = {}
    for name in LEARNERS:
        if name == "logreg":
            est = train.make_logreg(mp["logreg"], p["seed"])
        else:
            est = train.make_xgb(mp["xgb"], xgbp[target], p["seed"], train._pos_weight(yf))
            est.set_params(n_jobs=3)
        est.fit(fit[fts], yf)
        scores[name] = est.predict_proba(cs[fts])[:, 1].astype("float32")
    scores["ensemble"] = (scores["logreg"] + scores["xgb"]) / 2
    scores["persistence"] = cs[FLAG].to_numpy().astype("float32")
    scores["rule"] = cs[mp["rule_feature"]].fillna(0).to_numpy().astype("float32")
    return {"times": cs.index, "y": cs[y_col].to_numpy().astype(bool), "quiet": cs[FLAG].to_numpy() == 0,
            "in_cal": in_cal, "scores": scores, "n_features": len(fts), "features": fts}


def evaluate_fold(f: dict, cal_start: pd.Timestamp, rolling: bool) -> dict:
    c, s = f["in_cal"], ~f["in_cal"]
    y, q = f["y"], f["quiet"]
    out = {}
    for name, sc in f["scores"].items():
        if name == "persistence":
            out[name] = pr.evaluate_month(y[c], sc[c], y[s], sc[s], q[s], fixed_threshold=0.5)
        else:
            out[name] = pr.evaluate_month(y[c], sc[c], y[s], sc[s], q[s])
        if rolling and name in ("logreg", "xgb", "ensemble"):
            out[name + "_rolling"] = pr.evaluate_month_rolling(f["times"], y, sc, f["times"][s], y[s], sc[s], q[s], cal_start)
    out["climatology"] = {"A_all": {"tss": 0.0}, "A_quiet": {"tss": 0.0}}
    out["n_features"] = f["n_features"]
    return out


def run_experiment(cfg: dict, rolling: bool = False) -> dict:
    p = pr.P()
    df, feats = load_frame(cfg)
    xgbp = xgb_params()
    res = {"features": feats, "n_features": len(feats), "targets": {}}
    for target in p["targets"]:
        t0 = time.time()

        def one(m):
            mk = pr.fold_masks(df.index, m, p["purge_min"])
            b = pr.fold_bounds(m, p["purge_min"])
            return m, evaluate_fold(run_fold(df, feats, target, mk, b["score_start"], cfg, xgbp), b["cal_start"], rolling)

        months = dict(Parallel(n_jobs=4, prefer="threads")(delayed(one)(m) for m in p["months"]))
        res["targets"][target] = {"months": {m: months[m] for m in p["months"]}}
        print(f"  {target:6s} {time.time() - t0:5.0f}s", flush=True)
    return res


# ---------------------------------------------------------------- summaries and comparison
def monthly(res: dict, target: str, model: str, key: str = "A_all") -> np.ndarray:
    return np.array([res["targets"][target]["months"][m][model][key]["tss"] for m in pr.P()["months"]])


def summary(res: dict, models: list[str]) -> dict:
    out = {}
    for t in res["targets"]:
        out[t] = {}
        for mdl in models:
            a, q = monthly(res, t, mdl), monthly(res, t, mdl, "A_quiet")
            out[t][mdl] = {"all_mean": float(a.mean()), "all_std": float(a.std()), "quiet_mean": float(q.mean()),
                           "quiet_std": float(q.std()), "all_months": [round(float(v), 4) for v in a]}
            if "C_all" in res["targets"][t]["months"][pr.P()["months"][0]][mdl]:
                cs = [res["targets"][t]["months"][m][mdl]["C_all"] for m in pr.P()["months"]]
                out[t][mdl] |= {"C_pod_mean": float(np.mean([x["pod"] for x in cs])),
                                "C_far_mean": float(np.mean([x["far"] for x in cs])),
                                "C_tss_mean": float(np.mean([x["tss"] for x in cs]))}
    return out


def reference_learner(ref_summary: dict, target: str) -> str:
    return max(LEARNERS, key=lambda k: ref_summary[target][k]["all_mean"])


def compare(ref: dict, exp: dict, exp_model_for: dict) -> dict:
    """exp_model_for: target -> model key inside exp (e.g. 'xgb', 'ensemble', 'xgb_rolling')."""
    need = pr.P()["acceptance"]["min_months_improved"]
    rs = summary(ref, list(LEARNERS))
    out = {}
    for t in exp["targets"]:
        rl = reference_learner(rs, t)
        r_all, r_q = monthly(ref, t, rl), monthly(ref, t, rl, "A_quiet")
        e_all, e_q = monthly(exp, t, exp_model_for[t]), monthly(exp, t, exp_model_for[t], "A_quiet")
        improved = int((e_all > r_all).sum())
        kept = bool(e_all.mean() > r_all.mean() and improved >= need)
        out[t] = {"reference_learner": rl, "model": exp_model_for[t],
                  "ref_mean": float(r_all.mean()), "ref_std": float(r_all.std()),
                  "exp_mean": float(e_all.mean()), "exp_std": float(e_all.std()),
                  "ref_quiet_mean": float(r_q.mean()), "exp_quiet_mean": float(e_q.mean()),
                  "exp_quiet_std": float(e_q.std()), "months_improved": improved,
                  "delta": float(e_all.mean() - r_all.mean()), "decision": "KEPT" if kept else "DROPPED"}
    return out


# ---------------------------------------------------------------- I/O and MLflow
def _write(name: str, obj: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{name}.json"
    if p.exists():
        p.chmod(0o666)
        p.unlink()
    p.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8", newline="\n")


def _read(name: str) -> dict:
    return json.loads((OUT / f"{name}.json").read_text(encoding="utf-8"))


def _strip(res: dict) -> dict:
    """Monthly metrics only (no arrays)."""
    return {k: v for k, v in res.items()}


def log_mlflow(name: str, desc: str, cmp: dict | None, summ: dict, params: dict) -> None:
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow

    mlflow.set_tracking_uri(config.mlflow_uri())
    mlflow.set_experiment("flare-improve")
    months = pr.P()["months"]
    with mlflow.start_run(run_name=name):
        mlflow.set_tags(mu.run_tags() | {"experiment": name, "description": desc, "target": "all", "model": "see children",
                                         "horizon_min": "see children", "seed": str(pr.P()["seed"]),
                                         "protocol": "rolling monthly 2025-08..2026-05 (tune+val), test never read"})
        mlflow.log_params(params)
        mlflow.log_dict({"comparison": cmp, "summary": summ}, f"{name}.json")
        for t in summ:
            with mlflow.start_run(run_name=f"{name}-{t}", nested=True):
                mlflow.set_tags(mu.run_tags() | {"experiment": name, "target": t, "horizon_min": str(mu.horizon_min(t)),
                                                 "seed": str(pr.P()["seed"]),
                                                 "model": cmp[t]["model"] if cmp else ",".join(summ[t])})
                if cmp:
                    c = cmp[t]
                    mlflow.log_metrics({"tss_mean": c["exp_mean"], "tss_std": c["exp_std"], "ref_tss_mean": c["ref_mean"],
                                        "delta_tss": c["delta"], "months_improved": c["months_improved"],
                                        "quiet_tss_mean": c["exp_quiet_mean"], "kept": float(c["decision"] == "KEPT")})
                    model = c["model"]
                else:
                    model = None
                for mdl, s in summ[t].items():
                    if model and mdl != model:
                        continue
                    mlflow.log_metrics({f"{mdl}_all_tss_mean": s["all_mean"], f"{mdl}_quiet_tss_mean": s["quiet_mean"]})
                    for i, v in enumerate(s["all_months"]):
                        mlflow.log_metric(f"{mdl}_month_tss", v, step=i)
                    if "C_pod_mean" in s:
                        mlflow.log_metrics({f"{mdl}_C_pod_mean": s["C_pod_mean"], f"{mdl}_C_far_mean": s["C_far_mean"]})
                mlflow.set_tag("months", ",".join(months))


# ---------------------------------------------------------------- experiments
def run_reference() -> None:
    t0 = time.time()
    res = run_experiment({}, rolling=True)
    models = ["climatology", "persistence", "rule", "logreg", "xgb"]
    ref_summ = summary(res, models)
    _write("reference", {"protocol": pr.P(), "summary": ref_summ, "months": _strip(res), "seconds": time.time() - t0})
    log_mlflow("reference", "current features and models, rolling monthly protocol", None, ref_summ,
               {"n_features": res["n_features"]})
    rs = summary(res, list(LEARNERS))
    # E1: same models, daily thresholds from the previous 30 days
    e1 = compare(res, res, {t: reference_learner(rs, t) + "_rolling" for t in res["targets"]})
    e1_summ = summary(res, [f"{k}_rolling" for k in LEARNERS] + list(LEARNERS))
    _write("E1", {"comparison": e1, "summary": e1_summ, "description": DERIVED["E1"]})
    log_mlflow("E1", DERIVED["E1"], e1, e1_summ, {"rolling_days": pr.P()["rolling_days"], "far_cap": pr.P()["far_cap"]})
    # E7: ensemble, fixed thresholds as in the reference
    e7 = compare(res, res, {t: "ensemble" for t in res["targets"]})
    e7_summ = summary(res, ["ensemble"])
    _write("E7", {"comparison": e7, "summary": e7_summ, "description": DERIVED["E7"]})
    log_mlflow("E7", DERIVED["E7"], e7, e7_summ, {"members": "logreg,xgb"})
    print(f"reference + E1 + E7 done in {time.time() - t0:.0f}s")


def run_feature_experiment(name: str) -> None:
    t0 = time.time()
    cfg = FEATURE_EXPERIMENTS[name]
    ref = {"targets": _read("reference")["months"]["targets"]}
    res = run_experiment(cfg)
    rs = summary(ref, list(LEARNERS))
    cmp = compare(ref, res, {t: reference_learner(rs, t) for t in res["targets"]})
    summ = summary(res, list(LEARNERS))
    _write(name, {"comparison": cmp, "summary": summ, "description": cfg["desc"], "features": res["features"],
                  "n_features_per_fold": {t: [res["targets"][t]["months"][m]["n_features"] for m in pr.P()["months"]]
                                          for t in res["targets"]}, "seconds": time.time() - t0})
    log_mlflow(name, cfg["desc"], cmp, summ, {"n_features": res["n_features"], **{k: str(v) for k, v in cfg.items() if k != "desc"}})
    print(f"{name} done in {time.time() - t0:.0f}s")


IDEAS = ("E1", "E2", "E3", "E4", "E5", "E6", "E7")


def kept_ideas() -> dict[str, list[str]]:
    out = {t: [] for t in pr.P()["targets"]}
    for e in IDEAS:
        if (OUT / f"{e}.json").exists():
            for t, c in _read(e)["comparison"].items():
                if c["decision"] == "KEPT":
                    out[t].append(e)
    return out


def config_for(ideas: list[str]) -> dict:
    cfg = {"extra": [k for e, k in (("E2", "long"), ("E5", "spectral"), ("E6", "goes")) if e in ideas]}
    if "E3" in ideas:
        cfg["drift"] = True
    if "E4" in ideas:
        cfg["prune"] = True
    return cfg


def model_key(base: str, ideas: list[str]) -> str:
    return ("ensemble" if "E7" in ideas else base) + ("_rolling" if "E1" in ideas else "")


def _val_block_masks(index: pd.DatetimeIndex) -> tuple[dict, pd.Timestamp, pd.Timestamp]:
    """The original split: fit on tune before 2025-12-01 (minus purge), thresholds Dec-Jan, score the val period."""
    purge = pd.Timedelta(minutes=pr.P()["purge_min"])
    split = pd.Timestamp(config.load_params()["models"]["inner_split"], tz="UTC")
    v0, v1 = config.period_bounds("val")
    mk = {"fit": np.asarray(index < split - purge), "cal": np.asarray((index >= split) & (index < v0 - purge)),
          "score": np.asarray((index >= v0) & (index < v1))}
    return mk, split, v0


def _block_scores(f: dict, model: str, cal_start: pd.Timestamp) -> dict:
    """TSS at A (all, quiet) with a 95 % day-bootstrap interval for one model on the validation block."""
    from src.models import metrics

    rolling = model.endswith("_rolling")
    base = model.removesuffix("_rolling")
    c, s = f["in_cal"], ~f["in_cal"]
    y, q, sc, t = f["y"], f["quiet"], f["scores"][base], f["times"]
    if rolling:
        yhat = pr.rolling_yhat(t, y, sc, t[s], sc[s], cal_start)
    else:
        yhat = sc[s] >= pr.thr_max_tss(y[c], sc[c])
    days = pd.DatetimeIndex(sorted(t[s].floor("D").unique()))
    codes = days.get_indexer(t[s].floor("D"))
    bs = config.load_params()["models"]["bootstrap"]
    idx = metrics.bootstrap_indices(len(days), bs["n"], bs["seed"])
    out = {}
    for name, mask in (("all", np.ones(s.sum(), bool)), ("quiet", q[s])):
        dc = metrics.daily_counts(y[s][mask], yhat[mask], codes[mask], len(days))
        lo, hi = metrics.bootstrap_mean_tss([dc], idx, bs["level"])
        out[name] = pr.score_block(y[s][mask], yhat[mask]) | {"ci_low": lo, "ci_high": hi}
    return out


def run_final() -> None:
    t0 = time.time()
    p = pr.P()
    ref = {"targets": _read("reference")["months"]["targets"]}
    rs = summary(ref, list(LEARNERS))
    kept = kept_ideas()
    xgbp = xgb_params()
    final = {"targets": {}}
    val_block = {}
    frames: dict = {}
    for t in p["targets"]:
        ideas = kept[t]
        cfg = config_for(ideas)
        key = json.dumps(cfg, sort_keys=True)
        if key not in frames:
            frames[key] = load_frame(cfg)
        df, feats = frames[key]
        rolling = "E1" in ideas

        def one(m):
            mk = pr.fold_masks(df.index, m, p["purge_min"])
            b = pr.fold_bounds(m, p["purge_min"])
            return m, evaluate_fold(run_fold(df, feats, t, mk, b["score_start"], cfg, xgbp), b["cal_start"], rolling)

        months = dict(Parallel(n_jobs=4, prefer="threads")(delayed(one)(m) for m in p["months"]))
        final["targets"][t] = {"months": {m: months[m] for m in p["months"]}}
        # the original validation block, for comparison with the numbers reported so far
        base = reference_learner(rs, t)
        rkey = json.dumps({"extra": []}, sort_keys=True)
        if rkey not in frames:
            frames[rkey] = load_frame({"extra": []})
        dref, fref = frames[rkey]
        mk, split, v0 = _val_block_masks(dref.index)
        f_ref = run_fold(dref, fref, t, mk, v0, {}, xgbp)
        mk2, _, _ = _val_block_masks(df.index)
        f_fin = run_fold(df, feats, t, mk2, v0, cfg, xgbp)
        val_block[t] = {"ideas": ideas, "reference_model": base, "final_model": model_key(base, ideas),
                        "reference": _block_scores(f_ref, base, split),
                        "final": _block_scores(f_fin, model_key(base, ideas), split)}
        print(f"  final {t:6s} ideas={ideas} {time.time() - t0:5.0f}s", flush=True)
    cmp = compare(ref, final, {t: model_key(reference_learner(rs, t), kept[t]) for t in p["targets"]})
    for t in cmp:
        cmp[t]["ideas"] = kept[t]
    summ = summary(final, sorted({c["model"] for c in cmp.values()} & {"logreg", "xgb", "ensemble"}) or list(LEARNERS))
    _write("final", {"kept_ideas": kept, "comparison": cmp, "validation_block": val_block, "seconds": time.time() - t0})
    log_mlflow("final", "final candidate: only the KEPT ideas, per target", cmp, summ,
               {f"ideas_{t}": ",".join(v) or "none" for t, v in kept.items()})
    print(f"final done in {time.time() - t0:.0f}s")


def table_markdown() -> str:
    """Experiment x target table for docs/IMPROVEMENTS.md (all numbers from reports/improve/*.json)."""
    p = pr.P()
    ref = _read("reference")["summary"]
    lines = ["| Experiment | " + " | ".join(p["targets"]) + " |", "|---|" + "---|" * len(p["targets"])]
    row = ["**Reference** (best learner)"]
    for t in p["targets"]:
        rl = max(LEARNERS, key=lambda k: ref[t][k]["all_mean"])
        row.append(f"{ref[t][rl]['all_mean']:.3f} ± {ref[t][rl]['all_std']:.3f} ({'LogReg' if rl == 'logreg' else 'XGB'})")
    lines.append("| " + " | ".join(row) + " |")
    for e in IDEAS + ("final",):
        if not (OUT / f"{e}.json").exists():
            continue
        cmp = _read(e)["comparison"]
        cells = []
        for t in p["targets"]:
            c = cmp[t]
            tag = "**KEPT**" if c["decision"] == "KEPT" else "dropped"
            if e == "final":
                tag = "final"
            cells.append(f"{c['exp_mean']:.3f} ± {c['exp_std']:.3f}, {c['months_improved']}/{len(p['months'])}, {tag}")
        lines.append(f"| {e} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    arg = sys.argv[1]
    if arg == "reference":
        run_reference()
    elif arg in FEATURE_EXPERIMENTS:
        run_feature_experiment(arg)
    elif arg == "final":
        run_final()
    elif arg == "table":
        print(table_markdown())
    elif arg == "all":
        run_reference()
        for e in FEATURE_EXPERIMENTS:
            run_feature_experiment(e)
        run_final()
    else:
        raise SystemExit(f"unknown experiment {arg}")
