"""Write docs/FINAL_CHOICE_2.md from reports/dev2/choice.json and final_freeze.json (after src.dev2.final).

    python -m src.dev2.choice_doc
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from src import config
from src.dev2 import protocol as pr
from src.dev2 import run as rn

OUT = config.PROJECT_ROOT / "reports" / "dev2"


def sha(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _f(x, n=4):
    return "–" if x is None else f"{x:.{n}g}"


def doc() -> str:
    ch = rn.read("choice")
    fr = json.loads((OUT / "final_freeze.json").read_text(encoding="utf-8"))
    ing = json.loads((config.PROJECT_ROOT / "reports" / "holdout2" / "ingest.json").read_text(encoding="utf-8"))
    P = config.load_params()["dev2"]
    nm = len(P["months"])
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L: list[str] = []
    a = L.append
    a("# Final choice 2 — frozen before holdout2 is opened")
    a("")
    a(f"*Written {stamp}. Committed before any code built a holdout2 feature or label (`src/holdout2/evaluate.py` refuses "
      "to run otherwise and checks the model hashes in section 6). Nothing here may change after the holdout2 results are "
      "seen; any later change must be a new, dated section. Machine-readable: `params.yaml` → `dev2.final`, "
      "`reports/dev2/choice.json`, `reports/dev2/final_freeze.json`.*")
    a("")
    a("## 1. How the choice was made")
    a("")
    a(f"Evidence: the 14-month rolling protocol (2025-08 … 2026-09; the old test months are ordinary development data and "
      f"their old test scores were not used). Acceptance rule unchanged from `docs/IMPROVEMENTS.md`: mean monthly TSS up AND "
      f"at least {pr.need_months()} of {nm} months better (the same 60 % share as 6 of 10). Rule per target "
      "(`src/dev2/choose.py`, written before any development-2 result was read):")
    a("")
    a("1. Learner = the reference learner (LogReg / XGBoost) with the higher mean monthly TSS.")
    a("2. Aditya-only candidates, each against the reference with the same learner: R2 primary (own detector events), R3 "
      "stacked pretrained score, and the FINAL_CHOICE.md feature sets (c_30m E2+E3+E5 ensemble, m_30m E5). The KEPT "
      "candidate with the highest mean monthly TSS wins; none kept → base 44 features.")
    a("3. GOES-derived inputs only if they pass the rule on their own (E6 vs reference, R2 secondary vs R2 primary, "
      "m_30m E5+E6 vs E5). Then the champion is the `with_goes` variant; otherwise `aditya`.")
    a("4. R1: per input variant, the learner with the higher pooled per-trigger ≥M TSS averaged over k.")
    a("")
    a("## 2. Chosen model per target")
    a("")
    a("| Target | Learner | Champion inputs | Idea adopted | Reference: mean monthly / pooled / worst month | "
      "Aditya-only candidates (mean, months better, decision) | GOES-derived tests on their own |")
    a("|---|---|---|---|---|---|---|")
    for t, v in ch["targets"].items():
        r = v["reference"]
        cands = "; ".join(f"{k}: {c['exp_mean']:.3f}, {c['months_better']}/{nm}, {c['decision']}" for k, c in v["candidates"].items()) or "–"
        gt = "; ".join(f"{k}: {c['ref_mean']:.3f} → {c['exp_mean']:.3f}, {c['months_better']}/{nm}, {c['decision']}"
                       for k, c in v["goes_tests"].items()) or "–"
        inputs = (v["blocks"] or ["base 44"]) + (v["goes_blocks"] if v["choice"] == "with_goes" else [])
        a(f"| {t} | {v['learner']} | {' + '.join(inputs)} ({'Aditya-only' if v['choice'] == 'aditya' else 'with GOES'}) | "
          f"{v['idea']} | {r['mean_monthly_tss']:.3f} / {r['pooled_tss']:.3f} / {r['worst_month_tss']:.3f} ({r['worst_month']}) | "
          f"{cands} | {gt} |")
    a("")
    near = [(t, k, c) for t, v in ch["targets"].items() for k, c in v["candidates"].items()
            if c["decision"] == "DROPPED" and c["exp_mean"] > c["ref_mean"]]
    if near:
        a("Near misses (mean up, too few months): " + "; ".join(
            f"{t} {k}: {c['ref_mean']:.3f} → {c['exp_mean']:.3f}, {c['months_better']}/{nm} (needs {c['need']})" for t, k, c in near)
            + ". Under a literal \"6 months\" count they would have passed; the 60 % share was fixed in params.yaml before any "
            "development-2 result existed, and is kept.")
        a("")
    a("Blocks: base 44 = SoLEXS + HEL1OS features; ax = own detector events 24/48/72 h (R2 primary); long / drift / "
      "spectral = E2 / E3 / E5; goes = GOES XRS flux (E6); gc = GOES flare counts (known from end + 24 h); srs = NOAA SRS.")
    a("")
    a("Both input variants are frozen for every target, so each holdout2 result is shown with and without GOES:")
    a("")
    a("| Target | `aditya` inputs | `with_goes` inputs | Champion |")
    a("|---|---|---|---|")
    for t, v in fr["forecasts"].items():
        a(f"| {t} | {' + '.join(v['variants']['aditya']['blocks']) or 'base 44'} | "
          f"{' + '.join(['base 44'] + v['variants']['with_goes']['blocks'])} | {v['choice']} |")
    a("")
    a("## 3. Frozen training, calibration and thresholds")
    a("")
    a(f"- Fit: development rows before {P['final']['calibration_start']} minus 120 min (every 6th 10-s row, seed 42).")
    a(f"- Calibration (isotonic on the raw score): {P['final']['calibration_start']} … {P['final']['threshold_start']} minus 120 min.")
    a(f"- Thresholds on the raw score: {P['final']['threshold_start']} … 2026-09-12 minus 120 min. A = max TSS. M targets also "
      f"C = lowest threshold with FAR ≤ {P['far_cap']}, and K = minimum cost with a missed positive row costing "
      f"{P['cost_fn_fp']} false-alarm rows (sensitivity K{P['cost_sensitivity'][0]}, K{P['cost_sensitivity'][1]}). Baselines "
      "(rule, current flux) get thresholds from the same block; persistence alerts while a flare is in progress.")
    a("")
    a("| Target | Variant | Features | Fit rows (pos) | Calibration rows (pos) | Threshold rows (pos) | Threshold-block TSS at A | A | C | K10 |")
    a("|---|---|---|---|---|---|---|---|---|---|")
    for t, v in fr["forecasts"].items():
        for var, x in v["variants"].items():
            th = x["thresholds"]
            a(f"| {t} | {var} | {x['n_features']} | {x['fit_rows']:,} ({x['fit_pos']:,}) | {x['cal_rows']:,} ({x['cal_pos']:,}) | "
              f"{x['thr_rows']:,} ({x['thr_pos']:,}) | {x['thr_block_tss_A']:.3f} | {_f(th['A'])} | {_f(th.get('C'))} | {_f(th.get('K10'))} |")
    a("")
    r1 = fr["r1"]
    a("**R1 (early class prediction).** Learner per input variant: "
      + ", ".join(f"{k} → {v}" for k, v in P["final"]["r1"].items())
      + f". Fit on detections whose end was known before {P['final']['calibration_start']} minus 120 min "
      f"({r1['k0_aditya']['fit_triggers']} triggers, {r1['k0_aditya']['fit_m']} ≥M); thresholds (max TSS, ≥M and ≥C) on the "
      f"{r1['k0_aditya']['thr_triggers']} triggers of {P['final']['calibration_start']} … 2026-09-12 ({r1['k0_aditya']['thr_m']} ≥M).")
    a("")
    a("## 4. What will be reported from holdout2 (decided now)")
    a("")
    a(f"Holdout2: {ing['usable_days']} usable days ({', '.join(ing['usable_day_list'])}); GOES flares on them: "
      f"{ing['goes_flares_on_usable_days']}. **{ing['m_or_larger_on_usable_days']} ≥M flares < {ing['min_m_flares']}: every M "
      "result is UNDERPOWERED and no claim is made from it.**")
    a("")
    a("Headline metrics, for every target (champion variant first, then the other one = with / without GOES):")
    a("")
    a("1. TSS at operating point A pooled over all holdout2 rows, with a 95 % day-bootstrap interval (1,000 resamples, seed 0).")
    a("2. Per-month table: TSS at A for 2026-09 (1 day), 2026-10 (2 days), 2026-11 (8 days), with positives per month.")
    a("3. TSS at A on quiet-start rows, and on active vs quiet days (active = a GOES ≥M flare ended in the 72 h before the day).")
    a("4. Baselines at their own frozen thresholds: climatology (TSS 0), persistence, the 1-feature rule, current flux level.")
    a("5. M targets (UNDERPOWERED): POD, FAR and TSS at C (FAR ≤ 0.80) and K10 (cost), plus K5 / K20.")
    a("6. Calibration: Brier score raw vs isotonic vs climatology.")
    a("7. R1 per k ∈ {0, 1, 2, 3, 5} and input variant: per-trigger TSS, precision, recall for ≥M and ≥C; the 3-class "
      "confusion (<C, C, ≥M); lead time to NOAA's M1 crossing (median, share before it) for true ≥M alerts; the "
      "current-flux baseline.")
    a("")
    a("No threshold, model or feature is changed after these numbers are seen.")
    a("")
    a("## 5. Expected weaknesses, stated in advance")
    a("")
    a("- **Holdout2 is tiny and patchy:** 11 days in two clusters (2026-09-13; 2026-10-30 … 11-10 without 11-03/04). "
      "Intervals will be wide; the per-month table has 1, 2 and 8 days.")
    a("- **M results are underpowered** (7 ≥M flares on 3 days). The 12-day threshold block holds only a few ≥M flares, "
      "so the M thresholds are noisy.")
    a("- **After the 46-day gap** before 2026-10-30, long-window features (24 h context, 72 h event counts, 7-day drift "
      "medians) start without history on the first day.")
    never = sorted({f"{t} {k}" for t, v in fr["forecasts"].items() for var, x in v["variants"].items()
                    for k, th in x["thresholds"].items() if k != "A" and not (th < float("inf"))})
    if never:
        a("- **Operating points that never alert:** on the threshold block no threshold reaches FAR ≤ 0.80, and never "
          "alerting is the cheapest cost choice, for: " + ", ".join(never) + " (both variants). They will show POD 0 on "
          "holdout2; this is known now and is not a result.")
    a("- NOAA may still revise the most recent GOES event lists; the versions downloaded at the lock are used.")
    a("")
    a("## 6. Frozen files (SHA-256, checked by the holdout2 stage)")
    a("")
    a("| File | SHA-256 |")
    a("|---|---|")
    for f in sorted((config.PROJECT_ROOT / "models_final2").glob("*.joblib")):
        a(f"| `models_final2/{f.name}` | `{sha(f)}` |")
    a("")
    text = "\n".join(L)
    (config.PROJECT_ROOT / "docs" / "FINAL_CHOICE_2.md").write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return text


if __name__ == "__main__":
    doc()
