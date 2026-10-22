# Project audit — 2026-10-22

**Scope:** the whole repository at commit `36fc9b7`.

**Changes made during the audit:** only the two that were allowed.
- **(a) Notebook line endings: done.** `git checkout -- notebooks/01_eda.ipynb` alone did nothing, because git
  considered the file unchanged. The working copy was removed and restored from git, so the content equals the
  committed version and is now LF.
- **(b) Stale `dvc.lock` entries: not removable by DVC.** `dvc commit -f` keeps them, so `dvc.lock` was restored
  from a backup (unchanged), and the entries are reported below.

No code, data, params or MLflow runs were changed. The test period was not opened.

| # | Check | Result | Evidence | What to do |
|---|---|---|---|---|
| **A. Repository health** |||||
| A1 | git working tree clean | **WARN** | `git status`: ` M src/eda.py`, uncommitted. It is a refactor from the unfinished slide-figure task that moves the Neupert cross-correlation into a reusable `neupert_lags()`. Verified read-only: it reproduces the recorded result exactly (71 flares, median 0 s, IQR −10…+20 s vs `reports/eda_numbers.json`). | Commit it with the slide-figure work (it's needed for figures 05/06), or revert it with `git checkout -- src/eda.py`. |
| A2 | All tests pass | **PASS** (after fix a) | Before the fix: `1 failed, 56 passed` (`test_tracked_text_files_use_lf_line_endings`, notebook CRLF). After: **`57 passed in 4.17s`**. | Nothing. The LF test did its job. |
| A3 | `dvc status` clean | **PASS** | `Data and pipelines are up to date.` | — |
| A4 | `dvc repro --dry` has nothing to run | **PASS** | `Data and pipelines are up to date.` | — |
| A5 | Stale `dvc.lock` entries | **WARN** | `dvc.lock` has 11 stage entries; `dvc.yaml` defines 9. `solexs_flares` and `goes_match` are leftovers from the first pipeline (`3e0781a`). `dvc commit -f` doesn't remove them. | Harmless. To remove: delete the two blocks from `dvc.lock` by hand, run `dvc status`, commit. Not done (not a clean DVC operation). |
| A6 | Free disk space | **PASS** | `df -h`: C: **21 GB** free (92% used), D: **22 GB** free (83% used). Both above the 10 GB stop rule and the 15 GB extraction floor. | Watch D: before any further HEL1OS extraction (events and spectra would need about 25 GB). |
| **B. Training completeness** |||||
| B1 | 7 targets × 5 models; 3 seeds (LogReg, XGBoost); operating points A and B; all-rows and quiet-start; 95% intervals | **PASS** | Script over `reports/model_metrics.json`: nothing missing; LogReg/XGBoost seeds = [42, 43, 44]; deterministic models have 1 run; 1,260 values checked. | — |
| B2 | Saved models and thresholds exist and load | **PASS** (with a note) | `models/`: 14 files (`<target>_logreg.joblib`, `<target>_xgb.json` for 7 targets) + `thresholds.json`. All 14 load; every booster has trees; thresholds for A and B exist for every model. **Only the seed-42 model of each learner is saved**; climatology, persistence and the rule need only thresholds. | If the seed-averaged model should be served, save all seeds (or an ensemble). |
| B3 | `model_metrics.json` matches MLflow (`flare-models-v2`) | **PASS** | 5 spot checks against the latest child runs, all exactly equal: `now-xgb A_all_tss_mean` 0.726734; `c_60m-logreg A_all_tss_mean` 0.208240; `m_30m-logreg B_all_far_mean` 0.884817; `m_120m-xgb A_quiet_tss_ci_low` 0.147236; `c_120m-persistence A_all_hss_mean` 0.031585. | — |
| B4 | HEL1OS ablation finished | **PASS** (results weak) | 7 targets × {logreg, xgb} × {soft, hard, combined}, all present. Validation positive episodes: now 69, c_30m 60, c_60m 44, **c_120m 17, m_30m 15, m_60m 13, m_120m 12 (flagged too few)**. Results (TSS at A, all rows, LogReg soft/hard/combined): now 0.68/0.66/0.67; c_30m 0.14/0.00/0.15; c_60m 0.21/0.02/0.16. Only quiet-start nowcast LogReg improves (0.37 → 0.45). | Report as "hint, not result". More HEL1OS data is needed (see `CHALLENGES.md`). |
| B5 | No NaN or impossible metric values | **PASS** | All TSS, HSS and interval bounds in [−1, 1]; POD and FAR in [0, 1]; no NaN; every TSS mean lies inside its 95% interval. | — |
| **C. Correctness and leakage** |||||
| C1 | Leakage and test-lock tests pass | **PASS** | `30 passed`. This covers all of `tests/test_leakage.py` (27: future-perturbation for SoLEXS ×3 and HEL1OS ×3, AST no-centred-windows, labels strictly after t, no label across period end, causal activity flag ×5, chronological periods and files, tuner reads tune only, …) plus `test_training_refuses_the_test_period`, `test_model_code_never_names_the_test_file` and `test_cv_months_lie_inside_the_fit_part_of_tune`. | — |
| C2 | No code reads the test period outside the dataset builder | **PASS** (wording note) | `grep` shows "test" only in: `config.py` (period list; `data_range` spans all periods for ingestion); `dataset.py` (writes `test.parquet`, deliberately skips label statistics for test); `presentation_facts.py` (counts only: usable days, rows, sessions); `build_eda_notebook.py` (an assert that forbids test). No model, tuning, EDA or report code loads `test.parquet`. **Note:** ingestion, detection and feature building *process* test days, so they're ready for the final evaluation, but nothing is evaluated on them. | Say "never evaluated / never used for decisions" rather than "never touched". |
| C3 | Positive rates plausible and consistent | **PASS** | Val rates are identical in `dataset_summary.json`, `base_rates.json` and the training code: now 0.0697; ≥C 0.1196/0.2157/0.3514; ≥M 0.0134/0.0240/0.0417. Quiet-start rates match too. Tune spot checks also match (0.0843, 0.2631, 0.0303). These are plausible near solar maximum (EDA: 155–368 GOES flares/month). | — |
| C4 | HEL1OS missingness and causal availability flag | **PASS** | HEL1OS available on **tune 4.01%** (77,625 rows) and **val 6.32%** (51,667 rows); `hx_*` missing on 95.99% / 93.68% of rows. On available rows, `hx_czt_lo_log_mean_1m` is never missing and the lag/correlation features only 0.13–0.38% (warm-up). No row has `hx_*` values without availability. The flag is a trailing 60-s count (`features.py` line 113); causality tests pass. Test period not checked (locked). | — |
| C5 | Thresholds chosen on Dec–Jan only | **PASS** (one documented exception) | `train.split_tune` puts calibration = tune rows ≥ `inner_split` 2025-12-01 (tune ends 2026-01-31); `_score_block` calls `best_threshold(y_cal, s_cal, …)` only; climatology and persistence use fixed thresholds. **Exception:** the HEL1OS *ablation* chooses thresholds on Nov 2025 HEL1OS rows (`ablation.py` line 48), because no HEL1OS session falls in Dec–Jan. This is documented. | Keep stating the ablation exception on slides. |
| **D. Presentation readiness** |||||
| D1 | `docs/presentation_figures/01`–`10` exist | **FAIL** | Only `01_coverage_heatmap.png` and `02_longterm_lightcurve.png` exist. **Missing:** `03_monthly_flares_by_class`, `04_flare_profiles_by_class`, `05_neupert_lag_histogram`, `06_stacked_flare_example`, `07_detector_before_after`, `08_model_skill_validation`, `09_ablation`, `10_feature_importance`. That task was interrupted. | Re-run the slide-figure task; the `eda.py` refactor it needs is ready. For figure 10, note that the best ≥C 60 min model is logistic regression (coefficients of correlated features are unstable), so use permutation importance. |
| D2 | `docs/PRESENTATION_FACTS.md` complete | **WARN** | Sections A–I are present and sourced. Missing: a list of the slide figures (no reference to `presentation_figures`). Section H says HEL1OS covers "about 2% of rows", but it's **4.7%** of tune+val rows (C4). | Regenerate after the figures exist; fix the HEL1OS share in `src/presentation_facts.py`. |
| D3 | Neupert-lag check done | **PASS** | `reports/eda_numbers.json`: n = 71 flares, median 0 s, IQR −10…+20 s (tune+val, real overlapping SoLEXS + HEL1OS data); figure `docs/figures/eda/09_neupert_lag.png`. | Note the 10-s resolution limit (see `CHALLENGES.md`). |
| **E. Plan vs reality** |||||
| E1 | Claims in docs vs reality | **WARN** | (1) HEL1OS share stated inconsistently: `EDA_SUMMARY.md` #10 "about 2% of the time" (calendar hours are about 3.6%); `PRESENTATION_FACTS.md` H "about 2% of rows" (actual 4.7%); `WHAT_WE_DID.md` 1d "about 6% of tune+val rows" (6.3% is val only; combined 4.7%). (2) `WHAT_WE_DID.md` says 56/57 tests pass; now 57/57. (3) `docs/learn/INDEX.md` doesn't list `lesson-dvc-mlflow.md`. (4) "Test period never opened" is true for evaluation, but test days are processed (C2). Nothing is claimed as done that isn't: deployment, serving, monitoring, registry, pandera, Prefect and CI are all marked not done everywhere checked. | Correct the three HEL1OS statements and the test count in the next doc update; add the lesson to INDEX. |

## Summary
- **PASS 15, WARN 6, FAIL 1.**
- **The one FAIL:** the missing slide figures 03–10.
- **The warnings:** an uncommitted (but verified) refactor, stale lock entries, the facts sheet's missing figure
  list and HEL1OS share, inconsistent HEL1OS percentages across docs, and wording about the test period.
- **No correctness or leakage problems were found.**
