"""Test-period inputs for the one-time test scoring (stages solexs_spectral_test, goes_xrs_test_fetch, goes_xrs_test_minute).

These only prepare raw-derived inputs (spectral band rates, GOES XRS flux) for the test days with exactly the same code
as the tune/val versions (src/improve/spectral.py, src/improve/goes_xrs.py). They read no labels and score nothing;
their outputs are used only by src/final/evaluate_test.py and src/final/analysis.py.

    python -m src.final.test_inputs spectral | goes_fetch | goes_process
"""
from __future__ import annotations

import sys
import time

import pandas as pd
import requests

from src import config, solexs
from src.detection import detector
from src.improve import goes_xrs, spectral

OUT = config.processed_dir() / "final"
GOES_DIR = config.PROJECT_ROOT / "data" / "external" / "goes_xrs_test"


def _fresh(p):
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        p.chmod(0o666)
        p.unlink()
    return p


def spectral_test() -> None:
    P = config.load_params()
    sp = P["improve"]["spectral"]
    s = detector.DetectorSettings.from_params(P["flare_detection"])
    lo, hi = config.period_bounds("test")
    qc = pd.read_csv(config.processed_dir() / "solexs_qc.csv")
    usable = set(qc.loc[qc["usable"].astype(bool), "date"])
    days = [d for d in solexs.list_days(detector=P["solexs"]["detector"])
            if d.complete and lo <= d.date < hi and d.date.strftime("%Y-%m-%d") in usable]
    parts, t0 = [], time.time()
    for d in days:
        pi = d.lc.with_name(d.lc.name.replace(".lc.gz", ".pi.gz"))
        if not pi.exists():
            continue
        r = spectral.band_rates(pi, solexs.read_gti(d.gti), sp["low_channels"], sp["high_channels"])
        if not r.empty:
            parts.append(pd.DataFrame({c: detector.minute_means(r[c], s.min_valid_s_per_min)["m"] for c in ("low", "high", "total")}))
    out = pd.concat(parts).sort_index()
    out = out[~out.index.duplicated(keep="first")].astype("float32")
    out.to_parquet(_fresh(OUT / "solexs_spectral_minute_test.parquet"))
    print(f"{len(days)} test days, {len(out)} minutes, {time.time() - t0:.0f}s")


def goes_fetch() -> None:
    g = config.load_params()["improve"]["goes_xrs"]
    GOES_DIR.mkdir(parents=True, exist_ok=True)
    lo, hi = config.period_bounds("test")
    missing = []
    for d in pd.date_range(lo, hi - pd.Timedelta(days=1), freq="D"):
        name = f"sci_xrsf-l2-avg1m_{g['satellite']}_d{d:%Y%m%d}_{g['version']}.nc"
        p = GOES_DIR / name
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
    print(f"{len(list(GOES_DIR.glob('*.nc')))} files; missing on server: {missing}")


def goes_process() -> None:
    lo, hi = config.period_bounds("test")
    x = pd.concat([goes_xrs.read_day(f) for f in sorted(GOES_DIR.glob("*.nc"))]).sort_index()
    x = x[~x.index.duplicated(keep="first")]
    x.index = x.index.round("min")
    x = x[(x.index > lo) & (x.index <= hi)].astype("float32")
    x.to_parquet(_fresh(OUT / "goes_xrs_minute_test.parquet"))
    print(f"{len(x)} minutes, good xrsb {x['xrsb'].notna().mean():.3f}")


if __name__ == "__main__":
    {"spectral": spectral_test, "goes_fetch": goes_fetch, "goes_process": goes_process}[sys.argv[1]]()
