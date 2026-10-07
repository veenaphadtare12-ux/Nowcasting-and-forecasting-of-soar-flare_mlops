"""GOES-style flare detector on 1-minute mean SoLEXS counts.

Causality
---------
* Background (`trailing_background`) is a trailing quantile: bg[t] uses minutes <= t only.
* The TRIGGER is causal: it fires at the end of the first minute whose excess crosses the threshold, using only
  data up to that minute (`trigger_time`).
* Everything else in an event record (onset, peak, end, split points, cap) is the OFFLINE CATALOGUE: it uses the
  finished event (e.g. the end needs the decay that follows the peak). Catalogue columns are label-side only and
  must never be used as model input features (see CLAUDE.md rule 2 and tests/test_leakage.py).

Time convention
---------------
Minute means are labelled by the END of the minute they average, so a value at label t uses data in (t-1min, t].
Catalogue times are reported like GOES, as the START of the relevant minute: onset = first minute of the sustained
rise, end = first minute at/below the end level, peak = centre of the peak minute.

SoLEXS gives counts, not W/m^2: nothing here assigns a GOES class.
"""
from __future__ import annotations

from dataclasses import dataclass, fields

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

MINUTE = pd.Timedelta(minutes=1)


@dataclass(frozen=True)
class DetectorSettings:
    bg_window_min: int = 60
    bg_quantile: float = 0.2
    min_valid_s_per_min: int = 30
    threshold_sigma: float = 5.0
    min_excess_frac: float = 0.5
    min_excess_abs: float = 5.0
    rise_steps: int = 3
    min_rise_ratio: float = 1.4
    impulsive_factor: float = 0.0
    max_lookback_min: int = 30
    end_halfway_frac: float = 0.5
    end_confirm_min: int = 2
    dip_frac: float = 0.5
    min_duration_s: int = 120
    max_duration_s: int = 10800
    gap_end_min: int = 10

    @classmethod
    def from_params(cls, d: dict, **override) -> "DetectorSettings":
        names = {f.name for f in fields(cls)}
        return cls(**{**{k: v for k, v in d.items() if k in names}, **override})


# ------------------------------------------------------------------------------------------------------
def minute_means(counts: pd.Series, min_valid_s: int = 30) -> pd.DataFrame:
    """1 s counts (valid seconds only, UTC index) -> minute means labelled by the minute END.

    Returns columns `m` (mean counts/s, NaN when fewer than min_valid_s valid seconds) and `n` (valid seconds).
    The grid is continuous: missing minutes are NaN rows (gaps are never filled).
    """
    key = counts.index.floor("min")
    g = counts.groupby(key)
    m, n = g.mean(), g.size()
    grid = pd.date_range(m.index[0], m.index[-1], freq="min")
    out = pd.DataFrame({"m": m.reindex(grid), "n": n.reindex(grid).fillna(0).astype("int32")})
    out.loc[out["n"] < min_valid_s, "m"] = np.nan
    out.index = out.index + MINUTE  # label = end of minute
    out.index.name = "time"
    return out


def trailing_background(m: pd.Series, window_min: int, q: float) -> pd.Series:
    """Trailing (right-closed) low quantile of the minute means. Never centred."""
    return m.rolling(window_min, min_periods=max(10, window_min // 6)).quantile(q)


def _threshold(bg: float, s: DetectorSettings) -> float:
    return max(s.threshold_sigma * np.sqrt(max(bg, 1.0) / 60.0), s.min_excess_frac * bg, s.min_excess_abs)


def prepare(m: pd.Series, s: DetectorSettings) -> pd.DataFrame:
    """Add the causal background. Returned frame: m, bg (both indexed by minute-end label)."""
    return pd.DataFrame({"m": m, "bg": trailing_background(m, s.bg_window_min, s.bg_quantile)})


# ------------------------------------------------------------------------------------------------------
def _rise_start(mv: np.ndarray, k: int, s: DetectorSettings) -> tuple[int, int]:
    """Start index of the strictly increasing run that ends at k, and its number of steps."""
    lo = max(0, k - s.max_lookback_min)
    j = k
    while j - 1 >= lo and np.isfinite(mv[j - 1]) and mv[j] > mv[j - 1]:
        j -= 1
    return j, k - j


def _split(mv: np.ndarray, i0: int, i1: int, bg0: float, thr0: float, s: DetectorSettings) -> list[int]:
    """Valley indices that split [i0, i1] into separate flares (dip >= dip_frac of lower peak - bg)."""
    if i1 - i0 < 4:
        return []
    seg = pd.Series(mv[i0 : i1 + 1]).interpolate(limit_area="inside").to_numpy()
    sm = pd.Series(seg).rolling(3, center=True, min_periods=1).mean().to_numpy()  # offline catalogue: centred is fine
    pk, props = find_peaks(sm, prominence=max(thr0, 1e-9))
    if len(pk) < 2:
        return []
    heights, prom = sm[pk], props["prominences"]
    keep = [i for i in range(len(pk)) if prom[i] >= s.dip_frac * max(heights[i] - bg0, 1e-9) or heights[i] == heights.max()]
    pk = pk[keep]
    return [int(i0 + a + np.argmin(sm[a : b + 1])) for a, b in zip(pk[:-1], pk[1:])]


def detect(frame: pd.DataFrame, s: DetectorSettings) -> pd.DataFrame:
    """Detect flares on a (m, bg) minute frame. See module docstring for causal vs catalogue fields."""
    cols = ["onset", "peak", "end", "trigger_time", "bg_counts_s", "peak_counts_s", "excess_counts_s",
            "duration_s", "hit_cap", "was_split", "rise_steps", "open_at_end", "ended_by_gap"]
    mv, bv, lab = frame["m"].to_numpy(float), frame["bg"].to_numpy(float), frame.index
    N = len(mv)
    events: list[dict] = []
    k = 0
    while k < N:
        if not (np.isfinite(mv[k]) and np.isfinite(bv[k])) or mv[k] - bv[k] <= _threshold(bv[k], s):
            k += 1
            continue
        st, steps = _rise_start(mv, k, s)
        ratio_ok = mv[k] / max(mv[st], 1e-9) >= s.min_rise_ratio
        impulsive = s.impulsive_factor > 0 and (mv[k] - bv[k]) >= s.impulsive_factor * _threshold(bv[k], s)
        if not ((steps >= s.rise_steps and ratio_ok) or impulsive):
            k += 1
            continue
        # --- event confirmed (trigger at k, rise began at st); background frozen from here on
        bg0 = bv[st - 1] if st > 0 and np.isfinite(bv[st - 1]) else bv[st]
        thr0 = _threshold(bg0, s)
        P, pk, j, below, first, nan_run = mv[k], k, k + 1, 0, None, 0
        end, by_gap, open_end = None, False, False
        while j < N:
            v = mv[j]
            if not np.isfinite(v):
                nan_run += 1
                if nan_run >= s.gap_end_min:
                    end, by_gap = j - nan_run + 1, True
                    break
                j += 1
                continue
            nan_run = 0
            if v > P:
                P, pk, below, first = v, j, 0, None
            elif j > pk and (v <= bg0 + s.end_halfway_frac * (P - bg0) or v <= bg0 + thr0):
                below += 1
                first = j if below == 1 else first
                if below >= s.end_confirm_min:
                    end = first
                    break
            else:
                below, first = 0, None
            j += 1
        if end is None:
            end, open_end = N - 1, True
        # --- split merged events at deep dips, then cap duration
        cuts = _split(mv, st, end, bg0, thr0, s)
        edges = [st, *cuts, end]
        for a, b in zip(edges[:-1], edges[1:]):
            seg = mv[a : b + 1]
            if not np.isfinite(seg).any():
                continue
            ipk = a + int(np.nanargmax(seg))
            onset_t = lab[a] - MINUTE
            end_t = lab[b] - MINUTE if b > a else lab[b]
            hit_cap = (end_t - onset_t).total_seconds() > s.max_duration_s
            if hit_cap:
                end_t = onset_t + pd.Timedelta(seconds=s.max_duration_s)
            dur = (end_t - onset_t).total_seconds()
            if dur < s.min_duration_s:
                continue
            events.append(
                {
                    "onset": onset_t, "peak": lab[ipk] - pd.Timedelta(seconds=30), "end": end_t,
                    "trigger_time": lab[k] if a == st else onset_t + MINUTE,
                    "bg_counts_s": float(bg0), "peak_counts_s": float(mv[ipk]),
                    "excess_counts_s": float(mv[ipk] - bg0), "duration_s": dur, "hit_cap": bool(hit_cap),
                    "was_split": len(cuts) > 0, "rise_steps": int(steps) if a == st else 0,
                    "open_at_end": bool(open_end and b == end), "ended_by_gap": bool(by_gap and b == end),
                }
            )
        k = max(end + 1, k + 1)
    return pd.DataFrame(events, columns=cols)


def detect_series(m: pd.Series, s: DetectorSettings) -> pd.DataFrame:
    """Convenience: minute means -> background -> events."""
    return detect(prepare(m, s), s)
