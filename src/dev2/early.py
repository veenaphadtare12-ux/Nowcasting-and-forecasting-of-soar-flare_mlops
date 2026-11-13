"""R1: early flare-class prediction, anchored on the causal detector TRIGGER (never the backdated onset).

Population: every real detector trigger (catalogue segment 0 of each detection, `trigger_time` = the moment the
detector first knew), including false triggers (no GOES flare). At trigger + k minutes (k = 0, 1, 2, 3, 5) the
features use only data labelled at or before that moment:
    rise rate (1 and 3 min, log flux), curvature (second difference), current flux and excess over the background
    frozen at the trigger, peak so far, rise steps at the trigger, spectral ratio (temperature proxy) and its 3-min
    slope, high-band rate, hard X-rays (HEL1OS) when present. Non-Aditya variant: + GOES XRS-B level and 3-min slope.
Targets per trigger, from the GOES flares paired with the detection's first segment (largest class; none = false
trigger):  (a) y_m = reaches >= M;  (b) peak class in {<C, C, >=M}, decided ordinally by the >=M and >=C models.
Evaluation: rolling monthly by trigger month (fit on detections whose end was known before month m-1, threshold
= max TSS on month m-1, score month m). Per-trigger TSS / precision / recall, pooled and per month.
Lead time = (end of the first GOES-19 XRS-B 1-min average >= 1e-5 W/m^2) - (our alert time), for true >= M triggers
that are alerted; false alarms are counted as such and have no lead time. Baseline: current flux level only.
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np
import pandas as pd

from src import config, goes
from src.detection.matching import goes_flux
from src.dev2 import protocol as pr
from src.final import features as ff
from src.models import train

KS = (0, 1, 2, 3, 5)
LOG_FLOOR = 0.1
HX = ["hel1os_available", "hx_cdte_lo_log_mean_1m", "hx_cdte_hi_log_mean_1m", "hx_czt_lo_log_mean_1m",
      "hx_hr_cdte", "hx_cdte_lo_ratio_bg"]
ADITYA = ["f_log_m", "f_excess", "f_ratio", "f_bg", "f_rise1", "f_rise3", "f_curv", "f_peak_so_far", "f_rise_steps",
          "f_sp_ratio", "f_sp_slope3", "f_sp_high"] + HX
GOESF = ["f_gx_b", "f_gx_slope3"]
OUT = config.PROJECT_ROOT / "reports" / "dev2"


# ---------------------------------------------------------------- population and labels
def detections(events: pd.DataFrame, pairs: pd.DataFrame, glist: pd.DataFrame) -> pd.DataFrame:
    """One row per real trigger with its labels. events/pairs/glist: catalogue, (event, goes) pairs, GOES list."""
    first = events[events["segment"] == 0].copy()     # index = catalogue row number, as used in `pairs`
    flux = glist["goes_class"].astype(str).map(goes_flux)
    if len(pairs):
        pf = pairs.assign(flux=flux.loc[pairs["goes"]].to_numpy()).groupby("event")["flux"].max()
    else:
        pf = pd.Series(dtype=float)
    first["peak_flux"] = pf.reindex(first.index).fillna(0.0).to_numpy()
    first["y_c"] = first["peak_flux"] >= goes_flux("C1.0")
    first["y_m"] = first["peak_flux"] >= goes_flux("M1.0")
    first["cls3"] = first["y_c"].astype(int) + first["y_m"].astype(int)
    return first[["trigger_time", "end_known_time", "end", "bg_counts_s", "rise_steps", "peak_flux", "y_c", "y_m", "cls3"]]


def _at(series: pd.Series, times: pd.DatetimeIndex, tol_min: int = 3) -> np.ndarray:
    """Last value labelled at or before each time (within tol), NaN otherwise."""
    s = series.dropna().sort_index()
    left = pd.DataFrame({"t": pd.DatetimeIndex(times).as_unit("ns")})
    right = pd.DataFrame({"t": s.index.as_unit("ns"), "v": s.to_numpy()})
    return pd.merge_asof(left, right, on="t", direction="backward", tolerance=pd.Timedelta(minutes=tol_min))["v"].to_numpy()


def features(det: pd.DataFrame, k: int, minute: pd.Series, spectral: pd.DataFrame, rows: pd.DataFrame | None,
             gx: pd.DataFrame | None) -> pd.DataFrame:
    """Features at trigger + k min for every detection. All inputs are labelled at the moment they are known."""
    tau = pd.DatetimeIndex(det["trigger_time"]) + pd.Timedelta(minutes=k)
    lm = np.log10(minute.clip(lower=LOG_FLOOR))
    l0, l1, l2, l3 = (_at(lm, tau - pd.Timedelta(minutes=j)) for j in (0, 1, 2, 3))
    bg = det["bg_counts_s"].to_numpy(float)
    m0 = 10 ** l0
    out = pd.DataFrame(index=det.index)
    out["f_log_m"] = l0
    out["f_excess"] = np.log10(np.maximum(m0 - bg, LOG_FLOOR))
    out["f_ratio"] = np.log10(np.maximum(m0 / np.maximum(bg, LOG_FLOOR), 1e-3))
    out["f_bg"] = np.log10(np.maximum(bg, LOG_FLOOR))
    out["f_rise1"] = l0 - l1
    out["f_rise3"] = (l0 - l3) / 3
    out["f_curv"] = l0 - 2 * l1 + l2
    pk = np.full(len(det), np.nan)
    for j in range(0, k + 1):          # max over trigger .. trigger + k (all labelled <= tau)
        pk = np.fmax(pk, _at(lm, tau - pd.Timedelta(minutes=j)))
    out["f_peak_so_far"] = pk - out["f_bg"].to_numpy()
    out["f_rise_steps"] = det["rise_steps"].to_numpy(float)
    sr = np.log10((spectral["high"] / spectral["low"].where(spectral["low"] > 0)).clip(lower=1e-6))
    s0, s3 = _at(sr, tau), _at(sr, tau - pd.Timedelta(minutes=3))
    out["f_sp_ratio"], out["f_sp_slope3"] = s0, (s0 - s3) / 3
    out["f_sp_high"] = _at(np.log10(spectral["high"].clip(lower=LOG_FLOOR)), tau)
    for c in HX:
        out[c] = _at(rows[c], tau, tol_min=1) if rows is not None and c in rows else np.nan
    if gx is not None:
        lb = np.log10(gx["xrsb"].where(gx["xrsb"] > 0))
        g0, g3 = _at(lb, tau), _at(lb, tau - pd.Timedelta(minutes=3))
        out["f_gx_b"], out["f_gx_slope3"] = g0, (g0 - g3) / 3
    return out


def first_m1_time(det: pd.DataFrame, gx: pd.DataFrame, m1: float) -> np.ndarray:
    """End of the first GOES XRS-B 1-min average >= m1 in [trigger - 60 min, end + 60 min] (NaT if none)."""
    b = gx["xrsb"].dropna()
    hit = b.index[b.to_numpy() >= m1].as_unit("ns").asi8.view("datetime64[ns]")
    out = np.full(len(det), np.datetime64("NaT"), dtype="datetime64[ns]")
    t0 = (pd.DatetimeIndex(det["trigger_time"]) - pd.Timedelta(minutes=60)).as_unit("ns").asi8.view("datetime64[ns]")
    t1 = (pd.DatetimeIndex(det["end"]) + pd.Timedelta(minutes=60)).as_unit("ns").asi8.view("datetime64[ns]")
    i = np.searchsorted(hit, t0, "left")
    ok = i < len(hit)
    j = np.where(ok, i, 0)
    good = ok & (hit[j] <= t1)
    out[good] = hit[j[good]]
    return out


# ---------------------------------------------------------------- models
def make(kind: str, y: np.ndarray, seed: int):
    if kind == "logreg":
        return train.make_logreg(config.load_params()["models"]["logreg"], seed)
    from xgboost import XGBClassifier

    return XGBClassifier(n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                         min_child_weight=5, eval_metric="aucpr", tree_method="hist", random_state=seed, n_jobs=4,
                         scale_pos_weight=train._pos_weight(y))


def fit_scores(kind, Xf, yf, Xs, seed) -> np.ndarray:
    if yf.sum() == 0:
        return np.zeros(len(Xs))
    return make(kind, yf, seed).fit(Xf, yf).predict_proba(Xs)[:, 1]


def cls_decision(s_c, s_m, thr_c, thr_m) -> np.ndarray:
    return np.where(s_m >= thr_m, 2, np.where(s_c >= thr_c, 1, 0))


def prf(c) -> dict:
    tp, fp, fn, _ = c
    return {"tss": pr.tss_of(c), "precision": tp / max(tp + fp, 1), "recall": tp / max(tp + fn, 1),
            "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(c[3])}


# ---------------------------------------------------------------- development data
def dev_inputs() -> dict:
    proc = config.processed_dir()
    hi = pr.dev_end()
    ev = pd.read_parquet(proc / "events.parquet")
    ev = ev[ev["end_known_time"] < hi]
    glist = pd.read_parquet(proc / "goes_matched.parquet")
    pairs = pd.read_parquet(proc / "events_pairs.parquet")
    det = detections(ev, pairs[pairs["event"].isin(ev.index)], glist)
    gaps = {d.normalize() for d in goes.missing_days(config.period_bounds("tune")[0], hi)}
    det = det[~pd.DatetimeIndex(det["trigger_time"]).normalize().isin(gaps)]
    minute = pd.read_parquet(proc / "solexs_minute.parquet")["m"]
    minute = minute[minute.index < hi]
    spectral = ff._source("spectral", include_test=True)
    gx = ff._source("goes", include_test=True)
    rows = pr.load(HX)
    return {"det": det, "minute": minute, "spectral": spectral[spectral.index < hi], "gx": gx[gx.index < hi], "rows": rows}


def rolling(det: pd.DataFrame, X: pd.DataFrame, cols: list[str], learners, t_m1: np.ndarray, k: int, active) -> dict:
    p = pr.P()
    trig = pd.DatetimeIndex(det["trigger_time"])
    tau = trig + pd.Timedelta(minutes=k)
    known = pd.DatetimeIndex(det["end_known_time"])
    res = {}
    for m in p["months"]:
        b = pr.fold_bounds(m, p["purge_min"])
        fit = np.asarray(known < b["fit_end"])
        cal = np.asarray((trig >= b["cal_start"]) & (trig < b["cal_end"]))
        sc = np.asarray((trig >= b["score_start"]) & (trig < b["score_end"]))
        out = {"n_score": int(sc.sum()), "m_score": int(det["y_m"][sc].sum()), "c_score": int(det["y_c"][sc].sum())}
        for kind in list(learners) + ["flux"]:
            s = {}
            for tgt in ("y_c", "y_m"):
                y = det[tgt].to_numpy()
                if kind == "flux":
                    s[tgt] = X["f_log_m"].fillna(-9).to_numpy()
                else:
                    s[tgt] = np.full(len(det), np.nan)
                    idx = cal | sc
                    s[tgt][idx] = fit_scores(kind, X.loc[fit, cols], y[fit].astype(int), X.loc[idx, cols], p["seed"])
            th = {tgt: pr.thr_max_tss(det[tgt].to_numpy()[cal], s[tgt][cal]) for tgt in s}
            ym, yc = det["y_m"].to_numpy(), det["y_c"].to_numpy()
            am = s["y_m"][sc] >= th["y_m"]
            pred = cls_decision(s["y_c"][sc], s["y_m"][sc], th["y_c"], th["y_m"])
            lead = (t_m1[sc] - tau[sc].as_unit("ns").asi8.view("datetime64[ns]")) / np.timedelta64(1, "m")
            lead_tp = lead[ym[sc] & am & ~np.isnan(lead)]
            out[kind] = {"thr_m": th["y_m"], "thr_c": th["y_c"],
                         "m": pr.counts(ym[sc], am), "c": pr.counts(yc[sc], s["y_c"][sc] >= th["y_c"]),
                         "m_active": pr.counts(ym[sc][active[sc]], am[active[sc]]),
                         "m_quietday": pr.counts(ym[sc][~active[sc]], am[~active[sc]]),
                         "cls_confusion": pd.crosstab(det["cls3"].to_numpy()[sc], pred).reindex(index=[0, 1, 2], columns=[0, 1, 2], fill_value=0).to_numpy().tolist(),
                         "lead_tp_min": [round(float(v), 1) for v in lead_tp]}
        res[m] = out
    return res


def summarise(res: dict, kind: str) -> dict:
    ms = [m for m in res]
    mt = np.array([pr.tss_of(res[m][kind]["m"]) for m in ms])
    w = int(np.argmin(mt))
    leads = np.array([v for m in ms for v in res[m][kind]["lead_tp_min"]])
    conf = np.sum([res[m][kind]["cls_confusion"] for m in ms], axis=0)
    per_cls = {name: {"precision": float(conf[i, i] / max(conf[:, i].sum(), 1)), "recall": float(conf[i, i] / max(conf[i].sum(), 1))}
               for i, name in enumerate(("<C", "C", ">=M"))}
    return {"m_pooled": prf(pr.pooled([res[m][kind]["m"] for m in ms])),
            "m_mean_monthly_tss": float(mt.mean()), "m_worst_month": ms[w], "m_worst_month_tss": float(mt[w]),
            "m_active_days": prf(pr.pooled([res[m][kind]["m_active"] for m in ms])),
            "m_quiet_days": prf(pr.pooled([res[m][kind]["m_quietday"] for m in ms])),
            "c_pooled": prf(pr.pooled([res[m][kind]["c"] for m in ms])),
            "class_confusion": conf.tolist(), "class_scores": per_cls,
            "lead_n": int(len(leads)), "lead_median_min": float(np.median(leads)) if len(leads) else None,
            "lead_iqr_min": [float(np.quantile(leads, .25)), float(np.quantile(leads, .75))] if len(leads) else None,
            "lead_share_before_m1": float((leads > 0).mean()) if len(leads) else None,
            "monthly_m_tss": [round(float(v), 4) for v in mt]}


def run() -> dict:
    t0 = time.time()
    d = dev_inputs()
    det = d["det"].reset_index(drop=True)
    m1 = config.load_params()["final"]["lead_time"]["m1_flux"]
    t_m1 = first_m1_time(det, d["gx"], m1)
    active = pr.active_day_flags(pd.DatetimeIndex(det["trigger_time"]))
    out = {"description": __doc__.split("\n\n")[0], "n_triggers": int(len(det)), "n_m": int(det["y_m"].sum()),
           "n_c_or_more": int(det["y_c"].sum()), "n_false": int((det["peak_flux"] == 0).sum()),
           "m_with_goes19_m1_crossing": int((~np.isnat(t_m1) & det["y_m"].to_numpy()).sum()),
           "variants": {}}
    for k in KS:
        X = features(det, k, d["minute"], d["spectral"], d["rows"], d["gx"])
        for var, cols in (("aditya", ADITYA), ("with_goes", ADITYA + GOESF)):
            res = rolling(det, X, cols, ("logreg", "xgb"), t_m1, k, active)
            key = f"k{k}_{var}"
            out["variants"][key] = {"k": k, "inputs": var, "months": res,
                                    "summary": {kind: summarise(res, kind) for kind in ("logreg", "xgb", "flux")}}
            s = out["variants"][key]["summary"]
            print(f"  k={k} {var:9s} M: logreg TSS {s['logreg']['m_pooled']['tss']:.3f} (P {s['logreg']['m_pooled']['precision']:.2f}"
                  f" R {s['logreg']['m_pooled']['recall']:.2f}) xgb {s['xgb']['m_pooled']['tss']:.3f} flux {s['flux']['m_pooled']['tss']:.3f}"
                  f" | lead median {s['logreg']['lead_median_min']} min, {s['logreg']['lead_share_before_m1']}", flush=True)
    out["seconds"] = time.time() - t0
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "r1.json"
    if p.exists():
        p.unlink()
    p.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8", newline="\n")
    print(f"R1 done in {out['seconds']:.0f}s: {out['n_triggers']} triggers, {out['n_m']} reach >=M")
    return out


if __name__ == "__main__":
    {"run": run}[sys.argv[1]]()
