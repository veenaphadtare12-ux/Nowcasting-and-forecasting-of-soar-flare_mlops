"""Small, retrying downloader for public NOAA files (GOES XRS science files, SWPC event reports, SRS).

A 404 means the file does not exist on the server (returned as None); any other failure is retried and finally raised,
so a transient error is never mistaken for missing data.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

NGDC = "https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/daily_reports"
EVENTS_URL = NGDC + "/solar_event_reports/{d:%Y}/{d:%m}/{d:%Y%m%d}events.txt"
SRS_URL = NGDC + "/solar_region_summaries/{d:%Y}/{d:%m}/{d:%Y%m%d}SRS.txt"
XRS_BASE = "https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/goes/{sat}/l2/data/xrsf-l2-avg1m_science"


def xrs_name(sat: str, day: pd.Timestamp, version: str = "v2-2-2") -> str:
    return f"sci_xrsf-l2-avg1m_g{sat[-2:]}_d{day:%Y%m%d}_{version}.nc"


def xrs_url(sat: str, day: pd.Timestamp, version: str = "v2-2-2") -> str:
    return f"{XRS_BASE.format(sat=sat)}/{day:%Y}/{day:%m}/{xrs_name(sat, day, version)}"


def fetch(url: str, dest: Path, timeout: int = 60, tries: int = 5) -> Path | None:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(tries):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 404:
                return None
            if r.status_code == 200:
                tmp = dest.with_suffix(dest.suffix + ".part")
                tmp.write_bytes(r.content)
                tmp.replace(dest)
                return dest
            last = RuntimeError(f"HTTP {r.status_code} for {url}")
        except requests.RequestException as e:
            last = e
        time.sleep(2 ** attempt)
    raise RuntimeError(f"could not download {url}") from last


def fetch_many(jobs: list[tuple[str, Path]], workers: int = 6) -> list[Path | None]:
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(lambda j: fetch(*j), jobs))
