# CLAUDE.md — solar-flare-project

Nowcasting and forecasting of solar flares by combining Aditya-L1 SoLEXS (soft X-ray)
and HEL1OS (hard X-ray) Level-1 data. These rules are permanent; follow them in all code.

## Permanent rules

1. **No random train/test splits.** Splits are always chronological (train < validation < test in time).
2. **All model input features are causal.** Computed only from data at or before the current
   timestamp. Rolling windows are trailing, never centered.
3. **Forecast labels come strictly from AFTER the input window ends.**
4. **Primary metrics are TSS and HSS.** Never report accuracy alone.
5. **Raw data is never modified.** Processed data goes to `data/processed/`.
6. **Every training run is logged to MLflow.**
7. **Code layout:** code in `src/`, exploration in `notebooks/`, tests in `tests/`.

## Periods, tuning and labels (params.yaml `periods`)

- tune 2025-04-09..2026-01-31, val 2026-02-01..2026-05-31, test 2026-06-01..2026-09-12. Use these everywhere.
- Detector thresholds are tuned ONLY on the tune period (`python -m src.detection.tune`, logged to MLflow); chosen
  values are copied into params.yaml by hand. Nothing is tuned on val. The test period is never evaluated,
  inspected or tuned on (its dataset summary deliberately has no label statistics).
- Detector event catalogue fields (onset, peak, end, class, match) are label-side only, never features.
- Positives come only from GOES-matched events; GOES class only from the match. Days with no NOAA report
  (2025-12-30, 2025-12-31) have no GOES truth: excluded from evaluation, labels marked not ok.
- Training code must filter forecast rows on `ok_<h>m` (and nowcast rows on `ok_now`).

## Pipeline notes

- Run DVC with the venv on PATH (`.venv\Scripts\activate`, then `dvc repro`); `dvc.yaml` uses plain `python`.
- DVC outputs are read-only hardlinks into `D:/dvc-cache`: never write into an existing output in place.
  Pipeline code unlinks a file before writing it (`_fresh`); do the same in any new stage.
- MLflow tracking: `sqlite:///mlflow.db` at the project root (the file store is deprecated in MLflow 3).

## Environment

- Windows. Project lives at `D:\projects\solar-flare-project`. Virtual env: `.venv` on Python 3.12 (`py -3.12`). Use `.venv\Scripts\python.exe`.
- All paths come from `params.yaml` via `src/config.py`; never hard-code paths. Raw data is never copied.
- `antlr4-python3-runtime==4.9.3` (needed by dvc via hydra-core) has no PyPI wheel. It is pure Python and was built into a wheel locally (`pip wheel antlr4-python3-runtime==4.9.3 --no-deps -w <dir>`), then `pip install --only-binary=:all: --find-links <dir> -r requirements.txt`.
- Jupyter kernel name: `solar-flare`.

## Data locations

Raw data lives outside the repo on D: (about 9.5 GB). Roots are set in `params.yaml` (`paths.data_root_solexs`, `paths.data_root_hel1os`):

- SoLEXS: `D:\MLOPS_CP\Data\SoLEXS\AL1_SLX_L1_<YYYYMMDD>_<ver>\SDD1|SDD2\AL1_SOLEXS_<YYYYMMDD>_SDD{1,2}_L1.{lc,pi,gti,hk}.gz`
- HEL1OS: `D:\MLOPS_CP\Data\HELIOS\<YYYY>\<MM>\<DD>\HLS_<YYYYMMDD>_<HHMMSS>_<dur>sec_lev1_V<ver>\{cdte,czt,aux,events}\`
- Original zips (backup): `D:\MLOPS_CP\Data\original_zips\`

## Data format notes (verified from files)

- SoLEXS light curves (`.lc.gz`, ext `RATE`): columns `TIME` (s, Unix epoch: MJDREFI=40587, MJDREFF=0,
  TIMESYS=UTC), `COUNTS`, 1 s cadence, 86400 rows/day, NaN rows occur. Light curves exist only for SDD2.
  The zero-point keyword is spelled `TIMZERO` (=0) in these files.
- HEL1OS light curves (`lightcurve_{cdte,czt}{1,2}.fits`): one extension per energy band; columns `MJD`, `ISOT`
  (UTC), `CTR` (cts/sec), `STAT_ERR`; 1 s cadence. No TIMESYS/TIMEUNIT/MJDREF headers; time is an explicit MJD column.
- SoLEXS (2024-10-01 .. 2026-09-13) and HEL1OS (2024-07-01 .. 2024-12-22) have **no overlapping dates** in
  the data currently held. The pipeline must work with SoLEXS alone and accept HEL1OS when available.

## TEACHING MODE (the user is a 3rd-year student learning MLOps through this project)

1. Work one task at a time. After each task, write a lesson file `docs/learn/NN-short-name.md`
   (NN = 01, 02, ...) and then STOP. Wait until the user types "continue" before starting the next task.
2. Every lesson file has these sections, in simple language:
   - What we built (2-3 sentences, plain words)
   - Why it matters (the problem it solves, with an everyday analogy)
   - Concepts (each new idea explained from zero, no undefined jargon)
   - Tools used (what each tool is, what it did here, the 3-5 most useful commands)
   - Walkthrough of the code (the key files, with the 10-20 most important lines quoted and explained line by line)
   - Hands-on (3-6 exercises the user does themselves in the terminal or a notebook, with the exact commands,
     the expected output, and how to tell if it worked)
   - Break it on purpose (one safe experiment: change something, see what fails, undo it)
   - Check yourself (5 quiz questions; answers at the bottom under a spoiler line)
   - Questions to discuss with my tutor (3 deeper questions)
   - Key numbers (results from this task to remember for the review)
3. Never do the hands-on exercises for the user. If they ask for help, give hints first.
4. Keep `docs/learn/INDEX.md` updated: one line per lesson with its status.
5. Commit after each task, including the lesson file.
