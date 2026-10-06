"""Data-pipeline stages (run by DVC; each stage reads params.yaml, never hard-coded paths).

    python -m src.pipeline fetch_goes | solexs_clean | solexs_flares | goes_match | hel1os_index

Raw data is only ever read. Everything written goes to data/processed/ (or data/external/ for the GOES lists).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src import config, flares, goes, hel1os, solexs

REPORTS = config.PROJECT_ROOT / "reports"


def _clean_dir() -> Path:
    return config.processed_dir() / "solexs_clean"


def fetch_goes() -> None:
    p = config.load_params()["subset"]
    # one day of margin either side so events crossing midnight are present
    start = (pd.Timestamp(p["start"]) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    end = (pd.Timestamp(p["end"]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    res = goes.download_range(start, end)
    print(res)
    if res["missing"]:
        print("WARNING: no GOES report for", res["missing"])


def solexs_clean() -> None:
    P = config.load_params()
    sub, sx = P["subset"], P["solexs"]
    days = solexs.list_days(detector=sx["detector"])
    complete, incomplete = solexs.select_days(days, sub["start"], sub["end"])
    out = _clean_dir()
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.parquet"):  # stage output is a function of params; rebuild from scratch
        old.unlink()
    rows = []
    for d in complete:
        clean, qc = solexs.clean_day(d)
        qc["usable"] = bool(qc["valid_fraction"] >= sx["min_valid_fraction"])
        if qc["usable"]:
            clean["counts"] = clean["counts"].astype("float32")
            clean.to_parquet(out / f"{d.date:%Y%m%d}.parquet")
        rows.append(qc)
    for d in incomplete:  # GTI-only / missing light curve: excluded, but recorded
        rows.append({"date": f"{d.date:%Y-%m-%d}", "version": d.version, "usable": False, "valid_fraction": 0.0,
                     "reason": "incomplete (no light curve or no GTI)"})
    qc = pd.DataFrame(rows).sort_values("date")
    qc.to_csv(config.processed_dir() / "solexs_qc.csv", index=False)
    print(f"days in range: {len(qc)}, usable: {int(qc['usable'].sum())}, "
          f"incomplete: {len(incomplete)}, low-coverage: {int((~qc['usable']).sum()) - len(incomplete)}")


def _load_clean(date: pd.Timestamp) -> pd.Series | None:
    f = _clean_dir() / f"{date:%Y%m%d}.parquet"
    return pd.read_parquet(f)["counts"].astype("float64") if f.exists() else None


def solexs_flares() -> None:
    P = config.load_params()
    det = P["flare_detection"]
    warm = pd.Timedelta(seconds=det["background_window_s"])
    out = []
    for f in sorted(_clean_dir().glob("*.parquet")):
        date = pd.Timestamp(f.stem, tz="UTC")
        cur = _load_clean(date)
        prev = _load_clean(date - pd.Timedelta(days=1))  # trailing warm-up only: causal
        series = pd.concat([prev[prev.index >= date - warm], cur]) if prev is not None else cur
        ev = flares.detect_day(series, **det)
        ev = ev[(ev["onset"] >= date) & (ev["onset"] < date + pd.Timedelta(days=1))]
        out.append(ev)
    fl = pd.concat(out, ignore_index=True) if out else pd.DataFrame()
    fl.to_parquet(config.processed_dir() / "flares.parquet")
    print(f"detected {len(fl)} flares in {len(out)} days")


def valid_intervals(max_gap_s: int = 120) -> pd.DataFrame:
    """Contiguous stretches of valid SoLEXS data (a gap longer than max_gap_s ends a stretch)."""
    spans = []
    for f in sorted(_clean_dir().glob("*.parquet")):
        t = pd.read_parquet(f).index
        br = np.where(np.diff(t.as_unit("s").asi8) > max_gap_s)[0]
        starts = np.r_[0, br + 1]
        stops = np.r_[br, len(t) - 1]
        spans += [(t[a], t[b]) for a, b in zip(starts, stops)]
    return pd.DataFrame(spans, columns=["start", "stop"])


def goes_match() -> None:
    P = config.load_params()
    fl = pd.read_parquet(config.processed_dir() / "flares.parquet")
    qc = pd.read_csv(config.processed_dir() / "solexs_qc.csv")
    usable = qc[qc["usable"]]["date"]
    lo, hi = pd.Timestamp(usable.min(), tz="UTC") - pd.Timedelta(days=1), pd.Timestamp(usable.max(), tz="UTC") + pd.Timedelta(days=2)
    g = goes.load_flare_list()
    g = g[(g["begin"] >= lo) & (g["begin"] < hi)].reset_index(drop=True)
    fm, gm = flares.match_goes(fl, g, P["goes_match"]["tolerance_s"])
    summary = flares.summarize_match(fm, gm, valid_intervals())
    summary["days_used"] = int(len(usable))
    summary["days_in_range"] = int(len(qc))
    summary["days_excluded"] = qc.loc[~qc["usable"], "date"].tolist()
    summary["detected_per_day"] = float(len(fm) / max(len(usable), 1))
    fm.to_parquet(config.processed_dir() / "flares_matched.parquet")
    gm.to_parquet(config.processed_dir() / "goes_matched.parquet")
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "metrics.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))


def hel1os_index() -> None:
    """Optional stage: parse HEL1OS (newest version per session) and report real coverage."""
    out = config.processed_dir() / "hel1os"
    out.mkdir(parents=True, exist_ok=True)
    sessions = hel1os.list_sessions()
    if not sessions:
        print("no HEL1OS sessions found; skipping (HEL1OS is optional)")
        (out / "coverage.csv").write_text("")
        return
    kept = hel1os.newest_per_session(sessions)
    frames, cov = [], []
    for s in kept:
        df = hel1os.read_session(s)
        cov.append(hel1os.coverage(s, df))
        frames.append(df)
    pd.DataFrame(cov).to_csv(out / "coverage.csv", index=False)
    allf = pd.concat(frames).sort_index()
    allf = allf[~allf.index.duplicated(keep="last")]
    allf.to_parquet(out / "sessions.parquet")
    print(f"{len(sessions)} sessions found, {len(kept)} kept (newest version), {len(allf)} rows")


STAGES = {f.__name__: f for f in (fetch_goes, solexs_clean, solexs_flares, goes_match, hel1os_index)}

if __name__ == "__main__":
    STAGES[sys.argv[1]]()
