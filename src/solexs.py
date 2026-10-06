"""SoLEXS Level-1 reader (SDD2 light curves + GTI).

Verified file facts (see CLAUDE.md): `.lc.gz` ext RATE, columns TIME (Unix-epoch seconds, UTC) and COUNTS,
1 s cadence, up to 86400 rows/day, NaN rows occur. SDD1 folders usually hold only a GTI file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from astropy.io import fits

from src import config

_DAY_RE = re.compile(r"AL1_SLX_L1_(\d{8})_v([\d.]+)$")


@dataclass(frozen=True)
class SolexsDay:
    date: pd.Timestamp
    version: str
    folder: Path
    lc: Path | None
    gti: Path | None

    @property
    def complete(self) -> bool:
        """A day is usable only if it has both a light curve and GTI (GTI-only folders are incomplete)."""
        return self.lc is not None and self.gti is not None


def list_days(root: Path | None = None, detector: str = "SDD2") -> list[SolexsDay]:
    root = Path(root) if root else config.solexs_root()
    days = []
    for folder in sorted(root.iterdir()):
        m = _DAY_RE.match(folder.name)
        if not (folder.is_dir() and m):
            continue
        ymd, ver = m.groups()
        det = folder / detector
        stem = f"AL1_SOLEXS_{ymd}_{detector}_L1"
        lc, gti = det / f"{stem}.lc.gz", det / f"{stem}.gti.gz"
        days.append(
            SolexsDay(pd.Timestamp(ymd, tz="UTC"), ver, folder, lc if lc.exists() else None, gti if gti.exists() else None)
        )
    return days


def read_lightcurve(path: Path) -> pd.DataFrame:
    """Raw light curve: UTC DatetimeIndex, float `counts` (NaN rows kept)."""
    with fits.open(path) as h:
        d = h["RATE"].data
        t = np.asarray(d["TIME"], dtype="float64")
        c = np.asarray(d["COUNTS"], dtype="float64")
    idx = pd.to_datetime(t, unit="s", utc=True)
    return pd.DataFrame({"counts": c}, index=pd.DatetimeIndex(idx, name="time"))


def read_gti(path: Path) -> pd.DataFrame:
    """Good time intervals as UTC start/stop."""
    with fits.open(path) as h:
        d = h[1].data
        start = np.asarray(d["START"], dtype="float64")
        stop = np.asarray(d["STOP"], dtype="float64")
    return pd.DataFrame(
        {"start": pd.to_datetime(start, unit="s", utc=True), "stop": pd.to_datetime(stop, unit="s", utc=True)}
    )


def gti_mask(index: pd.DatetimeIndex, gti: pd.DataFrame) -> np.ndarray:
    """True for timestamps that fall inside any GTI interval [start, stop]."""
    t = index.as_unit("ns").asi8
    mask = np.zeros(len(index), dtype=bool)
    for s, e in zip(gti["start"].dt.as_unit("ns").astype("int64"), gti["stop"].dt.as_unit("ns").astype("int64")):
        mask |= (t >= s) & (t <= e)
    return mask


def clean_day(day: SolexsDay) -> tuple[pd.DataFrame, dict]:
    """Return (clean light curve, QC info). Clean = non-NaN counts AND inside GTI.

    The returned frame keeps only valid seconds (NaN rows dropped, out-of-GTI rows dropped); gaps are simply
    absent timestamps, never filled.
    """
    lc = read_lightcurve(day.lc)
    gti = read_gti(day.gti)
    n_raw = len(lc)
    nan = lc["counts"].isna().to_numpy()
    in_gti = gti_mask(lc.index, gti)
    valid = ~nan & in_gti
    out = lc.loc[valid].copy()
    qc = {
        "date": day.date.strftime("%Y-%m-%d"),
        "version": day.version,
        "rows_raw": n_raw,
        "rows_nan": int(nan.sum()),
        "rows_outside_gti": int((~in_gti).sum()),
        "rows_valid": int(valid.sum()),
        "valid_fraction": float(valid.sum() / 86400.0),
        "gti_intervals": len(gti),
        "gti_exposure_s": float((gti["stop"] - gti["start"]).dt.total_seconds().sum()),
        "max_gap_s": float(out.index.to_series().diff().dt.total_seconds().max()) if len(out) > 1 else np.nan,
    }
    return out, qc


def select_days(days: list[SolexsDay], start: str | None, end: str | None) -> tuple[list[SolexsDay], list[SolexsDay]]:
    """(complete days in range, incomplete days in range)."""
    lo = pd.Timestamp(start, tz="UTC") if start else None
    hi = pd.Timestamp(end, tz="UTC") if end else None
    inrange = [d for d in days if (lo is None or d.date >= lo) and (hi is None or d.date <= hi)]
    return [d for d in inrange if d.complete], [d for d in inrange if not d.complete]
