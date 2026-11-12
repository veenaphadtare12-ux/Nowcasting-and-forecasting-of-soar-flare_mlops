# Test sanity check (read-only, 2026-11-13)

**Nothing was retrained, re-tuned or re-scored.**
- Test numbers come from the frozen per-row scores written once by `evaluate_test`
  (`data/processed/final/test_scores.parquet`), with the frozen thresholds in `models_final/thresholds.json`.
- Rolling numbers come from `reports/improve/reference.json`.
- Computed by `python -m src.final.sanity` → `reports/final/sanity.json`. That script does not read the test
  dataset file.

## 1. Why the test TSS is higher than the rolling evaluation

### 1a. The two numbers are aggregated differently (the biggest part of the gap)
The rolling figure is the **mean of 10 monthly TSS values**. The test figure is **one TSS pooled over all 3.4
months**. A month with few flares and near-zero skill pulls a mean of months down much more than it pulls a pooled
score down.

Here are both aggregations, side by side:

| Target | Rolling: mean of monthly TSS | Rolling: pooled over the 10 months | Test: mean of monthly TSS | **Test: pooled** (reported) |
|---|---|---|---|---|
| now (XGB) | 0.701 | 0.708 | 0.763 | **0.758** |
| c_30m | 0.155 (ref. LogReg) / 0.193 (final candidate) | 0.170 (ref. LogReg)* | 0.302 | **0.358** |
| c_60m (XGB) | 0.189 | 0.199 | 0.269 | **0.304** |
| m_30m | 0.258 (ref. LogReg) / 0.311 (final candidate) | 0.363 (ref. LogReg)* | 0.280 | **0.518** |
| m_60m (LogReg) | 0.261 | **0.402** | **0.282** | **0.494** |

\*Pooled rolling values exist only for the reference models. Monthly counts were not saved for the final-candidate
configurations.

Sources: pooled rolling values rebuilt from the saved monthly counts (TP = POD × positives, FP = alerts − TP) in
`reference.json`; test monthly values in `sanity.json` → `monthly`.

**Comparing like with like:**
- For the M targets the test mean of monthly TSS (0.28) is about the same as the rolling one (0.26–0.31).
- Most of the apparent jump for M flares (0.26 → 0.49) comes from comparing a mean of months with a pooled score.

### 1b. Base rates (share of positive rows; `ok` rows)

| Target | tune | val | test |
|---|---|---|---|
| now | 8.4% | 7.0% | 7.0% |
| c_30m | 14.7% | 12.0% | 11.0% |
| c_60m | 26.3% | 21.6% | 20.0% |
| m_30m | 1.58% | 1.34% | **1.80%** |
| m_60m | 3.03% | 2.40% | **3.46%** |

- The test period has *more* M-flare rows than tune or val, and *fewer* C-flare rows.
- TSS doesn't depend directly on the base rate, but more M rows means more M flares to recognise.

### 1c. GOES flares per month in the test (by peak time)

| Month | B | C | M | X |
|---|---|---|---|---|
| 2026-06 | 14 | 198 | 12 | 2 |
| 2026-07 | 19 | 124 | **53** | 1 |
| 2026-08 | 82 | 142 | 12 | 0 |
| 2026-09 (1–12 only) | 42 | 39 | 3 | 0 |
| *tune + val mean per month* | *24* | *191* | *23* | *1.5* |

- **July 2026 holds 53 of the test's 80 M flares (66%),** mostly one long active stretch from 29 June to 5 July.
- That isn't unprecedented: the busiest tune/val month had 73 M flares.
- Source: `sanity.json` → `goes_per_month`.

### 1d. Training size

| Target | Final model fit rows (1 per minute) | Rolling folds: mean (min – max) |
|---|---|---|
| now | 418,664 | 231,685 (90,176 – 388,480) |
| c_30m | 416,524 | 230,519 (89,809 – 386,471) |
| c_60m | 414,333 | 229,318 (89,431 – 384,415) |
| m_30m | 416,524 | 230,519 (89,809 – 386,471) |
| m_60m | 414,333 | 229,318 (89,431 – 384,415) |

- The final models saw about **1.8× more data** than the average rolling fold.
- For m_60m that's about 12,500 positive rows, and it includes the whole of the first validation months.
- More data plausibly explains part of the remaining gap, especially for the C targets.
- Source: `sanity.json` → `training_size`.

## 2. Baselines on the test, next to the chosen models (TSS at operating point A)

| Target | Chosen: all / quiet-start | Runner-up: all / quiet | Rule: all / quiet | Persistence: all / quiet |
|---|---|---|---|---|
| now | **0.758** / 0.548 | 0.742 / 0.514 | 0.654 / 0.264 | 0.668 / 0.000 |
| c_30m | **0.358** / 0.372 | 0.268 / 0.275 | 0.003 / −0.007 | 0.017 / 0.000 |
| c_60m | **0.304** / 0.311 | 0.311 / 0.315 | 0.027 / 0.007 | 0.026 / 0.000 |
| m_30m | **0.518** / 0.534 | 0.505 / 0.528 | 0.055 / 0.032 | 0.045 / 0.000 |
| m_60m | **0.494** / 0.497 | 0.489 / 0.489 | 0.064 / 0.004 | 0.080 / 0.000 |

- **The baselines did not get easier on the test.** For every forecast target they stay near zero (≤ 0.08), as in
  the rolling evaluation (best baseline ≤ 0.11).
- **Persistence is 0 on quiet-start rows by construction.**
- **Quiet-start skill is as high as all-row skill** for every forecast target. So the forecasts are not simply
  "a flare is already in progress".
- Source: `reports/final/test_metrics.json` → `targets.<t>.metrics.{chosen,runner_up,rule,persistence}.A`.

## 3. Feature sets of the final models

| Target | Model | Features | Base 44 | E2 long context | E5 spectral | E6 GOES XRS | E3 drift-normalised |
|---|---|---|---|---|---|---|---|
| now | XGBoost | 44 | 44 | – | – | – | no |
| c_30m | LogReg + XGB average | **67** | 44 | 17 | 6 | – | yes (transforms existing columns) |
| c_60m | XGBoost | 44 | 44 | – | – | – | no |
| m_30m | LogReg | 56 | 44 | – | 6 | **6** | no |
| m_60m | LogReg | 44 | 44 | – | – | – | no |

- Source: the feature lists stored in `models_final/<target>_chosen.joblib` (`sanity.json` → `features`).
- **Correction:** `FINAL_CHOICE.md` and `MODEL_CARD.md` said c_30m has 64 features. The stored model has **67**
  (44 + 17 + 6), so the earlier figure was an arithmetic slip in the text. The model itself is exactly the
  pre-registered configuration (same ideas E2/E3/E5).

### GOES XRS is an input only for m_30m: causality checks

The GOES features are `gx_b_log`, `gx_a_log`, `gx_ratio_log`, `gx_b_slope_5m`, `gx_b_slope_15m` and
`gx_b_max_60m`.

1. **No flux value from after t.**
   - Each GOES 1-minute average is stamped at the **end** of its minute (start + 60 s) and joined to the rows
     backwards in time (`merge_asof(direction="backward")`).
   - On 500 test-period rows, the newest GOES value used was **0–50 s old**, never in the future.
2. **Future-perturbation test on the test period.**
   - At 20 random test-period cut times, every GOES value after the cut was multiplied by a random factor of 5–50,
     and the features were rebuilt.
   - Largest change of any GOES feature at the cut: **0.0**.
   - Source: `sanity.json` → `goes_causality`.
3. **Can the label be inferred from flux that is already rising before t?** A forecast label counts flares whose
   *label start* is strictly after t. The label start is the SoLEXS onset when the detector matched the flare,
   otherwise the GOES begin time. So a row can be positive while GOES flux has already started rising, if GOES
   began before the SoLEXS onset.
   - **How common:** 24 of the 83 test ≥M flares have a label start after their GOES begin (median 3 min). That
     affects **407 positive rows: 2.9% of m_30m positives** (1.5% of m_60m).
   - **With those rows removed:** m_30m TSS goes **0.518 → 0.526** (chosen, with GOES) and **0.512** (runner-up,
     without GOES). m_60m goes 0.494 → 0.497.
   - The score does not depend on these "already rising" rows, and the same small effect exists for the SoLEXS
     features, so it's not specific to GOES.
4. **GOES adds almost nothing on the test.** The m_30m model with GOES beats the same model without GOES by only
   +0.013 TSS (paired p = 0.27), consistent with the 0.98 correlation between GOES and SoLEXS
   (`docs/IMPROVEMENTS.md`, E6).

## 4. Per-month test TSS (frozen threshold A, all rows)

| Target | Jun | Jul | Aug | Sep (12 days) | Pooled | Pooled without the best month |
|---|---|---|---|---|---|---|
| now | 0.748 | 0.708 | 0.794 | 0.804 | 0.758 | 0.749 (without Sep) |
| c_30m | 0.324 | 0.345 | 0.393 | 0.148 | 0.358 | 0.339 (without Aug) |
| c_60m | 0.272 | 0.200 | 0.398 | 0.207 | 0.304 | 0.262 (without Aug) |
| m_30m | 0.326 | **0.574** | 0.329 | −0.110 | 0.518 | **0.298** (without Jul) |
| m_60m | 0.259 | **0.521** | 0.471 | −0.122 | 0.494 | **0.317** (without Jul) |

Source: `sanity.json` → `monthly`.

- **Nowcast and C forecasts:** stable across months. No single month drives them.
- **M forecasts:** driven by **July**. Without July, m_60m drops from 0.49 to 0.32 and m_30m from 0.52 to 0.30.
- In July the Sun was continuously active. Our M models mostly signal "active period" (`MODEL_CARD.md`), so they
  are right most of the time in such a month.
- **September** (3 M flares in 12 days) has negative skill. This is the same pattern as the near-zero rolling months
  (Aug 2025: 0.01, Mar 2026: −0.05).

## 5. Conclusion

**The higher test score is explained. Nothing suspicious was found.**

1. **Most of the gap is aggregation.** The rolling figure averages months; the test figure is pooled. Measured the
   same way, the M targets agree: test mean of monthly TSS 0.28 vs rolling 0.26–0.31. Pooled rolling m_60m (0.40)
   is already close to the test (0.49).
2. **The rest has ordinary causes:**
   - the final models had about 1.8× more training data;
   - the test had more M-flare rows (3.5% vs 2.4–3.0%);
   - one very active month (July, 66% of test M flares) carried the M scores.
3. **No leakage signs:**
   - the baselines stayed near zero;
   - quiet-start skill equals all-row skill;
   - the GOES input is strictly causal (future perturbation changes nothing) and adds only +0.013;
   - removing "already rising" rows doesn't lower the score;
   - the nowcast and C targets are stable month to month.

**What to say honestly:** the pooled test TSS for M flares (about 0.5) is a best case driven by an active July. A
typical month's skill is closer to 0.3, and a quiet month can have no skill at all. The C targets improved more than
the aggregation alone explains (c_60m: rolling pooled 0.20 → test 0.30). More training data is the likely reason,
but with one test period this can't be proven.
