"""E6 data stage: NOAA GOES-19 XRS L2 1-minute averages (public), tune + val days only.

    python -m src.improve.goes_xrs fetch     ->  data/external/goes_xrs/*.nc       (daily files, never modified)
    python -m src.improve.goes_xrs process   ->  data/processed/goes_xrs_minute.parquet

Only daily files up to the last validation day are downloaded, so no test-period values are ever on disk.
Each record's time is the START of its minute; the value is known only at the END, so it is labelled start + 60 s.
Only good-quality minutes (flag 0) are kept.
"""
from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd
import requests

from src import config

J2000 = pd.Timestamp("2000-01-01 12:00:00", tz="UTC")


def _dir():
    return config.PROJECT_ROOT / "data" / "external" / "goes_xrs"


def _days():
    lo, hi = config.period_bounds("tune")[0], config.period_bounds("val")[1]
    return pd.date_range(lo, hi - pd.Timedelta(days=1), freq="D")


def fetch() -> None:
    g = config.load_params()["improve"]["goes_xrs"]
    out = _dir()
    out.mkdir(parents=True, exist_ok=True)
    missing = []
    for d in _days():
        name = f"sci_xrsf-l2-avg1m_{g['satellite']}_d{d:%Y%m%d}_{g['version']}.nc"
        p = out / name
        if p.exists() and p.stat().st_size > 0:
            continue
        url = f"{g['base_url']}/{d:%Y}/{d:%m}/{name}"
        for attempt in range(4):
            try:
                r = requests.get(url, timeout=60)
                if r.status_code == 200:
                    p.write_bytes(r.content)
                    break
                if r.status_code == 404:
                    missing.append(name)
                    break
            except requests.RequestException:
                pass
            time.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError(f"could not download {url}")
    print(f"{len(list(out.glob('*.nc')))} files in {out}; missing on server: {missing}")


def read_day(path) -> pd.DataFrame:
    import h5py

    with h5py.File(path, "r") as f:
        t = J2000 + pd.to_timedelta(f["time"][:], unit="s")
        cols = {}
        for ch in ("xrsa", "xrsb"):
            v = f[f"{ch}_flux"][:].astype("float64")
            v[(f[f"{ch}_flag"][:] != 0) | ~np.isfinite(v) | (v <= 0)] = np.nan
            cols[ch] = v
    return pd.DataFrame(cols, index=pd.DatetimeIndex(t + pd.Timedelta(seconds=60), name="time"))


def process() -> pd.DataFrame:
    hi = config.period_bounds("val")[1]
    files = sorted(_dir().glob("*.nc"))
    x = pd.concat([read_day(f) for f in files]).sort_index()
    x = x[~x.index.duplicated(keep="first")]
    x.index = x.index.round("min")
    x = x[x.index <= hi].astype("float32")
    p = config.processed_dir() / "goes_xrs_minute.parquet"
    if p.exists():
        p.chmod(0o666)
        p.unlink()
    x.to_parquet(p)
    print(f"{len(files)} files, {len(x)} minutes, good xrsb {x['xrsb'].notna().mean():.3f} -> {p}")
    return x


if __name__ == "__main__":
    {"fetch": fetch, "process": process}[sys.argv[1]]()
