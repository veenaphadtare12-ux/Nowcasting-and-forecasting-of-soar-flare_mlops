"""Feature frames for the frozen final models: 44 base features + the improvement ideas chosen per target.

The builders in src/improve/features_extra.py stop at the end of validation (their `_hi`). For the one-time test
scoring, `build(..., end=...)` temporarily moves that end; the builders themselves are unchanged, so the improvement
stages (and their DVC hashes) stay as they are. Callers decide which periods' rows are passed in; only
src/final/evaluate_test.py ever passes test rows.
"""
from __future__ import annotations

import contextlib
import json

import pandas as pd

from src import config
from src.improve import features_extra as fx
from src.models import train

IDEA_SOURCES = {"E2": "long", "E5": "spectral", "E6": "goes"}


def base_features() -> list[str]:
    return json.loads((config.PROJECT_ROOT / "reports" / "model_metrics.json").read_text(encoding="utf-8"))["features"]


@contextlib.contextmanager
def _end(end: pd.Timestamp | None):
    if end is None:
        yield
        return
    old = fx._hi
    fx._hi = lambda: end
    try:
        yield
    finally:
        fx._hi = old


def _source(kind: str, include_test: bool) -> pd.DataFrame | None:
    proc = config.processed_dir()
    if kind == "spectral":
        parts = [pd.read_parquet(proc / "solexs_spectral_minute.parquet")]
        if include_test:
            parts.append(pd.read_parquet(proc / "final" / "solexs_spectral_minute_test.parquet"))
    elif kind == "goes":
        parts = [pd.read_parquet(proc / "goes_xrs_minute.parquet")]
        if include_test:
            parts.append(pd.read_parquet(proc / "final" / "goes_xrs_minute_test.parquet"))
    else:
        return None
    s = pd.concat(parts).sort_index()
    return s[~s.index.duplicated(keep="first")]


def build(df: pd.DataFrame, ideas: list[str], end: pd.Timestamp | None = None, include_test: bool = False
          ) -> tuple[pd.DataFrame, list[str]]:
    """df: base rows (features, labels, flag). Returns (frame with extra columns, feature list)."""
    P = config.load_params()
    feats = base_features()
    out = df
    with _end(end):
        for idea in ("E2", "E5", "E6"):
            if idea not in ideas:
                continue
            kind = IDEA_SOURCES[idea]
            if kind == "long":
                proc = config.processed_dir()
                minute = pd.read_parquet(proc / "solexs_minute.parquet")["m"]
                ev = pd.read_parquet(proc / "events.parquet", columns=["trigger_time", "end", "peak_counts_s", "hit_cap", "ended_by_gap", "end_known_time"])
                g = fx.long_context_grid(minute, ev, P["improve"], P["flare_detection"])
            elif kind == "spectral":
                g = fx.spectral_grid(_source("spectral", include_test))
            else:
                g = fx.goes_grid(_source("goes", include_test))
            ex = fx.asof_rows(g.astype("float32"), out.index)
            out = pd.concat([out, ex], axis=1)
            feats = feats + list(ex.columns)
    if "E3" in ideas:
        out = fx.drift_normalise(out, P["improve"]["drift_days"])
    return out, feats


def label_columns() -> list[str]:
    return sorted({c for t in config.load_params()["final"]["targets"] for c in train.TARGETS[t]})
