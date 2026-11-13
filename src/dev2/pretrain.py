"""R3: pretraining on GOES XRS 1-min flux (2017-02-07 .. 2025-03-28, GOES-16), evaluated on SoLEXS with and without
fine-tuning, under the 14-month rolling protocol.

    python -m src.dev2.pretrain fetch      # GOES-16 XRS science files + NOAA event reports for the pretraining years
    python -m src.dev2.pretrain mapping    # background-normalised GOES vs SoLEXS check against the EDA power law
    python -m src.dev2.pretrain run        # pretrain, then zero-shot / fine-tune / stacked, rolling 14 months

Common, background-normalised features (computed the same way on any 1-min light curve x labelled at minute end):
    bg = trailing 60-min 20 % quantile of x;  n_r_now = log10(x / bg);  n_r_mean5, n_r_max15, n_r_max60, n_r_max6h,
    n_r_max24h = log10(window statistic / bg);  n_slope5, n_slope15 = trailing slope of log10 x per minute;
    n_accel = n_slope5 - its value 5 min earlier;  n_bg_change24h = log10(bg / bg 24 h earlier).
Ratios and log slopes do not depend on the instrument's units, which is what makes GOES and SoLEXS comparable.
Labels for pretraining: a GOES flare of class >= C / >= M STARTS (event-report begin) in (t, t + h]. Classes in
GOES-13/14/15 reports carry NOAA's old 0.7 scaling and are divided by 0.7 to match the GOES-16+ (science) scale.
No pretraining row, label window or lookback reaches an evaluation month (all end before 2025-03-28).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from src import config, goes, noaa
from src.detection.matching import goes_flux
from src.dev2 import protocol as pr
from src.improve import features_extra as fx
from src.improve import goes_xrs

OUT = config.PROJECT_ROOT / "reports" / "dev2"
NORM = ["n_r_now", "n_r_mean5", "n_r_max15", "n_r_max60", "n_r_max6h", "n_r_max24h", "n_slope5", "n_slope15",
        "n_accel", "n_bg_change24h"]
OLD_SATS = {"G13", "G14", "G15"}


def R() -> dict:
    return config.load_params()["dev2"]["r3"]


def _p(key: str) -> Path:
    p = Path(R()[key])
    return p if p.is_absolute() else config.PROJECT_ROOT / p


def days() -> pd.DatetimeIndex:
    return pd.date_range(R()["start"], R()["end"], freq="D")


# ---------------------------------------------------------------- data
def fetch() -> None:
    r = R()
    ds = days()
    ev_days = pd.date_range(pd.Timestamp(r["start"]) - pd.Timedelta(days=2), pd.Timestamp(r["end"]) + pd.Timedelta(days=1))
    jobs = [(noaa.xrs_url(r["satellite"], d), _p("xrs_dir") / noaa.xrs_name(r["satellite"], d)) for d in ds]
    jobs += [(noaa.EVENTS_URL.format(d=d), _p("events_dir") / f"{d:%Y%m%d}events.txt") for d in ev_days]
    t0 = time.time()
    res = noaa.fetch_many(jobs, workers=8)
    miss = [j[1].name for j, x in zip(jobs, res) if x is None]
    print(f"{len(jobs) - len(miss)} of {len(jobs)} files in {time.time() - t0:.0f}s; missing on server: {len(miss)} {miss[:10]}")


def goes16_minutes() -> pd.Series:
    files = sorted(_p("xrs_dir").glob("*.nc"))
    x = pd.concat([goes_xrs.read_day(f)["xrsb"] for f in files]).sort_index()
    x = x[~x.index.duplicated(keep="first")]
    x.index = x.index.round("min")
    end = pd.Timestamp(R()["end"], tz="UTC") + pd.Timedelta(days=1)
    return x[x.index <= end].astype("float64")


def hist_flares() -> pd.DataFrame:
    g = goes.load_flare_list(events_path=_p("events_dir"))
    flux = g["goes_class"].astype(str).map(goes_flux)
    g["flux"] = np.where(g["obs"].isin(OLD_SATS), flux / R()["old_sat_scale"], flux)
    return g


# ---------------------------------------------------------------- common normalised features
def norm_grid(x: pd.Series) -> pd.DataFrame:
    """x: 1-min light curve labelled at minute end (any units). Returns the NORM features on a full 1-min grid."""
    r = R()
    x = fx._full_minutes(x.where(x > 0))
    lx = np.log10(x)
    bg = x.rolling(r["bg_window_min"], min_periods=10).quantile(r["bg_quantile"])
    lbg = np.log10(bg)
    g = pd.DataFrame(index=x.index)
    g["n_r_now"] = lx - lbg
    g["n_r_mean5"] = np.log10(x.rolling(5, min_periods=3).mean()) - lbg
    for name, w, mp in (("n_r_max15", "15min", 8), ("n_r_max60", "60min", 30), ("n_r_max6h", "6h", 180), ("n_r_max24h", "24h", 720)):
        g[name] = np.log10(x.rolling(w, min_periods=mp).max()) - lbg
    g["n_slope5"] = fx._rolling_slope(lx, "5min", 3) / 60.0        # _rolling_slope is per hour -> per minute
    g["n_slope15"] = fx._rolling_slope(lx, "15min", 8) / 60.0
    g["n_accel"] = g["n_slope5"] - g["n_slope5"].shift(5)
    g["n_bg_change24h"] = lbg - lbg.shift(1440)
    return g.astype("float32")


def onset_labels(index: pd.DatetimeIndex, starts: np.ndarray, h: int) -> np.ndarray:
    """1 where a flare start lies in (t, t + h min]."""
    t = index.as_unit("ns").asi8
    s = np.sort(starts)
    return (np.searchsorted(s, t + h * 60_000_000_000, "right") - np.searchsorted(s, t, "right")) > 0


def pretrain_frame() -> tuple[pd.DataFrame, list[str]]:
    """GOES-16 rows (every stride minutes) with NORM features and the 4 labels + ok flags."""
    r = R()
    x = goes16_minutes()
    g = norm_grid(x)
    fl = hist_flares()
    begin = fl["begin"].dropna()
    starts_c = begin[fl.loc[begin.index, "flux"] >= goes_flux("C1.0")].to_numpy(dtype="datetime64[ns]").astype("int64")
    starts_m = begin[fl.loc[begin.index, "flux"] >= goes_flux("M1.0")].to_numpy(dtype="datetime64[ns]").astype("int64")
    valid = x.reindex(g.index).notna()
    end = pd.Timestamp(r["end"], tz="UTC") + pd.Timedelta(days=1)
    have = {f.name[:8] for f in _p("events_dir").glob("*events.txt")}
    day_ok = pd.Series([d.strftime("%Y%m%d") in have for d in g.index.floor("D")], index=g.index)
    rows = g.iloc[:: r["stride_min"]].copy()
    rows = rows[rows[NORM].notna().sum(axis=1) >= 8]
    tgts = {}
    for h in (60, 120):
        fut = valid.astype(float).iloc[::-1].rolling(h, min_periods=1).mean().iloc[::-1].shift(-1)  # share of (t, t+h] observed
        ok = (fut.reindex(rows.index) >= 0.5) & day_ok.reindex(rows.index) & (rows.index <= end - pd.Timedelta(minutes=h))
        ok &= day_ok.reindex(rows.index + pd.Timedelta(minutes=h)).fillna(False).to_numpy()
        rows[f"ok_{h}m"] = ok.to_numpy()
        rows[f"y_c_{h}m"] = onset_labels(rows.index, starts_c, h)
        rows[f"y_m_{h}m"] = onset_labels(rows.index, starts_m, h)
        tgts[h] = ok
    return rows, NORM


# ---------------------------------------------------------------- mapping check
def mapping() -> dict:
    """Peak of each GOES-matched SoLEXS detection: log10(SoLEXS peak / bg) vs log10(GOES peak / GOES bg), and the
    EDA power law: SoLEXS peak excess (counts/s) ~ GOES peak flux ^ 1.34. Development data only."""
    proc = config.processed_dir()
    ev = pd.read_parquet(proc / "events.parquet")
    ev = ev[ev["is_goes_matched"].astype(bool) & (ev["onset"] < pr.dev_end())]
    from src.final import features as ff

    gx = ff._source("goes", include_test=True)["xrsb"].dropna()
    gbg = gx.rolling("60min", min_periods=10).quantile(0.2)
    rows = []
    for _, e in ev.iterrows():
        w = gx[(gx.index > e["onset"]) & (gx.index <= e["end"] + pd.Timedelta(minutes=2))]
        if len(w) < 3:
            continue
        b = gbg.asof(e["onset"])
        if not np.isfinite(b) or b <= 0:
            continue
        rows.append({"sx_ratio": np.log10(e["peak_counts_s"] / max(e["bg_counts_s"], 0.1)),
                     "gx_ratio": np.log10(w.max() / b), "sx_excess": np.log10(max(e["excess_counts_s"], 0.1)),
                     "gx_peak": np.log10(w.max()), "cls": str(e["goes_class"])[:1]})
    d = pd.DataFrame(rows)
    d = d[np.isfinite(d).all(axis=1) if False else d.notna().all(axis=1)]
    big = d[d["cls"].isin(["C", "M", "X"])]
    s_pl, i_pl = np.polyfit(big["gx_peak"], big["sx_excess"], 1)
    s_r, i_r = np.polyfit(d["gx_ratio"], d["sx_ratio"], 1)
    out = {"n_flares": int(len(d)), "n_c_or_more": int(len(big)),
           "power_law_slope_excess_vs_goes_flux": float(s_pl), "eda_power_law_slope": 1.34,
           "ratio_slope_solexs_vs_goes": float(s_r), "ratio_intercept": float(i_r),
           "ratio_corr": float(np.corrcoef(d["gx_ratio"], d["sx_ratio"])[0, 1]),
           "median_ratio_solexs_over_goes": float(np.median(d["sx_ratio"] / d["gx_ratio"].where(d["gx_ratio"] > 0.05)))}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "r3_mapping.json").write_text(json.dumps(out, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    {"fetch": fetch, "mapping": mapping}[sys.argv[1]]()
