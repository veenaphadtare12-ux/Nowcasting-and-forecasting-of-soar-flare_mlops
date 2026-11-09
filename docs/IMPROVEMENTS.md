# Improvement experiments

*Section 1 was written on 2026-11-09, before any experiment was run. The results sections are added afterwards.*
The test period (2026-06-01 … 2026-09-12) is never opened, read or scored in any of this work.

## 1. Protocol and acceptance rule (fixed in advance)

**Rolling monthly evaluation over tune + val** (`src/improve/protocol.py`, settings in `params.yaml` → `improve`).
For each month m from 2025-08 to 2026-05 (10 months):

- **Fit** on all rows before the start of month m−1, minus a 120-min purge gap.
- **Thresholds** come from month m−1, minus a 120-min purge at its end, so that no label window reaches into month m.
- **Score** on month m.

Metrics:
- The metric is **TSS at operating point A** (the threshold that maximises TSS on the threshold month), on all rows.
  Quiet-start rows (causal activity flag = 0) are reported as well.
- Each experiment reports the **mean ± std over the 10 months**.
- Primary targets: **c_60m** and **m_60m**. Also reported: now, c_30m, m_30m.
- One seed (42); the seed spread in the main training was about 0.001 TSS. Same row stride (6) and XGBoost settings
  per target as the current models.

**Reference:** the current feature set and models (LogReg, XGBoost, plus the climatology, persistence and 1-feature
rule baselines) re-scored with this protocol → `reports/improve/reference.json`.

**Acceptance rule.** An idea is **KEPT** for a target only if, compared with the reference, it **raises the mean
monthly TSS** (operating point A, all rows) **and improves at least 6 of the 10 months**. Otherwise it is recorded as
**no gain** and **DROPPED** for that target.

How the comparison is made:
- The comparison uses the learner that is best in the reference for that target (higher mean monthly TSS), and the
  experiment uses the **same learner**.
- For the ensemble (E7), the averaged model is compared with that same reference learner.
- A month counts as "improved" only if its TSS is strictly higher. Ties count as not improved.

**Known limits of the protocol, stated before the results:**
- The XGBoost tree settings were chosen earlier by cross-validation on Aug–Nov 2025, which overlaps the first
  scored months. This favours the reference and the experiments equally, so the comparisons stay fair, but the
  absolute numbers are slightly optimistic.
- Validation months (Feb–May 2026) were already used for model selection, which is why the protocol scores all
  10 months.
- The final test-period score remains the only fully unbiased number.

## 2. Experiments

| ID | Idea | What changes |
|---|---|---|
| E1 | Adaptive thresholds | Thresholds refreshed daily from the previous 30 days (resolved labels only, never earlier than month m−1), instead of the fixed threshold month. Also adds operating point C: the lowest threshold with FAR ≤ 0.80 on the same rows; POD and FAR at C are reported for M targets. |
| E2 | Long-context features | Mean, max and slope of log SoLEXS counts over 3/6/12/24 h. Number of detector events and largest confirmed event peak in the last 6 h and 24 h. Hours since the last detector trigger. |
| E3 | Drift-robust features | Level features divided by their own trailing 7-day median; signed features (slopes, differences) divided by the trailing 7-day median of the count rate. |
| E4 | Feature pruning | For each pair with \|r\| > 0.95 on the fit rows of each fold, drop the later (more derived) feature in the feature list. |
| E5 | Spectral features | SoLEXS SDD2 .pi spectra: low band (PI channels 20–59) and high band (80–159) rates, their ratio (temperature proxy) and its 5/15-min slopes, and a HOPE-style flag (ratio and total counts both rising). |
| E6 | GOES XRS ablation | GOES-19 XRS 1-min long and short channel flux, their ratio, slopes and 60-min max, only up to t (each minute is labelled at its end). |
| E7 | Ensemble | Mean of the LogReg and XGBoost probabilities; threshold as in the reference. |
| E8 | InceptionTime (optional) | Only if time and disk allow. |

**On E2 and the rule in CLAUDE.md** ("detector catalogue fields are label-side only"): E2 uses only what the
detector knows in real time:
- an event counts from its **trigger time**;
- its peak counts only once its end is **confirmed** (the same logic as the causal activity flag).

Offline catalogue fields (onset found by looking back, GOES class, match) are still never used. Future-perturbation
tests cover every new feature.
