"""Rolling monthly evaluation over tune + val (never the test period).

For each month m in params `improve.months`:
    fit       = rows before the start of month m-1, minus a purge gap
    calibrate = rows of month m-1, minus a purge gap at its end      -> thresholds
    score     = rows of month m
No row of month m (and no label window that reaches into month m) is used to fit or to set thresholds for month m.

The adaptive-threshold variant (E1) refreshes the threshold every day d of month m from rows in
[max(d - rolling_days, start of m-1), d - purge): earlier days of month m whose labels are already resolved.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import config
from src.models import metrics

ALLOWED = ("tune", "val")


def P() -> dict:
    return config.load_params()["improve"]


def load(columns: list[str] | None = None) -> pd.DataFrame:
    """tune + val rows (the test file is never opened)."""
    parts = [pd.read_parquet(config.processed_dir() / "dataset" / f"{p}.parquet", columns=columns) for p in ALLOWED]
    d = pd.concat(parts).sort_index()
    end = config.period_bounds("val")[1]
    assert d.index.max() < end, "test-period rows found"
    return d


def month_start(m: str) -> pd.Timestamp:
    return pd.Timestamp(m + "-01", tz="UTC")


def fold_bounds(m: str, purge_min: int) -> dict[str, pd.Timestamp]:
    s_m = month_start(m)
    s_prev = s_m - pd.offsets.MonthBegin(1)
    purge = pd.Timedelta(minutes=purge_min)
    return {"fit_end": s_prev - purge, "cal_start": s_prev, "cal_end": s_m - purge,
            "score_start": s_m, "score_end": s_m + pd.offsets.MonthBegin(1)}


def fold_masks(index: pd.DatetimeIndex, m: str, purge_min: int) -> dict[str, np.ndarray]:
    b = fold_bounds(m, purge_min)
    return {"fit": np.asarray(index < b["fit_end"]),
            "cal": np.asarray((index >= b["cal_start"]) & (index < b["cal_end"])),
            "score": np.asarray((index >= b["score_start"]) & (index < b["score_end"]))}


def rolling_windows(score_index: pd.DatetimeIndex, cal_start: pd.Timestamp, days: int, purge_min: int):
    """For each scored day d: (day start, window start, window end) for its threshold. The window never starts before
    the threshold block (cal_start), so the model's own fit rows are never used to set a threshold."""
    out = []
    for d in pd.DatetimeIndex(sorted(score_index.floor("D").unique())):
        out.append((d, max(d - pd.Timedelta(days=days), cal_start), d - pd.Timedelta(minutes=purge_min)))
    return out


# ---------------------------------------------------------------- thresholds and scores
def thr_max_tss(y, s) -> float:
    if y.sum() == 0 or (~y.astype(bool)).sum() == 0:
        return np.inf
    return float(metrics.best_threshold(y, s, "tss")[0])


def thr_far_cap(y, s, cap: float) -> float:
    """Lowest threshold whose alerts have FAR <= cap (i.e. the highest POD allowed by the cap). inf if none."""
    y = np.asarray(y).astype(bool)
    o = np.argsort(-s, kind="mergesort")
    ss, yy = s[o], y[o]
    tp, fp = np.cumsum(yy), np.cumsum(~yy)
    last = np.r_[ss[1:] != ss[:-1], True]          # evaluate only at the end of each run of tied scores
    far = fp / np.maximum(tp + fp, 1)
    ok = last & (far <= cap) & (tp > 0)
    return float(ss[np.flatnonzero(ok)[-1]]) if ok.any() else np.inf


def score_block(y, yhat) -> dict:
    c = metrics.contingency(np.asarray(y).astype(bool), np.asarray(yhat).astype(bool))
    return {"tss": float(metrics.tss(c)), "pod": c["tp"] / max(c["tp"] + c["fn"], 1),
            "far": c["fp"] / max(c["tp"] + c["fp"], 1), "n": int(len(y)), "pos": int(np.sum(y)),
            "alerts": int(np.sum(yhat))}


def evaluate_month(y_cal, s_cal, y_sc, s_sc, quiet_sc, fixed_threshold: float | None = None) -> dict:
    """Operating point A (max TSS on calibration) on all and quiet-start rows; plus C (FAR cap) on all rows."""
    thr = fixed_threshold if fixed_threshold is not None else thr_max_tss(y_cal, s_cal)
    out = {"thr_A": thr, "A_all": score_block(y_sc, s_sc >= thr), "A_quiet": score_block(y_sc[quiet_sc], s_sc[quiet_sc] >= thr)}
    if fixed_threshold is None:
        thr_c = thr_far_cap(y_cal, s_cal, P()["far_cap"])
        out |= {"thr_C": thr_c, "C_all": score_block(y_sc, s_sc >= thr_c)}
    return out


def rolling_yhat(times_cs, y_cs, s_cs, times_sc, s_sc, cal_start: pd.Timestamp, far_cap: float | None = None):
    """Alerts for the scored rows with a threshold refreshed every day from the previous rolling_days days
    (rows in [max(d - days, cal_start), d - purge)). far_cap=None -> max TSS (A); else lowest thr with FAR <= cap (C)."""
    p = P()
    yhat = np.zeros(len(s_sc), bool)
    day_sc = times_sc.floor("D")
    for d, w0, w1 in rolling_windows(times_sc, cal_start, p["rolling_days"], p["purge_min"]):
        w = (times_cs >= w0) & (times_cs < w1)
        assert not np.any(times_cs[w] >= d), "rolling window reaches the scored day"
        thr = thr_max_tss(y_cs[w], s_cs[w]) if far_cap is None else thr_far_cap(y_cs[w], s_cs[w], far_cap)
        rows = np.asarray(day_sc == d)
        yhat[rows] = s_sc[rows] >= thr
    return yhat


def evaluate_month_rolling(times_cs, y_cs, s_cs, times_sc, y_sc, s_sc, quiet_sc, cal_start: pd.Timestamp) -> dict:
    """E1: daily-refreshed thresholds (operating points A and C) from the same fold model's scores."""
    yhat_a = rolling_yhat(times_cs, y_cs, s_cs, times_sc, s_sc, cal_start)
    yhat_c = rolling_yhat(times_cs, y_cs, s_cs, times_sc, s_sc, cal_start, P()["far_cap"])
    return {"A_all": score_block(y_sc, yhat_a), "A_quiet": score_block(y_sc[quiet_sc], yhat_a[quiet_sc]),
            "C_all": score_block(y_sc, yhat_c)}
