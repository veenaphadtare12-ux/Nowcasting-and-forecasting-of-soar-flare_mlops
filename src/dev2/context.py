"""R2 context features. All strictly causal; every grid point is stamped with the moment its value is known.

Primary (Aditya-only): our own detector's events in the past 24/48/72 h. An event counts only once its end is
confirmed (`activity.end_known_time`): count of events whose end became known in (t - W, t], and the largest peak
(log10 counts/s) among them.

Secondary (non-Aditya, GOES-derived):
* GOES flare counts by class: a flare is known only from its end + 24 h (reporting latency). For window W the count
  covers flares whose known time is in (t - W, t], i.e. the latest W hours of the delayed list.
* NOAA SRS active-region summary: issued 00:30 UT; used from 01:00 UT of its date until the next one.
Product versions: NOAA SWPC "edited events" daily reports and "Solar Region Summary" daily text files, as mirrored at
NOAA NCEI (`src/noaa.py`), downloaded on 2026-11-13.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src import activity, config, noaa
from src.detection.matching import goes_flux

LOG_FLOOR = 0.1


def _grid(lo: pd.Timestamp, hi: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.date_range(lo.floor("min"), hi.ceil("min"), freq="1min", tz="UTC")


def _window_count_max(known: np.ndarray, value: np.ndarray, grid: pd.DatetimeIndex, w_h: int):
    """For each grid time T: number of items with known time in (T - W, T] and the max value among them (0 if none)."""
    o = np.argsort(known)
    k, v = known[o], value[o]
    T = grid.as_unit("ns").asi8.view("datetime64[ns]")
    W = np.timedelta64(w_h * 3600, "s")
    a = np.searchsorted(k, T - W, "right")
    b = np.searchsorted(k, T, "right")
    n = (b - a).astype("float32")
    mx = np.zeros(len(T), dtype="float32")
    for i in range(len(k)):        # each item raises the max on the grid span where it is inside the window
        s = np.searchsorted(T, k[i], "left")
        e = np.searchsorted(T, k[i] + W, "left")
        if e > s:
            np.maximum(mx[s:e], v[i], out=mx[s:e])
    return n, mx


def aditya_grid(events: pd.DataFrame, lo: pd.Timestamp, hi: pd.Timestamp) -> pd.DataFrame:
    """events: detector catalogue (trigger_time, end, peak_counts_s, hit_cap, ended_by_gap). Rows known before hi."""
    P = config.load_params()
    fd = P["flare_detection"]
    known = activity.end_known_time(events, fd["end_confirm_min"], fd["gap_end_min"])
    known = np.maximum(known.to_numpy(dtype="datetime64[ns]"), events["trigger_time"].to_numpy(dtype="datetime64[ns]"))
    keep = known < np.datetime64(hi.tz_localize(None))
    pk = np.log10(np.maximum(events["peak_counts_s"].to_numpy(dtype=float), LOG_FLOOR))[keep]
    g = _grid(lo, hi)
    out = {}
    for w in P["dev2"]["context_windows_h"]:
        n, mx = _window_count_max(known[keep], pk, g, w)
        out[f"ax_n_{w}h"], out[f"ax_max_peak_{w}h"] = n, mx
    grid = pd.DataFrame(out, index=g)
    return grid[grid.index < hi]


def goes_count_grid(flares: pd.DataFrame, lo: pd.Timestamp, hi: pd.Timestamp) -> pd.DataFrame:
    """flares: GOES list (begin, peak, end, goes_class). Known time = end (or peak, or begin) + latency."""
    P = config.load_params()["dev2"]
    lat = pd.Timedelta(hours=P["goes_count_latency_h"])
    endt = flares["end"].fillna(flares["peak"]).fillna(flares["begin"])
    known = (endt + lat).to_numpy(dtype="datetime64[ns]")
    keep = known < np.datetime64(hi.tz_localize(None))
    flux = flares["goes_class"].astype(str).map(goes_flux).to_numpy(dtype=float)
    g = _grid(lo, hi)
    out = {}
    for w in P["context_windows_h"]:
        for cls, sel in (("c", (flux >= goes_flux("C1.0")) & (flux < goes_flux("M1.0"))), ("m", flux >= goes_flux("M1.0"))):
            m = keep & sel
            n, _ = _window_count_max(known[m], np.zeros(m.sum(), dtype="float32"), g, w)
            out[f"gc_n_{cls}_{w}h"] = n
        lf = np.log10(np.maximum(flux[keep], 1e-9)) + 9.0   # 0 = nothing known; A1 = 1, C1 = 3, M1 = 4, X1 = 5
        _, mx = _window_count_max(known[keep], lf.astype("float32"), g, w)
        out[f"gc_max_class_{w}h"] = mx
    grid = pd.DataFrame(out, index=g)
    return grid[grid.index < hi]


# ---------------------------------------------------------------- NOAA SRS
_ISSUED = re.compile(r":Issued:\s+(\d{4} \w{3} \d{1,2} \d{4}) UTC")
_REGION = re.compile(r"^(\d{4,5})\s+[NS]\d\d[EW]\d\d\s+\d+\s+(\d+)\s+(\w{3})\s+\d+\s+(\d+)\s+([A-Za-z-]+)")


def parse_srs(text: str) -> dict | None:
    m = _ISSUED.search(text)
    if not m:
        return None
    issued = pd.Timestamp(pd.to_datetime(m.group(1), format="%Y %b %d %H%M"), tz="UTC")
    sec = text.split("I.  Regions with Sunspots", 1)
    regs = []
    if len(sec) == 2:
        for line in sec[1].split("IA.", 1)[0].splitlines()[1:]:
            r = _REGION.match(line.strip())
            if r:
                regs.append({"area": int(r.group(2)), "z": r.group(3), "nn": int(r.group(4)), "mag": r.group(5).lower()})
    area = np.array([r["area"] for r in regs], dtype=float)
    return {"issued": issued,
            "srs_n_regions": float(len(regs)),
            "srs_area_total_log": float(np.log10(1 + area.sum())),
            "srs_area_max_log": float(np.log10(1 + (area.max() if len(area) else 0))),
            "srs_spots_total": float(sum(r["nn"] for r in regs)),
            "srs_n_gamma": float(sum("gamma" in r["mag"] for r in regs)),
            "srs_n_delta": float(sum("delta" in r["mag"] for r in regs)),
            "srs_n_large_z": float(sum(r["z"][:1].upper() in "DEF" for r in regs))}


def srs_dir() -> Path:
    p = Path(config.load_params()["dev2"]["srs_dir"])
    return p if p.is_absolute() else config.PROJECT_ROOT / p


def fetch_srs_dev() -> None:
    """Development-period SRS files (tune start - 3 days .. end of the old test period)."""
    lo, hi = config.period_bounds("tune")[0] - pd.Timedelta(days=3), config.period_bounds("test")[1]
    days = pd.date_range(lo, hi - pd.Timedelta(days=1), freq="D")
    res = noaa.fetch_many([(noaa.SRS_URL.format(d=d), srs_dir() / f"{d:%Y%m%d}SRS.txt") for d in days])
    print(f"{sum(r is not None for r in res)} of {len(days)} SRS files; missing: "
          f"{[str(d.date()) for d, r in zip(days, res) if r is None]}")


def srs_grid(files: list[Path], lo: pd.Timestamp, hi: pd.Timestamp) -> pd.DataFrame:
    after = pd.Timedelta(minutes=config.load_params()["dev2"]["srs_available_after_min"])
    rows = [r for f in files if (r := parse_srs(f.read_text(errors="replace")))]
    df = pd.DataFrame(rows)
    df["avail"] = df["issued"].dt.floor("D") + after          # 00:30 issue -> used from 01:00 of the same date
    df["avail"] = np.maximum(df["avail"], df["issued"])
    df = df[df["avail"] < hi].drop(columns="issued").sort_values("avail").drop_duplicates("avail", keep="last")
    g = _grid(lo, hi)
    out = df.set_index("avail").reindex(g, method="ffill", tolerance=pd.Timedelta(hours=48))
    return out[out.index < hi].astype("float32")


if __name__ == "__main__":
    {"fetch_srs": fetch_srs_dev}[sys.argv[1]]()
