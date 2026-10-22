# Challenges: what went wrong, what we learned, what is still open

Written for the project presentation, in plain language. Every number has its source. Dates are from `docs/PROGRESS.md` and `git log`.

---

## Part 1 — Solved challenges

### 1. Python 3.14 had no ready-made packages, and one package had none at all (antlr)
- **Problem:**
  - The first virtual environment used the wrong Python (the MSYS2/Git-Bash one). `pip` tried to *build* numpy and
    astropy from source code and failed with SSL errors.
  - The next attempt, on Python 3.14, could not install `dvc` from pre-built packages ("wheels").
- **Impact:** we couldn't install the project tools. Nothing else could start.
- **How it was found:** `pip install` errors; a "wheels only" dry run showed `dvc` failing on 3.14.
- **Fix:**
  - Rebuilt the environment on **Python 3.12**.
  - One dependency, `antlr4-python3-runtime==4.9.3` (needed by DVC through hydra-core), has no wheel at all. It is
    pure Python, so we built its wheel locally once and installed everything else wheels-only. This is recorded in `CLAUDE.md`.
- **Lesson:** the newest Python is not always the best choice for a project; pick the version your tools support.
  Check installability *before* building on it.

### 2. OneDrive syncing the project
- **Problem:** the project started inside a OneDrive-synced Desktop folder. OneDrive tried to upload every file the
  moment it was written: gigabytes of extracted data and thousands of small files.
- **Impact:** extraction ran very slowly, the cloud quota was at risk, and files were locked ("device or resource busy").
- **How it was found:** extraction was much slower than expected, and `mv` failed with "resource busy".
- **Fix:**
  - Paused OneDrive during extraction.
  - Moved the project to `D:\projects\solar-flare-project`, keeping its git history.
  - Raw data lives on `D:\MLOPS_CP\Data`, outside any synced folder.
- **Lesson:** keep code and large data out of cloud-synced folders; use git and DVC for versioning instead.

### 3. Windows line endings (CRLF) broke DVC's change detection
- **Problem:**
  - DVC decides "has this changed?" from a fingerprint of the file's bytes.
  - Git on Windows rewrote files with Windows line endings (`\r\n`), and Python and pandas on Windows *write* `\r\n`
    by default.
  - The bytes changed while the content didn't, so DVC thought code had changed and re-ran stages.
- **Impact:** wasted 15–30 minute pipeline runs, and confusing "changed" messages.
- **How it was found:** after `git checkout` of an unchanged file, `dvc status` reported a stage as changed.
- **Fix:**
  - A `.gitattributes` file forcing Unix line endings.
  - All 21 affected files normalised.
  - Every report writer now writes `\n` explicitly.
  - A test fails if any tracked text file has `\r\n` (`tests/test_pipeline.py`).
  - The test caught the problem again on 2026-10-22, in the notebook, and it was fixed.
- **Lesson:** reproducibility tools hash *bytes*, not *meaning*; make file formats deterministic.

### 4. MLflow 3 refused the folder-based store
- **Problem:** MLflow 3.16 rejects the old `./mlruns` folder store with an error.
- **Impact:** the first full 108-trial detector search finished, but crashed while logging, and its results were lost.
- **How it was found:** a traceback at the end of the tuning run.
- **Fix:**
  - Switched tracking to a SQLite database (`mlflow.db`).
  - The tuner now saves its CSV/JSON results **before** logging, so a logging failure can never lose a finished search.
- **Lesson:** write results to disk first, then report them; never let reporting be the only copy.

### 5. The first flare detector produced overlong events
- **Problem:** the first detector ended a flare only when it decayed to 10% of the peak, against a background that kept moving.
- **Impact** (tuning period, legacy detector; *source: `reports/detection_metrics.json`*):
  - 218 events longer than 2 hours, some lasting 15 hours
  - onset error vs NOAA: median 5.8 min, p90 76 min
  - separate flares merged into one
- **How it was found:** before/after figures of example flares, and the duration histogram.
- **Fix:**
  - Rebuilt the detector with NOAA's GOES rules: onset = first minute of a sustained rise; end = halfway back to
    the background, which is frozen during the flare.
  - Added dip splitting and a 3-hour cap.
  - Tuned on the tuning period only (300 trials, MLflow).
  - Result: 5 events over 2 h, onset median 1 min / p90 10 min *(same source)*.
- **Lesson:** use the domain's standard definitions, and look at examples, not only averages.

### 6. Label noise from detector misses
- **Problem:** forecast labels were first built from *our* detections. The tuned detector catches only about 86% of
  C-class flares (and 18% of B), so every missed flare became a wrong "no flare coming" label.
- **Impact:** the model was taught that some real flares didn't exist. C-class forecast scores were held back.
- **How it was found:** comparing the detector with the GOES list (recall by class), and EDA examples of missed flares.
- **Fix:**
  - Forecast labels now come **directly from the NOAA GOES list**, using our more precise onset where we matched the flare.
  - ≥C-within-30-min positives in tune rose from 235,984 to 281,541 rows *(source: `reports/label_comparison.json`)*.
  - C-class validation TSS rose from 0.18 to 0.20 *(source: `docs/PROGRESS.md`)*.
- **Lesson:** the quality of the labels limits the model more than the choice of algorithm.

### 7. Deleted HEL1OS folders and a wrong conclusion (my mistake)
- **Problem:** on 2026-09-17, while tidying data, I deleted the extracted 2025/2026 HEL1OS folders, *assuming* they
  were empty, without checking.
- **Impact:** for a month the project wrongly believed "HEL1OS and SoLEXS never overlap". The hard X-ray part of the
  project was set aside.
- **How it was found:** a read-only inventory of every archive on D: (2026-10-22) found 77 HEL1OS sessions in the
  kept zips that were not extracted, many overlapping SoLEXS days *(source: `reports/data_inventory.csv`)*.
- **Fix:**
  - No data was lost: the original zips had been kept.
  - The light curves and aux files were re-extracted: 847 files, all verified, no overwrites.
  - `CLAUDE.md` was corrected.
  - A permanent rule was added: **never delete or move data without asking, and check folder contents first**.
- **Lesson:** never delete what you haven't looked inside. Keeping the original archives turned a disaster into a
  delay. An inventory step catches wrong assumptions.

### 8. Disk space
- **Problem:**
  - Drive C: hit 100% full (0 bytes free) during the first HEL1OS extraction.
  - Later, the 77 new HEL1OS sessions needed 28.6 GB unpacked while D: had 27 GB free.
- **Impact:** extraction failed partway through, and full extraction was impossible.
- **How it was found:** "No space left on device" errors; the inventory's size check before extracting.
- **Fix:**
  - Moved extraction to D:.
  - Extracted only what the pipeline reads: light curves + aux, 3.9 GB of 28.6 GB. Event lists (19 GB) and
    spectra (5.7 GB) stay in the zips.
  - Free space now: C: 21 GB, D: 22 GB *(source: `df -h`, 2026-10-22)*.
- **Lesson:** check uncompressed sizes against free space *before* unpacking, and know which files your code actually uses.

### 9. Too few flares for early stopping
- **Problem:** XGBoost's early stopping was judged on Dec 2025–Jan 2026, which held only 27 M-or-stronger flares.
- **Impact:** the M-class models stopped after 0–24 trees, which is almost no learning, and calibration scores were noisy.
- **How it was found:** the logged `best_iteration` values *(source: `docs/PROGRESS.md`, Task 2)*.
- **Fix:**
  - **Rolling-origin cross-validation:** train on earlier months, score on Aug, Sep, Oct and Nov 2025.
  - Settings chosen by average score over 4 months.
  - Dec–Jan used only to set alert thresholds.
- **Lesson:** a validation set must contain enough of the rare event you care about; average over several time blocks.

### 10. The GitHub connector token
- **Problem:** the GitHub connection used by the assistant fails with "Authorization header is badly formatted".
- **Impact:** no GitHub automation (pull requests, CI setup) from the assistant. The project works locally with git;
  CI is not done.
- **How it was found:** connection errors at session start.
- **Fix:** only the user can fix this, by re-entering the token through `/mcp`. **Not yet fixed.**
- **Lesson:** some fixes need a person with credentials; record them as blockers instead of working around them.

### Other problems fixed along the way (short)
- **pandas time units:** times were stored in *seconds*, so integer comparisons silently matched nothing. Fixed by
  converting to nanoseconds; a test checks it.
- **HEL1OS parser bug:** bands in newer files start at different sub-second offsets, and the parser dropped about
  99% of rows. Fixed by rounding each band to whole seconds before joining; a regression test was added.
- **DVC deleted the EDA figures:** a stage owned the whole `docs/figures/` folder. It now lists its own files.
- **Two truncated download bundles:** read safely by scanning zip headers; all complete days were already extracted.
- **No NOAA report for 2025-12-30 and 2025-12-31:** those days are excluded from evaluation, and their labels are
  marked "don't trust".

---

## Part 2 — Open problems

### 1. The Neupert lag of 0 s
- **What we see:** hard X-rays and the soft X-ray rise rate peak together. Median lag 0 s, middle half −10 to +20 s,
  over 71 flares *(source: `reports/eda_numbers.json`)*.
- **Why it's still open:**
  - 0 s is what the Neupert effect predicts, so it confirms that the instruments' clocks agree.
  - But it was measured on **10-second** bins, so any real lag shorter than about 10 s is invisible.
  - Only flares with a clear correlation (≥ 0.3) were kept, which may favour clean, simple flares.
- **Effect on results:** none on the models (no feature depends on the lag value). It limits what we can claim
  physically.
- **Planned fix:**
  - Re-measure at 1-second cadence.
  - Report how many flares failed the 0.3 correlation cut.
  - Check the lag against flare class.

### 2. High false-alarm rates for M-class forecasts
- **What we see:** at the main threshold (max TSS), 88–97% of M-class alarms are false. FAR 0.97 / 0.92 / 0.88 for
  30 / 60 / 120 min *(source: `reports/model_metrics.json`)*.
- **Effect on results:** good TSS (0.39–0.47), but an operator would stop trusting alerts this noisy. Operating
  point B (max HSS) lowers FAR somewhat, at the cost of missing more flares.
- **Planned fix:**
  - Choose thresholds by a real cost of misses vs false alarms, or cap FAR.
  - Calibrate the probabilities.
  - Report probabilities instead of yes/no.

### 3. Weak C-class skill
- **What we see:** the best ≥C models reach TSS 0.21–0.27, catching about 44–51% of flare windows with FAR 0.44–0.81
  *(source: `reports/model_metrics.json`)*.
- **Effect on results:**
  - C forecasts are only modestly better than chance.
  - EDA shows no single feature separates "C flare coming" from "none" *(source: `docs/EDA_SUMMARY.md`, finding 7)*.
- **Planned fix:**
  - Add context the light curve alone lacks: longer history, active-region information, the GOES flux itself as an input.
  - Try sequence models.
  - Remove near-duplicate features.

### 4. HEL1OS covers only a small share of the rows
- **What we see:** hard X-ray data is available on **4.0% of tuning rows** and **6.3% of validation rows**
  (215.6 h and 143.5 h) *(source: dataset files, `reports/eda_numbers.json`)*.
- **Effect on results:**
  - Adding HEL1OS features doesn't measurably change the main models.
  - The soft-vs-hard ablation has too few flares for C-in-120-min and all M targets (12–17 positive episodes).
  - Only one hint: a better quiet-start nowcast (TSS 0.45 vs 0.37) *(source: `reports/model_metrics.json`, ablation)*.
- **Planned fix:** obtain more HEL1OS sessions (especially Dec–Jan and the test months), re-run the ablation, and
  consider a dedicated model for HEL1OS-available rows.

### 5. Data gaps on the 17th of every month
- **What we see:** the 17th is only about 11% observed, against about 80% on other days. 23.7% of all minutes are
  missing *(source: `reports/eda_numbers.json`)*.
- **Effect on results:**
  - Those days are dropped or their labels are marked "don't trust", so fewer training examples.
  - Flares on those days are never seen.
  - It can create fake "time-of-month" patterns.
- **Planned fix:** ask the data provider why (likely a regular operation), keep treating it as missing (never
  filling it), and check that no model learns the calendar.

### 6. The model registry is empty
- **What we see:** MLflow has 600 runs but 0 registered models *(source: `mlflow.db`)*.
- **Effect on results:** none on the scores. But there's no official "this is the model in use" record, which a real
  service needs.
- **Planned fix:** register the selected model per target (for example `flare-nowcast` v1), give it an alias such as
  `candidate`, and promote it only after the final test.

### 7. The deployment half has not started
- **What we see:** serving (FastAPI), packaging (Docker), CI (GitHub Actions) and monitoring (Evidently/Prometheus/
  Grafana) are **not done**. Data validation (pandera) and orchestration (Prefect) are installed but unused.
- **Effect on results:** the models can't yet be used by anyone else, and nothing would warn us if the live data drifted.
  The EDA already shows drift: background 12.8 → 5.2 counts/s.
- **Planned fix**, in order:
  1. the one final test-period score
  2. pandera schemas on the data tables
  3. a Prefect flow around `dvc repro`
  4. a FastAPI service with the registered model
  5. a Dockerfile (Docker Desktop is installed)
  6. GitHub Actions running the tests, once the token is fixed
  7. Evidently drift reports
