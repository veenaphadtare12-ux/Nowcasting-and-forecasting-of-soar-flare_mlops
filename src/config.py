"""Single source of truth for paths and parameters (reads params.yaml)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARAMS_FILE = PROJECT_ROOT / "params.yaml"


@lru_cache(maxsize=1)
def load_params(path: str | None = None) -> dict:
    with open(path or PARAMS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _resolve(p: str) -> Path:
    """Absolute paths are used as-is; relative paths are relative to the project root."""
    path = Path(p)
    return path if path.is_absolute() else PROJECT_ROOT / path


def path(key: str) -> Path:
    return _resolve(load_params()["paths"][key])


def solexs_root() -> Path:
    return path("data_root_solexs")


def hel1os_root() -> Path:
    return path("data_root_hel1os")


def processed_dir() -> Path:
    return path("processed_dir")


# ---- chronological periods -------------------------------------------------------------------------
import pandas as pd  # noqa: E402

PERIOD_NAMES = ("tune", "val", "test")


def period_bounds(name: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """[start, end) of a period in UTC (end is the day AFTER the configured last day)."""
    p = load_params()["periods"][name]
    return pd.Timestamp(p["start"], tz="UTC"), pd.Timestamp(p["end"], tz="UTC") + pd.Timedelta(days=1)


def data_range() -> tuple[pd.Timestamp, pd.Timestamp]:
    """Overall [start, end) covered by all periods."""
    return period_bounds("tune")[0], period_bounds("test")[1]


def assign_period(times: pd.DatetimeIndex | pd.Series) -> pd.Series:
    """Period name for each UTC timestamp ('' outside all periods)."""
    t = pd.Series(pd.DatetimeIndex(times).as_unit("ns"))
    out = pd.Series("", index=t.index, dtype=object)
    for name in PERIOD_NAMES:
        lo, hi = period_bounds(name)
        out[(t >= lo) & (t < hi)] = name
    return out


def validate_periods() -> None:
    """Periods must be chronological, contiguous-or-gapped, and non-overlapping."""
    b = [period_bounds(n) for n in PERIOD_NAMES]
    for (lo, hi) in b:
        assert lo < hi, "empty period"
    for (_, hi), (lo, _) in zip(b[:-1], b[1:]):
        assert hi <= lo, "periods overlap or are out of chronological order"


def mlflow_uri() -> str:
    """MLflow tracking URI from params.yaml; a relative sqlite path is resolved against the project root."""
    uri = load_params()["paths"]["mlflow_tracking_uri"]
    if uri.startswith("sqlite:///") and not Path(uri[len("sqlite:///"):]).is_absolute():
        return "sqlite:///" + (PROJECT_ROOT / uri[len("sqlite:///"):]).as_posix()
    return uri
