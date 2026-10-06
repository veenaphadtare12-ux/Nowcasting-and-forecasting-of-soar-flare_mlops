"""HEL1OS Level-1 light-curve parser (optional input everywhere downstream).

Verified file facts: `cdte/lightcurve_cdte{1,2}.fits` and `czt/lightcurve_czt{1,2}.fits`, one BinTable extension per
energy band (EXTNAME like CDTE1_LC_BAND_5.00KEV_TO_20.00KEV), columns MJD, ISOT (UTC), CTR (cts/sec),
STAT_ERR. Headers carry no TIMESYS/MJDREF, so time comes from the MJD / ISOT columns.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from astropy.io import fits

from src import config

_SESSION_RE = re.compile(r"HLS_(\d{8})_(\d{6})_(\d+)sec_lev1_V(\d+)$")
_BAND_RE = re.compile(r"(CDTE|CZT)([12])_LC_BAND_([\d.]+)KEV_TO_([\d.]+)KEV", re.I)
DETECTORS = ("cdte1", "cdte2", "czt1", "czt2")


@dataclass(frozen=True)
class Session:
    folder: Path
    start: pd.Timestamp
    duration_s: int
    version: int

    @property
    def name(self) -> str:
        return self.folder.name


def list_sessions(root: Path | None = None) -> list[Session]:
    root = Path(root) if root else config.hel1os_root()
    out = []
    for f in sorted(root.glob("*/*/*/HLS_*")):
        m = _SESSION_RE.match(f.name)
        if f.is_dir() and m:
            ymd, hms, dur, ver = m.groups()
            out.append(Session(f, pd.Timestamp(ymd + hms, tz="UTC"), int(dur), int(ver)))
    return out


def newest_per_session(sessions: list[Session], same_start_tol_s: int = 60) -> list[Session]:
    """Keep only the newest processing version per session.

    Sessions are the same observation when their start times agree within `same_start_tol_s` (durations may differ
    between versions, e.g. V211 3840 s vs V311 43193 s). Ties on version keep the longer duration.
    """
    kept: list[Session] = []
    for s in sorted(sessions, key=lambda x: (x.start, -x.version, -x.duration_s)):
        dup = next((k for k in kept if abs((k.start - s.start).total_seconds()) <= same_start_tol_s), None)
        if dup is None:
            kept.append(s)
        elif (s.version, s.duration_s) > (dup.version, dup.duration_s):
            kept[kept.index(dup)] = s
    return sorted(kept, key=lambda x: x.start)


def _band_label(ext_name: str) -> tuple[str, str] | None:
    m = _BAND_RE.match(ext_name)
    if not m:
        return None
    det = f"{m.group(1).lower()}{m.group(2)}"
    lo, hi = float(m.group(3)), float(m.group(4))
    return det, f"{lo:g}-{hi:g}keV"


def read_lightcurve_file(path: Path) -> pd.DataFrame:
    """One detector file -> wide frame, UTC index, columns `<det>_<band>` (CTR) and `<det>_<band>_err`."""
    cols = {}
    with fits.open(path) as h:
        for ext in h[1:]:
            lab = _band_label(ext.name)
            if lab is None:
                continue
            det, band = lab
            d = ext.data
            # MJD -> UTC; MJD 40587 == 1970-01-01. ISOT is also present; MJD is the numeric source of truth.
            secs = (np.asarray(d["MJD"], dtype="float64") - 40587.0) * 86400.0
            t = pd.to_datetime(np.round(secs, 3), unit="s", utc=True).as_unit("ms")
            s = pd.Series(np.asarray(d["CTR"], dtype="float64"), index=t)
            e = pd.Series(np.asarray(d["STAT_ERR"], dtype="float64"), index=t)
            cols[f"{det}_{band}"] = s[~s.index.duplicated()]
            cols[f"{det}_{band}_err"] = e[~e.index.duplicated()]
    df = pd.DataFrame(cols).sort_index()
    df.index.name = "time"
    return df


def read_session(session: Session) -> pd.DataFrame:
    """All detectors/bands of a session on a common 1 s grid (nearest-second rounding of the native timestamps)."""
    frames = []
    for sub, det in (("cdte", "cdte1"), ("cdte", "cdte2"), ("czt", "czt1"), ("czt", "czt2")):
        f = session.folder / sub / f"lightcurve_{det}.fits"
        if f.exists():
            frames.append(read_lightcurve_file(f))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, axis=1)
    out.index = out.index.round("1s")  # native stamps are ~1 s apart with sub-second offsets
    out = out[~out.index.duplicated(keep="first")]
    return out


def coverage(session: Session, df: pd.DataFrame) -> dict:
    """Real coverage: the observed span vs. the nominal duration in the folder name, plus gaps."""
    base = {"session": session.name, "version": session.version, "nominal_duration_s": session.duration_s}
    if df.empty:
        return {**base, "rows": 0, "span_s": 0.0, "coverage_of_nominal": 0.0, "gap_count": 0, "max_gap_s": 0.0}
    t = df.index.to_series()
    span = (t.iloc[-1] - t.iloc[0]).total_seconds()
    dt = t.diff().dt.total_seconds().dropna()
    gaps = dt[dt > 1.5]
    total = df.filter(regex=r"^(cdte|czt)[12]_[\d.\-]+keV$")
    return {
        **base,
        "start": t.iloc[0], "end": t.iloc[-1], "rows": len(df), "span_s": span,
        "coverage_of_nominal": float(min(len(df) / session.duration_s, 1.0)) if session.duration_s else np.nan,
        "coverage_of_span": float(len(df) / (span + 1)),
        "gap_count": int(len(gaps)), "max_gap_s": float(gaps.max()) if len(gaps) else 0.0,
        "bands": int(total.shape[1]),
    }


def load_optional(processed_dir: Path | None = None) -> pd.DataFrame | None:
    """Downstream entry point: processed HEL1OS table, or None when no HEL1OS data exists."""
    p = (Path(processed_dir) if processed_dir else config.processed_dir()) / "hel1os" / "sessions.parquet"
    return pd.read_parquet(p) if p.exists() else None


def attach_optional(base: pd.DataFrame, hel1os: pd.DataFrame | None) -> pd.DataFrame:
    """Join HEL1OS onto a SoLEXS frame by timestamp (backward-looking, no future leakage); no-op if absent."""
    if hel1os is None or hel1os.empty:
        return base
    return pd.merge_asof(
        base.sort_index(), hel1os.sort_index(), left_index=True, right_index=True,
        direction="backward", tolerance=pd.Timedelta(seconds=2),
    )
