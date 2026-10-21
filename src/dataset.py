"""Build the modelling dataset: causal 10 s features + labels, split chronologically by period.

Output: data/processed/dataset/{tune,val,test}.parquet, reports/dataset_summary.json.
Rows are assigned to a period by their timestamp; labels whose future window leaves the period are marked not ok
(purged), so no label crosses a period boundary.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src import config, features, goes, hel1os, labels

LABEL_PREFIXES = ("y_", "ok_")
META_COLUMNS = ("period",)


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if not c.startswith(LABEL_PREFIXES) and c not in META_COLUMNS]


def _fresh(path):
    if path.exists():
        path.chmod(0o666)
        path.unlink()
    return path


def label_changes(new: pd.DataFrame, old: pd.DataFrame, horizons: list[int]) -> dict:
    """Forecast positives under the new (GOES-direct) vs old (matched-detection) labels, on ok rows."""
    out = {}
    for h in horizons:
        ok = new[f"ok_{h}m"].astype(bool)
        for cls in ("c", "m"):
            col = f"y_{cls}_{h}m"
            n, o = new.loc[ok, col].astype(bool), old.loc[ok, col].astype(bool)
            out[col] = {"ok_rows": int(ok.sum()), "old_pos": int(o.sum()), "new_pos": int(n.sum()),
                        "gained": int((n & ~o).sum()), "lost": int((o & ~n).sum()),
                        "changed_frac_of_old": float(((n != o).sum()) / max(int(o.sum()), 1))}
    return out


def build_all() -> dict:
    P = config.load_params()
    fp, lp = P["features"], P["labels"]
    cad, windows = fp["cadence_s"], fp["windows_min"]
    proc = config.processed_dir()
    clean_dir = proc / "solexs_clean"
    events = pd.read_parquet(proc / "events.parquet")
    goes_list = pd.read_parquet(proc / "goes_matched.parquet")
    pairs = pd.read_parquet(proc / "events_pairs.parquet")
    valid_minutes = pd.read_parquet(proc / "solexs_minute.parquet")["m"].notna()
    gaps = goes.missing_days(*config.data_range())
    hel = hel1os.load_optional()
    warm = pd.Timedelta(minutes=max(windows) + 70)

    parts: dict[str, list[pd.DataFrame]] = {p: [] for p in config.PERIOD_NAMES}
    files = sorted(clean_dir.glob("*.parquet"))
    loaded: dict[pd.Timestamp, pd.Series] = {}
    for f in files:
        date = pd.Timestamp(f.stem, tz="UTC")
        cur = pd.read_parquet(f)["counts"].astype("float64")
        prev = loaded.get(date - pd.Timedelta(days=1))
        series = pd.concat([prev[prev.index > date - warm], cur]) if prev is not None else cur
        loaded = {date: cur}  # keep only yesterday in memory
        binned = features.bin_counts(series, cad)
        feat = features.solexs_features(binned, windows, cad)
        hf = features.hel1os_features(hel, feat.index, cad)
        if hf.shape[1]:
            feat = feat.join(hf)
        feat = feat[(feat.index > date) & (feat.index <= date + pd.Timedelta(days=1))]
        feat = feat[feat["rate"].notna() & (feat["valid_frac_5m"] >= fp["min_valid_frac_5m"])]
        per = config.assign_period(feat.index).to_numpy()
        for p in config.PERIOD_NAMES:
            sel = feat[per == p]
            if len(sel):
                parts[p].append(sel)

    out_dir = proc / "dataset"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict = {"cadence_s": cad, "periods": {}, "goes_missing_days": [str(d.date()) for d in gaps]}
    comparison: dict = {}
    for p in config.PERIOD_NAMES:
        df = pd.concat(parts[p]).astype("float32")
        lo, hi = config.period_bounds(p)
        label_args = (df.index, events, lp["horizons_min"], lp["min_class_c"], lp["min_class_m"], valid_minutes,
                      pd.Series(hi, index=df.index), gaps)
        lab = labels.make_labels(*label_args, goes=goes_list, pairs=pairs)
        if p != "test":  # how many forecast positives the GOES-direct labels changed (never computed for test)
            comparison[p] = label_changes(lab, labels.make_labels(*label_args), lp["horizons_min"])
        df = df.join(lab)
        df["period"] = p
        path = _fresh(out_dir / f"{p}.parquet")
        df.to_parquet(path, compression="zstd")
        s = {
            "rows": int(len(df)), "first": str(df.index.min()), "last": str(df.index.max()),
            "file_mb": round(path.stat().st_size / 1e6, 1), "n_features": len(feature_columns(df)),
        }
        summary["periods"][p] = s
        if p == "test":  # the test period stays unexamined: sizes only, no label statistics
            continue
        s["nowcast_pos_rate"] = float(df.loc[df["ok_now"], "y_now"].mean())
        for h in lp["horizons_min"]:
            ok = df[f"ok_{h}m"]
            s[f"{h}m"] = {"ok_rows": int(ok.sum()), "pos_rate_C": float(df.loc[ok, f"y_c_{h}m"].mean()),
                          "pos_rate_M": float(df.loc[ok, f"y_m_{h}m"].mean())}
    summary["feature_columns"] = feature_columns(df)
    reports = config.PROJECT_ROOT / "reports"
    reports.mkdir(exist_ok=True)
    _fresh(reports / "dataset_summary.json").write_text(json.dumps(summary, indent=2), newline="\n")
    _fresh(reports / "label_comparison.json").write_text(json.dumps(comparison, indent=2), newline="\n")
    print(json.dumps(comparison, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "feature_columns"}, indent=2))
    return summary
