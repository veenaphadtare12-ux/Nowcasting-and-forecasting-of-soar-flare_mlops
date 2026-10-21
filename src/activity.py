"""Causal "is a flare in progress right now?" flag, from the detector's own real-time decisions.

The flag at time t uses only what the detector could know at t:
* an event becomes active at its `trigger_time` (end of the minute whose data confirmed the rise), not at its
  catalogue onset (which is found by looking back);
* it stays active until its end is CONFIRMED: the end minute plus `end_confirm_min` quiet minutes; for events cut by
  the duration cap, at the cap time; for events ended by a data gap, once the gap has lasted `gap_end_min` minutes.

All detections count (GOES-matched or not): the GOES list is not available in real time. This is a meta column used
for the persistence baseline and the quiet-start evaluation split; it is not a model input feature.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _ns(x) -> np.ndarray:
    return pd.DatetimeIndex(x).as_unit("ns").asi8


def end_known_time(events: pd.DataFrame, end_confirm_min: int, gap_end_min: int) -> pd.Series:
    """When the detector knows each event has ended."""
    end = events["end"].copy()
    normal = ~events["hit_cap"].astype(bool) & ~events["ended_by_gap"].astype(bool)
    end[normal] = end[normal] + pd.Timedelta(minutes=end_confirm_min)
    gap = events["ended_by_gap"].astype(bool)
    end[gap] = end[gap] + pd.Timedelta(minutes=gap_end_min)
    return end


def flare_in_progress(times: pd.DatetimeIndex, events: pd.DataFrame, end_confirm_min: int, gap_end_min: int) -> np.ndarray:
    """int8 array: 1 where trigger_time <= t < end_known_time for any detection."""
    t = _ns(times)
    if events.empty:
        return np.zeros(len(t), dtype=np.int8)
    a = np.searchsorted(t, _ns(events["trigger_time"]), side="left")
    b = np.searchsorted(t, _ns(end_known_time(events, end_confirm_min, gap_end_min)), side="left")
    diff = np.zeros(len(t) + 1, dtype=np.int32)
    np.add.at(diff, a, 1)
    np.add.at(diff, b, -1)
    return (np.cumsum(diff[:-1]) > 0).astype(np.int8)
