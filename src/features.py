"""Causal model features at 10-second cadence, built from 1 s SoLEXS counts (HEL1OS optional).

Every feature at time t uses only data in (-inf, t]:
* 10 s bins are right-closed and labelled at their END: the bin at t averages (t-10s, t].
* All windows are trailing `rolling(n)` on a continuous 10 s grid (gaps are NaN, never filled). No `center=True`,
  no negative shifts. tests/test_leakage.py enforces this by perturbing the future and checking nothing changes.
* No event-catalogue quantity (onset, peak, end, class, match) is ever a feature.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BG_WINDOW_MIN = 60
BG_QUANTILE = 0.2


def bin_counts(counts: pd.Series, cadence_s: int = 10) -> pd.DataFrame:
    """1 s counts (valid seconds only) -> continuous right-closed bins labelled at the bin end."""
    r = counts.resample(f"{cadence_s}s", label="right", closed="right")
    out = pd.DataFrame({"rate": r.mean(), "n": r.count()})
    grid = pd.date_range(out.index[0], out.index[-1], freq=f"{cadence_s}s")
    out = out.reindex(grid)
    out["n"] = out["n"].fillna(0)
    out.index.name = "time"
    return out


def solexs_features(binned: pd.DataFrame, windows_min: list[int], cadence_s: int = 10) -> pd.DataFrame:
    rate, n = binned["rate"], binned["n"]
    per_min = 60 // cadence_s
    f = pd.DataFrame(index=binned.index)
    f["rate"] = rate
    f["log_rate"] = np.log10(rate.clip(lower=0) + 1.0)
    tsec = pd.Series((binned.index.as_unit("s").asi8 - binned.index.as_unit("s").asi8[0]).astype(float), index=binned.index)
    for w in windows_min:
        k = w * per_min
        roll = rate.rolling(k, min_periods=max(1, k // 2))
        f[f"mean_{w}m"] = roll.mean()
        f[f"max_{w}m"] = roll.max()
        if w >= 5:
            f[f"std_{w}m"] = roll.std()
            # linear trend over the trailing window, counts/s per minute
            f[f"slope_{w}m"] = rate.rolling(k, min_periods=k // 2).cov(tsec) / tsec.rolling(k, min_periods=k // 2).var() * 60.0
        f[f"valid_frac_{w}m"] = n.rolling(k, min_periods=1).sum() / (k * cadence_s)
    kb = BG_WINDOW_MIN * per_min
    bg = rate.rolling(kb, min_periods=kb // 6).quantile(BG_QUANTILE)
    f["bg_60m"] = bg
    f["excess_1m"] = f["mean_1m"] - bg
    f["ratio_1m_bg"] = f["mean_1m"] / bg.clip(lower=1.0)
    f["ratio_1m_60m"] = f["mean_1m"] / f["mean_60m"].clip(lower=1.0)
    f["ratio_5m_60m"] = f["mean_5m"] / f["mean_60m"].clip(lower=1.0)
    f["d_mean_1m_5m"] = f["mean_1m"] - f["mean_5m"]
    # acceleration: change of the 5-min slope over the last 5 min (trailing difference, positive lag only)
    f["accel_5m"] = f["slope_5m"] - f["slope_5m"].shift(5 * per_min)
    return f


def hel1os_features(hel: pd.DataFrame | None, grid: pd.DatetimeIndex, cadence_s: int = 10) -> pd.DataFrame:
    """Optional HEL1OS features on the same grid; empty (no columns) when HEL1OS is absent or does not overlap."""
    if hel is None or hel.empty:
        return pd.DataFrame(index=grid)
    totals = [c for c in hel.columns if not c.endswith("_err") and ("1.8-90keV" in c or "18-160keV" in c)]
    h = hel[totals]
    h = h[(h.index > grid[0] - pd.Timedelta(minutes=10)) & (h.index <= grid[-1])]
    if h.empty:
        return pd.DataFrame(index=grid)
    b = h.resample(f"{cadence_s}s", label="right", closed="right").mean().reindex(grid)
    per_min = 60 // cadence_s
    out = pd.DataFrame(index=grid)
    for c in totals:
        out[f"hel_{c}_mean_1m"] = b[c].rolling(per_min, min_periods=1).mean()
        out[f"hel_{c}_max_5m"] = b[c].rolling(5 * per_min, min_periods=1).max()
    out["hel_available"] = b[totals].notna().any(axis=1).astype("int8")
    return out
