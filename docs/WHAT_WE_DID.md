# What we did — explained simply

This file explains the whole project so far in plain words. Every number has its source next to it in brackets,
for example *(source: `reports/model_metrics.json`)*. If something is not done, it says **not done**.

Written on 2026-10-22, at commit `40d0d40` *(source: `git log`)*. Nothing was changed to write it: no code, data,
params, `dvc.yaml`, MLflow runs or git history.

> **Two things to know before you read**
> - The working copy has one uncommitted code change, in `src/eda.py`: a refactor started during the unfinished
>   slide-figure task. It was left as it is. *(source: `git status`)*
> - One test currently fails (56 of 57 pass). The working copy of `notebooks/01_eda.ipynb` has Windows (CRLF) line
>   endings, although its content is the same as in git. The fix is one command: `git checkout -- notebooks/01_eda.ipynb`
>   (it rewrites the file with Unix line endings). It was not run, because this task is read-only. *(source: `pytest -q`, see "Live outputs")*

---

## 1. Status vs the plan

**Words used here**
- A **stage** is one step of the project.
- **Done** means it works and is tested. **Partial** means part of it works. **Not started** means no code exists yet.

### 1a. The planned stages

| Stage | Status | Files that implement it | What it does (one line) |
|---|---|---|---|
| 1. Ingest | **Done** | `src/solexs.py`, `src/hel1os.py`, `src/goes.py`, `src/data_inventory.py`, `src/pipeline.py` (stages `fetch_goes`, `solexs_clean`, `hel1os_index`) | Reads raw satellite files and the NOAA flare list, removes bad seconds, and saves clean tables. |
| 2. Detect | **Done** | `src/detection/detector.py`, `matching.py`, `tune.py`, `legacy.py`, `plots.py` (stages `detect_events`, `legacy_events`, `match_goes`, `evaluate_detector`) | Finds flares in the SoLEXS light curve and checks each one against NOAA's GOES list. |
| 3. Features | **Done** | `src/features.py`, `src/dataset.py` (stage `build_dataset`) | Turns the light curves into 44 numbers every 10 seconds, using only the past. |
| 4. Windows / labels | **Done** | `src/labels.py`, `src/activity.py`, `src/dataset.py` (stage `build_dataset`) | Writes the answers the model must learn ("flare now?", "flare within 30/60/120 min?"), with "trust this answer?" flags. |
| 5. Train / track | **Partial** | `src/models/train.py`, `metrics.py`, `ablation.py`, `report.py`, `plots.py` (stage `train`); MLflow in `mlflow.db` | Trains and compares 5 models per target and logs every run. **Not done:** the final score on the test period, and the MLflow model registry is empty. |
| 6. Serve | **Not started** | — | (Would be: an API that returns a flare forecast.) **Not done.** |
| 7. Deploy | **Not started** | — | (Would be: package the API in Docker and run it.) **Not done.** |
| 8. Monitor | **Not started** | — | (Would be: watch live data and model quality over time.) **Not done.** The EDA only *shows* that the data drift. |
| EDA | **Done** | `notebooks/01_eda.ipynb`, `notebooks/build_eda_notebook.py`, `src/eda.py`, `docs/EDA_SUMMARY.md` | Looks at the data from 9 angles before modelling, using tuning and validation data only. |

### 1b. The planned tools

**Words used here**
- **used** = our code calls it.
- **installed but unused** = it's on the computer, but no project code uses it.
- **not installed** = it isn't there.

| Tool | Status | Where it is used |
|---|---|---|
| Git | used | Whole project; 19 commits *(source: `git log`)* |
| DVC | used | `dvc.yaml` (9 stages), `dvc.lock`, cache on `D:/dvc-cache` *(source: `dvc.yaml`, `.dvc/config`)* |
| MLflow | used | `src/detection/tune.py`, `src/models/train.py`; data in `mlflow.db` (600 runs) *(source: `mlflow.db`)* |
| params.yaml | used | Every setting; read through `src/config.py` |
| pytest | used | `tests/` (57 tests) *(source: `pytest --collect-only`)* |
| pandera | installed but unused | In `requirements.txt` (0.34.0); no code imports it |
| Prefect | installed but unused | In `requirements.txt` (3.8.7); no code imports it |
| XGBoost | used | `src/models/train.py`, `src/models/ablation.py` |
| scikit-learn | used | Logistic regression, imputer and scaler, AUC/AP metrics (`src/models/train.py`, `src/models/metrics.py`) |
| PyTorch / tsai | not installed | — |
| Optuna | not installed | — (a grid search was used instead; see below) |
| FastAPI | installed but unused | Comes with MLflow (0.142.2 in `requirements.txt`); no project code |
| Streamlit | not installed | — |
| Docker | installed but unused | Docker Desktop is on this computer (`docker` 29.7.2), but the engine was not running and there is no Dockerfile |
| Kubernetes | installed but unused | `kubectl` comes with Docker Desktop; nothing uses it |
| GitHub Actions | not used | No `.github/` folder; the GitHub connection still fails |
| Prometheus | installed but unused | Only the Python client library (`prometheus_client` 0.26.0), as a dependency; no server, no code |
| Grafana | not installed | — |
| Evidently | not installed | — |

### 1c. Overall progress

**About 60% done.** Stages 1–4 and EDA are done and stage 5 is mostly done, but the "production" half (serve,
deploy, monitor) and the final test-period evaluation have not been started.

### 1d. Where reality differs from the plan, and why

| Plan said | What we actually did | Why |
|---|---|---|
| Optuna for tuning | A **grid search**: try every combination from a list. 300 combinations for the detector *(source: `reports/tuning_results.csv`)*, 24 settings × 4 folds for XGBoost *(source: `params.yaml` `models.cv`)* | The search spaces are small and discrete, a grid checks all of them, and the result is easy to reproduce and explain. Optuna is not installed. |
| PyTorch / tsai (deep learning on time series) | Logistic regression + XGBoost on 44 hand-made features | Simpler models first, to set honest baselines. Deep learning is **not done**. |
| Labels from our own detector | Forecast labels taken **directly from the NOAA GOES list** | The detector misses about 14% of C-class flares; those misses would become wrong "no flare" labels *(source: `reports/label_comparison.json`)*. |
| DVC tracks the raw data | Raw data stays on `D:\MLOPS_CP\Data` and is read through paths in `params.yaml` (not `dvc add`-ed) | It's 9.5+ GB and never changes; copying it into the cache would double the disk use. |
| MLflow with a folder (`mlruns/`) | MLflow with a **SQLite database** (`mlflow.db`) | MLflow 3 refuses the old folder store. |
| Use both instruments everywhere | HEL1OS is **optional**; only its light curves and aux files were extracted (847 files) | It covers only about 6% of tune+val rows, and full extraction (28.6 GB) did not fit on D: *(source: `docs/PROGRESS.md`)*. |
| Early stopping for XGBoost | **Rolling-origin cross-validation** (score each month after training on earlier months) | Early stopping on Dec–Jan used too few flares and stopped after 0–85 trees. |
| — | Test period **never opened** | It's kept for one final, honest score. |

---

## 2. What each stage actually does

### Ingest (getting the data in)
- **Input:** raw SoLEXS files in `D:/MLOPS_CP/Data/SoLEXS`, HEL1OS files in `D:/MLOPS_CP/Data/HELIOS`, and NOAA daily
  flare reports from the internet *(source: `params.yaml` `paths`)*.
- **Output:**
  - `data/processed/solexs_clean/` (one table per day, one row per good second)
  - `data/processed/solexs_minute.parquet` (1-minute averages)
  - `data/processed/solexs_qc.csv` (quality report per day)
  - `data/external/goes_events/` (NOAA reports)
  - `data/processed/hel1os/sessions.parquet` and `coverage.csv`
- **Main functions:** `solexs.list_days`, `solexs.clean_day` (keeps a second only if it has a number *and* is inside a
  "good time interval"), `goes.download_range`, `hel1os.newest_per_session`, `hel1os.read_session`.
- **Key settings:**
  - `solexs.detector: SDD2`, the only detector with light curves
  - `solexs.min_valid_fraction: 0.5`, the minimum for a day to be usable
  - `periods`: tune 2025-04-09…2026-01-31, val 2026-02-01…05-31, test 2026-06-01…09-12
- **Key number:** **424 usable SoLEXS days** of 452 day folders in the periods *(source: `data/processed/solexs_qc.csv`)*;
  98 HEL1OS sessions after keeping the newest version *(source: `data/processed/hel1os/coverage.csv`)*.

### Detect (finding flares)
- **Input:** `solexs_minute.parquet` and the NOAA reports.
- **Output:**
  - `events_raw.parquet` (our detections)
  - `events.parquet` (detections plus "matched to GOES?")
  - `events_pairs.parquet`, `goes_matched.parquet`
  - `reports/detection_metrics.json` and before/after figures in `docs/figures/`
- **Main functions:** `detector.detect_series` (finds start, peak and end the way NOAA does) and `matching.match_goes`
  (pairs each detection with overlapping GOES flares). `tune.run` searched the settings; it's run by hand, not a DVC stage.
- **Key settings** *(source: `params.yaml` `flare_detection`, `goes_match`)*:
  - `min_excess_frac: 1.0` and `min_excess_abs: 12.0`: the signal must at least double and rise by 12 counts/s
  - `rise_steps: 3`: 3 rising minutes in a row
  - `dip_frac: 0.3`: split two flares if the dip between them is 30% deep
  - `max_duration_s: 10800`: 3-hour cap
  - `tolerance_s: 300`: 5-minute matching window
- **Key number:** flare start time is off by a **median of 1 minute** compared with NOAA (validation p90 = 9 min)
  *(source: `reports/detection_metrics.json`, `new.val.onset_error_min`)*.

### Features (the numbers the model sees)
- **Input:** `solexs_clean/`, `hel1os/sessions.parquet`.
- **Output:** feature columns inside `data/processed/dataset/{tune,val,test}.parquet`.
- **Main functions:** `features.bin_counts` (10-second bins that only contain the past), `features.solexs_features`
  (averages, maxima, slopes and ratios over the last 1, 5, 15 and 60 minutes), `features.hel1os_features` (hard X-ray
  rates, hardness ratios, lags, Neupert correlation; missing when HEL1OS is off).
- **Key settings:** `features.cadence_s: 10`, `windows_min: [1, 5, 15, 60]`, `min_valid_frac_5m: 0.8`.
- **Key number:** **44 features** (27 SoLEXS + 17 HEL1OS) *(source: `reports/dataset_summary.json`)*.

### Windows / labels (the answers)
- **Input:** `events.parquet`, `events_pairs.parquet`, `goes_matched.parquet`, `solexs_minute.parquet`.
- **Output:** label columns (`y_now`, `y_c_30m` … `y_m_120m`), "trust" flags (`ok_*`) and `flare_in_progress_at_t`,
  in the same dataset files. `reports/label_comparison.json` compares the old and new labels.
- **Main functions:** `labels.make_labels`, `labels.goes_onsets` (flare start times from GOES), `labels.future_ok`
  (is the future window fully observed?), `activity.flare_in_progress` (did the detector, *at that moment*, think a
  flare was happening?).
- **Key settings:** `labels.horizons_min: [30, 60, 120]`, `min_class_c: C1.0`, `min_class_m: M1.0`.
- **Key number:** tuning rows **1,936,953**, validation **816,920**, test 792,482 (count only)
  *(source: `reports/dataset_summary.json`)*.

### Train / track (learning and recording)
- **Input:** `data/processed/dataset/tune.parquet` and `val.parquet` only. The code refuses to open `test.parquet`.
- **Output:**
  - `models/` (saved models and thresholds)
  - `reports/model_metrics.json`, `reports/validation_table.md`, `reports/xgb_cv.csv`
  - `docs/model_figures/val_skill.png`
  - MLflow runs in `mlflow.db`
- **Main functions:**
  - `train.xgb_cv`: rolling-origin cross-validation to pick XGBoost settings
  - `train.train_target`: fits 5 models
  - `train.aggregate`: averages 3 seeds and computes the 95% interval by resampling days
  - `ablation.run_ablation`: soft vs hard vs combined features
- **Key settings** *(source: `params.yaml` `models`)*:
  - `inner_split: 2025-12-01`: fit before it; Dec–Jan used only to choose alert thresholds
  - `seeds: [42, 43, 44]`
  - `bootstrap.n: 1000`
- **Key number:** nowcast **TSS 0.727** [0.71, 0.74] with XGBoost *(source: `reports/model_metrics.json`)*.

### EDA (looking before modelling)
- **Input:** tuning + validation data only (the first notebook cell checks this).
- **Output:** `notebooks/01_eda.ipynb` (executed), 15 figures in `docs/figures/eda/`, `reports/eda_numbers.json`,
  `docs/EDA_SUMMARY.md`.
- **Key number:** the **Neupert lag** (delay between hard X-rays and the rise of soft X-rays) is a median of **0 s**
  over 71 flares *(source: `reports/eda_numbers.json`, `hel1os.neupert`)*.

---

## 3. DVC, explained with our real setup

### What DVC is
**DVC (Data Version Control)** does for data and pipelines what Git does for code. Think of a **recipe book with a
smart kitchen**: the recipe (`dvc.yaml`) lists every step, its ingredients (inputs) and dishes (outputs). The kitchen
remembers a fingerprint of everything it cooked (`dvc.lock`). When you change one ingredient, `dvc repro` re-cooks
only the dishes that depend on it, and old dishes are kept in a store room (the **cache**), so you can go back to
any earlier version.

### The pipeline map (`dvc dag`)

`dvc dag` draws the stages as boxes and the dependencies as lines *(full output in "Live outputs" below)*. A line
from box A down to box B means "B uses an output of A".

| Arrow (A → B) | What flows along it |
|---|---|
| `solexs_clean` → `detect_events` | 1-minute SoLEXS averages (`solexs_minute.parquet`) |
| `solexs_clean` → `legacy_events` | cleaned 1-second days (`solexs_clean/`) for the old detector |
| `solexs_clean` → `evaluate_detector` | 1-minute averages (to know which minutes were observed) |
| `solexs_clean` → `build_dataset` | cleaned seconds (features) and minutes (label trust flags) |
| `fetch_goes` → `match_goes` | NOAA flare reports |
| `fetch_goes` → `build_dataset` | NOAA reports (which days have no report) |
| `detect_events` → `match_goes` | our detections |
| `legacy_events` → `match_goes` | the old detector's detections |
| `match_goes` → `evaluate_detector` | detections marked "matched to GOES" + GOES list |
| `match_goes` → `build_dataset` | the catalogue used for labels and the activity flag |
| `hel1os_index` → `build_dataset` | HEL1OS hard X-ray table (optional in code) |
| `build_dataset` → `train` | the finished dataset |

### Every stage: dependencies, params, outputs *(source: `dvc.yaml`)*

| Stage | Depends on (code + data) | Params | Outputs |
|---|---|---|---|
| `fetch_goes` | `src/goes.py`, `src/pipeline.py` | `periods` | `data/external/goes_events` |
| `solexs_clean` | `src/solexs.py`, `src/detection/detector.py`, `src/pipeline.py` | `paths.data_root_solexs`, `periods`, `solexs`, `flare_detection.min_valid_s_per_min` | `data/processed/solexs_clean`, `solexs_minute.parquet`, `solexs_qc.csv` |
| `detect_events` | `detector.py`, `pipeline.py`, `solexs_minute.parquet` | `flare_detection`, `periods` | `events_raw.parquet` |
| `legacy_events` | `src/detection/legacy.py`, `pipeline.py`, `solexs_clean` | `flare_detection_legacy`, `periods` | `legacy_events_raw.parquet` |
| `match_goes` | `matching.py`, `goes.py`, `pipeline.py`, `events_raw.parquet`, `legacy_events_raw.parquet`, `goes_events` | `goes_match`, `periods` | `events.parquet`, `events_pairs.parquet`, `legacy_events.parquet`, `legacy_events_pairs.parquet`, `goes_matched.parquet` |
| `evaluate_detector` | `matching.py`, `src/detection/plots.py`, `pipeline.py`, minute file, events + pairs, legacy events + pairs, `goes_matched.parquet` | `evaluation`, `periods` | 9 files in `docs/figures/` (listed one by one); metric `reports/detection_metrics.json` |
| `build_dataset` | `features.py`, `labels.py`, `dataset.py`, `activity.py`, `pipeline.py`, `solexs_clean`, minute file, `events.parquet`, `events_pairs.parquet`, `goes_matched.parquet`, `goes_events`, `data/processed/hel1os` | `features`, `labels`, `periods`, `flare_detection.end_confirm_min`, `flare_detection.gap_end_min` | `data/processed/dataset`; metrics `dataset_summary.json`, `label_comparison.json` |
| `train` | `src/models/train.py`, `metrics.py`, `plots.py`, `report.py`, `ablation.py`, `src/dataset.py`, `pipeline.py`, `data/processed/dataset` | `models`, `periods` | `models/`, `docs/model_figures`, `reports/validation_table.md`, `reports/xgb_cv.csv`; metric `reports/model_metrics.json` |
| `hel1os_index` | `src/hel1os.py`, `pipeline.py` | `paths.data_root_hel1os` | `data/processed/hel1os` |

**9 stages** in `dvc.yaml`. `dvc.lock` contains **11** entries: two are left over from the first pipeline version
(`solexs_flares`, `goes_match`). They are harmless, but they're stale. *(source: `dvc.yaml`, `dvc.lock`)*

### Where the raw data lives
- **Raw data** stays in `D:\MLOPS_CP\Data` (SoLEXS, HELIOS, original zips). It is **not tracked by DVC** (no `dvc add`).
- Stages **read it as an external path** from `params.yaml` (`paths.data_root_solexs`, `paths.data_root_hel1os`,
  `paths.archive_root`).
- **Why:** it's large and never changes, and project rules forbid modifying it. Copying it into the DVC cache would
  double the disk use.
- **Consequence:** if new raw files appear, DVC won't notice by itself; you re-run the affected stage (`dvc repro -f <stage>`).

### Cache: where and how
- **Location:** `D:/dvc-cache` *(source: `.dvc/config`)*. It currently holds 255 objects, 1.2 GB *(source: `du` on `D:\dvc-cache`)*.
- **Type:** `hardlink,symlink` *(source: `.dvc/config`)*. A **hardlink** is a second name for the same file on disk,
  like two doors into one room. `data/processed/events.parquet` and its cache copy are one file with 2 names
  *(source: link count = 2)*.
- **What that means for disk use:** the current outputs (`data/processed`, 566 MB) cost no extra space on top of the
  cache. The cache is bigger (1.2 GB) only because it also keeps **old versions**.
- **The catch:** outputs are read-only. Our code deletes a file before writing a new one (`_fresh()`), so the cached
  copy is never damaged.

### Data versions (`git log --oneline -- dvc.lock`)
Every commit that changed `dvc.lock` is one **data version**, because `dvc.lock` stores the fingerprints of all
outputs. There are **10 versions** *(source: `git log -- dvc.lock`; changes found by comparing `dvc.lock` between
neighbouring commits)*:

| # | Commit | Date | Message (short) | What changed in the data |
|---|---|---|---|---|
| 1 | `3e0781a` | 2026-10-06 06:45 | Add stage-2 data pipeline | First pipeline: 5 stages (`fetch_goes`, `solexs_clean`, `solexs_flares`, `goes_match`, `hel1os_index`) |
| 2 | `48b5577` | 2026-10-06 06:49 | Run data pipeline on all 458 SoLEXS days | Date range widened: GOES, clean data, flares and matches all rebuilt |
| 3 | `07c7845` | 2026-10-07 12:05 | Tighten flare detector … | 5 new stages (`detect_events`, `legacy_events`, `match_goes`, `evaluate_detector`, `build_dataset`); periods changed, so clean data and GOES rebuilt |
| 4 | `2d15602` | 2026-10-21 18:41 | … `.gitattributes` … | Line-ending fix: fingerprints re-recorded; dataset and evaluation outputs updated (same content) |
| 5 | `8a6564a` | 2026-10-21 19:27 | Add model training stage | New `train` stage; clean-data and HEL1OS outputs re-recorded (text files rewritten with Unix line endings) |
| 6 | `ad923ad` | 2026-10-21 19:51 | Forecast labels from the GOES list | New labels: dataset and models changed |
| 7 | `2d4d4f5` | 2026-10-21 20:05 | Add causal `flare_in_progress_at_t` | Dataset gained the activity column; models re-run |
| 8 | `3722f6e` | 2026-10-21 20:27 | Rebuild training … | Training rewritten (baselines, CV, seeds, intervals): models and reports changed |
| 9 | `4c5968d` | 2026-10-22 01:12 | Fix HEL1OS band alignment bug … | 98 HEL1OS sessions indexed; dataset rebuilt with 44 features |
| 10 | `998609a` | 2026-10-22 01:48 | Retrain with HEL1OS features + ablation … | Models retrained; detector figures listed file by file |

### How to go back to an old version
Run these in the project folder with the venv active. First commit or stash any local changes; right now `src/eda.py`
has one, so `git stash` it first.

```
git stash                      # park the uncommitted change in src/eda.py
git switch --detach 3722f6e    # code + dvc.lock as they were in version 8
dvc checkout                   # put the matching data files back from the cache
dvc status                     # should print: Data and pipelines are up to date.
```
To return to today:
```
git switch master
dvc checkout
git stash pop                  # bring back the src/eda.py change
```
To check that everything matches at any time: `dvc status`. Today it prints **"Data and pipelines are up to date."**
*(see "Live outputs")*.

---

## 4. MLflow, explained with our real runs

### What MLflow is
**MLflow** is a **lab notebook for experiments**. Each time you try something (a setting, a model), it writes down
what you tried (**parameters**), how well it did (**metrics**), and any files produced (**artifacts**, such as a saved
model). Later you can sort, compare and reopen any attempt. We store everything in one SQLite database file,
**`mlflow.db`**, in the project folder *(source: `params.yaml` `paths.mlflow_tracking_uri`)*.

### Experiments and runs *(source: `mlflow.db`)*

| Experiment | Runs | What one run is | First run | Last run |
|---|---|---|---|---|
| `detector-tuning` | 410 | One detector setting tried on the tuning period (2 "parent" runs = 2 grid searches, 108 + 300 "child" trials) | 2026-10-07 11:42 | 2026-10-07 11:48 |
| `flare-models` | 105 | One model (rule / LogReg / XGBoost) for one target, first training version; 5 training runs × 21 | 2026-10-21 18:47 | 2026-10-21 19:57 |
| `flare-models-v2` | 85 | Parent = one target; children = its 5 models (climatology, persistence, rule, LogReg, XGBoost). 2 training runs × (7 parents + 35 children) + 1 ablation run | 2026-10-21 20:11 | 2026-10-22 01:44 |
| `Default` | 0 | (unused) | — | — |

**Total 600 runs.**

### Detector tuning experiment
- **What was searched** *(source: `params.yaml` `tuning.grid`)*: every combination of
  - `min_excess_frac` ∈ {0.3, 0.5, 0.8, 1.0, 1.5}: how many times the background the signal must rise
  - `min_excess_abs` ∈ {3, 5, 8, 12, 16} counts/s: the minimum rise
  - `rise_steps` ∈ {2, 3, 4}: how many rising minutes in a row
  - `dip_frac` ∈ {0.3, 0.5}: how deep a dip splits two flares
  - `impulsive_factor` ∈ {0, 4}: whether one big jump also counts as a rise

  That's 5 × 5 × 3 × 2 × 2 = **300 trials**. A first, smaller grid had 108.
- **Scoring rule** *(source: `src/detection/tune.py`)*:
  - start from the **F1** of "match rate" and "C-and-above recall"; F1 is high only when both are high
  - minus 0.5 × the fraction of events longer than 2 h
  - minus 0.01 × the median onset error in minutes
  - only tuning-period data is used
- **Best settings:** `min_excess_frac` 1.0, `min_excess_abs` 12, `rise_steps` 3, `dip_frac` 0.3, `impulsive_factor` 0
  *(source: `reports/tuning_best.json`, `params.yaml`)*.
- **Top 5 trials** *(source: `reports/tuning_results.csv`)*:

| # | frac | abs | rise steps | dip | impulsive | score | match rate | C+ recall | onset error (median, min) | events > 2 h |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1.0 | 12 | 3 | 0.3 | 0 | **0.7986** | 0.762 | 0.865 | 1.0 | 5 |
| 2 | 1.0 | 12 | 3 | 0.5 | 0 | 0.7979 | 0.761 | 0.865 | 1.0 | 6 |
| 3 | 1.0 | 8 | 3 | 0.3 | 0 | 0.7977 | 0.749 | 0.880 | 1.0 | 5 |
| 4 | 1.0 | 16 | 3 | 0.3 | 0 | 0.7975 | 0.782 | 0.838 | 1.0 | 5 |
| 5 | 1.0 | 16 | 3 | 0.5 | 0 | 0.7971 | 0.782 | 0.838 | 1.0 | 6 |

### Model experiments: latest results *(source: `reports/model_metrics.json`, the last `flare-models-v2` training run)*

**What the four scores mean:**
- **TSS:** the share of flares warned about, minus the share of quiet times wrongly alarmed. 0 = no skill, 1 = perfect.
- **HSS:** how much better than random guessing, taking into account how often we say "yes".
- **POD:** of all real flares, the share we warned about (hit rate).
- **FAR:** of all our alarms, the share that were false.

**How to read the table:**
- Validation period 2026-02-01…05-31, 114 days, operating point A (threshold = max TSS on Dec–Jan), all rows.
- TSS is the mean ± std over 3 seeds, with the 95% interval from resampling days. ★ = best model for that target.
- **All results here use the new labels** (taken from GOES).

| Target | Model | TSS (mean ± std) | 95% interval | HSS | POD | FAR |
|---|---|---|---|---|---|---|
| now | Climatology | 0.000 | [0.00, 0.00] | 0.000 | 0.00 | 0.00 |
| now | Persistence | 0.657 | [0.63, 0.68] | 0.645 | 0.68 | 0.34 |
| now | Rule | 0.634 | [0.61, 0.66] | 0.362 | 0.77 | 0.71 |
| now | LogReg | 0.677 ± 0.001 | [0.66, 0.70] | 0.408 | 0.80 | 0.67 |
| now | **XGBoost ★** | **0.727 ± 0.001** | [0.71, 0.74] | 0.520 | 0.81 | 0.57 |
| c_30m | Climatology | 0.000 | [0.00, 0.00] | 0.000 | 0.00 | 0.00 |
| c_30m | Persistence | 0.016 | [-0.00, 0.04] | 0.019 | 0.09 | 0.86 |
| c_30m | Rule | 0.034 | [0.01, 0.06] | 0.026 | 0.23 | 0.86 |
| c_30m | **LogReg ★** | **0.208 ± 0.000** | [0.15, 0.26] | 0.127 | 0.48 | 0.81 |
| c_30m | XGBoost | 0.161 ± 0.013 | [0.11, 0.21] | 0.129 | 0.33 | 0.79 |
| c_60m | Climatology | 0.000 | [0.00, 0.00] | 0.000 | 0.00 | 0.00 |
| c_60m | Persistence | 0.013 | [-0.00, 0.03] | 0.017 | 0.08 | 0.75 |
| c_60m | Rule | 0.031 | [0.01, 0.06] | 0.032 | 0.21 | 0.76 |
| c_60m | **LogReg ★** | **0.208 ± 0.001** | [0.14, 0.27] | 0.188 | 0.44 | 0.66 |
| c_60m | XGBoost | 0.192 ± 0.007 | [0.13, 0.25] | 0.190 | 0.37 | 0.64 |
| c_120m | Climatology | 0.000 | [0.00, 0.00] | 0.000 | 0.00 | 0.00 |
| c_120m | Persistence | 0.026 | [0.01, 0.04] | 0.032 | 0.09 | 0.57 |
| c_120m | Rule | 0.032 | [0.01, 0.06] | 0.032 | 0.36 | 0.63 |
| c_120m | LogReg | 0.268 ± 0.002 | [0.20, 0.34] | 0.270 | 0.51 | 0.47 |
| c_120m | **XGBoost ★** | **0.270 ± 0.003** | [0.20, 0.34] | 0.280 | 0.47 | 0.44 |
| m_30m | Climatology | 0.000 | [0.00, 0.00] | 0.000 | 0.00 | 0.00 |
| m_30m | Persistence | 0.108 | [0.06, 0.16] | 0.034 | 0.18 | 0.97 |
| m_30m | Rule | 0.050 | [0.01, 0.08] | 0.033 | 0.08 | 0.96 |
| m_30m | **LogReg ★** | **0.468 ± 0.001** | [0.33, 0.57] | 0.041 | 0.76 | 0.97 |
| m_30m | XGBoost | 0.388 ± 0.005 | [0.25, 0.50] | 0.036 | 0.66 | 0.97 |
| m_60m | Climatology | 0.000 | [0.00, 0.00] | 0.000 | 0.00 | 0.00 |
| m_60m | Persistence | 0.089 | [0.05, 0.13] | 0.045 | 0.16 | 0.95 |
| m_60m | Rule | 0.139 | [0.08, 0.20] | 0.041 | 0.28 | 0.95 |
| m_60m | **LogReg ★** | **0.468 ± 0.000** | [0.30, 0.61] | 0.099 | 0.66 | 0.92 |
| m_60m | XGBoost | 0.418 ± 0.004 | [0.26, 0.55] | 0.066 | 0.69 | 0.94 |
| m_120m | Climatology | 0.000 | [0.00, 0.00] | 0.000 | 0.00 | 0.00 |
| m_120m | Persistence | 0.076 | [0.04, 0.11] | 0.056 | 0.15 | 0.92 |
| m_120m | Rule | 0.113 | [0.06, 0.16] | 0.027 | 0.43 | 0.94 |
| m_120m | **LogReg ★** | **0.388 ± 0.001** | [0.21, 0.56] | 0.134 | 0.58 | 0.88 |
| m_120m | XGBoost | 0.348 ± 0.003 | [0.15, 0.52] | 0.117 | 0.55 | 0.89 |

**Old labels vs new labels** *(source: `mlflow.db` run times vs `git log`)*:
- **Old labels**, from our detector only: the first 3 batches of `flare-models` (63 runs, 18:47–19:22 on 21 Oct),
  logged before commit `ad923ad` (19:51).
- **New labels**, from GOES: the last 2 batches of `flare-models` (42 runs, 19:48–19:57) and **all** `flare-models-v2`
  runs. The table above is new-label only.

**Model registry:** **empty**: 0 registered models, 0 versions *(source: `mlflow.db` tables `registered_models`,
`model_versions`)*. A registry is a shelf of "official" model versions (for example "production v3"). We save model
files as run artifacts and in `models/`, but have **not done** registry promotion yet.

### How to open the MLflow UI on our setup
With the venv active, in the project folder:
```
mlflow ui --backend-store-uri sqlite:///mlflow.db
```
Then open **http://127.0.0.1:5000** in a browser.
- **If it says the port is in use:** an MLflow UI from an earlier session may still be running. Open the address
  anyway, or start on another port with `--port 5001`.
- **To stop it:** press Ctrl+C.

**Find the best run (detector tuning)**
1. In the left list, click **detector-tuning**.
2. In the runs table, click the **▸ arrow** next to the newest `grid-tune-period` run to expand its child trials.
3. Click **Columns** and tick the metric **score**.
4. Click the **score** column header twice to sort from high to low. The top row is the best run.
5. Click it: the **Parameters** section shows the settings (frac 1.0, abs 12, …).

**Compare two runs**
1. In **flare-models-v2**, expand the latest `m_60m` parent run.
2. Tick the boxes of `m_60m-logreg` and `m_60m-xgb`.
3. Click **Compare**.
4. Scroll to the metrics table and look at `A_all_tss_mean`, `A_all_far_mean` and `A_quiet_tss_mean` side by side.

**View a plot or file saved in a run**
- **No PNG plots were saved inside MLflow runs: not done.** Our figures are saved in `docs/` instead.
- **Files you can open:**
  - in a `flare-models-v2` parent run, the **Artifacts** tab has `xgb_cv.csv` and the saved models
  - in a `flare-models` XGBoost run, the **Artifacts** tab has `feature_importance.json`
  - in `hel1os-ablation`, the **Artifacts** tab has `ablation.json`

  Click a file to preview it.
- **Plots MLflow draws itself:** in the Compare page, choose a **parallel coordinates** or **scatter** plot of metrics
  (for example `max_depth` vs `A_all_tss_mean`).

---

## 5. Tests

**57 tests** in 5 files *(source: `pytest --collect-only -q`)*. Today **56 pass and 1 fails**: the line-ending check,
because of the notebook file's working copy (see the top of this file).

| Group (file, number) | What they check (one line each) |
|---|---|
| **Detector** (`test_detector.py`, 7) | Start found at the beginning of the rise; end at half-decay; background frozen during a flare; trigger uses only the past; double peaks split; 3-h cap; pure noise gives no flares. |
| **Data inventory** (`test_inventory.py`, 3) | Archive names parsed correctly; truncated zips listed safely; extraction writes only chosen files and **never overwrites**. |
| **Leakage** (`test_leakage.py`, 27) ⭐ | See below; these protect against "seeing the future". |
| **Models** (`test_models.py`, 12) | TSS/HSS formulas; best-threshold search; baselines; time-ordered CV folds; bootstrap intervals; ablation helpers; **test period locked**. |
| **Pipeline** (`test_pipeline.py`, 8) | UTC time conversion; GOES text parser; time-unit-safe masks; GOES class only from GOES; HEL1OS newest-version rule; HEL1OS sub-second bug; HEL1OS optional; Unix line endings. |

**Leakage tests ⭐** (a "leak" means the model accidentally sees future information):
- `test_features_unchanged_when_future_is_altered` (×3) and `test_hel1os_features_unchanged_when_future_is_altered`
  (×3): scramble the future, and past features must not change.
- `test_no_centered_windows_or_negative_shifts_in_feature_code`: reads the code's structure (AST) and fails on any
  window or shift that looks ahead.
- `test_forecast_label_uses_only_onsets_strictly_after_t`, `test_label_window_never_crosses_period_end`,
  `test_label_not_ok_without_goes_truth_or_data`: labels look only *after* t, never cross into another period, and
  are marked "don't trust" when data is missing.
- `test_flare_in_progress_flag_is_causal` (×5): the activity flag never uses data after t.
- `test_periods_are_chronological_and_disjoint`, `test_built_dataset_files_are_chronological`: tune < val < test in time.
- `test_tuner_only_reads_the_tune_period`: detector tuning can't see validation or test.

**The tests that keep the test period locked:**
- `test_training_refuses_the_test_period`: asking the training code to load "test" raises an error.
- `test_model_code_never_names_the_test_file`: no model code even mentions `test.parquet`.

---

## 6. Results summary: the 10 most important numbers

1. **424** SoLEXS days are usable (at least half the day observed) out of 452 day folders in our periods. *(source: `data/processed/solexs_qc.csv`)*
2. **23.7%** of all minutes in tuning + validation have no SoLEXS data, and the 17th of each month is only about 11% covered. *(source: `reports/eda_numbers.json`, `coverage`)*
3. Our detector finds the start of a flare within a **median of 1 minute** of NOAA's time. *(source: `reports/detection_metrics.json`, `new.val.onset_error_min.median_abs`)*
4. It catches **88%** of GOES C-class flares and **93%** of M-class flares in validation. *(source: `reports/detection_metrics.json`, `new.val.goes_recall_by_class`)*
5. Events longer than 2 hours dropped from **218 to 5** after the detector rebuild (tuning period). *(source: `reports/detection_metrics.json`, `legacy.tune` vs `new.tune` `n_events_gt_long`)*
6. Nowcasting ("is a flare happening now?") reaches **TSS 0.727** (95% interval 0.71–0.74), better than the persistence baseline at 0.657. *(source: `reports/model_metrics.json`)*
7. Forecasting an M-class flare within 30 minutes reaches **TSS 0.468** (interval 0.33–0.57), but **97%** of those alarms are false (FAR 0.97). *(source: `reports/model_metrics.json`, `m_30m`)*
8. Forecast skill stays almost the same when no flare is already happening (quiet-start ≥M 30 min: TSS **0.465**), so the models don't just copy "a flare is going on". *(source: `reports/model_metrics.json`, quiet subset)*
9. Hard X-rays (HEL1OS) overlap only **215.6 h** of tuning and **143.5 h** of validation, and the Neupert lag is a **median of 0 s** over 71 flares. *(source: `reports/eda_numbers.json`, `hel1os`)*
10. The pipeline has **9 DVC stages**, **57 tests**, **600 MLflow runs** and **10 data versions**, and the test period has **never been opened**. *(source: `dvc.yaml`, `pytest`, `mlflow.db`, `git log -- dvc.lock`)*

---

## 7. Live outputs

Commands run on 2026-10-22 in `D:\projects\solar-flare-project` with the venv active. The output is pasted exactly.

```
$ git log --oneline -15
40d0d40 Regenerate presentation facts against commit 998609a
998609a Retrain with HEL1OS features + soft/hard ablation; EDA notebook and figures; fix DVC owning docs/figures; presentation figures and facts generator; lessons 10-13
4c5968d Fix HEL1OS band alignment bug, add causal hard X-ray features (availability, hardness, lags, Neupert), rebuild dataset with 98 HEL1OS sessions
2054289 Extract light curves + aux for 77 HEL1OS sessions (847 files verified, no overwrites, zips kept); lesson 09 part 2
627d783 CLAUDE.md: never delete or move data without asking; check folder contents before any cleanup
486b07e Read-only data inventory of all Aditya-L1 archives on D: (finds 77 unextracted HEL1OS sessions overlapping SoLEXS), correct CLAUDE.md, lesson 09
3722f6e Rebuild training: climatology/persistence baselines, rolling-origin CV for XGBoost, 3 seeds, operating points A/B, day-bootstrap intervals, quiet-start reporting, validation table; lessons 07-08
2d4d4f5 Add causal flare_in_progress_at_t meta column (trigger to confirmed end) with causality tests
ad923ad Forecast labels from the GOES list directly (missed flares become positives), label comparison report, tests
8a6564a Add model training stage (rule, logistic regression, XGBoost per target), TSS/HSS metrics, MLflow logging, LF-safe writers, lesson 06
2d15602 Add catch-up lessons 01-05, progress log, and .gitattributes to stop CRLF rewrites breaking DVC hashes
b61ab00 Switch CLAUDE.md to autonomous build mode rules
feefab6 Add teaching-mode rules to CLAUDE.md
07c7845 Tighten flare detector (GOES-style onset/end, frozen background, dip splitting, 3 h cap), tune on tune period only, add labels, causal 10 s features and leakage tests
48b5577 Run data pipeline on all 458 SoLEXS days

$ dvc status
Data and pipelines are up to date.

$ dvc dag
                                                                                        +--------------+                                 
                                                                                       *| solexs_clean |***                              
                                                                                 ****** +--------------+   ******                        
                                                                           ******        ***          ***        *******                 
                                                                    *******             *                *              ******           
                                                              ******                  **                  **                  ******     
                          +------------+                  ****             +---------------+         +---------------+              **** 
                          | fetch_goes |*******           *                | detect_events |         | legacy_events |                 * 
                          +------------+       ************                +---------------+         +---------------+                 * 
                                 *                        *************                 ***           **                               * 
                                 *                        *            ***********         *        **                                 * 
                                 *                        *                       *******   **    **                                   * 
+--------------+                 ***                      *                             +------------+                               *** 
| hel1os_index |*****               ***                   *                           **| match_goes |                           ****    
+--------------+     ********          *****              *                     ******  +------------+                       ****        
                             *********      ***           *               ******                      **                 ****            
                                      ******** *****      *         ******                              **           ****                
                                              ***** **    *     ****                                      **      ***                    
                                                 +---------------+                                 +-------------------+                 
                                                 | build_dataset |                                 | evaluate_detector |                 
                                                 +---------------+                                 +-------------------+                 
                                                          *                                                                              
                                                          *                                                                              
                                                          *                                                                              
                                                     +-------+                                                                           
                                                     | train |                                                                           
                                                     +-------+                                                                           

$ git log --oneline -- dvc.lock
998609a Retrain with HEL1OS features + soft/hard ablation; EDA notebook and figures; fix DVC owning docs/figures; presentation figures and facts generator; lessons 10-13
4c5968d Fix HEL1OS band alignment bug, add causal hard X-ray features (availability, hardness, lags, Neupert), rebuild dataset with 98 HEL1OS sessions
3722f6e Rebuild training: climatology/persistence baselines, rolling-origin CV for XGBoost, 3 seeds, operating points A/B, day-bootstrap intervals, quiet-start reporting, validation table; lessons 07-08
2d4d4f5 Add causal flare_in_progress_at_t meta column (trigger to confirmed end) with causality tests
ad923ad Forecast labels from the GOES list directly (missed flares become positives), label comparison report, tests
8a6564a Add model training stage (rule, logistic regression, XGBoost per target), TSS/HSS metrics, MLflow logging, LF-safe writers, lesson 06
2d15602 Add catch-up lessons 01-05, progress log, and .gitattributes to stop CRLF rewrites breaking DVC hashes
07c7845 Tighten flare detector (GOES-style onset/end, frozen background, dip splitting, 3 h cap), tune on tune period only, add labels, causal 10 s features and leakage tests
48b5577 Run data pipeline on all 458 SoLEXS days
3e0781a Add stage-2 data pipeline (SoLEXS clean, flare detection, GOES match, HEL1OS parser) with DVC

$ pytest -q        (last 15 lines of the output; the earlier lines are the same traceback)
        root = Path(__file__).resolve().parents[1]
        files = subprocess.check_output(["git", "ls-files"], cwd=root, text=True).split()
        binary = (".png", ".parquet", ".db", ".joblib", ".gz", ".fits")
        # dvc.lock is written by DVC itself (CRLF on Windows); it is never a stage dependency, and git stores it as LF.
        skip = {"dvc.lock"}
        crlf = [f for f in files if not f.endswith(binary) and f not in skip and (root / f).exists()
                and b"\r\n" in (root / f).read_bytes()]
>       assert not crlf, f"CRLF line endings in: {crlf}"
E       AssertionError: CRLF line endings in: ['notebooks/01_eda.ipynb']
E       assert not ['notebooks/01_eda.ipynb']

tests\test_pipeline.py:91: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_pipeline.py::test_tracked_text_files_use_lf_line_endings - ...
1 failed, 56 passed in 3.76s

$ python (MLflow summary from mlflow.db)
Default          runs=   0  first=None  last=None
detector-tuning  runs= 410  first=2026-10-07 11:42:30  last=2026-10-07 11:48:16
flare-models     runs= 105  first=2026-10-21 18:47:31  last=2026-10-21 19:57:32
flare-models-v2  runs=  85  first=2026-10-21 20:11:06  last=2026-10-22 01:44:08
total runs: 600 | registered models: 0
```
