"""Time-window guards for the operational flows (ingest, replay, drift, retrain).

While the ML phase is frozen, every flow may only touch DEVELOPMENT data: [tune start, development end). Anything after
the development end (holdout2 and any newer data) is reserved for the next one-time evaluation and is never read here.
Scoring (score_replay) is narrower still: only tune + val, so the old test period is never re-scored.
"""

from __future__ import annotations

import pandas as pd

from src import config

SCORABLE_PERIODS = ("tune", "val")


class LockedPeriodError(PermissionError):
    """The requested window touches data that the operational flows may not read."""


def dev_window() -> tuple[pd.Timestamp, pd.Timestamp]:
    return config.period_bounds("tune")[0], config.period_bounds("test")[1]


def scorable_window() -> tuple[pd.Timestamp, pd.Timestamp]:
    return config.period_bounds("tune")[0], config.period_bounds("val")[1]


def _ts(x) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def check_window(start, end, kind: str = "dev") -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return (start, end) as UTC timestamps, or raise LockedPeriodError. kind: 'dev' or 'score'."""
    s, e = _ts(start), _ts(end)
    lo, hi = dev_window() if kind == "dev" else scorable_window()
    if not s < e:
        raise ValueError(f"empty window {s} .. {e}")
    if s < lo or e > hi:
        what = "development data" if kind == "dev" else "the tune + val periods (the old test is never re-scored)"
        raise LockedPeriodError(
            f"window {s:%Y-%m-%d} .. {e:%Y-%m-%d} is outside {what}: allowed {lo:%Y-%m-%d} .. {hi:%Y-%m-%d} "
            "(exclusive). Data after the development end is locked for the next one-time evaluation."
        )
    return s, e
