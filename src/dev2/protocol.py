"""Development protocol 2: rolling monthly evaluation over every development month (2025-08 .. 2026-09).

Same fold logic as src/improve/protocol.py (fit before month m-1 minus purge, thresholds on month m-1 minus purge,
score month m) and the same acceptance rule (docs/IMPROVEMENTS.md), now over 14 months. The old test period
(2026-06-01 .. 2026-09-12) is ordinary development data here; nothing after it is ever read (holdout2 is locked).

Every result reports, at operating point A (max TSS on the threshold month):
  mean of monthly TSS (+ std), worst month, pooled TSS (contingency summed over all scored months),
  TSS on quiet-start rows, and TSS on active vs quiet days.
Active day = a GOES >= M flare ended in the 72 h before the day starts. It is an EVALUATION split only and never a
model input. R4 operating points (cost-based, FAR-capped) are chosen on the same threshold month.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import config, goes
from src.improve import protocol as pr0
from src.models import metrics

DEV_PERIODS = ("tune", "val", "test")


def P() -> dict:
    return config.load_params()["dev2"]


def dev_end() -> pd.Timestamp:
    """End (exclusive) of the development data: the day after the old test period."""
    return config.period_bounds("test")[1]


def load(columns: list[str] | None = None) -> pd.DataFrame:
    """All development rows (tune + val + old test). Nothing at or after dev_end() exists in these files."""
    parts = [pd.read_parquet(config.processed_dir() / "dataset" / f"{p}.parquet", columns=columns) for p in DEV_PERIODS]
    d = pd.concat(parts).sort_index()
    assert d.index.max() < dev_end(), "rows after the development period found"
    return d


fold_bounds = pr0.fold_bounds
fold_masks = pr0.fold_masks
thr_max_tss = pr0.thr_max_tss
thr_far_cap = pr0.thr_far_cap


def thr_cost(y, s, cost_fn_fp: float) -> float:
    """Threshold minimising FP + cost_fn_fp * FN on the threshold block (inf = never alert, if that is cheapest)."""
    y = np.asarray(y).astype(bool)
    if not y.any():
        return np.inf
    o = np.argsort(-s, kind="mergesort")
    ss, yy = s[o], y[o]
    tp, fp = np.cumsum(yy), np.cumsum(~yy)
    last = np.r_[ss[1:] != ss[:-1], True]
    cost = fp + cost_fn_fp * (y.sum() - tp)
    cost = np.where(last, cost, np.inf)
    i = int(np.argmin(cost))
    return float(ss[i]) if cost[i] < cost_fn_fp * y.sum() else np.inf


# ---------------------------------------------------------------- active / quiet days (evaluation only)
def goes_flares() -> pd.DataFrame:
    g = goes.load_flare_list()
    return g[g["begin"] < dev_end()]


def active_day_flags(times: pd.DatetimeIndex, flares: pd.DataFrame | None = None) -> np.ndarray:
    """True where the row's UTC day is active: a GOES >= M flare ended in [day start - 72 h, day start)."""
    g = goes_flares() if flares is None else flares
    m = g[g["class_letter"].isin(["M", "X"])]
    end = m["end"].fillna(m["peak"]).fillna(m["begin"]).sort_values().to_numpy(dtype="datetime64[ns]")
    day = pd.DatetimeIndex(times).floor("D")
    ud = pd.DatetimeIndex(day.unique())
    D = ud.as_unit("ns").asi8.view("datetime64[ns]")
    W = np.timedelta64(P()["active_lookback_h"] * 3600, "s")
    n = np.searchsorted(end, D, "left") - np.searchsorted(end, D - W, "left")
    act = pd.Series(n > 0, index=ud)
    return act.reindex(day).to_numpy()


# ---------------------------------------------------------------- one fold
def counts(y, yhat) -> list[int]:
    c = metrics.contingency(y, yhat)
    return [c["tp"], c["fp"], c["fn"], c["tn"]]


def tss_of(c) -> float:
    return float(metrics.tss(dict(zip(("tp", "fp", "fn", "tn"), c))))


def evaluate_scores(y_cal, s_cal, y_sc, s_sc, quiet_sc, active_sc, fixed: float | None = None) -> dict:
    """Contingency counts on the scored month at A (all / quiet-start / active days / quiet days) and the R4 points."""
    p = P()
    out = {}
    thr = fixed if fixed is not None else thr_max_tss(y_cal, s_cal)
    a = s_sc >= thr
    out["thr_A"] = float(thr)
    out["A_all"] = counts(y_sc, a)
    out["A_quietstart"] = counts(y_sc[quiet_sc], a[quiet_sc])
    out["A_active"] = counts(y_sc[active_sc], a[active_sc])
    out["A_quietday"] = counts(y_sc[~active_sc], a[~active_sc])
    if fixed is None:
        tc = thr_far_cap(y_cal, s_cal, p["far_cap"])
        out["thr_C"] = float(tc)
        out["C_all"] = counts(y_sc, s_sc >= tc)
        for r in [p["cost_fn_fp"]] + list(p["cost_sensitivity"]):
            tk = thr_cost(y_cal, s_cal, r)
            out[f"thr_K{r}"] = float(tk)
            out[f"K{r}_all"] = counts(y_sc, s_sc >= tk)
    return out


# ---------------------------------------------------------------- summaries
def pooled(cs: list[list[int]]) -> list[int]:
    return [int(x) for x in np.sum(np.asarray(cs), axis=0)]


def pod_far(c) -> dict:
    tp, fp, fn, _ = c
    return {"pod": tp / max(tp + fn, 1), "far": fp / max(tp + fp, 1)}


def summarise(months: dict, model: str) -> dict:
    """months: month -> {model -> evaluate_scores output}."""
    ms = list(months)
    mt = np.array([tss_of(months[m][model]["A_all"]) for m in ms])
    q = np.array([tss_of(months[m][model]["A_quietstart"]) for m in ms])
    w = int(np.argmin(mt))
    out = {"mean_monthly_tss": float(mt.mean()), "std_monthly_tss": float(mt.std()),
           "worst_month": ms[w], "worst_month_tss": float(mt[w]),
           "pooled_tss": tss_of(pooled([months[m][model]["A_all"] for m in ms])),
           "pooled_quietstart_tss": tss_of(pooled([months[m][model]["A_quietstart"] for m in ms])),
           "mean_monthly_quietstart_tss": float(q.mean()),
           "active_days_tss": tss_of(pooled([months[m][model]["A_active"] for m in ms])),
           "quiet_days_tss": tss_of(pooled([months[m][model]["A_quietday"] for m in ms])),
           "active_days_positives": int(sum(months[m][model]["A_active"][0] + months[m][model]["A_active"][2] for m in ms)),
           "quiet_days_positives": int(sum(months[m][model]["A_quietday"][0] + months[m][model]["A_quietday"][2] for m in ms)),
           "monthly_tss": [round(float(v), 4) for v in mt]}
    if "C_all" in months[ms[0]][model]:
        for k in ["C"] + [f"K{r}" for r in [P()["cost_fn_fp"]] + list(P()["cost_sensitivity"])]:
            c = pooled([months[m][model][f"{k}_all"] for m in ms])
            out[f"{k}_pooled"] = {"tss": tss_of(c), **pod_far(c),
                                  "mean_monthly_tss": float(np.mean([tss_of(months[m][model][f"{k}_all"]) for m in ms]))}
    return out


def need_months() -> int:
    return int(np.ceil(P()["acceptance"]["min_share_months_improved"] * len(P()["months"]) - 1e-9))


def compare(ref_months: dict, ref_model: str, exp_months: dict, exp_model: str) -> dict:
    """Acceptance rule: mean monthly TSS up AND at least need_months() months strictly better."""
    ms = list(ref_months)
    r = np.array([tss_of(ref_months[m][ref_model]["A_all"]) for m in ms])
    e = np.array([tss_of(exp_months[m][exp_model]["A_all"]) for m in ms])
    better = int((e > r).sum())
    kept = bool(e.mean() > r.mean() and better >= need_months())
    rs, es = summarise(ref_months, ref_model), summarise(exp_months, exp_model)
    return {"ref_model": ref_model, "exp_model": exp_model, "ref_mean": float(r.mean()), "exp_mean": float(e.mean()),
            "delta_mean": float(e.mean() - r.mean()), "months_better": better, "months": len(ms),
            "need": need_months(), "decision": "KEPT" if kept else "DROPPED",
            "ref_pooled": rs["pooled_tss"], "exp_pooled": es["pooled_tss"],
            "ref_worst": rs["worst_month_tss"], "exp_worst": es["worst_month_tss"],
            "ref_active": rs["active_days_tss"], "exp_active": es["active_days_tss"],
            "ref_quietday": rs["quiet_days_tss"], "exp_quietday": es["quiet_days_tss"]}
