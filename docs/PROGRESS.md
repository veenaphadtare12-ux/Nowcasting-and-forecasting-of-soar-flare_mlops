# Progress log

Newest entries at the bottom. Each entry: what was done, key numbers, decisions (with reasons), problems.

## Before this log (summary of commits 7c9339f … 07c7845)

- **Setup.** Scaffolding, git, venv. Rebuilt on Python 3.12 (3.14 had no `dvc` wheels). `params.yaml` and `CLAUDE.md`
  added. `antlr4-python3-runtime==4.9.3` was built locally from its pure-Python sdist (no PyPI wheel exists).
- **Ingestion.** SoLEXS SDD2 light curves plus GTI → 1 s Parquet per day and a 1-min grid. 452 day folders in the
  periods, 424 usable (≥ 50% valid). HEL1OS parser: 27 → 23 sessions after the newest-version rule; no date overlap
  with SoLEXS, so HEL1OS is optional everywhere.
- **Detection.** GOES-style detector (trailing quantile background, Poisson threshold, onset = sustained rise,
  end = halfway decay, frozen background, dip splitting, 3 h cap). Tuned on the tune period only (300-trial grid,
  MLflow). Tune: match rate 0.76, C+ recall 0.865, onset error median 1 / p90 10 min, 5 events > 2 h.
  Val: 0.76, 0.887, 1/9 min, 2 events > 2 h.
- **Labels/features.** Nowcast + ≥C/≥M forecasts at 30/60/120 min, with `ok` flags. 27 causal features at 10 s
  cadence. Rows: tune 1.94 M / val 0.82 M / test 0.79 M (118.5 / 49.3 / 47.1 MB).
- **DVC + tests.** 8 stages, hardlink cache on `D:/dvc-cache`, 28 tests including leakage tests.

## 2026-10-21 — Task 1: catch-up lessons 01–05

**Done**
- Wrote `docs/learn/01-setup.md`, `02-ingestion.md`, `03-detection.md`, `04-labels-features.md`,
  `05-dvc-and-tests.md`, and `docs/learn/INDEX.md`.
- Every quoted line and "expected output" was checked against the current code and data. The "break it"
  experiments of lessons 02, 04 and 05 were run and reverted to confirm their outcomes.
- `CLAUDE.md`: teaching-mode rules replaced by autonomous-build-mode rules (the two conflicted).

**Problem found and fixed: CRLF line endings broke DVC's change detection**
- *Symptom:* after `git checkout -- src/features.py` (while verifying lesson 04's experiment), `dvc status` reported
  `build_dataset` as changed, although the code was identical.
- *Cause:* `core.autocrlf=true` makes git write Windows CRLF endings on checkout. DVC hashes raw bytes, so the
  file's md5 no longer matched `dvc.lock`. 21 tracked text files had CRLF in the working copy.
- *Fix:* added `.gitattributes` (`* text=auto eol=lf`, binaries marked binary), normalised the 21 files to LF,
  `git add --renormalize .`, then `dvc commit -f` to record the new hashes. No content changed (verified with
  `git diff --cached --ignore-cr-at-eol`), so re-running stages was unnecessary. After the fix the lesson-05
  experiment (edit a param, `git checkout`) leaves `dvc status` clean.

**Decisions**
- *Lesson 03 is honest about MAD.* The task asked for "MAD noise", but the detector does not use MAD; it uses
  Poisson counting noise √(bg/60) plus relative and absolute floors. The lesson explains MAD as a concept and says
  clearly that the code doesn't use it.
- *No pipeline code changed*, so no stage re-run was needed; `dvc status` is clean after `dvc commit`.

**Key numbers:** 28 tests pass (3 s). `dvc status`: up to date. Free disk: C: 18 GB, D: 27 GB (D: dropped from
41 GB since 7 Oct; not caused by this project, which uses about 2 GB on D:).

**Oddity noted, not touched:** `D:\dvc-cache\1NPDPRO5.DOC` (55 KB, dated Sep 2025) is not a DVC file. It looks like
a user document that ended up in that folder. DVC ignores it.

## 2026-10-21 — Task 2: model training (stage 5)

**Done**
- `src/models/metrics.py` (contingency, TSS, HSS, POD, FAR, exact best-threshold search), `src/models/train.py`
  (rule / logistic regression / XGBoost for 7 targets), `src/models/plots.py`, new DVC stage `train`,
  `tests/test_models.py` (6 tests), lesson `docs/learn/06-model-training.md`.
- Every run is logged to MLflow, experiment `flare-models` (21 runs per training run: target × model; params,
  calibration and validation metrics, model file, feature importance).

**Key numbers (validation, 2026-02-01 … 2026-05-31; threshold frozen from calibration)**

| Target | Selected | TSS | HSS | POD | FAR |
|---|---|---|---|---|---|
| nowcast | XGB | 0.722 | 0.515 | 0.80 | 0.57 |
| ≥C 30/60/120 min | LogReg/LogReg/XGB | 0.181 / 0.177 / 0.233 | 0.106 / 0.159 / 0.248 | 0.43 / 0.39 / 0.41 | 0.83 / 0.70 / 0.47 |
| ≥M 30/60/120 min | LogReg | 0.477 / 0.426 / 0.378 | 0.045 / 0.097 / 0.144 | 0.74 / 0.60 / 0.54 | 0.96 / 0.92 / 0.88 |

The one-feature rule baseline scores TSS 0.02–0.14 on the forecasts, so the models add real skill.

**Decisions**
- *Kept the tuned detector* (the open recall trade-off from Task 1). The alternative setting differed by only
  0.0009 in score, and changing it would invalidate the validated detector numbers.
- *Inner time split of the tune period* (fit < 2025-12-01 minus a 120-min purge; calibrate on Dec–Jan). Early
  stopping and thresholds come from calibration only. Validation is used once per model, for model selection.
  `load_period` refuses the test period, and a test enforces it.
- *Stride 6* (1 row per minute) for fitting: 248k rows instead of 1.49M, because adjacent 10-s rows are near-duplicates.
- *Threshold = max TSS on calibration*, per the project's primary metric. Consequence: many false alarms for rare M flares.
- *No re-tuning on validation results*: XGBoost's early-stopping weakness was recorded rather than iterated away,
  to avoid overfitting model choices to validation.

**Problems found**
- *Thin calibration months:* XGBoost early-stops very early on M targets (best iteration 0 for ≥M in 30 min,
  18–24 for 60/120 min). Dec–Jan held only 27 M-or-stronger flares, so `aucpr` is noisy there.
  Calibration TSS (0.23–0.33) is below validation TSS (0.38–0.48) for the M targets.
- *High false-alarm ratio for M:* 0.88–0.96 at the TSS-optimal threshold. That's expected for rare events, but an
  operational system would need a different threshold rule (see lesson 06 discussion questions).
- *Windows writes CRLF:* Python's `write_text` and pandas' `to_csv` write CRLF on Windows, so regenerated reports
  disagreed with git (LF) and DVC hashes flip-flopped. Fixed: every text writer now passes `newline="\n"` /
  `lineterminator="\n"`. A new test fails if any tracked text file has CRLF (`dvc.lock` is exempt, because DVC
  writes it itself and it is never a stage dependency).
- *GitHub MCP server is not connected:* "Authorization header is badly formatted". It can't be fixed from here;
  the user must reconnect it with `/mcp`. Not needed for this work (git is local).

**Checks:** 35 tests pass. `dvc repro` (full rerun, about 15 min) reproduced identical model scores, and
`dvc status` is clean. Free disk: C: 18 GB, D: 27 GB.

## 2026-10-21 — Task 3.1: forecast labels taken directly from GOES

**Done.** Forecast labels (`y_c_*`, `y_m_*`) are now positive when any GOES flare of class ≥C (≥M) starts in
`(t, t+h]`. A GOES flare's onset is the SoLEXS onset of the detection it is the *primary* match of (the
overlapping GOES flare whose begin is closest to that detection's onset), otherwise its GOES begin time. `ok`
flags and nowcast labels are unchanged. `reports/label_comparison.json` (tune and val only) compares new and old
labels. Two new tests: a GOES flare the detector missed gives a positive; a second flare merged into one
detection keeps its own GOES start.

**Positives on ok rows, old → new (gained / lost)**

| Label | tune | val |
|---|---|---|
| ≥C 30 min | 235,984 → 281,541 (+49,649 / −4,092) | 84,784 → 97,164 (+13,862 / −1,482) |
| ≥C 60 min | 430,630 → 502,306 (+74,994 / −3,318) | 155,503 → 174,227 (+20,404 / −1,680) |
| ≥C 120 min | 715,775 → 809,914 (+95,831 / −1,692) | 259,077 → 281,172 (+23,301 / −1,206) |
| ≥M 30 min | 30,348 → 30,270 (+2,508 / −2,586) | 10,849 → 10,927 (+918 / −840) |
| ≥M 60 min | 57,052 → 57,826 (+3,474 / −2,700) | 18,896 → 19,420 (+1,328 / −804) |
| ≥M 120 min | 106,358 → 108,388 (+4,704 / −2,674) | 33,023 → 33,371 (+1,152 / −804) |

**Interpretation**
- *C gains:* GOES C flares the tuned detector missed (it catches about 86% of C+). These were label noise before.
- *M lost and gained together:* onset shifts. The old method put a merged detection's *strongest* GOES class on the
  detection's onset, which could be much earlier than the M flare's own start. The new method uses the M flare's own start.

**Old models re-run on the new labels (validation TSS):** ≥C 30/60/120 min 0.199 / 0.193 / 0.279
(was 0.181 / 0.177 / 0.233); ≥M 0.479 / 0.455 / 0.382 (was 0.477 / 0.426 / 0.378). Nowcast unchanged (0.722).
Cleaner labels help the C forecasts most.

**Decision.** One lesson (07) covers tasks 3.1–3.2 (label noise, quiet-start) and one lesson (08) covers tasks
3.3–3.5 (baselines, CV, operating points, bootstrap), instead of five small lessons. The topics are tightly
linked and the user asked for one explanatory lesson covering them.

## 2026-10-21 — Task 3.2: causal activity flag and quiet-start split

**Done.** New `src/activity.py` adds a meta column `flare_in_progress_at_t`, based on the detector's real-time decisions:
- *Start:* the event becomes active at `trigger_time`, not at the catalogue onset.
- *End:* it stays active until the end is *confirmed*. That's end + `end_confirm_min` (2 min); the cap time for
  capped events; or end + `gap_end_min` (10 min) for events ended by a data gap.
- *All detections count:* matched or not, because the GOES list isn't available in real time.

The column is excluded from model features (`META_COLUMNS`) and is used for the persistence baseline and the
quiet-start evaluation split.

**Tests:** 7 new tests. One checks that the flag up to time T never changes when everything after T is removed (5 cut
points around a synthetic flare); one checks that it starts at the trigger, not the onset, and ends at confirmation.
43 tests pass.

**Key numbers**
- Flag on: 8.8% of tune rows, 7.3% of val rows.
- Val, `y_now` given the flag: flag=1 → 65.7% in a GOES-matched flare; flag=0 → 2.4% (mostly unmatched
  detections and onset-to-trigger lag).
- Val base rates by flag: ≥C in 60 min 21.3% (flag 0) vs 24.5% (flag 1); ≥M in 60 min 2.2% vs 5.3%.
  So an ongoing flare more than doubles the chance of an M flare starting soon (flares cluster).

**Decision.** The all-rows vs quiet-start metrics are reported by the rewritten training stage (tasks 3.3–3.5), so
every number comes from the final models and is reported once.

## 2026-10-21 — Tasks 3.3–3.5: baselines, robust XGBoost, operating points, bootstrap intervals

**Done.** The training stage (`src/models/train.py`, `metrics.py`, `report.py`, `plots.py`) was rewritten:
- *Five models per target:* climatology (constant = fit-period positive rate), persistence (`flare_in_progress_at_t`),
  1-feature rule, logistic regression, XGBoost.
- *XGBoost settings by rolling-origin CV:* train on all earlier months, score on Aug, Sep, Oct, Nov 2025 (120-min
  purge), metric aucpr. Grid: max_depth {3,5} × min_child_weight {5,50} × reg_lambda {1,10} × n_estimators
  {100,300,600}, the tree counts scored from one 600-tree fit via `iteration_range`. No early stopping. Dec–Jan is
  used only for thresholds.
- *Seeds:* LogReg and XGBoost fitted with seeds 42/43/44, reported as mean ± std.
- *Operating points from Dec–Jan:* A = max TSS (main), B = max HSS (fewer false alarms).
- *Intervals:* 95% intervals from 1,000 resamples of the 114 validation days. The same draws are used for every model,
  and the interval is for the seed-mean TSS.
- *Subsets:* everything is reported on all rows and on quiet-start rows.
- *Outputs:* `reports/validation_table.md`, `reports/xgb_cv.csv`, `reports/model_metrics.json`,
  `docs/model_figures/val_skill.png`, MLflow experiment `flare-models-v2` (42 runs). 5 new tests (48 total).

**Validation TSS, operating point A (mean over seeds [95% day-bootstrap interval]), all rows / quiet-start**

| Target | Persistence | Rule | LogReg | XGBoost | Selected |
|---|---|---|---|---|---|
| nowcast | 0.657 / 0.000 | 0.634 / 0.297 | 0.678 / 0.406 | **0.726 [0.71, 0.74]** / 0.448 | XGBoost |
| ≥C 30 min | 0.016 / 0 | 0.034 / 0.019 | **0.196 [0.14, 0.25]** / 0.193 | 0.151 / 0.155 | LogReg |
| ≥C 60 min | 0.013 / 0 | 0.031 / 0.018 | **0.194 [0.14, 0.25]** / 0.193 | 0.192 / 0.192 | LogReg |
| ≥C 120 min | 0.026 / 0 | 0.032 / 0.010 | 0.263 / 0.263 | **0.263 [0.20, 0.33]** / 0.263 | XGBoost |
| ≥M 30 min | 0.108 / 0 | 0.050 / 0.026 | **0.478 [0.34, 0.58]** / 0.475 | 0.423 / 0.407 | LogReg |
| ≥M 60 min | 0.089 / 0 | 0.139 / 0.070 | **0.454 [0.28, 0.60]** / 0.438 | 0.328 / 0.314 | LogReg |
| ≥M 120 min | 0.076 / 0 | 0.113 / 0.067 | **0.382 [0.19, 0.55]** / 0.377 | 0.342 / 0.338 | LogReg |

Climatology is 0 everywhere, by construction. Seed std is 0.000–0.011.

**Findings**
- *Nowcast beats persistence:* XGBoost 0.726 [0.71, 0.74] vs persistence 0.657 [0.63, 0.68], intervals separated.
  On quiet-start rows it still reaches 0.448: it catches flares before the detector's own trigger.
- *Forecast skill isn't just clustering:* quiet-start TSS is almost identical to all-rows TSS for every forecast
  target, while persistence is near zero. The models use the activity *level* (background, recent maxima), not
  "a flare is happening now".
- *Uncertainty is dominated by day-to-day variation, not seeds:* intervals are about ±0.05 (C) and ±0.15–0.2 (M)
  wide. For M targets the LogReg and XGBoost intervals overlap, so LogReg winning is not a statistically clear
  result.
- *CV choice barely matters for M:* the top settings differ by < 0.001 aucpr, while fold-to-fold std is about 0.04.
- *Operating point B trades POD for fewer false alarms.* ≥M 120 min LogReg: A POD 0.56 / FAR 0.88 / HSS 0.14 →
  B POD 0.40 / FAR 0.77 / HSS 0.26. For the nowcast, XGBoost B: FAR 0.30 / HSS 0.66 at POD 0.66.

**Decisions**
- Thresholds are applied unchanged to the quiet-start subset (one operating model, two report views).
- CV uses stride 30 (1 row per 5 min) for speed, while final fits use stride 6. The chosen tree counts may be
  slightly conservative for the larger final training set.
- Model selection stays "highest mean val TSS at A among Rule/LogReg/XGBoost". Baselines are reference points,
  not candidates.
- Saved models: the seed-42 LogReg and XGBoost per target, plus `models/thresholds.json` (A and B for every model).

**IMPORTANT — validation has now been used for two model comparisons** (Task 2 with the old detector-based labels,
and this rewrite with GOES-direct labels). Each comparison picks winners on validation, so validation scores are now
somewhat optimistic. **The test period (2026-06-01 … 2026-09-12) is the only fully unbiased score left.** It has
never been opened, and it must be used once, at the end, with every choice frozen.

**Checks:** 48 tests pass. `dvc repro` ran the `train` stage (about 16 min). `dvc status` is clean.

**Note on the run:** the first background training run was interrupted when the session was resumed ("Try again");
it was restarted and completed normally. No partial results were used.

## 2026-10-22 — Prompt 4, start: running jobs

No training was running. The last training run (tasks 3.3–3.5) had completed and its results were already recorded
above (commit `3722f6e`). The Python processes still alive were an MLflow UI server (started 2026-10-21 20:49),
which was left running.

## 2026-10-22 — Task 4.1: inventory of all Aditya-L1 data on D: (read-only)

**Done.** New `src/data_inventory.py` (`python -m src.data_inventory inventory`) lists every archive under
`paths.archive_root` (new param, `D:/MLOPS_CP/Data/original_zips`). For each archive it records the instrument,
dates, version, compressed and uncompressed size (from the zip listing), and whether its files already exist with
matching sizes. Truncated zips are listed by scanning local file headers, and an entry counts only if its compressed
stream is complete. Output: `reports/data_inventory.csv` (1,054 archives). 2 new tests; one caught a version-parsing
bug (`1.0.` instead of `1.0`), which was fixed.

**Search.** The whole of D: was searched (skipping `D:\dvc-cache`, `D:\projects`, the recycle bin and system
folders). The only Aditya-L1 data is in `D:\MLOPS_CP\Data` (extracted folders plus `original_zips`). The only other
archive is unrelated: `D:\self_driving_car_training_data\tusimple\tusimple.zip` (23.2 GB).

**Findings**

| Group | Archives | Extracted? | New data |
|---|---|---|---|
| SoLEXS day zips (`mlops_cp` + `inner_solexs_zips`) | 913 (455 + 458; duplicates) | all yes | none |
| SoLEXS bundles (3 ok) | 3 | yes (all inner zips present) | none |
| SoLEXS bundles (2 truncated, Sep 15) | 2 | yes: all 19 + 71 complete entries are already in `inner_solexs_zips`; 1 entry in each is cut off | none |
| HEL1OS session zips (`mlops_cp` + `inner_hel1os_zips`) | 131 (27 + 104) | 54 yes, **77 no** | **77 sessions** |
| HEL1OS bundles | 5 | inner zips all present | — |

- **New SoLEXS days:** none. All 458 SoLEXS days on disk are already in the pipeline.
- **New HEL1OS sessions:** 77, dated 2025-01 (1), 2025-04 (23), 2025-06 (2), 2025-08 (2), 2025-11 (10),
  2026-04 (18), 2026-09 (21). Versions: V111 ×48, V112 ×24, V211 ×4, V311 ×1.
- **Overlap with usable SoLEXS days:**
  - tune: 22 sessions on 11 usable days
  - val: 13 sessions on 6 usable days
  - test: 17 sessions on 9 days. These are counted only, never analysed.
  - 25 more sessions fall on non-usable SoLEXS days or outside the periods.

**Disk check (Task 2 blocked).** The 77 new sessions take **28.6 GB uncompressed** (4.2 GB compressed). D: has
27 GB free, so full extraction would leave about −1.6 GB, far below the 15 GB floor. By file type:
- event lists (`events/evt.fits`): 19.0 GB
- spectra: 5.7 GB
- light curves: 3.6 GB
- aux (GTI, housekeeping): 0.25 GB

The pipeline only reads light curves (and could use aux). Even full extraction of just the 35 tune+val overlap
sessions (12.4 GB) would leave 14.6 GB, also below the floor. **Stopped before extraction, as instructed; nothing
was extracted or deleted.** Options are reported to the user.

**My earlier mistake, found during this inventory.** On 2026-09-17, while consolidating data onto D:, I deleted
`D:\hel1os_extracted\2025` and `...\2026` assuming they were empty leftovers, without checking their contents. They
held the extracted 2025/2026 HEL1OS sessions. No data was lost, because the original zips were kept, but it led to
the wrong conclusion "HEL1OS and SoLEXS do not overlap", which had been written into `CLAUDE.md`. That statement is
now corrected.

## 2026-10-22 — Task 4.2: selective extraction of the 77 HEL1OS sessions

**Done (user chose option 1).** Only light curves and aux files were extracted (new param
`paths.hel1os_extract_include: ["/cdte/lightcurve_", "/czt/lightcurve_", "/aux/"]`), into `data_root_hel1os`, using
the same `YYYY/MM/DD/HLS_.../{cdte,czt,aux}` structure as the existing sessions. Event lists and spectra stay inside
the zips. All zips are kept; nothing was moved or deleted. Files are opened with mode `"x"`, so nothing can be
overwritten; a size clash with an existing file would be kept and reported, but none occurred.

**Verification:** 77 archives, 847 / 847 expected files written (11 per session: 4 light curves, 4 GTI, `hk.fits`,
2 detector-map text files), 0 size mismatches, 693 / 693 FITS files open with astropy. HEL1OS folder: 6.4 → 9.9 GB,
104 session folders. D: free: 27 → 23 GB. Inventory state for the 77 sessions: `selected` (all chosen files present).
Logged in `reports/data_inventory.csv` (columns `files_expected`, `files_written`, `count_ok`, `size_mismatch`,
`fits_checked`, `fits_failed`).

**Fix:** `verify_fits` counted the text files as "checked". It now counts only FITS files.

**New rule in CLAUDE.md (rule 8):** never delete or move a data folder or archive without asking; check folder
contents before any cleanup.

**Decision:** the extraction lesson was added to lesson 09 (data inventory, part 2) rather than as a separate
lesson; it's the same topic.
