"""Cross-match of detected SoLEXS events with the GOES (NOAA) flare list, and per-period evaluation.

A GOES class is attached to a SoLEXS event ONLY through this match (SoLEXS gives counts, not W/m^2).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_CLASS_BASE = {"A": 1e-8, "B": 1e-7, "C": 1e-6, "M": 1e-5, "X": 1e-4}
MINUTE = pd.Timedelta(minutes=1)


def goes_flux(cls: str) -> float:
    """GOES class string ('C3.2') -> peak flux in W/m^2 (used only for ordering/thresholding GOES events)."""
    return _CLASS_BASE[cls[0]] * float(cls[1:] or 1)


def _ns(s: pd.Series) -> np.ndarray:
    return s.dt.as_unit("ns").astype("int64").to_numpy()


def match_goes(events: pd.DataFrame, goes: pd.DataFrame, tolerance_s: int = 300):
    """Many-to-many interval match: SoLEXS [onset, end] overlaps GOES [begin - tol, end + tol].

    Returns (events with is_goes_matched/goes_class columns, goes with n_solexs_matches, pairs frame).
    `goes_class` is the strongest overlapping GOES event; unmatched events get NA.
    """
    ev = events.copy().reset_index(drop=True)
    g = goes.copy().reset_index(drop=True)
    ev["n_goes_overlap"] = 0
    ev["is_goes_matched"] = False
    ev["goes_class"] = pd.NA
    ev["goes_class_all"] = pd.NA
    g["n_solexs_matches"] = 0
    pairs = []
    if len(ev) and len(g):
        tol = pd.Timedelta(seconds=tolerance_s)
        gb, ge = _ns(g["begin"] - tol), _ns(g["end"] + tol)
        flux = g["goes_class"].map(goes_flux).to_numpy()
        eo, ee = _ns(ev["onset"]), _ns(ev["end"])
        for k in range(len(ev)):
            hit = np.where((gb <= ee[k]) & (ge >= eo[k]))[0]
            if len(hit):
                ev.at[k, "n_goes_overlap"] = len(hit)
                ev.at[k, "is_goes_matched"] = True
                ev.at[k, "goes_class"] = g.at[hit[np.argmax(flux[hit])], "goes_class"]
                ev.at[k, "goes_class_all"] = ",".join(g.loc[hit, "goes_class"])
                g.loc[hit, "n_solexs_matches"] += 1
                pairs += [(k, int(h)) for h in hit]
    return ev, g, pd.DataFrame(pairs, columns=["event", "goes"])


def evaluate_period(
    ev: pd.DataFrame, g: pd.DataFrame, pairs: pd.DataFrame, valid_minutes: pd.Series,
    start: pd.Timestamp, end: pd.Timestamp, size_cut: float, long_event_s: float, duration_bins_min: list, exclude_days: list | None = None,
) -> dict:
    """Detector metrics for events with onset in [start, end) vs GOES flares peaking in valid data in [start, end)."""
    excl = pd.DatetimeIndex(exclude_days or [])
    e_idx = ev.index[(ev["onset"] >= start) & (ev["onset"] < end) & ~ev["onset"].dt.floor("D").isin(excl)]
    e = ev.loc[e_idx]
    pk = g["peak"].fillna(g["begin"])
    in_p = (pk >= start) & (pk < end)
    lab = (pk.dt.floor("min") + MINUTE)
    valid = lab.map(lambda t: bool(valid_minutes.get(t, False))).astype(bool)
    gg = g[in_p & valid & ~pk.dt.floor("D").isin(excl)]
    out: dict = {"goes_missing_days_excluded": [str(d.date()) for d in excl], "period": [str(start.date()), str((end - pd.Timedelta(days=1)).date())]}

    # --- events
    out["n_events"] = int(len(e))
    out["n_events_matched"] = int(e["is_goes_matched"].sum())
    out["match_rate_all"] = float(e["is_goes_matched"].mean()) if len(e) else None
    big = e["excess_counts_s"] >= size_cut
    out["size_cut_counts_s"] = size_cut
    out["n_events_above_cut"] = int(big.sum())
    out["precision_above_cut"] = float(e.loc[big, "is_goes_matched"].mean()) if big.any() else None

    # --- GOES recall
    rec = gg["n_solexs_matches"] > 0
    out["n_goes_flares"] = int(len(gg))
    out["goes_recall"] = float(rec.mean()) if len(gg) else None
    cls = gg["class_letter"]
    out["goes_recall_by_class"] = {
        c: {"n": int((cls == c).sum()), "recall": float(rec[cls == c].mean())} for c in sorted(cls.unique())
    }
    cm = cls.isin(["C", "M", "X"])
    out["goes_recall_C_and_above"] = float(rec[cm].mean()) if cm.any() else None

    # --- onset error vs GOES begin: per recalled GOES flare, nearest matched event onset
    errs = []
    if len(pairs):
        pr = pairs[pairs["goes"].isin(gg.index) & pairs["event"].isin(e_idx)]
        if len(pr):
            d = (ev.loc[pr["event"], "onset"].to_numpy() - g.loc[pr["goes"], "begin"].to_numpy()).astype("timedelta64[s]").astype(float) / 60.0
            tmp = pd.DataFrame({"goes": pr["goes"].to_numpy(), "err_min": d})
            tmp["abs"] = tmp["err_min"].abs()
            errs = tmp.loc[tmp.groupby("goes")["abs"].idxmin(), "err_min"].to_numpy()
    errs = np.asarray(errs, dtype=float)
    out["onset_error_min"] = {
        "n": int(len(errs)),
        "median_signed": float(np.median(errs)) if len(errs) else None,
        "median_abs": float(np.median(np.abs(errs))) if len(errs) else None,
        "p90_abs": float(np.percentile(np.abs(errs), 90)) if len(errs) else None,
    }

    # --- durations
    dm = e["duration_s"] / 60.0
    bins = list(duration_bins_min) + [np.inf]
    hist = pd.cut(dm, bins=bins, right=False).value_counts().sort_index()
    out["duration_hist_min"] = {f"{int(a.left)}-{'inf' if np.isinf(a.right) else int(a.right)}": int(n) for a, n in hist.items()}
    out["duration_median_min"] = float(dm.median()) if len(dm) else None
    out["n_events_gt_long"] = int((e["duration_s"] > long_event_s).sum())
    out["long_event_s"] = long_event_s
    out["n_hit_cap"] = int(e["hit_cap"].sum()) if "hit_cap" in e else None
    out["n_was_split"] = int(e["was_split"].sum()) if "was_split" in e else None
    out["detected_class_balance_via_goes"] = e.loc[e["is_goes_matched"], "goes_class"].str[0].value_counts().sort_index().to_dict()
    out["goes_class_balance"] = cls.value_counts().sort_index().to_dict()
    return out
