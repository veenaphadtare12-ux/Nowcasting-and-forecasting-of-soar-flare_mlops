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


# ---------------------------------------------------------------- HEL1OS (hard X-ray), optional
HX_CHANNELS = {  # channel -> (detector family, list of bands summed); detectors 1 and 2 are averaged
    "cdte_lo": ("cdte", ["5-20keV"]),
    "cdte_hi": ("cdte", ["20-30keV", "30-40keV"]),
    "czt_lo": ("czt", ["20-40keV"]),
    "czt_hi": ("czt", ["40-60keV", "60-80keV", "80-150keV"]),
}
HX_FEATURES = (
    ["hel1os_available"]
    + [f"hx_{c}_{k}" for c in HX_CHANNELS for k in ("log_mean_1m", "max_5m")]
    + ["hx_cdte_lo_ratio_bg", "hx_czt_lo_ratio_bg", "hx_hr_cdte", "hx_hr_czt",
       "hx_cdte_lo_lag5m", "hx_cdte_lo_lag10m", "hx_cdte_lo_d5m", "hx_neupert_corr_10m"]
)


def hel1os_channels(hel: pd.DataFrame) -> pd.DataFrame:
    """1 s HEL1OS table (columns like `cdte1_5-20keV`) -> 4 hard X-ray channels (counts/s).

    Each band is the mean of detectors 1 and 2 where present (skip missing); a channel is the sum of its bands.
    """
    out = {}
    for name, (fam, bands) in HX_CHANNELS.items():
        parts = []
        for b in bands:
            cols = [f"{fam}{d}_{b}" for d in (1, 2) if f"{fam}{d}_{b}" in hel.columns]
            if cols:
                parts.append(hel[cols].mean(axis=1, skipna=True))
        out[name] = sum(parts) if parts else pd.Series(np.nan, index=hel.index)
    return pd.DataFrame(out, index=hel.index)


def hel1os_features(chan: pd.DataFrame | None, grid: pd.DatetimeIndex, cadence_s: int = 10,
                    sxr_rate: pd.Series | None = None) -> pd.DataFrame:
    """Causal hard X-ray features on the 10 s grid. Optional: no HEL1OS data -> no columns at all.

    `chan` is the output of `hel1os_channels`. Outside HEL1OS sessions every hx_* feature is NaN (missing, never
    filled) and `hel1os_available` is 0. XGBoost uses the missing values natively; logistic regression gets an
    explicit missing indicator plus imputation fitted on training rows (src/models/train.py).
    """
    if chan is None or chan.empty:
        return pd.DataFrame(index=grid)
    per_min = 60 // cadence_s
    lo = grid[0] - pd.Timedelta(minutes=80)  # trailing warm-up for the 60-min background
    h = chan[(chan.index > lo) & (chan.index <= grid[-1])]
    out = pd.DataFrame(index=grid)
    if h.empty:
        out["hel1os_available"] = np.zeros(len(grid), dtype="int8")
        for c in HX_FEATURES[1:]:
            out[c] = np.nan
        return out
    r = h.resample(f"{cadence_s}s", label="right", closed="right")
    b = r.mean().reindex(grid)
    n_valid = r.count()["czt_lo"].reindex(grid).fillna(0)
    # available: at least half of the last minute's seconds carry HEL1OS data (trailing, causal)
    out["hel1os_available"] = (n_valid.rolling(per_min, min_periods=1).sum() >= 30).astype("int8")
    avail = out["hel1os_available"].astype(bool)
    m1 = {c: b[c].rolling(per_min, min_periods=per_min // 2).mean() for c in HX_CHANNELS}
    for c in HX_CHANNELS:
        out[f"hx_{c}_log_mean_1m"] = np.log10(m1[c].clip(lower=0) + 1.0)
        out[f"hx_{c}_max_5m"] = b[c].rolling(5 * per_min, min_periods=per_min).max()
    kb = 60 * per_min
    for c in ("cdte_lo", "czt_lo"):
        bg = m1[c].rolling(kb, min_periods=kb // 6).quantile(0.2)
        out[f"hx_{c}_ratio_bg"] = m1[c] / bg.clip(lower=0.1)
    out["hx_hr_cdte"] = m1["cdte_hi"] / (m1["cdte_lo"] + 1.0)
    out["hx_hr_czt"] = m1["czt_hi"] / (m1["czt_lo"] + 1.0)
    out["hx_cdte_lo_lag5m"] = out["hx_cdte_lo_log_mean_1m"].shift(5 * per_min)    # positive shift = the past
    out["hx_cdte_lo_lag10m"] = out["hx_cdte_lo_log_mean_1m"].shift(10 * per_min)
    out["hx_cdte_lo_d5m"] = out["hx_cdte_lo_log_mean_1m"] - out["hx_cdte_lo_lag5m"]
    if sxr_rate is not None:
        # Neupert effect: hard X-ray flux tracks the time derivative of soft X-ray flux. Trailing 10-min correlation.
        dsxr = sxr_rate.reindex(grid).diff()
        out["hx_neupert_corr_10m"] = b["czt_lo"].rolling(10 * per_min, min_periods=5 * per_min).corr(dsxr)
    else:
        out["hx_neupert_corr_10m"] = np.nan
    for c in HX_FEATURES[1:]:  # never use hard X-ray values when HEL1OS is not currently observing
        out.loc[~avail, c] = np.nan
    return out[HX_FEATURES]
