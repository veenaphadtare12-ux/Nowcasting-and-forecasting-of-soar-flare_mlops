# Final choice — frozen before the test period is opened

*Written and committed on 2026-11-09, before any code that reads the test period existed. Machine-readable copy:
`params.yaml` → `final`. Nothing in this file may be changed after the test results are seen; any later change
must be a new, dated section that explains why.*

## 1. How the choice was made

The evidence is the rolling monthly evaluation (`docs/IMPROVEMENTS.md`, `reports/improve/*.json`): 10 months,
Aug 2025 – May 2026, each scored by a model fitted only on earlier months.

For each target:
1. **Learner:** the reference learner is the one with the higher mean monthly TSS under the rolling protocol
   (`reports/improve/reference.json` → `summary`).
2. **Extra ideas:** the improvement ideas (the "final candidate") are adopted only if both conditions hold:
   - the final candidate passed the pre-registered acceptance rule (mean monthly TSS up AND ≥ 6 of 10 months
     better);
   - it is **not worse on the original validation block** (`reports/improve/final.json` → `validation_block`).

   This second condition is added now as a tie-breaker for borderline cases, before the test is opened.
3. **Otherwise** the reference model on the 44 base features is kept: simpler models win ties.

| Target | Registry name | Chosen model | Features | Rolling mean TSS (months better) | Validation block TSS [95%] | Why |
|---|---|---|---|---|---|---|
| now | `flare-nowcast` | XGBoost | 44 base | 0.701 (XGB) vs 0.684 (LogReg) | 0.730 [0.71, 0.75] | Final candidate passed the rule (0.712, 7/10) but was lower on the validation block (0.722). Gain too small for 4 extra inputs: keep the reference. |
| c_30m | `flare-forecast-c30` | LogReg + XGBoost average | 44 base + E2 long context + E3 drift-normalised + E5 spectral (64) | 0.155 → **0.193** (9/10) | 0.208 → **0.290** [0.23, 0.35] | The one clear, consistent gain. |
| c_60m | `flare-forecast-c60` | XGBoost | 44 base | 0.189 (XGB) vs 0.173 (LogReg) | 0.188 [0.13, 0.24] | No idea passed the rule. |
| m_30m | `flare-forecast-m30` | LogReg | 44 base + E5 spectral + E6 GOES XRS (56) | 0.258 → 0.311 (7/10) | 0.468 → 0.474 [0.29, 0.60] | Passes both conditions. Caveat: depends on GOES XRS data. |
| m_60m | `flare-forecast-m60` | LogReg | 44 base | 0.261 (LogReg) vs 0.231 (XGB) | 0.467 [0.29, 0.60] | Final candidate (E5) passed the rule only at 6/10 and was lower on the validation block (0.459): keep the reference. |

Notes:
- **Runner-up per target** (for the paired test): the other learner on base features. For c_30m and m_30m it is
  the reference model they replaced (LogReg on base features).
- c_120m and m_120m were not part of the improvement experiments. They are not frozen or registered here, and they
  stay with the main training results (`reports/model_metrics.json`).

## 2. Frozen training and thresholds

| Step | Data | Rows used |
|---|---|---|
| Fit | 2025-04-09 → 2026-05-01 minus 120 min (tune + val except the last month) | `ok` rows, every 6th row, seed 42 |
| Thresholds | 2026-05-01 → 2026-06-01 minus 120 min (= month m−1 of the test, exactly as in the rolling protocol) | all `ok` rows |
| Test | 2026-06-01 → 2026-09-12 | all `ok` rows, **scored once** |

**Operating points**, all chosen on the threshold block only, then frozen:
- **A** = threshold with maximum TSS (the main metric);
- **B** = threshold with maximum HSS (fewer false alarms);
- **C** = lowest threshold whose alerts have FAR ≤ 0.80 (at most 4 false alarms per true alarm).

**Expected weaknesses, stated in advance:**
- The threshold block holds only 8 M flares (`reports/eda_numbers.json` → `activity.monthly_counts`), so the M
  thresholds are noisy.
- Operating point C was unusable for M flares in the rolling evaluation (POD 0.00–0.04).
- For C flares, C is degenerate: with about 20% positives, alerting on everything already has FAR ≈ 0.8.

## 3. What will be reported from the test (and nothing will be re-tuned)

**Main metrics:**
- TSS, HSS, POD and FAR at A, B and C, on all rows and on quiet-start rows.
- 95% day-bootstrap intervals (1,000 resamples).
- Baselines: climatology, persistence and the 1-feature rule, with thresholds from the same block.

**Paired day-bootstrap test** of TSS at A, chosen model vs:
- the best baseline;
- the runner-up model.

One-sided p-value = share of resamples in which the chosen model is not better.

**Calibration:**
- Reliability diagrams and Brier score per target.
- If calibration is poor, isotonic calibration is fitted on the threshold block only, and the test Brier score is
  reported before and after.
- Isotonic calibration is monotone, so the alerts don't change.

**Event-based evaluation**, per GOES flare. Flare start = the label onset rule in `src/labels.py` (`goes_onsets`):
- **Forecasts:** a flare of at least the target's class counts as warned if the model alerts (point A) at any row
  in [start − horizon, start). Lead time = start − first such alert.
- **Nowcast:** a GOES-matched event counts as detected if the model alerts between its onset and end. Delay =
  first alert − onset.
- A flare is scored only if ≥ 50% of its look-back window has usable rows.
- Results: hit rate and lead-time distribution per class.

**Operational lead time** for every M and X flare in the test:
- **NOAA's moment:** t_M1 = the end of the first GOES-19 XRS-B 1-minute average ≥ 1×10⁻⁵ W/m².
- **Our first alert:** the first alert (point A) of the m_30m, m_60m and nowcast models in
  [t_M1 − 120 min, t_M1 + 30 min].
- Lead = t_M1 − first alert. Positive means we warned before NOAA's M1 alert.

**Error analysis:**
- Missed M flares: figures of the light curve and our probability around each one.
- False-alarm clusters: alert episodes (gaps under 10 min merged) with no qualifying flare start within the
  horizon.

**Other outputs:**
- SHAP summary for the XGBoost nowcast, from XGBoost's built-in exact tree SHAP (`pred_contribs`).
- MLflow registry: one model per target, alias `champion`. Tags: target, thresholds, training dates, git commit,
  dvc.lock hash; signature and input example included.

---

## 4. Results — added on 2026-11-09 AFTER the one-time test (sections 1–3 above are unchanged)

**Order of events in git:**
1. Choice: `d31d6ab` (22:25 IST).
2. Test-evaluation code: `edac79a`.
3. Frozen and registered models: `5fb3338`.
4. Only then the test run, stage `evaluate_test`.

### Test vs rolling evaluation (TSS at operating point A, all rows)

| Target | Chosen model | Rolling protocol, mean ± std of 10 months | Original validation block | **Test** [95% day-bootstrap] | Test, quiet-start | Chosen − runner-up (one-sided p) | Chosen − best baseline (p) |
|---|---|---|---|---|---|---|---|
| now | XGBoost | 0.701 ± 0.035 | 0.730 | **0.758** [0.74, 0.78] | 0.548 | +0.016 (p ≤ 0.001) | +0.090 vs persistence (p ≤ 0.001) |
| c_30m | LogReg+XGB, E2/E3/E5 | 0.193 ± 0.113 | 0.290 | **0.358** [0.29, 0.42] | 0.372 | +0.091 (p ≤ 0.001) | +0.342 vs persistence (p ≤ 0.001) |
| c_60m | XGBoost | 0.189 ± 0.102 | 0.188 | **0.304** [0.23, 0.37] | 0.311 | −0.007 (p = 0.61) | +0.277 vs rule (p ≤ 0.001) |
| m_30m | LogReg, E5/E6 | 0.311 ± 0.185 | 0.474 | **0.518** [0.34, 0.63] | 0.534 | +0.013 (p = 0.27) | +0.463 vs rule (p ≤ 0.001) |
| m_60m | LogReg | 0.261 ± 0.174 | 0.467 | **0.494** [0.33, 0.60] | 0.497 | +0.005 (p = 0.15) | +0.414 vs persistence (p ≤ 0.001) |

Sources:
- `reports/improve/reference.json` and `final.json` (rolling and validation block);
- `reports/final/test_metrics.json` → `targets.<t>.metrics.chosen.A`, `paired`.
- p-values come from 1,000 paired day-bootstrap resamples, so "p ≤ 0.001" is the smallest value they can show.

### Reading
- **Every chosen model beats every baseline clearly** (p ≤ 0.001).
- **The one improvement adopted from the experiments, c_30m, is confirmed on the test:** +0.091 TSS over the model
  it replaced (p ≤ 0.001).
- **For c_60m, m_30m and m_60m the chosen model and the runner-up are statistically tied.** The choice between them
  doesn't matter much.
- **Test scores are higher than the rolling-protocol means.** The final models were trained on more data, and the
  rolling mean includes months with almost no skill (`docs/MODEL_CARD.md`). They are close to the original
  validation block for M targets.
- **Nothing was changed after these results.** The champions stay as registered (version 1).
