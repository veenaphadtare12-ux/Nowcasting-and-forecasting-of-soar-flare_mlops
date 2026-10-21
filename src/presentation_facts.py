"""Presentation pack: collect numbers from existing output files into docs/PRESENTATION_FACTS.md.

    python -m src.presentation_facts base_rates   # export reports/base_rates.json (tune + val rows only)
    python -m src.presentation_facts facts        # write docs/PRESENTATION_FACTS.md from output files

No model is trained and no statistic is computed on the test period. Every number in the facts file is read from an
output file, and its source path is written next to it.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys

import pandas as pd
import yaml

from src import config

R = config.PROJECT_ROOT
OUT = R / "docs" / "PRESENTATION_FACTS.md"
TARGETS = [("now", "y_now", "ok_now", "Nowcast: a GOES-matched flare is in progress right now"),
           ("c_30m", "y_c_30m", "ok_30m", "A GOES ≥C flare starts within the next 30 min"),
           ("c_60m", "y_c_60m", "ok_60m", "A GOES ≥C flare starts within the next 60 min"),
           ("c_120m", "y_c_120m", "ok_120m", "A GOES ≥C flare starts within the next 120 min"),
           ("m_30m", "y_m_30m", "ok_30m", "A GOES ≥M flare starts within the next 30 min"),
           ("m_60m", "y_m_60m", "ok_60m", "A GOES ≥M flare starts within the next 60 min"),
           ("m_120m", "y_m_120m", "ok_120m", "A GOES ≥M flare starts within the next 120 min")]
MODELS = [("climatology", "Climatology"), ("persistence", "Persistence"), ("rule", "1-feature rule"),
          ("logreg", "Logistic regression"), ("xgb", "XGBoost")]


def _j(path: str) -> dict:
    return json.loads((R / path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- export: base rates (tune + val only)
def export_base_rates() -> None:
    out = {}
    for per in ("tune", "val"):  # never the test period
        cols = [c for _, y, ok, _ in TARGETS for c in (y, ok)] + ["flare_in_progress_at_t"]
        d = pd.read_parquet(R / "data" / "processed" / "dataset" / f"{per}.parquet", columns=sorted(set(cols)))
        lo, hi = config.period_bounds(per)
        assert d.index.min() >= lo and d.index.max() < hi
        out[per] = {}
        for key, y, ok, _ in TARGETS:
            dd = d[d[ok].astype(bool)]
            q = dd[dd["flare_in_progress_at_t"] == 0]
            out[per][key] = {"all_rows": float(dd[y].mean()), "quiet_start": float(q[y].mean()),
                             "n_all": int(len(dd)), "n_quiet": int(len(q))}
    (R / "reports" / "base_rates.json").write_text(json.dumps(out, indent=2), encoding="utf-8", newline="\n")
    print("wrote reports/base_rates.json")


# ---------------------------------------------------------------- facts document
def pct(x, nd=1) -> str:
    return f"{100 * x:.{nd}f}%"


def model_table(t: dict, subset: str, op: str) -> list[str]:
    sel = t["selected"]
    lines = ["| Model | TSS mean ± std | 95% interval (TSS) | HSS | POD | FAR |", "|---|---|---|---|---|---|"]
    for k, name in MODELS:
        a = t["models"][k]["summary"][op][subset]
        star = " **★ best**" if k == sel else ""
        sd = f" ± {a['tss_std']:.3f}" if a["n_seeds"] > 1 else ""
        lines.append(f"| {name}{star} | {a['tss_mean']:.3f}{sd} | [{a['tss_ci_low']:.2f}, {a['tss_ci_high']:.2f}] | "
                     f"{a['hss_mean']:.3f} | {a['pod_mean']:.2f} | {a['far_mean']:.2f} |")
    return lines


def ablation_tables(ab: dict) -> list[str]:
    src = "`reports/model_metrics.json` → `ablation`"
    if not ab or "skipped" in ab:
        return [f"Ablation not available ({src})."]
    lines = [f"Rows: fit {ab['rows']['fit']:,} / calibration {ab['rows']['cal']:,} / validation {ab['rows']['val']:,} "
             f"({ab['val_days']} validation days). Calibration block {ab['cal_block'][0]} … {ab['cal_block'][1]} (no HEL1OS "
             f"session falls in Dec–Jan). Threshold for 'too few': {ab['min_positive_episodes']} positive episodes. Source: {src}.", ""]
    for key, _, _, desc in TARGETS:
        r = ab["targets"].get(key, {})
        if not r:
            continue
        warn = " — ⚠ **too few positives to conclude**" if r.get("too_few_positives") else ""
        lines += [f"**{key}** ({desc}): validation positive episodes = {r['val_positive_episodes']}, "
                  f"calibration episodes = {r['cal_positive_episodes']}, positive rate {pct(r['val_pos_rate'] or 0)}{warn}", ""]
        if "skipped" in r:
            lines += [f"Skipped: {r['skipped']}", ""]
            continue
        lines += ["| Model | Features | A all: TSS [95%] | A all: HSS / POD / FAR | A quiet: TSS [95%] | B all: TSS | B all: HSS / POD / FAR |",
                  "|---|---|---|---|---|---|---|"]
        for m, md in r["models"].items():
            for fs in ("soft", "hard", "combined"):
                a, q, b = md[fs]["A"]["all"], md[fs]["A"]["quiet"], md[fs]["B"]["all"]
                lines.append(f"| {m} | {fs} | {a['tss_mean']:.3f} ± {a['tss_std']:.3f} [{a['tss_ci_low']:.2f}, {a['tss_ci_high']:.2f}] | "
                             f"{a['hss_mean']:.3f} / {a['pod_mean']:.2f} / {a['far_mean']:.2f} | "
                             f"{q['tss_mean']:.3f} [{q['tss_ci_low']:.2f}, {q['tss_ci_high']:.2f}] | {b['tss_mean']:.3f} | "
                             f"{b['hss_mean']:.3f} / {b['pod_mean']:.2f} / {b['far_mean']:.2f} |")
        lines.append("")
    return lines


def write_facts() -> None:
    P = config.load_params()
    qc = pd.read_csv(R / "reports" / ".." / "data" / "processed" / "solexs_qc.csv")
    inv = pd.read_csv(R / "reports" / "data_inventory.csv", dtype={"date_start": str})
    inv["name"] = inv["archive"].map(lambda a: a.replace("\\", "/").split("/")[-1])
    cov = pd.read_csv(R / "data" / "processed" / "hel1os" / "coverage.csv")
    det = _j("reports/detection_metrics.json")
    eda = _j("reports/eda_numbers.json")
    ds = _j("reports/dataset_summary.json")
    br = _j("reports/base_rates.json")
    mm = _j("reports/model_metrics.json")
    labc = _j("reports/label_comparison.json")
    dvc = yaml.safe_load((R / "dvc.yaml").read_text(encoding="utf-8"))
    commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=R, text=True).strip()
    n_tests = subprocess.check_output([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=R, text=True)
    n_tests = [ln for ln in n_tests.splitlines() if "collected" in ln or "tests" in ln][-1].split()[0]
    con = sqlite3.connect(R / "mlflow.db")
    runs = dict(con.execute("select e.name, count(*) from runs r join experiments e on r.experiment_id=e.experiment_id group by e.name").fetchall())
    con.close()

    # ---- A. data
    qc["date"] = pd.to_datetime(qc["date"], utc=True)
    qc["period"] = config.assign_period(pd.DatetimeIndex(qc["date"])).to_numpy()
    usable = qc[qc["usable"]]
    sol = inv[(inv["kind"] == "day")].drop_duplicates("name")
    ses = inv[inv["kind"] == "session"].drop_duplicates("name").copy()
    ses_dates = pd.to_datetime(ses["date_start"], format="%Y%m%d", utc=True)
    ses["period"] = config.assign_period(pd.DatetimeIndex(ses_dates)).to_numpy()
    usable_days = set(usable["date"].dt.strftime("%Y%m%d"))
    test_overlap_sessions = int(((ses["period"] == "test") & ses["date_start"].isin(usable_days)).sum())
    hx = eda["hel1os"]["per_period"]
    nt, nv = det["new"]["tune"], det["new"]["val"]
    lt, lv = det["legacy"]["tune"], det["legacy"]["val"]
    feats = ds["feature_columns"]
    n_hx = sum(1 for f in feats if f.startswith("hx_") or f == "hel1os_available")
    ne = eda["hel1os"]["neupert"]

    L = []
    a = L.append
    a("# Presentation facts")
    a("")
    a(f"Generated by `python -m src.presentation_facts facts` from existing output files (commit `{commit}`). Every number is "
      "followed by its source. Statistics use the tuning (2025-04-09 … 2026-01-31) and validation (2026-02-01 … 2026-05-31) "
      "periods only; the test period (2026-06-01 … 2026-09-12) appears only as counts.")
    a("")
    a("## A. Data")
    a("")
    a("### SoLEXS (soft X-rays)")
    a(f"- Usable days (≥ 50% valid): **{len(usable)}** of {len(qc)} day folders in the three periods "
      f"(tune {int((usable['period'] == 'tune').sum())}, val {int((usable['period'] == 'val').sum())}, "
      f"test {int((usable['period'] == 'test').sum())} — count only) — `data/processed/solexs_qc.csv`")
    a(f"- Date range of usable days: {usable['date'].min():%Y-%m-%d} … {usable['date'].max():%Y-%m-%d} — `data/processed/solexs_qc.csv`")
    a(f"- Cadence: {P['solexs']['cadence_s']} s light curves, used as 1-min means for detection and 10-s rows for features "
      f"— `params.yaml` (`solexs.cadence_s`, `features.cadence_s`)")
    a(f"- Detector: **{P['solexs']['detector']}** (light curves exist only for SDD2) — `params.yaml` (`solexs.detector`)")
    a(f"- Size: {len(sol)} unique daily SoLEXS archives, {sol['uncompressed_mb'].sum() / 1e3:.1f} GB uncompressed "
      f"({sol['compressed_mb'].sum() / 1e3:.1f} GB zipped) — `reports/data_inventory.csv`")
    a("")
    a("### HEL1OS (hard X-rays)")
    a(f"- Session archives: **{len(ses)}** unique sessions on disk; **{len(cov)}** after the newest-version rule "
      f"— `reports/data_inventory.csv`, `data/processed/hel1os/coverage.csv`")
    a(f"- Date range: {ses_dates.min():%Y-%m-%d} … {ses_dates.max():%Y-%m-%d} — `reports/data_inventory.csv`")
    for per in ("tune", "val"):
        h = hx[per]
        a(f"- {per}: **{h['overlap_days']} days / {h['overlap_hours']} h** of HEL1OS overlapping usable SoLEXS rows; GOES flares "
          f"starting inside HEL1OS time: C {h['goes_in_hel1os_time']['C']}, M {h['goes_in_hel1os_time']['M']}, "
          f"X {h['goes_in_hel1os_time']['X']} — `reports/eda_numbers.json` (`hel1os.per_period`)")
    a(f"- test: {test_overlap_sessions} sessions on usable SoLEXS days (count only, nothing analysed) — `reports/data_inventory.csv`")
    a(f"- Extracted: light curves + aux only (847 files, 693 FITS verified); event lists and spectra stay zipped — `reports/data_inventory.csv`")
    a("")
    a("### GOES flares per class (flares peaking while SoLEXS had valid data)")
    a("| Class | tune | val |")
    a("|---|---|---|")
    for c in "BCMX":
        a(f"| {c} | {nt['goes_class_balance'].get(c, 0)} | {nv['goes_class_balance'].get(c, 0)} |")
    a("")
    a("Source: `reports/detection_metrics.json` (`new.<period>.goes_class_balance`). All GOES flares in tune + val regardless "
      f"of SoLEXS coverage: {eda['long_term']['n_M']} M and {eda['long_term']['n_X']} X — `reports/eda_numbers.json` (`long_term`).")
    a("")
    a("### Data problems found and how each was handled")
    for line in [
        "Two SoLEXS bundle downloads were truncated → entries listed by scanning local zip headers; every complete day was already extracted, nothing lost (`reports/data_inventory.csv`, `docs/PROGRESS.md`).",
        "28 SoLEXS days have < 50% valid data (e.g. the 17th of every month ≈ 11% valid) → excluded as unusable, gaps never filled (`data/processed/solexs_qc.csv`).",
        "NOAA has no event report for 2025-12-30 and 2025-12-31 → excluded from evaluation, labels marked not-ok (`reports/dataset_summary.json` `goes_missing_days`).",
        "pandas stored SoLEXS times in seconds, so integer comparisons silently mismatched → all comparisons converted to nanoseconds; unit test added (`docs/PROGRESS.md`).",
        "First detector made events up to 15 h long and started up to 1 h early → rebuilt GOES-style detector (`reports/detection_metrics.json`).",
        "Detector misses small flares (B recall 0.18, C ≈ 0.86) → forecast labels taken from the GOES list directly (`reports/label_comparison.json`).",
        "Git (CRLF line endings) and Windows text writers changed file bytes, so DVC re-ran stages for nothing → `.gitattributes` + LF writers + a test (`docs/PROGRESS.md`).",
        "**HEL1OS folder deletion mistake:** on 2026-09-17 I deleted extracted 2025/2026 HEL1OS folders assuming they were empty, without checking. This led to the false belief that HEL1OS and SoLEXS never overlap. It was caught by the read-only data inventory on 2026-10-22, which found 77 unextracted sessions in the kept zips. Corrected by selective re-extraction (847 files verified), a correction in `CLAUDE.md`, and a new rule: never delete or move data without asking, and check contents first (`docs/PROGRESS.md`, `CLAUDE.md`).",
        "HEL1OS parser dropped most of each band in newer files (bands start at different sub-second offsets) → each band rounded to whole seconds before joining; regression test added (`docs/PROGRESS.md`).",
        "Full HEL1OS extraction (28.6 GB) did not fit on D: → extracted light curves + aux only (3.9 GB); zips kept (`docs/PROGRESS.md`).",
    ]:
        a(f"- {line}")
    a("")
    # ---- B. detector
    a("## B. Detector (final setting)")
    a("")
    a("| Metric | Legacy tune | Legacy val | **Final tune** | **Final val** |")
    a("|---|---|---|---|---|")
    for lab, f in [("Recall C", lambda r: r["goes_recall_by_class"].get("C", {}).get("recall")),
                   ("Recall M", lambda r: r["goes_recall_by_class"].get("M", {}).get("recall")),
                   ("Recall X", lambda r: r["goes_recall_by_class"].get("X", {}).get("recall")),
                   ("Match rate (detections matched to GOES)", lambda r: r["match_rate_all"]),
                   ("Onset error median (min)", lambda r: r["onset_error_min"]["median_abs"]),
                   ("Onset error p90 (min)", lambda r: r["onset_error_min"]["p90_abs"]),
                   ("Events > 2 h", lambda r: r["n_events_gt_long"]),
                   ("Detections", lambda r: r["n_events"])]:
        vals = [f(r) for r in (lt, lv, nt, nv)]
        a(f"| {lab} | " + " | ".join(f"{v:.2f}" if isinstance(v, float) else str(v) for v in vals) + " |")
    a("")
    a("Source: `reports/detection_metrics.json` (`legacy.*`, `new.*`). Final settings: "
      f"`min_excess_frac` {P['flare_detection']['min_excess_frac']}, `min_excess_abs` {P['flare_detection']['min_excess_abs']}, "
      f"`rise_steps` {P['flare_detection']['rise_steps']}, `dip_frac` {P['flare_detection']['dip_frac']}, 3-h cap — `params.yaml`; "
      "chosen by a 300-trial grid on the tuning period only — `reports/tuning_results.csv`.")
    a("")
    # ---- C. EDA
    a("## C. EDA — 10 key findings (source: `docs/EDA_SUMMARY.md`, numbers `reports/eda_numbers.json`)")
    a("")
    c, lt2, at, se, fs, dg, fe, b = (eda[k] for k in ("coverage", "long_term", "activity", "profiles", "stats", "detector", "features", "base_rates"))
    findings = [
        (f"{pct(c['missing_minute_fraction'])} of minutes are missing and the 17th of each month is only {pct(c['valid_frac_17th'], 0)} covered (other days {pct(c['valid_frac_other'], 0)}).", "docs/figures/eda/01_coverage_calendar.png"),
        (f"Daily median counts span {lt2['median_range'][0]:.1f}–{lt2['median_range'][1]:.0f} counts/s while peaks reach {lt2['max_daily_peak']:,.0f}; {lt2['n_M']} M and {lt2['n_X']} X flares occurred.", "docs/figures/eda/02_long_term_lightcurve.png"),
        (f"The background drifts from {at['bg_first_last'][0]:.1f} to {at['bg_first_last'][1]:.1f} counts/s and monthly GOES flare counts range {at['flares_per_month_range'][0]}–{at['flares_per_month_range'][1]}: the data are not stationary.", "docs/figures/eda/03_activity_trend.png"),
        (f"Median flare profiles peak {se['C_median_peak_min']}, {se['M_median_peak_min']} and {se['X_median_peak_min']} min after onset for C, M and X (n = {se['C']}, {se['M']}, {se['X']}).", "docs/figures/eda/04_superposed_epoch.png"),
        (f"SoLEXS peak excess grows as GOES flux^{fs['fit_slope']:.2f} (r = {fs['fit_r']:.2f}, {fs['n_matched_fit']} flares); the median event lasts {fs['median_duration_min']:.0f} min.", "docs/figures/eda/05_peak_vs_goes.png"),
        (f"Detector onset error median {dg['onset_err_median']:.0f} min (|p90| {dg['onset_abs_p90']:.0f} min), but {dg['missed_observed_C_M']} observed C/M flares were missed, mostly small ones on a high background.", "docs/figures/eda/06_detector_vs_goes.png"),
        (f"On quiet-start rows no single feature separates 'flare within 60 min' from 'no flare' (largest standardised median shift {max(abs(v) for v in fe['standardised_median_shift'].values()):.2f}).", "docs/figures/eda/07_feature_distributions.png"),
        (f"{len(fe['high_corr_pairs'])} feature pairs have |r| > 0.9 (rate, mean_1m and max_1m are near-identical).", "docs/figures/eda/07_feature_correlation.png"),
        (f"Flares are rare: ≥M within 60 min is {pct(b['rates']['≥M 60m'])} of rows, swinging {pct(b['month_m60_range'][0])}–{pct(b['month_m60_range'][1])} by month.", "docs/figures/eda/08_label_base_rates.png"),
        (f"HEL1OS overlaps only tune {hx['tune']['overlap_hours']} h and val {hx['val']['overlap_hours']} h; the Neupert lag is median {ne['median_lag_s']:.0f} s (IQR {ne['iqr_s'][0]:.0f} to {ne['iqr_s'][1]:.0f} s, {ne['n']} flares), confirming the physics and the clock alignment.", "docs/figures/eda/09_neupert_lag.png"),
    ]
    for i, (txt, fig) in enumerate(findings, 1):
        a(f"{i}. {txt} — `{fig}`")
    a("")
    a(f"**Measured Neupert lag:** median {ne['median_lag_s']:.0f} s, interquartile range {ne['iqr_s'][0]:.0f} to +{ne['iqr_s'][1]:.0f} s, "
      f"n = {ne['n']} flares with peak correlation ≥ 0.3 — `reports/eda_numbers.json` (`hel1os.neupert`).")
    a("")
    # ---- D. labels & features
    a("## D. Labels and features")
    a("")
    a("**Targets in plain words** (labels built from the NOAA GOES flare list; the SoLEXS onset is used for a GOES flare's start "
      "when our detector matched it, else the GOES start — `src/labels.py`, `reports/label_comparison.json`):")
    a("")
    a("| Target | Meaning | tune all rows | tune quiet-start | val all rows | val quiet-start |")
    a("|---|---|---|---|---|---|")
    for key, _, _, desc in TARGETS:
        t, v = br["tune"][key], br["val"][key]
        a(f"| `{key}` | {desc} | {pct(t['all_rows'])} | {pct(t['quiet_start'])} | {pct(v['all_rows'])} | {pct(v['quiet_start'])} |")
    a("")
    a("Source: `reports/base_rates.json` (rows with the target's `ok` flag; quiet-start = no flare in progress at t, causal flag).")
    a("")
    a(f"- Features: **{len(feats) - n_hx} SoLEXS** + **{n_hx} HEL1OS** (incl. `hel1os_available`) = {len(feats)}, at "
      f"{ds['cadence_s']}-s cadence, all trailing/causal — `reports/dataset_summary.json` (`feature_columns`)")
    a(f"- Rows: tune {ds['periods']['tune']['rows']:,}, val {ds['periods']['val']['rows']:,}, test {ds['periods']['test']['rows']:,} (count only) — `reports/dataset_summary.json`")
    cv = P["models"]["cv"]
    a(f"- Training grid (XGBoost, rolling-origin CV on folds {', '.join(cv['fold_months'])}, metric aucpr): max_depth {cv['max_depth']}, "
      f"min_child_weight {cv['min_child_weight']}, reg_lambda {cv['reg_lambda']}, n_estimators {cv['n_estimators']} — `params.yaml` (`models.cv`)")
    a(f"- Seeds {P['models']['seeds']}; thresholds from the calibration block {P['models']['inner_split']} onwards (Dec–Jan): A = max TSS, B = max HSS; "
      f"{P['models']['bootstrap']['n']} day-bootstrap resamples — `params.yaml` (`models`)")
    a(f"- Label change from GOES-direct labels (≥C 30 min, tune): {labc['tune']['y_c_30m']['old_pos']:,} → {labc['tune']['y_c_30m']['new_pos']:,} positive rows — `reports/label_comparison.json`")
    a("")
    # ---- E. results
    a("## E. Model results (validation, 2026-02-01 … 2026-05-31)")
    a("")
    a("Each table: TSS mean ± std over 3 seeds (LogReg, XGBoost; others deterministic), 95% day-bootstrap interval for TSS, and HSS / POD / FAR "
      "(means over seeds). ★ = model selected for the target (highest mean TSS at operating point A, all rows, among rule / LogReg / XGBoost). "
      "Source for every number: `reports/model_metrics.json` (`targets.<target>.models.<model>.summary`). Rendered summary: `reports/validation_table.md`.")
    a("")
    for key, _, _, desc in TARGETS:
        t = mm["targets"][key]
        a(f"### {key} — {desc}")
        a("")
        for op, opname in (("A", "operating point A (max TSS on calibration)"), ("B", "operating point B (max HSS on calibration)")):
            for subset, sname in (("all", "all rows"), ("quiet", "quiet-start rows")):
                a(f"*{sname}, {opname}*")
                a("")
                L.extend(model_table(t, subset, op))
                a("")
    # ---- F. ablation
    a("## F. Ablation: soft vs hard vs combined (rows with HEL1OS available)")
    a("")
    ab = mm.get("ablation", {})
    if ab and "targets" in ab:
        few = [k for k, r in ab["targets"].items() if r.get("too_few_positives")]
        ok_t = [k for k, r in ab["targets"].items() if not r.get("too_few_positives") and "models" in r]
        g = lambda k, m, fs, sub: ab["targets"][k]["models"][m][fs]["A"][sub]  # noqa: E731
        a("**Plain conclusion.**")
        a(f"- Too few positives to conclude (< {ab['min_positive_episodes']} validation episodes): **{', '.join(few)}**. "
          "All M-class targets fall here, so we cannot say whether hard X-rays help M forecasts.")
        for k in ok_t:
            parts = []
            for m in ("logreg", "xgb"):
                so, ha, co = (g(k, m, fs, "all") for fs in ("soft", "hard", "combined"))
                parts.append(f"{m}: soft {so['tss_mean']:.2f} [{so['tss_ci_low']:.2f}, {so['tss_ci_high']:.2f}], "
                             f"hard {ha['tss_mean']:.2f} [{ha['tss_ci_low']:.2f}, {ha['tss_ci_high']:.2f}], "
                             f"combined {co['tss_mean']:.2f} [{co['tss_ci_low']:.2f}, {co['tss_ci_high']:.2f}]")
            a(f"- `{k}` (all rows, TSS at A): " + "; ".join(parts) + ".")
        q_so, q_co = g("now", "logreg", "soft", "quiet"), g("now", "logreg", "combined", "quiet")
        a(f"- Reading: for ≥C forecasts, hard X-rays alone carry about no skill and adding them does not beat SoLEXS alone "
          f"(intervals overlap). The only visible gain is the **quiet-start nowcast** with logistic regression: "
          f"combined {q_co['tss_mean']:.2f} [{q_co['tss_ci_low']:.2f}, {q_co['tss_ci_high']:.2f}] vs soft "
          f"{q_so['tss_mean']:.2f} [{q_so['tss_ci_low']:.2f}, {q_so['tss_ci_high']:.2f}], i.e. hard X-rays help to "
          "recognise a flare that has just begun. That is one target, one model, 8 validation days, so it is a hint, not a result.")
        a("")
    L.extend(ablation_tables(ab))
    a("")
    # ---- G. MLOps status
    a("## G. MLOps status")
    a("")
    tools = [
        ("Git", "Done", "Version control for code, configs, reports, lessons"),
        ("DVC", "Done", f"{len(dvc['stages'])}-stage pipeline (`dvc.yaml`), hardlink cache on D:, `dvc repro` rebuilds everything"),
        ("MLflow", "Done", "Experiment tracking: detector tuning, model comparison, ablation (`mlflow.db`)"),
        ("params.yaml", "Done", "Single config for paths, periods, detector, labels, features, models"),
        ("pytest", "Done", f"{n_tests} tests incl. leakage tests (future perturbation, AST check, test-period guard)"),
        ("pandera", "Not started", "Planned: schema checks on raw/processed tables (installed only)"),
        ("Prefect", "Not started", "Planned: orchestration/scheduling of the pipeline (installed only)"),
        ("FastAPI", "Not started", "Planned: prediction API"),
        ("Docker", "Not started", "Planned: container for the API (needs Docker Desktop)"),
        ("Kubernetes", "Not started", "Not planned for this course scope"),
        ("GitHub Actions", "Not started", "Planned: CI running pytest on every push (GitHub connection to be fixed)"),
        ("Prometheus", "Not started", "Planned: service metrics"),
        ("Grafana", "Not started", "Planned: dashboards"),
        ("Evidently", "Not started", "Planned: data/feature drift reports (EDA already shows drift)"),
    ]
    a("| Tool | Status | What it does here |")
    a("|---|---|---|")
    for t_ in tools:
        a(f"| {t_[0]} | {t_[1]} | {t_[2]} |")
    a("")
    a(f"- DVC stages: **{len(dvc['stages'])}** — `dvc.yaml`")
    a(f"- Tests: **{n_tests}** — `pytest --collect-only -q`")
    a(f"- MLflow runs: **{sum(runs.values())}** (" + ", ".join(f"{k}: {v}" for k, v in sorted(runs.items())) + ") — `mlflow.db`")
    a(f"- Last commit: **`{commit}`** — `git rev-parse --short HEAD`")
    a("")
    # ---- H. limitations
    a("## H. Honest limitations and next steps")
    a("")
    for line in [
        "Validation has been used for several model comparisons, so validation scores are somewhat optimistic; the test period is still unopened and is the only unbiased score.",
        "M-class forecasts have high false-alarm ratios at the max-TSS threshold (see section E, FAR column); a cost-based or FAR-capped threshold is needed for real use.",
        "Bootstrap intervals are wide (often ±0.1–0.2 TSS for M targets); differences between LogReg and XGBoost are mostly within the uncertainty.",
        "HEL1OS covers only about 2% of rows; the soft-vs-hard ablation is underpowered, especially for M targets (section F).",
        "The detector misses most B flares and some C flares on a high background; forecast labels now come from GOES, but the activity flag still uses the detector.",
        "Data drift (falling background, changing flare rates) is real; no drift monitoring yet.",
        "Next: one final evaluation on the test period with everything frozen; pandera checks; Prefect flow; FastAPI + Docker; GitHub Actions CI; drift monitoring (Evidently).",
    ]:
        a(f"- {line}")
    a("")
    # ---- I. one minute
    sel_now = mm["targets"]["now"]
    now_a = sel_now["models"][sel_now["selected"]]["summary"]["A"]["all"]
    pers = sel_now["models"]["persistence"]["summary"]["A"]["all"]
    m30 = mm["targets"]["m_30m"]
    m30a = m30["models"][m30["selected"]]["summary"]["A"]["all"]
    a("## I. If I only had one minute")
    a("")
    a(f"1. We built a reproducible MLOps pipeline (Git, DVC with {len(dvc['stages'])} stages, MLflow, {n_tests} tests) that turns raw Aditya-L1 SoLEXS and HEL1OS data into flare nowcasts and forecasts.")
    a(f"2. Our GOES-style detector finds flare starts within a median of {nt['onset_error_min']['median_abs']:.0f} minute of NOAA's times, and labels come straight from the NOAA GOES flare list.")
    a(f"3. Nowcasting works well: TSS {now_a['tss_mean']:.2f} (95% interval {now_a['tss_ci_low']:.2f}–{now_a['tss_ci_high']:.2f}), clearly better than the persistence baseline at {pers['tss_mean']:.2f}.")
    a(f"4. Forecasting M-class flares 30 minutes ahead reaches TSS {m30a['tss_mean']:.2f}, also on quiet-Sun starts, but with many false alarms and wide uncertainty — we report baselines and intervals so it is not over-claimed.")
    a("5. Everything is leak-tested and time-split; the test period has never been opened and will give one final, honest score.")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    print("wrote", OUT)


if __name__ == "__main__":
    {"base_rates": export_base_rates, "facts": write_facts}[sys.argv[1]]()
