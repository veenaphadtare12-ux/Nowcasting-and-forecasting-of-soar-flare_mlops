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
