"""Development experiments, protocol 2 (14 rolling months, old test period = development data, holdout2 never read).

    python -m src.dev2.run ref      # base 44 features, LogReg/XGB/ensemble + baselines, 7 targets
    python -m src.dev2.run e6       # + GOES XRS flux (non-Aditya)
    python -m src.dev2.run r2a      # + Aditya-only context (own detector events 24/48/72 h)
    python -m src.dev2.run r2b      # + GOES flare counts + NOAA SRS on top of r2a (non-Aditya)
    python -m src.dev2.run champ    # the frozen FINAL_CHOICE.md feature sets, re-checked on 14 months
    python -m src.dev2.run table    # markdown table of every result

Results: reports/dev2/<name>.json (monthly contingency counts per model, summaries, comparisons); MLflow
experiment `flare-dev2`.
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from src import config, goes
from src import mlflow_utils as mu
from src.dev2 import context as cx
from src.dev2 import protocol as pr
from src.final import features as ff
from src.improve import features_extra as fx
from src.models import train

OUT = config.PROJECT_ROOT / "reports" / "dev2"
FLAG = train.FLAG
LEARNERS = ("logreg", "xgb")
GOES_BLOCKS = {"goes", "gc", "srs"}          # non-Aditya inputs
EXPERIMENTS = {
    "e6": {"blocks": ["goes"], "targets": "r2+m_30m", "desc": "+ GOES XRS 1-min flux (non-Aditya)", "vs": "ref"},
    "r2a": {"blocks": ["ax"], "targets": "r2", "desc": "R2 primary: own detector events in the past 24/48/72 h", "vs": "ref"},
    "r2b": {"blocks": ["ax", "gc", "srs"], "targets": "r2",
            "desc": "R2 secondary: + GOES flare counts (end + 24 h) + NOAA SRS (non-Aditya)", "vs": "r2a"},
}


# ---------------------------------------------------------------- data
def xgb_params() -> dict:
    mm = json.loads((config.PROJECT_ROOT / "reports" / "model_metrics.json").read_text(encoding="utf-8"))
    return {t: mm["targets"][t]["xgb_cv_best"] for t in mm["targets"]}


def label_cols(targets) -> list[str]:
    return sorted({c for t in targets for c in train.TARGETS[t]})


_BASE: dict = {}


def base_frame() -> pd.DataFrame:
    if "df" not in _BASE:
        P = config.load_params()
        cols = ff.base_features() + label_cols(pr.P()["targets"]) + [FLAG, P["models"]["rule_feature"]]
        df = pr.load(list(dict.fromkeys(cols)))
        df["_active_day"] = pr.active_day_flags(df.index)          # evaluation only, never a feature
        _BASE["df"] = df
    return _BASE["df"]


def add_blocks(df: pd.DataFrame, blocks: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Base frame + extra feature blocks. Every block is built only from data before pr.dev_end()."""
    feats = ff.base_features()
    lo, hi = df.index.min() - pd.Timedelta(days=4), pr.dev_end()
    ideas = [i for b, i in (("long", "E2"), ("spectral", "E5"), ("goes", "E6"), ("drift", "E3")) if b in blocks]
    if ideas:
        df, feats = ff.build(df, ideas, end=hi, include_test=True)
    proc = config.processed_dir()
    for b in ("ax", "gc", "srs"):
        if b not in blocks:
            continue
        if b == "ax":
            ev = pd.read_parquet(proc / "events.parquet", columns=["trigger_time", "end", "peak_counts_s", "hit_cap", "ended_by_gap"])
            g = cx.aditya_grid(ev[ev["trigger_time"] < hi], lo, hi)
        elif b == "gc":
            fl = goes.load_flare_list()
            g = cx.goes_count_grid(fl[fl["begin"] < hi], lo, hi)
        else:
            g = cx.srs_grid(sorted(cx.srs_dir().glob("*SRS.txt")), lo, hi)
        ex = fx.asof_rows(g.astype("float32"), df.index)
        df = pd.concat([df, ex], axis=1)
        feats = feats + list(ex.columns)
    return df, feats


# ---------------------------------------------------------------- folds
def fit_predict(kind: str, target: str, Xf, yf, Xs, xgbp, seed: int):
    mp = config.load_params()["models"]
    if kind == "logreg":
        est = train.make_logreg(mp["logreg"], seed)
    else:
        est = train.make_xgb(mp["xgb"], xgbp[target], seed, train._pos_weight(yf))
        est.set_params(n_jobs=3)
    est.fit(Xf, yf)
    return est.predict_proba(Xs)[:, 1].astype("float32")


def run_fold(df, feats, target, m, learners, xgbp, baselines: bool) -> dict:
    p = pr.P()
    rule = config.load_params()["models"]["rule_feature"]
    y_col, ok_col = train.TARGETS[target]
    mk = pr.fold_masks(df.index, m, p["purge_min"])
    b = pr.fold_bounds(m, p["purge_min"])
    ok = df[ok_col].to_numpy().astype(bool)
    fit = df[mk["fit"] & ok].iloc[::p["train_stride"]]
    cs = df[(mk["cal"] | mk["score"]) & ok]
    c = np.asarray(cs.index < b["score_start"])
    s = ~c
    yf = fit[y_col].to_numpy().astype(int)
    scores = {k: fit_predict(k, target, fit[feats], yf, cs[feats], xgbp, p["seed"]) for k in learners}
    if "logreg" in scores and "xgb" in scores:
        scores["ensemble"] = (scores["logreg"] + scores["xgb"]) / 2
    if baselines:
        scores["rule"] = cs[rule].fillna(0).to_numpy().astype("float32")
        scores["flux"] = cs["log_rate"].fillna(-9).to_numpy().astype("float32")    # current flux level
    y = cs[y_col].to_numpy().astype(bool)
    q = cs[FLAG].to_numpy() == 0
    a = cs["_active_day"].to_numpy().astype(bool)
    out = {k: pr.evaluate_scores(y[c], v[c], y[s], v[s], q[s], a[s]) for k, v in scores.items()}
    if baselines:
        pers = cs[FLAG].to_numpy().astype("float32")
        out["persistence"] = pr.evaluate_scores(y[c], pers[c], y[s], pers[s], q[s], a[s], fixed=0.5)
    out["_n"] = {"fit": int(len(fit)), "fit_pos": int(yf.sum()), "cal": int(c.sum()), "cal_pos": int(y[c].sum()),
                 "score": int(s.sum()), "score_pos": int(y[s].sum())}
    return out


def run_targets(df, feats, targets, learners_for, baselines=False) -> dict:
    xgbp = xgb_params()
    res = {}
    for t in targets:
        t0 = time.time()
        L = learners_for(t)
        months = dict(Parallel(n_jobs=4, prefer="threads")(
            delayed(lambda m: (m, run_fold(df, feats, t, m, L, xgbp, baselines)))(m) for m in pr.P()["months"]))
        res[t] = {m: months[m] for m in pr.P()["months"]}
        print(f"  {t:7s} {time.time() - t0:5.0f}s", flush=True)
    return res


# ---------------------------------------------------------------- I/O
def write(name: str, obj: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{name}.json"
    if p.exists():
        p.chmod(0o666)
        p.unlink()
    p.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8", newline="\n")


def read(name: str) -> dict:
    return json.loads((OUT / f"{name}.json").read_text(encoding="utf-8"))


def best_learner(ref: dict, t: str) -> str:
    return max(LEARNERS, key=lambda k: ref["summary"][t][k]["mean_monthly_tss"])


def targets_for(spec: str) -> list[str]:
    p = pr.P()
    return {"all": p["targets"], "r2": p["r2_targets"], "r2+m_30m": p["r2_targets"] + ["m_30m"]}[spec]


def log_mlflow(name: str, desc: str, summ: dict, cmp: dict | None, params: dict) -> None:
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow

    mlflow.set_tracking_uri(config.mlflow_uri())
    mlflow.set_experiment("flare-dev2")
    with mlflow.start_run(run_name=name):
        mlflow.set_tags(mu.run_tags() | {"experiment": name, "description": desc, "seed": str(pr.P()["seed"]),
                                         "protocol": "rolling monthly 2025-08..2026-09 (dev incl. old test); holdout2 locked"})
        mlflow.log_params(params)
        for t, s in summ.items():
            for mdl, v in s.items():
                mlflow.log_metrics({f"{t}.{mdl}.mean_tss": v["mean_monthly_tss"], f"{t}.{mdl}.pooled_tss": v["pooled_tss"],
                                    f"{t}.{mdl}.worst_tss": v["worst_month_tss"], f"{t}.{mdl}.active_tss": v["active_days_tss"],
                                    f"{t}.{mdl}.quietday_tss": v["quiet_days_tss"]})
        if cmp:
            for t, c in cmp.items():
                mlflow.log_metrics({f"{t}.delta_mean": c["delta_mean"], f"{t}.months_better": c["months_better"],
                                    f"{t}.kept": float(c["decision"] == "KEPT")})
        mlflow.log_dict({"summary": summ, "comparison": cmp}, f"{name}.json")


def summarise_all(res: dict) -> dict:
    return {t: {mdl: pr.summarise(res[t], mdl) for mdl in res[t][pr.P()["months"][0]] if not mdl.startswith("_")}
            for t in res}


# ---------------------------------------------------------------- experiments
def run_ref() -> None:
    t0 = time.time()
    df = base_frame()
    feats = ff.base_features()
    res = run_targets(df, feats, pr.P()["targets"], lambda t: LEARNERS, baselines=True)
    summ = summarise_all(res)
    write("ref", {"description": "base 44 features (Aditya only), rolling 14 months", "n_features": len(feats),
                  "summary": summ, "months": res, "seconds": time.time() - t0})
    log_mlflow("ref", "base 44 features", summ, None, {"n_features": len(feats)})
    print(f"ref done in {time.time() - t0:.0f}s")


def run_feature(name: str) -> None:
    t0 = time.time()
    spec = EXPERIMENTS[name]
    ref = read("ref")
    df, feats = add_blocks(base_frame(), spec["blocks"])
    targets = targets_for(spec["targets"])
    res = run_targets(df, feats, targets, lambda t: (best_learner(ref, t),))
    summ = summarise_all(res)
    cmp = {t: pr.compare(ref["months"][t], best_learner(ref, t), res[t], best_learner(ref, t)) for t in targets}
    if spec["vs"] != "ref":
        base = read(spec["vs"])
        cmp_vs = {t: pr.compare(base["months"][t], best_learner(ref, t), res[t], best_learner(ref, t)) for t in targets}
    else:
        cmp_vs = None
    write(name, {"description": spec["desc"], "blocks": spec["blocks"], "aditya_only": not (GOES_BLOCKS & set(spec["blocks"])),
                 "features": feats, "summary": summ, "comparison_vs_ref": cmp, f"comparison_vs_{spec['vs']}": cmp_vs,
                 "months": res, "seconds": time.time() - t0})
    log_mlflow(name, spec["desc"], summ, cmp, {"blocks": ",".join(spec["blocks"]), "n_features": len(feats)})
    print(f"{name} done in {time.time() - t0:.0f}s")
    for t in targets:
        c = cmp[t]
        print(f"   {t}: {c['ref_mean']:.3f} -> {c['exp_mean']:.3f} ({c['months_better']}/{c['months']}) {c['decision']}"
              + (f" | vs {spec['vs']}: {cmp_vs[t]['delta_mean']:+.3f} ({cmp_vs[t]['months_better']}) {cmp_vs[t]['decision']}" if cmp_vs else ""))


CHAMP = {   # docs/FINAL_CHOICE.md feature sets, plus the Aditya-only variant of m_30m (E5 without E6)
    "c_30m": {"blocks": ["long", "drift", "spectral"], "model": "ensemble"},
    "m_30m": {"blocks": ["spectral", "goes"], "model": "logreg"},
    "m_30m_aditya": {"blocks": ["spectral"], "model": "logreg", "target": "m_30m"},
}


def run_champ() -> None:
    t0 = time.time()
    ref = read("ref")
    res, cmp, summ = {}, {}, {}
    for key, s in CHAMP.items():
        t = s.get("target", key)
        df, feats = add_blocks(base_frame(), s["blocks"])
        learners = LEARNERS if s["model"] == "ensemble" else (s["model"],)
        r = run_targets(df, feats, [t], lambda _: learners)[t]
        res[key] = r
        summ[key] = {s["model"]: pr.summarise(r, s["model"])}
        cmp[key] = pr.compare(ref["months"][t], best_learner(ref, t), r, s["model"])
        print(f"   {key}: {cmp[key]['ref_mean']:.3f} -> {cmp[key]['exp_mean']:.3f} ({cmp[key]['months_better']}) {cmp[key]['decision']}")
    write("champ", {"description": "FINAL_CHOICE.md feature sets re-checked on 14 months", "spec": CHAMP,
                    "summary": summ, "comparison_vs_ref": cmp, "months": res, "seconds": time.time() - t0})
    log_mlflow("champ", "FINAL_CHOICE.md feature sets", summ, cmp, {"configs": ",".join(CHAMP)})
    print(f"champ done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    arg = sys.argv[1]
    if arg == "ref":
        run_ref()
    elif arg in EXPERIMENTS:
        run_feature(arg)
    elif arg == "champ":
        run_champ()
    else:
        raise SystemExit(f"unknown {arg}")
