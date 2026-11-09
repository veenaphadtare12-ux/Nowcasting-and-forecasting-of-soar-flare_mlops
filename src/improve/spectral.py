"""E5 data stage: 1-min SoLEXS SDD2 band rates from the 1-s .pi spectra (tune + val days only).

    python -m src.improve.spectral   ->  data/processed/solexs_spectral_minute.parquet

Same cleaning as the light curve (inside GTI, non-NaN), same minute convention (label = minute end, NaN when fewer
than the minimum valid seconds). Bands are PI-channel ranges from params (`improve.spectral`); the files carry no
energy calibration, so the bands are defined by channel.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
from astropy.io import fits

from src import config, solexs
from src.detection import detector


def band_rates(pi_path, gti: pd.DataFrame, low: list[int], high: list[int]) -> pd.DataFrame:
    with fits.open(pi_path) as h:
        d = h["SPECTRUM"].data
        t = pd.to_datetime(np.asarray(d["TSTART"], dtype="float64"), unit="s", utc=True)
        c = np.asarray(d["COUNTS"], dtype="float64")
        expo = np.asarray(d["EXPOSURE"], dtype="float64")
    valid = ~np.isnan(c).all(axis=1) & solexs.gti_mask(pd.DatetimeIndex(t), gti) & (expo > 0)
    c, expo, t = c[valid], expo[valid], pd.DatetimeIndex(t)[valid]
    return pd.DataFrame({"low": np.nansum(c[:, low[0]:low[1]], 1) / expo, "high": np.nansum(c[:, high[0]:high[1]], 1) / expo,
                         "total": np.nansum(c, 1) / expo}, index=t) if len(t) else pd.DataFrame(columns=["low", "high", "total"])


def build() -> pd.DataFrame:
    P = config.load_params()
    sp = P["improve"]["spectral"]
    s = detector.DetectorSettings.from_params(P["flare_detection"])
    lo, hi = config.period_bounds("tune")[0], config.period_bounds("val")[1]
    qc = pd.read_csv(config.processed_dir() / "solexs_qc.csv")
    usable = set(qc.loc[qc["usable"].astype(bool), "date"])
    days = [d for d in solexs.list_days(detector=P["solexs"]["detector"])
            if d.complete and lo <= d.date < hi and d.date.strftime("%Y-%m-%d") in usable]
    parts, t0 = [], time.time()
    for i, d in enumerate(days):
        pi = d.lc.with_name(d.lc.name.replace(".lc.gz", ".pi.gz"))
        if not pi.exists():
            continue
        r = band_rates(pi, solexs.read_gti(d.gti), sp["low_channels"], sp["high_channels"])
        if r.empty:
            continue
        cols = {c: detector.minute_means(r[c], s.min_valid_s_per_min)["m"] for c in ("low", "high", "total")}
        parts.append(pd.DataFrame(cols))
        if i % 50 == 0:
            print(f"{i}/{len(days)} {d.date:%Y-%m-%d} {time.time() - t0:.0f}s", flush=True)
    out = pd.concat(parts).sort_index()
    out = out[~out.index.duplicated(keep="first")].astype("float32")
    assert out.index.max() <= hi, "test-period minutes found"
    path = config.processed_dir() / "solexs_spectral_minute.parquet"
    if path.exists():
        path.chmod(0o666)
        path.unlink()
    out.to_parquet(path)
    print(f"{len(days)} days, {len(out)} minutes, {time.time() - t0:.0f}s -> {path}")
    return out


if __name__ == "__main__":
    build()
