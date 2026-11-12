"""Read-only sanity check of the one-time test results -> reports/final/sanity.json (docs/TEST_SANITY.md).

    python -m src.final.sanity

Nothing is fitted, tuned or scored again: test numbers come from data/processed/final/test_scores.parquet (frozen scores
written by evaluate_test) with the frozen thresholds in models_final/thresholds.json. The test dataset file is not read.
"""
from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd

from src import config
from src.detection.matching import goes_flux
from src.final import analysis
from src.final.freeze import MODEL_DIR, REPORT, _fresh
from src.improve import features_extra as fx
from src.improve import protocol as pr
from src.models import metrics, train

TARGETS = ["now", "c_30m", "c_60m", "m_30m", "m_60m"]
MIN_CLASS = {"c_30m": "C1.0", "c_60m": "C1.0", "m_30m": "M1.0", "m_60m": "M1.0"}
HORIZON = {"c_30m": 30, "c_60m": 60, "m_30m": 30, "m_60m": 60}


def tss(y, yhat) -> float:
    return float(metrics.tss(metrics.contingency(np.asarray(y).astype(bool), np.asarray(yhat).astype(bool))))


def main() -> dict:
    proc = config.processed_dir()
    P = config.load_params()
    thr = json.loads((MODEL_DIR / "thresholds.json").read_text(encoding="utf-8"))
    sc = pd.read_parquet(proc / "final" / "test_scores.parquet")
    out = {}

    # 1a. base rates (ok rows): tune / val from the datasets, test from the frozen score file
    tv = pr.load(sorted({c for t in TARGETS for c in train.TARGETS[t]}) + [train.FLAG])
    rates = {}
    for t in TARGETS:
        y, ok = train.TARGETS[t]
        r = {}
        for per in ("tune", "val"):
            lo, hi = config.period_bounds(per)
            d = tv[(tv.index >= lo) & (tv.index < hi)]
            d = d[d[ok].astype(bool)]
            r[per] = float(d[y].mean())
        s = sc[sc[f"ok_{t}"]]
        r["test"] = float(s[f"y_{t}"].mean())
        rates[t] = r
    out["base_rates"] = rates

    # 1b. GOES flares per month by class (peak month), tune+val average vs each test month
    g = pd.read_parquet(proc / "goes_matched.parquet")
    g = g[g["peak"].fillna(g["begin"]) < config.period_bounds("test")[1]]
    g["month"] = g["peak"].fillna(g["begin"]).dt.tz_localize(None).dt.to_period("M").astype(str)
    cnt = g.groupby(["month", "class_letter"]).size().unstack(fill_value=0).reindex(columns=list("BCMX"), fill_value=0)
    t0 = config.period_bounds("test")[0]
    test_months = [m for m in cnt.index if m >= t0.strftime("%Y-%m")]
    tv_months = [m for m in cnt.index if "2025-04" <= m < t0.strftime("%Y-%m")]
    out["goes_per_month"] = {"test": {m: cnt.loc[m].astype(int).to_dict() for m in test_months},
                             "tune_val_mean": cnt.loc[tv_months].mean().round(1).to_dict(),
                             "tune_val_max_M": int(cnt.loc[tv_months, "M"].max()),
                             "note": "2026-06 starts 06-01, 2026-09 ends 09-12 (partial month)"}

    # 1c. training size: final models vs rolling folds (fit rows after the 1-in-6 stride)
    fz = json.loads((REPORT / "freeze.json").read_text(encoding="utf-8"))
    roll = {}
    for t in TARGETS:
        _, ok = train.TARGETS[t]
        okv = tv[ok].to_numpy().astype(bool)
        sizes = {m: int((pr.fold_masks(tv.index, m, P["improve"]["purge_min"])["fit"] & okv).sum() // 6) for m in P["improve"]["months"]}
        roll[t] = {"final_fit_rows": fz["targets"][t]["chosen"]["fit_rows"], "rolling_fit_rows": sizes,
                   "rolling_mean": int(np.mean(list(sizes.values()))),
                   "final_fit_positives": int(round(fz["targets"][t]["chosen"]["fit_rows"] * fz["targets"][t]["chosen"]["fit_positive_rate"]))}
    out["training_size"] = roll

    # 2. baselines vs chosen on the test (from test_metrics.json, written by evaluate_test)
    tm = json.loads((REPORT / "test_metrics.json").read_text(encoding="utf-8"))
    out["baselines"] = {t: {m: {sub: {k: tm["targets"][t]["metrics"][m]["A"][sub][k] for k in ("tss", "pod", "far", "ci_low", "ci_high")}
                                for sub in ("all", "quiet")}
                            for m in ("chosen", "runner_up", "rule", "persistence")} for t in TARGETS}

    # 3. feature sets + GOES causality
    feats = {}
    for t in TARGETS:
        m = joblib.load(MODEL_DIR / f"{t}_chosen.joblib")
        f = m["features"]
        feats[t] = {"model": m["model"], "ideas": m["ideas"], "n": len(f),
                    "groups": {"base": sum(1 for x in f if not x.startswith(("lc_", "ev_", "sp_", "gx_"))),
                               "E2_long": sum(1 for x in f if x.startswith(("lc_", "ev_"))),
                               "E5_spectral": sum(1 for x in f if x.startswith("sp_")),
                               "E6_goes": sum(1 for x in f if x.startswith("gx_"))},
                    "goes_features": [x for x in f if x.startswith("gx_")],
                    "drift_normalised_E3": "E3" in m["ideas"]}
    out["features"] = feats
    out["goes_causality"] = goes_checks(sc, thr)

    # 4. per-month test TSS at frozen threshold A (all rows), chosen + baselines
    monthly = {}
    for t in TARGETS:
        s = sc[sc[f"ok_{t}"]]
        mon = s.index.tz_localize(None).to_period("M").astype(str)
        monthly[t] = {}
        for m in sorted(set(mon)):
            d = s[mon == m]
            y = d[f"y_{t}"].to_numpy().astype(bool)
            monthly[t][m] = {"rows": int(len(d)), "pos_rate": float(y.mean()),
                             "chosen": tss(y, d[f"s_{t}_chosen"] >= thr[t]["chosen"]["A"]),
                             "rule": tss(y, d["rule"] >= thr[t]["rule"]["A"]),
                             "persistence": tss(y, d["persistence"] >= 0.5)}
        rest = s
        top = max(monthly[t], key=lambda m: monthly[t][m]["chosen"])
        keep = mon != top
        monthly[t]["without_best_month"] = {"dropped": top, "chosen": tss(rest[f"y_{t}"][keep], rest[f"s_{t}_chosen"][keep] >= thr[t]["chosen"]["A"])}
    out["monthly"] = monthly
    _fresh(REPORT / "sanity.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8", newline="\n")
    return out


def goes_checks(sc: pd.DataFrame, thr: dict) -> dict:
    """(a) future perturbation of the GOES features on test-period data; (b) how often a positive forecast row has a
    qualifying GOES flare whose GOES begin is already <= t (flux already rising) while its label onset is > t; and the
    test TSS of m_30m with those rows removed, chosen (with GOES) vs runner-up (no GOES)."""
    proc = config.processed_dir()
    gx = pd.read_parquet(proc / "final" / "goes_xrs_minute_test.parquet").astype("float64")
    old = fx._hi
    fx._hi = lambda: config.period_bounds("test")[1]
    try:
        rng = np.random.default_rng(0)
        rows = sc.index[rng.choice(len(sc), 3000, replace=False)].sort_values()
        cuts = rows[rng.choice(len(rows), 20, replace=False)]
        base_grid = fx.goes_grid(gx)
        worst = 0.0
        for cut in cuts:
            g2 = gx.copy()
            fut = g2.index > cut.floor("min")          # values whose minute ends after the last full minute <= cut
            g2.loc[fut] = g2.loc[fut] * rng.uniform(5, 50, size=(fut.sum(), 2))
            a = fx.asof_rows(base_grid.astype("float32"), pd.DatetimeIndex([cut]))
            b = fx.asof_rows(fx.goes_grid(g2).astype("float32"), pd.DatetimeIndex([cut]))
            d = np.nanmax(np.abs(a.to_numpy() - b.to_numpy())) if np.isfinite(a.to_numpy()).any() else 0.0
            worst = max(worst, float(np.nan_to_num(d)))
        # last minute used at row t: grid label <= t, i.e. the 1-min average that ENDED at or before t
        lag = []
        g_idx = base_grid.index
        for t in rows[:500]:
            k = g_idx.searchsorted(t, "right") - 1
            if k >= 0:
                lag.append((t - g_idx[k]).total_seconds())
    finally:
        fx._hi = old
    res = {"perturbation_cuts": 20, "max_abs_feature_change_at_cut": worst,
           "seconds_between_row_time_and_newest_goes_value": {"min": float(np.min(lag)), "max": float(np.max(lag))}}
    # (b) "already rising" rows
    goes = pd.read_parquet(proc / "goes_matched.parquet")
    fl = analysis.flare_starts(goes, pd.read_parquet(proc / "events.parquet"), pd.read_parquet(proc / "events_pairs.parquet"))
    t0, t1 = config.period_bounds("test")
    for t in ("m_30m", "m_60m"):
        h = pd.Timedelta(minutes=HORIZON[t])
        q = fl[(fl["flux"] >= goes_flux(MIN_CLASS[t])) & (fl["start"] > t0 - h) & (fl["start"] < t1 + h)]
        later = q[q["start"] > q["begin"]]
        s = sc[sc[f"ok_{t}"]]
        tt = s.index
        early = np.zeros(len(s), bool)
        for _, f in later.iterrows():   # rows in [GOES begin, label start) whose label is positive because of THIS flare
            early |= np.asarray((tt >= f["begin"]) & (tt < f["start"]) & (tt >= f["start"] - h))
        y = s[f"y_{t}"].to_numpy().astype(bool)
        keep = ~early
        res[t] = {"qualifying_flares_in_test": int(len(q)),
                  "flares_with_label_start_after_goes_begin": int(len(later)),
                  "median_start_minus_begin_min": float(((later["start"] - later["begin"]).dt.total_seconds() / 60).median()) if len(later) else None,
                  "positive_rows": int(y.sum()), "positive_rows_after_goes_begin": int((y & early).sum()),
                  "share_of_positives": float((y & early).sum() / max(y.sum(), 1)),
                  "tss_chosen_all": tss(y, s[f"s_{t}_chosen"] >= thr[t]["chosen"]["A"]),
                  "tss_chosen_without_those_rows": tss(y[keep], (s[f"s_{t}_chosen"] >= thr[t]["chosen"]["A"])[keep]),
                  "tss_runner_up_without_those_rows": tss(y[keep], (s[f"s_{t}_runner_up"] >= thr[t]["runner_up"]["A"])[keep])}
    return res


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, default=str))
