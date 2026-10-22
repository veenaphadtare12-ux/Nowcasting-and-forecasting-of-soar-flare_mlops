# Figure notes (for the guide)

All figures: 1920 × 1080 px, tuning (2025-04-09 … 2026-01-31) and validation (2026-02-01 … 2026-05-31) data only.
The test period is never evaluated. Orange = SoLEXS (soft X-rays), blue = HEL1OS (hard X-rays). Made by
`python -m src.presentation_figures`; the numbers behind figures 04–10 are in `reports/presentation_figures.json`.

---

## 01 — `01_coverage_heatmap.png`
**Caption:** Fraction of each day with valid SoLEXS data, one row per month and one column per day of the month.

**Key numbers**
- 331 usable days out of 418 calendar days — `reports/eda_numbers.json` (`coverage.days_usable`, `coverage.days`)
- 23.7% of minutes missing overall — `reports/eda_numbers.json` (`coverage.missing_minute_fraction`)
- The 17th of each month is only 11% valid (other days 80%) — `reports/eda_numbers.json` (`coverage.valid_frac_17th`, `valid_frac_other`)

**Takeaway:** The data have real, regular gaps; we excluded bad days and never filled gaps with invented values.

**Caveat:** White means "no data". Light-grey cells are dates that don't exist (e.g. 30 Feb), not missing data.

---

## 02 — `02_longterm_lightcurve.png`
**Caption:** Daily median and daily maximum SoLEXS count rate over tune + validation, with every GOES M- and X-class flare marked.

**Key numbers**
- 326 M-class and 21 X-class flares — `reports/eda_numbers.json` (`long_term.n_M`, `long_term.n_X`)
- 90% of daily medians lie between 3.5 and 91 counts/s (5th–95th percentile, not min–max); the highest 1-minute peak of any day is 34,637 counts/s — `reports/eda_numbers.json` (`long_term.median_range` = [p5, p95], `max_daily_peak`)

**Takeaway:** Near solar maximum, flares are frequent and the signal spans four orders of magnitude, so we work in log space and relative-to-background features.

**Caveats**
- Log scale. The daily maximum is a 1-minute mean, so very short spikes are smoothed.
- The single lowest and highest daily medians fall outside the 3.5–91 range; `median_range` deliberately reports the 5th–95th percentile so that a few extreme days don't define the range.

---

## 03 — `03_monthly_flares_by_class.png`
**Caption:** GOES flares per month, stacked by class (B, C, M, X), with the tuning/validation boundary marked.

**Key numbers**
- 155 to 368 flares per month — `reports/eda_numbers.json` (`activity.flares_per_month_range`)
- Totals: B 339, C 2,673, M 326, X 21 — `reports/eda_numbers.json` (`activity.monthly_counts`, summed)

**Takeaway:** Flare rates change from month to month (non-stationary data), which is why we split in time and report confidence intervals.

**Caveat:** These are all GOES flares, including those that happened while SoLEXS had no data. B-class counts are incomplete, because GOES under-reports B flares on a high background.

---

## 04 — `04_flare_profiles_by_class.png`
**Caption:** Superposed epoch analysis: the median SoLEXS light curve (normalised to each flare's peak excess) of C, M and X flares, aligned on the SoLEXS onset, with 25–75% bands.

**Key numbers**
- n = 1,596 C, 218 M, 16 X flares — `reports/presentation_figures.json` (`profiles_n`)
- Median time from onset to peak: C 7 min, M 12 min, X 15 min — `reports/eda_numbers.json` (`profiles.*_median_peak_min`)

**Takeaway:** Bigger flares take longer to reach their peak, so the first minutes after onset carry information about how big a flare will become.

**Caveat:** The X-class curve is based on only 16 flares, so its band is wide and its shape is noisy.

---

## 05 — `05_neupert_lag_histogram.png`
**Caption:** For each flare, the lag at which HEL1OS 20–40 keV hard X-rays best match the rate of rise of SoLEXS soft X-rays (the Neupert effect).

**Key numbers**
- n = 71 flares (GOES ≥C, peak correlation ≥ 0.3) — `reports/eda_numbers.json` (`hel1os.neupert.n`)
- Median lag 0 s; middle half −10 to +20 s — `reports/eda_numbers.json` (`hel1os.neupert.median_lag_s`, `iqr_s`)

**Takeaway:** Hard X-rays peak at the same moment soft X-rays rise fastest, as solar physics predicts. This also proves the two instruments' clocks are aligned.

**Caveats**
- The bin width (10 s) equals the data resolution. Lags shorter than 10 s can't be measured, so "0 s" means "within one 10-s step".
- 5 of the 71 flares lie beyond ±200 s (−290, −270, −220, +210, +210 s). These are likely mismatched peaks in complex events. The median is robust to them: it stays 0 s with or without them (checked with `eda.neupert_lags`, read-only).

---

## 06 — `06_stacked_flare_example.png`
**Caption:** One flare seen by both instruments: SoLEXS soft X-rays (top) and HEL1OS bands 5–150 keV (CdTe 5–20, CZT 20–40, CZT 40–150) (bottom).

**Key numbers**
- GOES X2.5 flare, SoLEXS onset 2026-04-24 08:01 UTC — `reports/presentation_figures.json` (`stacked_example`)
- Chosen by a fixed rule: the strongest GOES-matched flare with a clear hard X-ray response — `src/presentation_figures.py` (`stacked_example`)

**Takeaway:** Hard X-rays are spiky and short (the impulsive phase), while soft X-rays rise and decay smoothly. The two instruments see different parts of the same event.

**Caveats**
- Both panels use a **log scale**. On a linear scale, the gradual soft X-ray rise from 08:01 to about 08:09 is invisible, and the onset line would look misplaced.
- This flare is in the validation period, and it is a single example, not a statistic.

---

## 07 — `07_detector_before_after.png`
**Caption:** The old (legacy) and new detector on three real cases: early onset fixed, over-long event ended, merged flares separated. Legend: grey bar = old detector event, black bar = new detector event, shaded band = GOES flare (begin to end); orange line = SoLEXS 1-minute mean.

**Key numbers**
- Median onset error: 5.8 min (old) → 1.0 min (new), tune — `reports/detection_metrics.json` (`legacy.tune`, `new.tune` → `onset_error_min.median_abs`)
- Events longer than 2 h: 218 → 5 (tune) — `reports/detection_metrics.json` (`n_events_gt_long`)
- Share of detections matched to a GOES flare: 0.51 → 0.76 (tune) — `reports/detection_metrics.json` (`match_rate_all`)

**Takeaway:** The new GOES-style detector starts flares at the right time and ends them properly, so flare timing and labels are trustworthy.

**Caveats**
- The examples come from fixed rules (`src/detection/plots.py`, `pick_examples`), not from hand-picking.
- The new detector trades recall for precision: it misses most B flares (recall 0.18, old 0.99). That is why forecast labels come from GOES directly.

---

## 08 — `08_model_skill_validation.png`
**Caption:** Validation TSS (operating point A) of the best model vs the best baseline for each of the 7 targets, on all rows (top) and on quiet-start rows (bottom), with 95% day-bootstrap intervals.

**Key numbers**
- Nowcast: XGBoost 0.73 [0.71, 0.74] vs persistence 0.66 — `reports/model_metrics.json` (`targets.now.models.*.summary.A.all`)
- ≥M within 30 min: LogReg 0.47 [0.33, 0.57] vs best baseline 0.11; on quiet starts 0.46 — `reports/model_metrics.json` (`targets.m_30m`)
- ≥C within 60 min: LogReg 0.21 [0.14, 0.27] vs rule 0.03 — `reports/model_metrics.json` (`targets.c_60m`)

**Takeaway:** Every model beats its best simple baseline, and the forecasts keep their skill when no flare is in progress, so they are not just "a flare is already happening".

**Caveats**
- At these thresholds the ≥M models raise many false alarms (FAR 0.88–0.97).
- Validation was used to select models, so these scores are slightly optimistic.
- The best baseline is chosen separately per target and per panel.
- **Quiet start, especially for the nowcast:** a row is "quiet-start" when the causal activity flag `flare_in_progress_at_t` is 0.
  - The flag comes from our own detector in real time: it switches on at the detector's trigger and off once the end is confirmed.
  - So it can lag the GOES flare times by minutes. A quiet-start nowcast row can still lie inside a GOES flare that the detector hasn't triggered on yet; these rows are the hard early-detection cases.
  - Persistence ("yes while a flare is in progress") never alerts on quiet-start rows, so its quiet-start TSS is 0 by construction. That is why the nowcast's best quiet-start baseline is the 1-feature rule (0.30), not persistence.

---

## 09 — `09_ablation.png`
**Caption:** Soft X-ray features only vs hard X-ray features only vs both, on the rows where HEL1OS data exist, for LogReg (top) and XGBoost (bottom), with each target's number of validation positive episodes printed above it.

**Key numbers**
- 51,667 validation rows on 8 days — `reports/model_metrics.json` (`ablation.rows.val`, `ablation.val_days`)
- Positive episodes: nowcast 69, ≥C 30 min 60, ≥C 60 min 44; all M targets 12–15 and ≥C 120 min 17 (too few) — `reports/model_metrics.json` (`ablation.targets.*.val_positive_episodes`)
- Nowcast, LogReg, all rows: soft 0.68, hard 0.66, combined 0.67 — `reports/model_metrics.json` (`ablation.targets.now.models.logreg`)

**Takeaway:** With the HEL1OS data we have, hard X-rays add no clear skill. For M flares there are too few events to decide either way.

**Caveats**
- Faded bars have fewer than 30 positive episodes and shouldn't be compared.
- Thresholds were chosen on Nov 2025 HEL1OS rows, because no HEL1OS session falls in Dec–Jan.
- The only hint of a gain is not shown in this figure: the quiet-start nowcast with LogReg, combined 0.45 [0.42, 0.48] vs soft 0.37 [0.31, 0.43] (`ablation.targets.now.models.logreg.*.A.quiet`).

---

## 10 — `10_feature_importance.png`
**Caption:** The top 15 features of the ≥C-within-60-min model (logistic regression), measured by how much average precision drops when each feature is randomly shuffled (permutation importance).

**Key numbers**
- Top 3: `bg_60m` 0.085, `std_15m` 0.064, `mean_15m` 0.047 — `reports/presentation_figures.json` (`importance_top15`)
- Measured on the Dec 2025–Jan 2026 calibration rows (part of tune), 5 shuffles per feature — `src/presentation_figures.py` (`feature_importance`)

**Takeaway:** The model mostly uses the background level of the last hour and how variable the last 15 minutes were: an active, restless Sun predicts flares.

**Caveats**
- **No HEL1OS feature appears.** No HEL1OS session falls in Dec–Jan, so shuffling HEL1OS features can't change the score there. The figure says nothing about HEL1OS value (see 09).
- This is the seed-42 model, and features are correlated: shuffling one feature can be compensated by a near-copy, so individual importances are underestimated.
