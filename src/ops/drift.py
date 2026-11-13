"""check_drift logic: Evidently data-drift report, training features vs a recent window of development data.

Default reference = the champions' fit block (2025-04-09 .. 2026-04-30); default current = the last 30 days of
development data. Windows after the development end are refused (holdout data is never read). No model is run.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src import config
from src.ops.locks import check_window, dev_window

OUT = config.PROJECT_ROOT / "reports" / "drift"
SHARE_FLAG = 0.5  # flag drift when at least half of the features drifted (Evidently's default dataset rule)


def default_windows() -> dict:
    lo, hi = dev_window()
    fit_end = pd.Timestamp(config.load_params()["final"]["fit_end"], tz="UTC")
    return {"reference": (lo, fit_end), "current": (hi - pd.Timedelta(days=30), hi)}


def drift_report(
    ref: pd.DataFrame,
    cur: pd.DataFrame,
    features: list[str],
    out_dir: Path | None = None,
    name: str = "drift",
    max_rows: int = 20000,
    seed: int = 0,
) -> dict:
    from evidently import Report
    from evidently.presets import DataDriftPreset

    out_dir = Path(out_dir) if out_dir else OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    pick = lambda d: d.iloc[np.sort(rng.choice(len(d), min(max_rows, len(d)), replace=False))]  # noqa: E731
    feats = [f for f in features if ref[f].notna().any() and cur[f].notna().any()]  # e.g. HEL1OS absent in a window
    snap = Report([DataDriftPreset()]).run(
        current_data=pick(cur)[feats].astype(float), reference_data=pick(ref)[feats].astype(float)
    )
    d = snap.dict()
    per_col, share = {}, None
    for m in d["metrics"]:
        mid = str(m.get("metric_name") or m.get("metric_id"))
        if mid.startswith("DriftedColumnsCount"):
            share = float(m["value"]["share"])
        elif mid.startswith("ValueDrift(column="):
            col = mid.split("column=")[1].split(",")[0]
            thr = float(mid.split("threshold=")[1].rstrip(")")) if "threshold=" in mid else None
            method = mid.split("method=")[1].split(",")[0] if "method=" in mid else ""
            v = float(m["value"])
            # p-value tests drift when p < threshold; distance measures (Wasserstein, PSI, ...) when distance >= threshold
            drifted = None if thr is None else (v < thr if "p_value" in method else v >= thr)
            per_col[col] = {"score": v, "method": method, "threshold": thr, "drifted": drifted}
    summary = {
        "name": name,
        "n_reference": int(min(max_rows, len(ref))),
        "n_current": int(min(max_rows, len(cur))),
        "features_checked": len(feats),
        "features_skipped_all_missing": sorted(set(features) - set(feats)),
        "drifted_share": share,
        "drift_flag": bool(share is not None and share >= SHARE_FLAG),
        "drifted_features": sorted(c for c, v in per_col.items() if v["drifted"]),
        "per_feature_agrees_with_evidently": share is None
        or abs(sum(bool(v["drifted"]) for v in per_col.values()) / max(len(feats), 1) - share) < 1e-9,
        "per_feature": per_col,
    }
    snap.save_html(str(out_dir / f"{name}.html"))
    (out_dir / f"{name}.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8", newline="\n")
    return summary


def run_default(out_dir: Path | None = None) -> dict:
    """Training block vs the last 30 days of development data (feature columns only; labels are not read)."""
    from src.dev2 import protocol

    feats = json.loads((config.PROJECT_ROOT / "reports" / "dataset_summary.json").read_text(encoding="utf-8"))["feature_columns"]
    w = default_windows()
    for s, e in w.values():
        check_window(s, e, kind="dev")
    d = protocol.load(feats)  # development periods only
    sel = lambda a, b: d[(d.index >= a) & (d.index < b)]  # noqa: E731
    name = f"drift_{w['current'][0]:%Y%m%d}_{w['current'][1]:%Y%m%d}"
    return drift_report(sel(*w["reference"]), sel(*w["current"]), feats, out_dir, name)
