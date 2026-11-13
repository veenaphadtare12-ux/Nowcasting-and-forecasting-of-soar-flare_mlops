"""Stage evaluate_holdout2: the ONE stage that builds and reads holdout2 features and labels, and scores the frozen
FINAL_CHOICE_2 models once.

    python -m src.holdout2.evaluate

Refuses to run unless docs/FINAL_CHOICE_2.md is committed (and unchanged since), the frozen model files match the
SHA-256 values written in it, and every holdout2 file still matches docs/HOLDOUT2_LOCK.md.

Holdout2 inputs are built with the same functions as the development data:
* SoLEXS: `solexs.clean_day` -> 1 s counts -> `features.bin_counts` / `solexs_features` (10 s), minute means;
  the previous day (development data for 2026-09-13) is used only as trailing warm-up, as in `dataset.build_all`;
* detector on the minute series (warm-up from the 3 previous development days), GOES matching, labels
  (`labels.make_labels`, purged at the holdout2 end), causal activity flag;
* HEL1OS sessions inside holdout2 (newest version), SoLEXS spectra, GOES-19 XRS, GOES event lists and NOAA SRS for the
  extra feature blocks, each joined causally exactly as in development (`src/dev2/run.add_blocks`).
Outputs: reports/holdout2/metrics.json, reports/holdout2/results.md, MLflow experiment `flare-holdout2`.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess

import joblib
import numpy as np
import pandas as pd

from src import activity, config, features, goes, hel1os, labels, solexs
from src.detection import detector, matching
from src.dev2 import context as cx
from src.dev2 import early
from src.dev2 import protocol as pr
from src.final import features as ff
from src.holdout2 import ingest
from src.improve import features_extra as fx
from src.improve import goes_xrs, spectral
from src.models import metrics, train

ROOT = config.PROJECT_ROOT
MODEL_DIR = ROOT / "models_final2"
OUT = ROOT / "reports" / "holdout2"
FINAL_DOC = ROOT / "docs" / "FINAL_CHOICE_2.md"


# ---------------------------------------------------------------- guards
def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def require_final_choice_committed() -> dict:
    """FINAL_CHOICE_2.md must be committed and unchanged; frozen models must match its SHA-256 list; lock must hold."""
    rel = FINAL_DOC.relative_to(ROOT).as_posix()
    assert FINAL_DOC.exists(), "docs/FINAL_CHOICE_2.md does not exist: write and commit it first"
    commit = _git("log", "-1", "--format=%H %cI", "--", rel)
    assert commit, "docs/FINAL_CHOICE_2.md is not committed"
    assert not _git("status", "--porcelain", "--", rel), "docs/FINAL_CHOICE_2.md has uncommitted changes"
    text = FINAL_DOC.read_text(encoding="utf-8")
    for f in sorted(MODEL_DIR.glob("*.joblib")):
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        assert f"`{h}`" in text, f"{f.name} does not match the SHA-256 recorded in FINAL_CHOICE_2.md"
    assert ingest.verify(), "holdout2 files changed since the lock"
    return {"final_choice_commit": commit, "models_checked": len(list(MODEL_DIR.glob("*.joblib")))}


# ---------------------------------------------------------------- holdout2 inputs
def build_inputs(lo: pd.Timestamp | None = None, hi: pd.Timestamp | None = None, usable: set | None = None,
                 events_dir=None, xrs_files=None, srs_extra=None) -> dict:
    """Holdout2 inputs (defaults). The arguments exist only for the dry run on DEVELOPMENT days in
    tests/test_holdout2_pipeline.py, which checks that this path reproduces the development dataset."""
    P = config.load_params()
    fp, lp, fd = P["features"], P["labels"], P["flare_detection"]
    cad, windows = fp["cadence_s"], fp["windows_min"]
    if lo is None:
        lo, hi = ingest.bounds()
        usable = set(json.loads((OUT / "ingest.json").read_text(encoding="utf-8"))["usable_day_list"])
        events_dir = ingest.ext_dir() / "goes_events"
        xrs_files = sorted((ingest.ext_dir() / "goes_xrs").glob("*.nc"))
        srs_extra = sorted((ingest.ext_dir() / "srs").glob("*SRS.txt"))
    proc = config.processed_dir()
    all_days = solexs.list_days(detector=P["solexs"]["detector"])
    days = [d for d in all_days if d.complete and lo <= d.date < hi and f"{d.date:%Y-%m-%d}" in usable]
    s = detector.DetectorSettings.from_params(fd)

    # SoLEXS: clean 1 s counts and minute means
    clean = {d.date: solexs.clean_day(d)[0]["counts"].astype("float64") for d in days}
    mm = pd.concat([detector.minute_means(c, s.min_valid_s_per_min) for c in clean.values()])["m"]
    mm = mm[~mm.index.duplicated()]
    dev_minute = pd.read_parquet(proc / "solexs_minute.parquet")["m"]
    minute = pd.concat([dev_minute[dev_minute.index <= lo], mm[(mm.index > lo) & (mm.index <= hi)]])
    minute = minute.reindex(pd.date_range(minute.index.min(), hi, freq="min", name="time"))

    # detector (3 development days of warm-up), GOES matching
    warm = lo - pd.Timedelta(days=3)
    ev_all = detector.detect_series(minute[minute.index > warm], s)
    ev_all = ev_all[ev_all["trigger_time"] < hi].reset_index(drop=True)
    gl_dev = goes.load_flare_list()
    gl_dev = gl_dev[gl_dev["begin"] < lo]
    gl_h2 = goes.load_flare_list(events_path=events_dir)
    glist = pd.concat([gl_dev, gl_h2[(gl_h2["begin"] >= lo) & (gl_h2["begin"] < hi + pd.Timedelta(days=1))]]).sort_values("begin").reset_index(drop=True)
    gwin = glist[(glist["begin"] >= warm - pd.Timedelta(days=1)) & (glist["begin"] < hi + pd.Timedelta(days=1))].reset_index(drop=True)
    ev_m, gm, pairs = matching.match_goes(ev_all, gwin, P["goes_match"]["tolerance_s"])
    gaps = goes.missing_days(lo, hi, events_dir)

    # HEL1OS sessions inside holdout2 (optional input)
    sess = [x for x in hel1os.newest_per_session(hel1os.list_sessions()) if lo <= x.start < hi]
    hel = pd.concat([hel1os.read_session(x) for x in sess]).sort_index().astype("float32") if sess else None
    if hel is not None:
        hel = hel[~hel.index.duplicated(keep="last")]
    chan = features.hel1os_channels(hel) if hel is not None and not hel.empty else None

    # 10 s features, exactly as dataset.build_all
    warm_f = pd.Timedelta(minutes=max(windows) + 70)
    parts = []
    for d in days:
        prev_date = d.date - pd.Timedelta(days=1)
        prev = clean.get(prev_date)
        if prev is None and (proc / "solexs_clean" / f"{prev_date:%Y%m%d}.parquet").exists():
            prev = pd.read_parquet(proc / "solexs_clean" / f"{prev_date:%Y%m%d}.parquet")["counts"].astype("float64")
        cur = clean[d.date]
        series = pd.concat([prev[prev.index > d.date - warm_f], cur]) if prev is not None else cur
        binned = features.bin_counts(series, cad)
        feat = features.solexs_features(binned, windows, cad)
        hf = features.hel1os_features(chan, feat.index, cad, sxr_rate=binned["rate"])
        if hf.shape[1]:
            feat = feat.join(hf)
        feat = feat[(feat.index > d.date) & (feat.index <= d.date + pd.Timedelta(days=1))]
        feat = feat[feat["rate"].notna() & (feat["valid_frac_5m"] >= fp["min_valid_frac_5m"])]
        parts.append(feat)
    df = pd.concat(parts).astype("float32")
    df = df[(df.index > lo) & (df.index < hi)]
    for c in ff.base_features():                       # HEL1OS columns are absent when no session covers a day
        if c not in df:
            df[c] = np.float32(0.0) if c == "hel1os_available" else np.float32(np.nan)
    valid_minutes = minute.notna()
    lab = labels.make_labels(df.index, ev_m, lp["horizons_min"], lp["min_class_c"], lp["min_class_m"], valid_minutes,
                             pd.Series(hi, index=df.index), gaps, goes=gm, pairs=pairs)
    df = df.join(lab)
    df[train.FLAG] = activity.flare_in_progress(df.index, ev_m, fd["end_confirm_min"], fd["gap_end_min"])
    df["_active_day"] = pr.active_day_flags(df.index, glist)

    # sources for the extra blocks (development history + holdout2)
    sp_parts = []
    spc = P["improve"]["spectral"]
    for d in days:
        pi = d.lc.with_name(d.lc.name.replace(".lc.gz", ".pi.gz"))
        if pi.exists():
            r = spectral.band_rates(pi, solexs.read_gti(d.gti), spc["low_channels"], spc["high_channels"])
            if not r.empty:
                sp_parts.append(pd.DataFrame({c: detector.minute_means(r[c], s.min_valid_s_per_min)["m"] for c in ("low", "high", "total")}))
    sp_dev = ff._source("spectral", include_test=True)
    sp = pd.concat([sp_dev[sp_dev.index <= lo]] + [x[(x.index > lo) & (x.index <= hi)] for x in sp_parts]).sort_index()
    sp = sp[~sp.index.duplicated(keep="first")].astype("float32")
    gx_h2 = pd.concat([goes_xrs.read_day(f) for f in xrs_files]).sort_index()
    gx_h2 = gx_h2[~gx_h2.index.duplicated(keep="first")]
    gx_h2.index = gx_h2.index.round("min")
    gx_dev = ff._source("goes", include_test=True)
    gx = pd.concat([gx_dev[gx_dev.index <= lo], gx_h2[(gx_h2.index > lo) & (gx_h2.index <= hi)]]).astype("float32")
    gx = gx[~gx.index.duplicated(keep="first")]
    ev_dev = pd.read_parquet(proc / "events.parquet")
    ev_ctx = pd.concat([ev_dev[ev_dev["end_known_time"] < warm], ev_m[ev_m["end_known_time"] >= warm]], ignore_index=True)
    srs_files = sorted(set(sorted(cx.srs_dir().glob("*SRS.txt")) + list(srs_extra)))
    dev_rows = pr.load(ff.base_features())
    dev_rows = dev_rows[dev_rows.index <= lo]
    return {"df": df, "minute": minute, "events": ev_m, "events_ctx": ev_ctx, "goes_matched": gm, "pairs": pairs,
            "glist": glist, "spectral": sp, "gx": gx, "srs_files": srs_files, "dev_rows": dev_rows[dev_rows.index > lo - pd.Timedelta(days=8)],
            "days": [f"{d.date:%Y-%m-%d}" for d in days], "hel1os_sessions": [x.name for x in sess], "lo": lo, "hi": hi}


def add_blocks(inp: dict, blocks: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Holdout2 version of src/dev2/run.add_blocks: same builders, sources = development history + holdout2."""
    P = config.load_params()
    df, lo, hi = inp["df"], inp["lo"], inp["hi"]
    feats = ff.base_features()
    with ff._end(hi):
        for b in ("long", "spectral", "goes"):
            if b not in blocks:
                continue
            if b == "long":
                g = fx.long_context_grid(inp["minute"], inp["events_ctx"], P["improve"], P["flare_detection"])
            elif b == "spectral":
                g = fx.spectral_grid(inp["spectral"])
            else:
                g = fx.goes_grid(inp["gx"])
            ex = fx.asof_rows(g.astype("float32"), df.index)
            df = pd.concat([df, ex], axis=1)
            feats = feats + list(ex.columns)
    if "drift" in blocks:      # trailing 7-day medians need the development rows just before holdout2
        both = pd.concat([inp["dev_rows"], df[ff.base_features()]]).sort_index()
        nd = fx.drift_normalise(both, P["improve"]["drift_days"])
        for c in fx.LEVEL_FEATURES + fx.SIGNED_FEATURES:
            df[c] = nd.loc[df.index, c].to_numpy()
    start = lo - pd.Timedelta(days=4)
    for b in ("ax", "gc", "srs"):
        if b not in blocks:
            continue
        if b == "ax":
            g = cx.aditya_grid(inp["events_ctx"], start, hi)
        elif b == "gc":
            g = cx.goes_count_grid(inp["glist"], start, hi)
        else:
            g = cx.srs_grid(inp["srs_files"], start, hi)
        ex = fx.asof_rows(g.astype("float32"), df.index)
        df = pd.concat([df, ex], axis=1)
        feats = feats + list(ex.columns)
    return df, feats


# ---------------------------------------------------------------- scoring
def boot_ci(y, yhat, times, n, seed, level) -> tuple[float, float]:
    days = pd.DatetimeIndex(sorted(times.floor("D").unique()))
    codes = days.get_indexer(times.floor("D"))
    dc = metrics.daily_counts(y, yhat, codes, len(days))
    idx = metrics.bootstrap_indices(len(days), n, seed)
    return metrics.bootstrap_mean_tss([dc], idx, level)


def block_scores(y, s, thr, times, quiet, active, bs) -> dict:
    a = s >= thr
    out = {"thr": float(thr), "all": pr.counts(y, a), "quietstart": pr.counts(y[quiet], a[quiet]),
           "active_days": pr.counts(y[active], a[active]), "quiet_days": pr.counts(y[~active], a[~active])}
    out["tss"] = pr.tss_of(out["all"])
    out["ci95"] = boot_ci(y, a, times, bs["n"], bs["seed"], bs["level"])
    out["tss_quietstart"] = pr.tss_of(out["quietstart"])
    out["tss_active_days"] = pr.tss_of(out["active_days"])
    out["tss_quiet_days"] = pr.tss_of(out["quiet_days"])
    out["pod_far"] = pr.pod_far(out["all"])
    months = pd.DatetimeIndex(times).strftime("%Y-%m")
    out["per_month"] = {m: {"counts": pr.counts(y[months == m], a[months == m]), "tss": pr.tss_of(pr.counts(y[months == m], a[months == m])),
                            "positives": int(y[months == m].sum()), "rows": int((months == m).sum())} for m in sorted(set(months))}
    return out


def score_forecasts(inp: dict) -> dict:
    bs = config.load_params()["dev2"]["final"]["bootstrap"]
    rule = config.load_params()["models"]["rule_feature"]
    res, frames = {}, {}
    for f in sorted(MODEL_DIR.glob("*.joblib")):
        if f.name.startswith("r1_"):
            continue
        z = joblib.load(f)
        t, var = z["target"], z["variant"]
        key = tuple(z["blocks"])
        if key not in frames:
            frames[key] = add_blocks(inp, z["blocks"])
        df, feats = frames[key]
        assert feats == z["features"], f"{f.name}: feature list differs from the frozen model"
        y_col, ok_col = train.TARGETS[t]
        d = df[df[ok_col].astype(bool)]
        y = d[y_col].to_numpy().astype(bool)
        times = pd.DatetimeIndex(d.index)
        q = d[train.FLAG].to_numpy() == 0
        a = d["_active_day"].to_numpy().astype(bool)
        s = z["estimator"].predict_proba(d[feats])[:, 1]
        r = {"rows": int(len(d)), "positives": int(y.sum()), "days": int(times.floor("D").nunique()),
             "brier_raw": float(np.mean((s - y) ** 2)), "brier_isotonic": float(np.mean((z["isotonic"].predict(s) - y) ** 2)),
             "brier_climatology": float(np.mean((z["baseline_thresholds"]["climatology_rate"] - y) ** 2)),
             "points": {k: block_scores(y, s, th, times, q, a, bs) for k, th in z["thresholds"].items()}}
        if var == "aditya":       # baselines once per target (they do not depend on the variant)
            bt = z["baseline_thresholds"]
            r["baselines"] = {"rule": block_scores(y, d[rule].fillna(0).to_numpy(), bt["rule"]["A"], times, q, a, bs),
                              "flux": block_scores(y, d["log_rate"].fillna(-9).to_numpy(), bt["flux"]["A"], times, q, a, bs),
                              "persistence": block_scores(y, d[train.FLAG].to_numpy().astype(float), 0.5, times, q, a, bs),
                              "climatology": {"tss": 0.0, "note": "constant forecast: TSS = 0 by definition"}}
        res.setdefault(t, {})[var] = r
        print(f"  {t:7s} {var:9s} TSS_A {r['points']['A']['tss']:.3f} [{r['points']['A']['ci95'][0]:.2f}, "
              f"{r['points']['A']['ci95'][1]:.2f}]  pos {r['positives']}", flush=True)
    return res


def score_r1(inp: dict) -> dict:
    lo = inp["lo"]
    ev = inp["events"]
    det = early.detections(ev, inp["pairs"], inp["goes_matched"])
    det = det[pd.DatetimeIndex(det["trigger_time"]) >= lo].reset_index(drop=True)
    m1 = config.load_params()["final"]["lead_time"]["m1_flux"]
    t_m1 = early.first_m1_time(det, inp["gx"], m1)
    active = pr.active_day_flags(pd.DatetimeIndex(det["trigger_time"]), inp["glist"])
    out = {"n_triggers": int(len(det)), "n_m": int(det["y_m"].sum()), "n_c_or_more": int(det["y_c"].sum()),
           "n_false": int((det["peak_flux"] == 0).sum()), "variants": {}}
    for f in sorted(MODEL_DIR.glob("r1_*.joblib")):
        z = joblib.load(f)
        k = z["k"]
        X = early.features(det, k, inp["minute"], inp["spectral"], inp["df"], inp["gx"])
        tau = (pd.DatetimeIndex(det["trigger_time"]) + pd.Timedelta(minutes=k)).as_unit("ns").asi8.view("datetime64[ns]")
        r = {}
        for kind in ("model", "flux"):
            if kind == "model":
                s = {tgt: z["models"][tgt].predict_proba(X[z["features"]])[:, 1] for tgt in ("y_c", "y_m")}
                th = z["thresholds"]
            else:
                s = {tgt: X["f_log_m"].fillna(-9).to_numpy() for tgt in ("y_c", "y_m")}
                th = z["flux_thresholds"]
            ym, yc = det["y_m"].to_numpy(), det["y_c"].to_numpy()
            am = s["y_m"] >= th["y_m"]
            pred = early.cls_decision(s["y_c"], s["y_m"], th["y_c"], th["y_m"])
            lead = (t_m1 - tau) / np.timedelta64(1, "m")
            lt = lead[ym & am & ~np.isnan(lead)]
            r[kind] = {"m": early.prf(pr.counts(ym, am)), "c": early.prf(pr.counts(yc, s["y_c"] >= th["y_c"])),
                       "m_active_days": early.prf(pr.counts(ym[active], am[active])),
                       "m_quiet_days": early.prf(pr.counts(ym[~active], am[~active])),
                       "class_confusion": pd.crosstab(det["cls3"].to_numpy(), pred).reindex(index=[0, 1, 2], columns=[0, 1, 2], fill_value=0).to_numpy().tolist(),
                       "lead_tp_min": [round(float(v), 1) for v in lt],
                       "lead_median_min": float(np.median(lt)) if len(lt) else None,
                       "lead_share_before_m1": float((lt > 0).mean()) if len(lt) else None}
        out["variants"][f.stem.removeprefix("r1_")] = {"learner": z["learner"], **r}
    return out


def results_markdown(res: dict) -> str:
    fc = res["forecasts"]
    lines = ["| Target | Variant | Positives (days) | TSS at A [95% day-bootstrap] | Quiet-start | Active / quiet days | "
             "Best baseline (TSS) | Per month (Sep / Oct / Nov) |", "|---|---|---|---|---|---|---|---|"]
    for t in fc:
        for var, r in fc[t].items():
            a = r["points"]["A"]
            bl = fc[t]["aditya"]["baselines"]
            best = max(("rule", "flux", "persistence"), key=lambda k: bl[k]["tss"])
            pm = " / ".join(f"{a['per_month'][m]['tss']:.2f}" if m in a["per_month"] else "–" for m in ("2026-09", "2026-10", "2026-11"))
            flag = " (UNDERPOWERED)" if t.startswith("m_") and res["underpowered_m"] else ""
            lines.append(f"| {t}{flag} | {var}{' (champion)' if var == res['choice'][t] else ''} | {r['positives']} ({r['days']}) | "
                         f"**{a['tss']:.3f}** [{a['ci95'][0]:.2f}, {a['ci95'][1]:.2f}] | {a['tss_quietstart']:.3f} | "
                         f"{a['tss_active_days']:.3f} / {a['tss_quiet_days']:.3f} | {best} {bl[best]['tss']:.3f} | {pm} |")
    return "\n".join(lines)


def main() -> dict:
    guard = require_final_choice_committed()
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow

    inp = build_inputs()
    ing = json.loads((OUT / "ingest.json").read_text(encoding="utf-8"))
    F = config.load_params()["dev2"]["final"]
    res = {"guard": guard, "days": inp["days"], "hel1os_sessions": inp["hel1os_sessions"],
           "underpowered_m": bool(ing["m_results_underpowered"]), "m_flares_on_usable_days": ing["m_or_larger_on_usable_days"],
           "choice": {t: s["choice"] for t, s in F["targets"].items()},
           "n_events": int(len(inp["events"])), "n_events_matched": int(inp["events"]["is_goes_matched"].sum()),
           "forecasts": score_forecasts(inp), "r1": score_r1(inp)}
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in (("metrics.json", json.dumps(res, indent=1, default=str)), ("results.md", results_markdown(res) + "\n")):
        p = OUT / name
        if p.exists():
            p.chmod(0o666)
            p.unlink()
        p.write_text(text, encoding="utf-8", newline="\n")
    mlflow.set_tracking_uri(config.mlflow_uri())
    mlflow.set_experiment("flare-holdout2")
    with mlflow.start_run(run_name="holdout2-once"):
        mlflow.set_tags(train_tags := {"final_choice_commit": guard["final_choice_commit"], "holdout2": ",".join(inp["days"]),
                                       "underpowered_m": str(res["underpowered_m"])})
        for t, v in res["forecasts"].items():
            for var, r in v.items():
                mlflow.log_metric(f"{t}.{var}.tss_A", r["points"]["A"]["tss"])
        mlflow.log_dict(res, "holdout2_metrics.json")
    print(results_markdown(res))
    return res


if __name__ == "__main__":
    main()
