"""NOAA SWPC edited solar event reports -> GOES X-ray (XRA) flare table.

Source: daily reports mirrored at NOAA NCEI/NGDC
  .../swpc-products/daily_reports/solar_event_reports/YYYY/MM/YYYYMMDDevents.txt
These carry GOES 1-8 A flare class, begin/max/end (UTC). Classes come ONLY from GOES, never from
SoLEXS counts.
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

from src import config

BASE_URL = (
    "https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/daily_reports/"
    "solar_event_reports/{y}/{m}/{ymd}events.txt"
)
EVENTS_DIR = "data/external/goes_events"

# '5590 +     0624   0628      0632  G19  5   XRA  1-8A      C3.2    7.6E-04   4055'
_XRA = re.compile(
    r"^(?P<evt>\S+)\s+(?:\+\s+)?"
    r"(?P<b>[BUD]?\d{4}|////)\s+(?P<m>[BUD]?\d{4}|////)\s+(?P<e>[BUD]?\d{4}|////)\s+"
    r"(?P<obs>\w{3})\s+\S\s+XRA\s+1-8A\s+(?P<cls>[A-Z]\d+(?:\.\d+)?)\s+(?P<int>\S+)(?:\s+(?P<reg>\d+))?"
)


def events_dir() -> Path:
    return config.PROJECT_ROOT / EVENTS_DIR


def download_day(day: pd.Timestamp, out_dir: Path | None = None, timeout: int = 60) -> Path | None:
    out_dir = out_dir or events_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    ymd = day.strftime("%Y%m%d")
    dest = out_dir / f"{ymd}events.txt"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    url = BASE_URL.format(y=day.strftime("%Y"), m=day.strftime("%m"), ymd=ymd)
    last_err = None
    for attempt in range(5):
        try:
            r = requests.get(url, timeout=timeout)
        except requests.RequestException as e:  # timeout / connection reset: retry with backoff
            last_err = e
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 404:
            return None  # NOAA has no report for this day: genuinely missing GOES truth
        if r.status_code == 200:
            dest.write_bytes(r.content)
            return dest
        last_err = RuntimeError(f"HTTP {r.status_code} for {url}")
        time.sleep(2 ** attempt)
    # never silently treat a transient failure as "no GOES data for this day"
    raise RuntimeError(f"could not download {url} after retries") from last_err


def download_range(start: str, end: str, workers: int = 4) -> dict:
    days = pd.date_range(start, end, freq="D")
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(download_day, days))
    missing = [d.strftime("%Y-%m-%d") for d, r in zip(days, res) if r is None]
    return {"requested": len(days), "downloaded": len(days) - len(missing), "missing": missing}


def _hhmm(day: pd.Timestamp, token: str):
    if token == "////":
        return pd.NaT
    token = token.lstrip("BUD")
    return day + pd.Timedelta(hours=int(token[:2]), minutes=int(token[2:]))


def parse_events_text(text: str, day: pd.Timestamp) -> list[dict]:
    rows = []
    for line in text.splitlines():
        m = _XRA.match(line)
        if not m:
            continue
        b, mx, e = (_hhmm(day, m.group(k)) for k in ("b", "m", "e"))
        # roll over midnight if the end (or max) wraps
        if pd.notna(b) and pd.notna(e) and e < b:
            e += pd.Timedelta(days=1)
        if pd.notna(b) and pd.notna(mx) and mx < b:
            mx += pd.Timedelta(days=1)
        rows.append(
            {
                "begin": b, "peak": mx, "end": e, "goes_class": m.group("cls"),
                "obs": m.group("obs"), "region": m.group("reg"),
                "integrated_flux": m.group("int"),
            }
        )
    return rows


def missing_days(start: pd.Timestamp, end: pd.Timestamp, events_path: Path | None = None) -> list[pd.Timestamp]:
    """UTC days in [start, end) with no downloaded NOAA event report (no GOES truth for those days)."""
    events_path = events_path or events_dir()
    have = {f.name[:8] for f in events_path.glob("*events.txt")}
    days = pd.date_range(start.tz_localize(None) if start.tzinfo else start, end.tz_localize(None) if end.tzinfo else end,
                         freq="D", inclusive="left")
    return [pd.Timestamp(d, tz="UTC") for d in days if d.strftime("%Y%m%d") not in have]


def load_flare_list(start: str | None = None, end: str | None = None, events_path: Path | None = None) -> pd.DataFrame:
    """All GOES XRA flares in downloaded reports, UTC-aware, one row per event."""
    events_path = events_path or events_dir()
    rows = []
    for f in sorted(events_path.glob("*events.txt")):
        day = pd.Timestamp(f.name[:8])
        if start and day < pd.Timestamp(start):
            continue
        if end and day > pd.Timestamp(end):
            continue
        rows += parse_events_text(f.read_text(errors="replace"), day)
    df = pd.DataFrame(rows, columns=["begin", "peak", "end", "goes_class", "obs", "region", "integrated_flux"])
    if df.empty:
        return df
    for c in ("begin", "peak", "end"):
        df[c] = pd.to_datetime(df[c], utc=True)
    # Several GOES satellites may report the same flare; keep one row per (begin, class)
    df = df.drop_duplicates(subset=["begin", "goes_class"]).sort_values("begin").reset_index(drop=True)
    df["class_letter"] = df["goes_class"].str[0]
    return df


if __name__ == "__main__":
    p = config.load_params()["subset"]
    print(download_range(p["start"], p["end"]))
