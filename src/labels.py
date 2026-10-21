"""Nowcast and forecast labels.

Rules (CLAUDE.md):
* Nowcast (`y_now`): a GOES-matched SoLEXS event is in progress. Unmatched detections are never positives.
* Forecast (`y_c_*`, `y_m_*`): taken from the GOES flare list DIRECTLY, so a GOES flare the detector missed is still
  a positive. The onset used for a GOES flare is the SoLEXS onset of the detection it is the primary match of
  (closest GOES begin to that detection's onset), otherwise the GOES begin time (`goes_onsets`).
* GOES class comes only from GOES, never from SoLEXS counts.
* Forecast labels look strictly AFTER the input window ends: a row at time t (features use data <= t)
  is positive for horizon h when a qualifying flare STARTS in (t, t + h].
* A label is only trustworthy if the future window is observed: `ok_<h>m` is False when (t, t+h] runs past the
  end of the row's period, has too little valid SoLEXS data, or touches a day with no GOES report.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.detection.matching import goes_flux


def _ns(x) -> np.ndarray:
    return pd.DatetimeIndex(x).as_unit("ns").asi8


def qualifying_onsets(events: pd.DataFrame, min_class: str | None) -> np.ndarray:
    """Sorted onset times (ns) of GOES-matched events with GOES class >= min_class (None = any matched)."""
    e = events[events["is_goes_matched"].astype(bool)]
    if min_class is not None:
        e = e[e["goes_class"].astype(str).map(goes_flux) >= goes_flux(min_class)]
    return np.sort(_ns(e["onset"]))


def goes_onsets(goes: pd.DataFrame, events: pd.DataFrame, pairs: pd.DataFrame, min_class: str) -> np.ndarray:
    """Sorted onset times (ns) of all GOES flares with class >= min_class.

    For each detection, its *primary* GOES flare is the overlapping one whose begin is closest to the detection's
    onset; that GOES flare takes the (more precise) SoLEXS onset. Every other GOES flare, including flares the
    detector missed and second flares merged into one detection, keeps its GOES begin time.
    `pairs` holds (event index, goes index) rows from the cross-match.
    """
    g = goes[goes["goes_class"].astype(str).map(goes_flux) >= goes_flux(min_class)]
    onset = g["begin"].copy()
    if len(pairs):
        pr = pairs.copy()
        pr["ev_onset"] = events.loc[pr["event"], "onset"].to_numpy()
        pr["g_begin"] = goes.loc[pr["goes"], "begin"].to_numpy()
        pr["d"] = (pr["ev_onset"] - pr["g_begin"]).abs()
        prim = pr.loc[pr.groupby("event")["d"].idxmin()]          # each detection's closest GOES flare
        prim = prim.sort_values("d").drop_duplicates("goes")       # a GOES flare keeps its closest detection
        prim = prim.set_index("goes")["ev_onset"]
        idx = g.index.intersection(prim.index)
        onset.loc[idx] = prim.loc[idx].to_numpy()
    return np.sort(_ns(onset.dropna()))


def nowcast_label(times: pd.DatetimeIndex, events: pd.DataFrame) -> np.ndarray:
    """1 where any GOES-matched flare is in progress (onset <= t < end)."""
    t = _ns(times)
    e = events[events["is_goes_matched"].astype(bool)]
    diff = np.zeros(len(t) + 1, dtype=np.int32)
    a = np.searchsorted(t, _ns(e["onset"]), side="left")
    b = np.searchsorted(t, _ns(e["end"]), side="left")
    np.add.at(diff, a, 1)
    np.add.at(diff, b, -1)
    return (np.cumsum(diff[:-1]) > 0).astype(np.int8)


def forecast_label(times: pd.DatetimeIndex, onsets_ns: np.ndarray, horizon_min: int) -> np.ndarray:
    """1 where a qualifying flare starts in (t, t + h]. Strictly after t: an onset exactly at t does not count."""
    t = _ns(times)
    h = pd.Timedelta(minutes=horizon_min).value
    lo = np.searchsorted(onsets_ns, t, side="right")
    hi = np.searchsorted(onsets_ns, t + h, side="right")
    return (hi > lo).astype(np.int8)


def future_ok(
    times: pd.DatetimeIndex, horizon_min: int, valid_minutes: pd.Series, period_end: pd.Series,
    goes_missing_days: list, min_valid_frac: float,
) -> np.ndarray:
    """True when (t, t+h] lies inside the row's period, is >= min_valid_frac observed, and has GOES coverage."""
    t = _ns(times)
    h = pd.Timedelta(minutes=horizon_min).value
    inside = (t + h) <= _ns(period_end)
    # valid minutes are labelled by minute END; count those with label in (t, t+h]
    vm = valid_minutes[valid_minutes].index
    cum = _ns(vm)
    n_valid = np.searchsorted(cum, t + h, side="right") - np.searchsorted(cum, t, side="right")
    observed = n_valid >= min_valid_frac * horizon_min
    ok = inside & observed
    for d in goes_missing_days:
        d0 = pd.Timestamp(d).value
        d1 = d0 + pd.Timedelta(days=1).value
        ok &= ~((t < d1) & (t + h >= d0))  # window touches a day without GOES truth
    return ok


def make_labels(
    times: pd.DatetimeIndex, events: pd.DataFrame, horizons_min: list[int], min_class_c: str, min_class_m: str,
    valid_minutes: pd.Series, period_end: pd.Series, goes_missing_days: list, min_valid_frac: float = 0.9,
    goes: pd.DataFrame | None = None, pairs: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Labels for every row. With `goes` given, forecast labels come from the GOES list directly (current method);
    without it, from GOES-matched detections only (the old method, kept for comparison)."""
    out = pd.DataFrame(index=times)
    out["y_now"] = nowcast_label(times, events)
    day = times.floor("D")
    out["ok_now"] = ~day.isin(pd.DatetimeIndex(goes_missing_days))
    if goes is not None:
        pairs = pairs if pairs is not None else pd.DataFrame(columns=["event", "goes"])
        on_c = goes_onsets(goes, events, pairs, min_class_c)
        on_m = goes_onsets(goes, events, pairs, min_class_m)
    else:
        on_c = qualifying_onsets(events, min_class_c)
        on_m = qualifying_onsets(events, min_class_m)
    for h in horizons_min:
        out[f"y_c_{h}m"] = forecast_label(times, on_c, h)
        out[f"y_m_{h}m"] = forecast_label(times, on_m, h)
        out[f"ok_{h}m"] = future_ok(times, h, valid_minutes, period_end, goes_missing_days, min_valid_frac)
    return out
