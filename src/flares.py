"""Flare detection on SoLEXS light curves + cross-match with the GOES (NOAA) flare list.

Detection is causal: onset uses only trailing windows (smoothing and background both look backwards).
Event-catalogue quantities derived after onset (peak time, end time) describe the finished event and are
LABEL-side only; they must never be used as model input features.

SoLEXS gives counts, not W/m^2, so a GOES class is only ever attached through the GOES cross-match.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_CLASS_BASE = {"A": 1e-8, "B": 1e-7, "C": 1e-6, "M": 1e-5, "X": 1e-4}


def goes_flux(cls: str) -> float:
    """GOES class string ('C3.2') -> peak flux in W/m^2 (used only for ordering GOES events)."""
    return _CLASS_BASE[cls[0]] * float(cls[1:] or 1)


def trailing_background(counts: pd.Series, smooth_window_s: int, bg_window_s: int, q: float):
    """Causal smoothing + background. Both windows are trailing (right-closed), never centred."""
    smooth = counts.rolling(f"{smooth_window_s}s", min_periods=max(5, smooth_window_s // 2)).mean()
    bg = smooth.rolling(f"{bg_window_s}s", min_periods=max(60, bg_window_s // 6)).quantile(q)
    return smooth, bg


def detect_day(
    counts: pd.Series,
    smooth_window_s: int = 60,
    background_window_s: int = 3600,
    background_quantile: float = 0.2,
    threshold_sigma: float = 5.0,
    min_excess_frac: float = 0.5,
    min_excess_abs: float = 5.0,
    min_duration_s: int = 120,
    end_frac: float = 0.1,
    merge_gap_s: int = 120,
    step_s: int = 10,
) -> pd.DataFrame:
    """Detect flares in one clean light curve (valid seconds only, UTC index).

    A sample is 'elevated' when smooth - bg > max(sigma*sqrt(bg/window), frac*bg, abs) with bg the trailing
    background. Once a flare starts, the background is frozen at its pre-onset value; the flare ends when the
    smoothed rate stays below bg0 + end_frac*(peak - bg0) for merge_gap_s (so double-peaked events are merged).
    """
    cols = ["onset", "peak", "end", "bg_counts_s", "peak_counts_s", "excess_counts_s", "duration_s"]
    if len(counts) < 2 * background_window_s // 6:
        return pd.DataFrame(columns=cols)
    smooth, bg = trailing_background(counts, smooth_window_s, background_window_s, background_quantile)
    # decimate to step_s grid (trailing values only: take the value at each grid time)
    grid = pd.date_range(counts.index[0].ceil(f"{step_s}s"), counts.index[-1], freq=f"{step_s}s")
    s = smooth.reindex(grid, method="pad", tolerance=pd.Timedelta(seconds=step_s))
    b = bg.reindex(grid, method="pad", tolerance=pd.Timedelta(seconds=step_s))
    sv, bv = s.to_numpy(), b.to_numpy()
    n = len(grid)
    gap_steps = max(1, merge_gap_s // step_s)

    def thr(bg_val):
        return max(threshold_sigma * np.sqrt(max(bg_val, 1.0) / smooth_window_s), min_excess_frac * bg_val, min_excess_abs)

    events, i = [], 0
    while i < n:
        if np.isnan(sv[i]) or np.isnan(bv[i]) or sv[i] - bv[i] <= thr(bv[i]):
            i += 1
            continue
        onset_i = i
        bg0 = bv[max(0, onset_i - 6)]  # background ~1 min before onset, frozen for this event
        if np.isnan(bg0):
            bg0 = bv[onset_i]
        peak_v, peak_i, below, j = sv[i], i, 0, i
        while j < n:
            v = sv[j]
            if np.isnan(v):
                below += 1  # data gap counts as time not elevated
            else:
                if v > peak_v:
                    peak_v, peak_i = v, j
                level = bg0 + max(end_frac * (peak_v - bg0), 0.5 * thr(bg0))
                below = below + 1 if v < level else 0
            if below >= gap_steps:
                break
            j += 1
        end_i = max(min(j - gap_steps + 1, n - 1), peak_i)
        dur = (end_i - onset_i) * step_s
        if dur >= min_duration_s:
            events.append(
                (grid[onset_i], grid[peak_i], grid[end_i], float(bg0), float(peak_v), float(peak_v - bg0), dur)
            )
        i = max(j, onset_i + 1)
    return pd.DataFrame(events, columns=cols)


def match_goes(flares: pd.DataFrame, goes: pd.DataFrame, tolerance_s: int = 300):
    """Many-to-many interval cross-match of detected flares against the GOES list.

    A pair matches when [onset, end] of the SoLEXS event overlaps [begin - tol, end + tol] of the GOES event.
    Returns (flares with goes_* columns, goes with n_solexs_matches).
    """
    tol = pd.Timedelta(seconds=tolerance_s)
    fl = flares.copy().reset_index(drop=True)
    g = goes.copy().reset_index(drop=True)
    fl["n_goes_overlap"] = 0
    fl["goes_class"] = pd.NA
    fl["goes_class_all"] = pd.NA
    g["n_solexs_matches"] = 0
    if len(fl) and len(g):
        go_b, go_e = (g["begin"] - tol).dt.as_unit("ns").astype("int64").to_numpy(), (g["end"] + tol).dt.as_unit("ns").astype("int64").to_numpy()
        flux = g["goes_class"].map(goes_flux).to_numpy()
        for k, r in fl.iterrows():
            hit = np.where((go_b <= r["end"].value) & (go_e >= r["onset"].value))[0]
            if len(hit):
                fl.at[k, "n_goes_overlap"] = len(hit)
                fl.at[k, "goes_class"] = g.at[hit[np.argmax(flux[hit])], "goes_class"]  # strongest GOES event
                fl.at[k, "goes_class_all"] = ",".join(g.loc[hit, "goes_class"])
                g.loc[hit, "n_solexs_matches"] += 1
    return fl, g


def summarize_match(fl: pd.DataFrame, g: pd.DataFrame, valid_intervals: pd.DataFrame | None = None) -> dict:
    """Detected-flare match rate, GOES recall (within SoLEXS valid time) and class balance."""
    out = {"n_detected": int(len(fl))}
    matched = fl["n_goes_overlap"] > 0 if len(fl) else pd.Series(dtype=bool)
    out["n_detected_matched_goes"] = int(matched.sum())
    out["goes_match_rate"] = float(matched.mean()) if len(fl) else None
    if valid_intervals is not None and len(g):
        # keep only GOES flares whose PEAK is inside SoLEXS valid observing time
        p = g["peak"].fillna(g["begin"])
        inside = np.zeros(len(g), dtype=bool)
        for s, e in zip(valid_intervals["start"], valid_intervals["stop"]):
            inside |= ((p >= s) & (p <= e)).to_numpy()
        g = g.loc[inside]
    out["n_goes_in_valid_time"] = int(len(g))
    rec = g["n_solexs_matches"] > 0
    out["goes_recall"] = float(rec.mean()) if len(g) else None
    out["goes_recall_by_class"] = {
        c: {"n": int((g["class_letter"] == c).sum()), "recall": float(rec[g["class_letter"] == c].mean())}
        for c in sorted(g["class_letter"].unique())
    }
    out["goes_class_balance_all"] = g["class_letter"].value_counts().sort_index().to_dict()
    out["detected_class_balance_via_goes"] = (
        fl.loc[matched, "goes_class"].str[0].value_counts().sort_index().to_dict() if matched.any() else {}
    )
    out["n_detected_unmatched"] = int((~matched).sum()) if len(fl) else 0
    return out
