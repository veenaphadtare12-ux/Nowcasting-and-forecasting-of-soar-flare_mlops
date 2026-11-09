"""Extra candidate features for the improvement experiments. All causal (trailing only).

Every source is put on a 1-minute grid whose timestamp is the END of the minute (the moment the value is known) and
attached to the 10-s rows with a backward as-of join: row t only sees grid points <= t. Nothing at or after the end of
the validation period is read.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import activity, config

LOG_FLOOR = 0.1


def _hi() -> pd.Timestamp:
    return config.period_bounds("val")[1]


def asof_rows(grid: pd.DataFrame, rows: pd.DatetimeIndex) -> pd.DataFrame:
    """Value of the last grid point at or before each row time."""
    g = grid.sort_index()
    left = pd.DataFrame({"time": rows.as_unit("ns")})
    right = g.reset_index().rename(columns={g.index.name or "index": "time"})
    right["time"] = pd.DatetimeIndex(right["time"]).as_unit("ns")
    out = pd.merge_asof(left, right, on="time", direction="backward", tolerance=pd.Timedelta(minutes=15))
    return out.set_index(pd.DatetimeIndex(rows)).drop(columns="time")


def _full_minutes(s: pd.Series) -> pd.Series:
    idx = pd.date_range(s.index.min(), s.index.max(), freq="1min", tz="UTC")
    return s.reindex(idx)


def _rolling_slope(y: pd.Series, window: str, min_count: int) -> pd.Series:
    """Least-squares slope (per hour) of y over a trailing time window; NaN where fewer than min_count points."""
    t = (y.index - y.index[0]).total_seconds().to_numpy() / 3600.0
    v = y.notna().to_numpy()
    yy = np.where(v, y.to_numpy(), 0.0)
    tt = np.where(v, t, 0.0)
    df = pd.DataFrame({"n": v.astype(float), "t": tt, "y": yy, "ty": tt * yy, "tt": tt * tt}, index=y.index)
    s = df.rolling(window).sum()
    num = s["n"] * s["ty"] - s["t"] * s["y"]
    den = s["n"] * s["tt"] - s["t"] ** 2
    out = num / den.where(den > 0)
    return out.where(s["n"] >= min_count)


# ---------------------------------------------------------------- E2 long context
def long_context_grid(minute: pd.Series, events: pd.DataFrame, P: dict, fd: dict) -> pd.DataFrame:
    """minute: SoLEXS 1-min mean counts/s labelled at minute end. events: detector catalogue (only trigger_time,
    end-known time and peak are used, each only from the moment the detector knows it)."""
    hi = _hi()
    m = _full_minutes(minute[minute.index < hi])
    ly = np.log10(m.clip(lower=LOG_FLOOR))
    out = {}
    for w in P["long_windows_h"]:
        mp = w * 30  # at least half the minutes of the window
        r = ly.rolling(f"{w}h", min_periods=mp)
        out[f"lc_mean_{w}h"] = r.mean()
        out[f"lc_max_{w}h"] = r.max()
        out[f"lc_slope_{w}h"] = _rolling_slope(ly, f"{w}h", mp)
    g = pd.DataFrame(out, index=m.index)
    e = events[events["trigger_time"] < hi]
    trig = e["trigger_time"].sort_values().to_numpy(dtype="datetime64[ns]")
    T = g.index.as_unit("ns").asi8.view("datetime64[ns]")
    for w in P["event_windows_h"]:
        W = np.timedelta64(w * 3600, "s")
        g[f"ev_n_{w}h"] = (np.searchsorted(trig, T, "right") - np.searchsorted(trig, T - W, "right")).astype("float32")
        # largest peak of events that started (triggered) in the window AND whose end is already confirmed
        best = np.zeros(len(T))  # log10 counts/s; 0 = no finished event in the window
        known = activity.end_known_time(e, fd["end_confirm_min"], fd["gap_end_min"]).to_numpy(dtype="datetime64[ns]")
        for tr, kn, pk in zip(e["trigger_time"].to_numpy(dtype="datetime64[ns]"), known, e["peak_counts_s"].to_numpy()):
            a = np.searchsorted(T, max(kn, tr), "left")
            b = np.searchsorted(T, tr + W, "right")
            if b > a:
                np.maximum(best[a:b], np.log10(max(pk, LOG_FLOOR)), out=best[a:b])
        g[f"ev_max_peak_{w}h"] = best
    last = np.searchsorted(trig, T, "right") - 1
    since = np.where(last >= 0, (T - trig[np.maximum(last, 0)]) / np.timedelta64(1, "h"), np.inf)
    g["ev_hours_since_last"] = np.minimum(since, P["since_event_cap_h"])
    return g


# ---------------------------------------------------------------- E3 drift-robust
LEVEL_FEATURES = ["rate", "mean_1m", "max_1m", "mean_5m", "max_5m", "std_5m", "mean_15m", "max_15m", "std_15m",
                  "mean_60m", "max_60m", "std_60m", "bg_60m"]
SIGNED_FEATURES = ["slope_5m", "slope_15m", "slope_60m", "excess_1m", "d_mean_1m_5m", "accel_5m"]


def drift_normalise(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """Level features / their own trailing `days`-day median; signed features (median ~0) / the trailing median of
    `rate`. Medians are computed on a 10-min grid (value known at the grid time) and joined backwards."""
    out = df.copy()
    meds = {}
    for f in LEVEL_FEATURES:
        g = df[f].resample("10min", label="right", closed="right").last()
        meds[f] = g.rolling(f"{days}D", min_periods=6 * 24).median()
    med = asof_rows(pd.DataFrame(meds), df.index)
    for f in LEVEL_FEATURES:
        out[f] = df[f] / med[f].where(med[f] > 0)
    for f in SIGNED_FEATURES:
        out[f] = df[f] / med["rate"].where(med["rate"] > 0)
    return out


# ---------------------------------------------------------------- E5 spectral
def spectral_grid(sp: pd.DataFrame) -> pd.DataFrame:
    """sp: 1-min band rates (low, high, total) labelled at minute end."""
    hi = _hi()
    sp = sp[sp.index < hi]
    idx = pd.date_range(sp.index.min(), sp.index.max(), freq="1min", tz="UTC")
    sp = sp.reindex(idx)
    lr = np.log10((sp["high"] / sp["low"].where(sp["low"] > 0)).clip(lower=1e-6))
    lt = np.log10(sp["total"].clip(lower=LOG_FLOOR))
    g = pd.DataFrame({"sp_low_log": np.log10(sp["low"].clip(lower=LOG_FLOOR)),
                      "sp_high_log": np.log10(sp["high"].clip(lower=LOG_FLOOR)),
                      "sp_ratio_log": lr}, index=idx)
    for w in (5, 15):
        g[f"sp_ratio_slope_{w}m"] = _rolling_slope(lr, f"{w}min", (w + 1) // 2)
    tot_slope = _rolling_slope(lt, "5min", 3)
    hope = (g["sp_ratio_slope_5m"] > 0) & (tot_slope > 0)
    g["sp_hope"] = hope.astype("float32").where(g["sp_ratio_slope_5m"].notna() & tot_slope.notna())
    return g


# ---------------------------------------------------------------- E6 GOES XRS
def goes_grid(x: pd.DataFrame) -> pd.DataFrame:
    """x: GOES XRS 1-min averages (xrsa, xrsb in W/m^2) labelled at minute END (start + 60 s)."""
    hi = _hi()
    x = x[x.index < hi]
    idx = pd.date_range(x.index.min(), x.index.max(), freq="1min", tz="UTC")
    x = x.reindex(idx)
    lb = np.log10(x["xrsb"].where(x["xrsb"] > 0))
    la = np.log10(x["xrsa"].where(x["xrsa"] > 0))
    g = pd.DataFrame({"gx_b_log": lb, "gx_a_log": la, "gx_ratio_log": la - lb}, index=idx)
    for w in (5, 15):
        g[f"gx_b_slope_{w}m"] = _rolling_slope(lb, f"{w}min", (w + 1) // 2)
    g["gx_b_max_60m"] = lb.rolling("60min", min_periods=30).max()
    return g


def extra_block(kind: str, rows: pd.DatetimeIndex) -> pd.DataFrame:
    """Extra feature columns for the given 10-s row times."""
    proc = config.processed_dir()
    params = config.load_params()
    P = params["improve"]
    if kind == "long":
        minute = pd.read_parquet(proc / "solexs_minute.parquet")["m"]
        ev = pd.read_parquet(proc / "events.parquet", columns=["trigger_time", "end", "peak_counts_s", "hit_cap", "ended_by_gap"])
        g = long_context_grid(minute, ev, P, params["flare_detection"])
    elif kind == "spectral":
        g = spectral_grid(pd.read_parquet(proc / "solexs_spectral_minute.parquet"))
    elif kind == "goes":
        g = goes_grid(pd.read_parquet(proc / "goes_xrs_minute.parquet"))
    else:
        raise ValueError(kind)
    return asof_rows(g.astype("float32"), rows)
