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
