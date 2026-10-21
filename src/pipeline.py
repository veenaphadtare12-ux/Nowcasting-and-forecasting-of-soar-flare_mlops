"""Data-pipeline stages (run by DVC; each stage reads params.yaml, never hard-coded paths or dates).

    python -m src.pipeline fetch_goes | solexs_clean | detect_events | legacy_events | match_goes
                           | evaluate_detector | build_dataset | hel1os_index

Raw data is only ever read. Everything written goes to data/processed/ (or data/external/, reports/, docs/).
The TEST period is never evaluated or tuned on here; it only flows through to the final dataset file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src import config, goes, hel1os, solexs
from src.detection import detector, legacy, matching

REPORTS = config.PROJECT_ROOT / "reports"
MINUTE = pd.Timedelta(minutes=1)


def _clean_dir() -> Path:
    return config.processed_dir() / "solexs_clean"


def _p(name: str) -> Path:
    return config.processed_dir() / name


def _fresh(path: Path) -> Path:
    """Remove an existing output before writing it.

    DVC checks outputs out as read-only HARDLINKS into the cache; writing into one in place would modify the cached
    object. Unlinking first always creates a new file.
    """
    if path.exists():
        path.chmod(0o666)
        path.unlink()
    return path


def _last_day() -> pd.Timestamp:
    return config.data_range()[1] - pd.Timedelta(days=1)


# ---------------------------------------------------------------------------------------------------
def fetch_goes() -> None:
    lo, hi = config.data_range()
    res = goes.download_range(str((lo - pd.Timedelta(days=1)).date()), str((hi + pd.Timedelta(days=1)).date()))
    print(res)
    if res["missing"]:
        print("WARNING: no GOES report for", res["missing"])


def solexs_clean() -> None:
    P = config.load_params()
    sx = P["solexs"]
    lo, hi = config.data_range()
    days = solexs.list_days(detector=sx["detector"])
    complete, incomplete = solexs.select_days(days, str(lo.date()), str(_last_day().date()))
    out = _clean_dir()
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.parquet"):  # stage output is a function of params; rebuild from scratch
        _fresh(old)
    rows, minutes = [], []
    s = detector.DetectorSettings.from_params(P["flare_detection"])
    for d in complete:
        clean, qc = solexs.clean_day(d)
        qc["usable"] = bool(qc["valid_fraction"] >= sx["min_valid_fraction"])
        if qc["usable"]:
            minutes.append(detector.minute_means(clean["counts"], s.min_valid_s_per_min))
            clean["counts"] = clean["counts"].astype("float32")
            clean.to_parquet(out / f"{d.date:%Y%m%d}.parquet")
        rows.append(qc)
    for d in incomplete:  # GTI-only / missing light curve: excluded, but recorded
        rows.append({"date": f"{d.date:%Y-%m-%d}", "version": d.version, "usable": False, "valid_fraction": 0.0,
                     "reason": "incomplete (no light curve or no GTI)"})
    qc = pd.DataFrame(rows).sort_values("date")
    qc.to_csv(_fresh(_p("solexs_qc.csv")), index=False, lineterminator="\n")
    # continuous minute grid over the whole range; unusable / missing days are NaN rows (never filled)
    mm = pd.concat(minutes)
    mm = mm[~mm.index.duplicated()]
    grid = pd.date_range(lo + MINUTE, hi, freq="min", name="time")
    mm = mm.reindex(grid)
    mm["n"] = mm["n"].fillna(0).astype("int32")
    mm.to_parquet(_fresh(_p("solexs_minute.parquet")))
    print(f"days in range: {len(qc)}, usable: {int(qc['usable'].sum())}, incomplete: {len(incomplete)}, "
          f"low-coverage: {int((~qc['usable']).sum()) - len(incomplete)}; valid minutes {int(mm['m'].notna().sum())}")


def minute_series() -> pd.Series:
    return pd.read_parquet(_p("solexs_minute.parquet"))["m"]


# ---------------------------------------------------------------------------------------------------
def detect_events() -> None:
    P = config.load_params()
    s = detector.DetectorSettings.from_params(P["flare_detection"])
    ev = detector.detect_series(minute_series(), s)
    ev["period"] = config.assign_period(ev["onset"]).to_numpy()
    ev.to_parquet(_fresh(_p("events_raw.parquet")))
    summ = ev.groupby("period").agg(n=("onset", "size"), hit_cap=("hit_cap", "sum"), split=("was_split", "sum"))
    print(summ)


def _load_clean(date: pd.Timestamp) -> pd.Series | None:
    f = _clean_dir() / f"{date:%Y%m%d}.parquet"
    return pd.read_parquet(f)["counts"].astype("float64") if f.exists() else None


def legacy_events() -> None:
    """'Before' detector, only for comparison; run on tune+val days (never test)."""
    P = config.load_params()
    det = P["flare_detection_legacy"]
    warm = pd.Timedelta(seconds=det["background_window_s"])
    stop = config.period_bounds("val")[1]
    out = []
    for f in sorted(_clean_dir().glob("*.parquet")):
        date = pd.Timestamp(f.stem, tz="UTC")
        if date >= stop:
            continue
        cur = _load_clean(date)
        prev = _load_clean(date - pd.Timedelta(days=1))
        series = pd.concat([prev[prev.index >= date - warm], cur]) if prev is not None else cur
        ev = legacy.detect_day_legacy(series, **det)
        out.append(ev[(ev["onset"] >= date) & (ev["onset"] < date + pd.Timedelta(days=1))])
    ev = pd.concat(out, ignore_index=True)
    ev["hit_cap"] = False
    ev["was_split"] = False
    ev["period"] = config.assign_period(ev["onset"]).to_numpy()
    ev.to_parquet(_fresh(_p("legacy_events_raw.parquet")))
    print(f"legacy: {len(ev)} events")


# ---------------------------------------------------------------------------------------------------
def goes_list() -> pd.DataFrame:
    lo, hi = config.data_range()
    g = goes.load_flare_list()
    return g[(g["begin"] >= lo - pd.Timedelta(days=1)) & (g["begin"] < hi + pd.Timedelta(days=1))].reset_index(drop=True)


def match_goes() -> None:
    P = config.load_params()
    tol = P["goes_match"]["tolerance_s"]
    g = goes_list()
    for name in ("events", "legacy_events"):
        raw = pd.read_parquet(_p(f"{name}_raw.parquet"))
        ev, gm, pairs = matching.match_goes(raw, g, tol)
        ev.to_parquet(_fresh(_p(f"{name}.parquet")))
        pairs.to_parquet(_fresh(_p(f"{name}_pairs.parquet")))
        if name == "events":
            gm.to_parquet(_fresh(_p("goes_matched.parquet")))
        print(name, len(ev), "events;", int(ev["is_goes_matched"].sum()), "matched")


def evaluate_detector() -> None:
    """Metrics for tune and val only (test is never evaluated), new vs legacy, plus before/after plots."""
    from src.detection import plots

    P = config.load_params()
    cfg = P["evaluation"]
    mm = minute_series()
    valid = mm.notna()
    gm = pd.read_parquet(_p("goes_matched.parquet"))
    gaps = goes.missing_days(*config.data_range())
    res = {}
    for label in ("legacy_events", "events"):
        ev = pd.read_parquet(_p(f"{label}.parquet"))
        pairs = pd.read_parquet(_p(f"{label}_pairs.parquet"))
        # per-version GOES match counts (legacy and new match the same GOES list independently)
        g = gm.drop(columns="n_solexs_matches").copy()
        g["n_solexs_matches"] = 0
        if len(pairs):
            cnt = pairs.groupby("goes").size()
            g.loc[cnt.index, "n_solexs_matches"] = cnt.to_numpy()
        res["new" if label == "events" else "legacy"] = {
            per: matching.evaluate_period(
                ev, g, pairs, valid, *config.period_bounds(per),
                size_cut=cfg["size_cut_counts_s"], long_event_s=cfg["long_event_s"],
                duration_bins_min=cfg["duration_bins_min"], exclude_days=gaps,
            )
            for per in ("tune", "val")
        }
    REPORTS.mkdir(exist_ok=True)
    _fresh(REPORTS / "detection_metrics.json").write_text(json.dumps(res, indent=2, default=str), newline="\n")
    plots.make_all()
    for ver in res:
        for per in res[ver]:
            r = res[ver][per]
            print(ver, per, {k: r[k] for k in ("n_events", "match_rate_all", "precision_above_cut", "goes_recall_C_and_above",
                                                "n_events_gt_long", "n_hit_cap")}, r["onset_error_min"])


def build_dataset() -> None:
    from src import dataset

    dataset.build_all()


def train() -> None:
    """Fit rule / logistic regression / XGBoost per target on tune, select on val; never reads test."""
    from src.models import train as model_train

    model_train.run()


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
    pd.DataFrame(cov).to_csv(_fresh(out / "coverage.csv"), index=False, lineterminator="\n")
    allf = pd.concat(frames).sort_index().astype("float32")
    allf = allf[~allf.index.duplicated(keep="last")]
    allf.to_parquet(_fresh(out / "sessions.parquet"))
    print(f"{len(sessions)} sessions found, {len(kept)} kept (newest version), {len(allf)} rows")


STAGES = {
    f.__name__: f
    for f in (fetch_goes, solexs_clean, detect_events, legacy_events, match_goes, evaluate_detector,
              build_dataset, train, hel1os_index)
}

if __name__ == "__main__":
    STAGES[sys.argv[1]]()
