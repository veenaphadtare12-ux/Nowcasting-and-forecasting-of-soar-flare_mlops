# Lesson 16 — Improving a model honestly: rolling evaluation, a rule fixed in advance, and 7 experiments

## What we built
- **A fairer way to measure skill:** a *rolling monthly evaluation* over 10 months (Aug 2025 – May 2026). Each
  month m is predicted by a model trained only on months before m−1, with thresholds taken from month m−1.
- **An acceptance rule, written down before any experiment ran** (`docs/IMPROVEMENTS.md`, section 1).
- **Seven experiments, each compared with the same reference:**
  - E1 adaptive thresholds;
  - E2 long-context features;
  - E3 drift-robust features;
  - E4 feature pruning;
  - E5 SoLEXS spectral features;
  - E6 GOES XRS flux;
  - E7 an ensemble.
- **Two new DVC data stages** (`solexs_spectral`, `goes_xrs_fetch` → `goes_xrs_minute`) and one DVC stage per
  experiment (`improve_reference`, `improve_E2` … `improve_final`).
- **A new MLflow experiment, `flare-improve`,** with one parent run per experiment.
- **8 new leakage tests** (`tests/test_improve.py`).

## Why it matters (an everyday analogy)
Imagine studying for an exam by repeatedly checking yourself against the *same* practice paper. After twenty
attempts you score very well, but partly because you've memorised that paper. Our validation period had become such
a practice paper: we had looked at it for many model comparisons.

The rolling evaluation is like getting **ten fresh practice papers, one per month**. The acceptance rule is like
promising your teacher *before* the exam: "I'll only claim I improved if I beat my old score on at least 6 of the 10
papers." Writing the promise first stops you from inventing a convenient rule afterwards.

## Concepts
- **Rolling-origin (walk-forward) evaluation:** train on the past, test on the next block, then move forward. It
  copies how the model would really be used, one month after another.
- **Purge gap:** a 60-min forecast label at 23:30 on 31 March looks at flares up to 00:30 on 1 April. Rows that close
  to the next block are dropped (120 min), so no label secretly contains information from the scored month.
- **Mean ± std over months:** the std shows how much skill swings from month to month. A small average gain with a
  big swing is not convincing; that's why we also count *months improved*.
- **Pre-registered acceptance rule:** the decision rule is fixed before seeing results. This blocks the
  "garden of forking paths": trying many ideas and keeping whichever looks good by chance.
- **Adaptive threshold (E1):** instead of one threshold chosen on an old month, re-choose it every day from the last
  30 days. This helps if the best threshold drifts, and hurts if 30 days hold too few flares to choose it reliably.
- **Operating point C:** the lowest threshold whose alerts have FAR ≤ 0.80, i.e. "at most 4 false alarms per true
  alarm". It is reported for M targets, where FAR was 0.88–0.97.
- **Long context (E2):** flares cluster in active regions that live for days. Hours-long trends and "how many
  flares happened today" carry information that a 60-min window cannot see.
- **Causal detector features:** an event may be used from its *trigger time* (when the detector would have
  raised it live), and its peak only after its end is *confirmed*. The catalogue onset, which is found by looking
  back, is never used.
- **Drift normalisation (E3):** dividing by a trailing 7-day median turns "120 counts/s" into "1.5× this week's
  normal". It removes slow changes of the background and the solar cycle.
- **Collinearity pruning (E4):** features that are nearly copies of each other (|r| > 0.95) add noise for linear
  models. Dropping one of each pair simplifies the model.
- **Temperature proxy (E5):** hotter plasma emits relatively more high-energy X-rays, so the ratio of a high-energy
  band to a low-energy band rises as a flare heats up. The **HOPE** idea uses "temperature and counts both rising"
  as an early warning sign.
- **Ablation (E6):** run the same thing with and without one input to measure its contribution. Here the input is
  GOES XRS flux. This tests whether an external, operational data source adds skill on top of SoLEXS.
- **Ensemble (E7):** average two different models; their mistakes partly cancel out.

## Tools used
- **DVC:** each experiment is a stage. `dvc repro improve_final` runs any experiment whose code, data or params
  changed. `dvc status` shows what is out of date.
- **MLflow:** experiment `flare-improve`; each parent run is one experiment, with child runs per target.
  - Metrics: `tss_mean`, `delta_tss`, `months_improved`, `kept`.
  - `*_month_tss` is logged with step = month index, so the MLflow UI draws a month-by-month line.
- **h5py:** reads the GOES netCDF-4 files (netCDF-4 is HDF5 inside).
- **astropy:** reads the SoLEXS `.pi` spectra (one 340-channel spectrum per second).

Useful commands:
```
dvc repro improve_E2
python -m src.improve.run table
mlflow ui --backend-store-uri sqlite:///mlflow.db
```

## Code walkthrough
- `src/improve/protocol.py`:
  - `fold_masks` returns the fit / threshold / score rows for month m;
  - `rolling_yhat` refreshes thresholds daily from rows in `[max(d−30 days, start of m−1), d − 120 min)`;
  - `thr_far_cap` finds operating point C.
- `src/improve/features_extra.py`: every source is put on a minute grid stamped at the minute's **end** and joined
  with `merge_asof(direction="backward")`, so a row only sees values that already existed.
  - `long_context_grid` (E2), `drift_normalise` (E3), `spectral_grid` (E5), `goes_grid` (E6).
- `src/improve/spectral.py` and `src/improve/goes_xrs.py`: the two data stages. GOES files are downloaded only up to
  the last validation day.
- `src/improve/run.py`:
  - `run_fold` fits LogReg and XGBoost for one month;
  - `compare` applies the acceptance rule;
  - `run_final` combines only the KEPT ideas and also scores the original validation block.

## Hands-on
1. `python -m src.improve.run table`. *Expected:* the experiment × target table from `docs/IMPROVEMENTS.md`.
2. `python -c "import json; r=json.load(open('reports/improve/reference.json')); print(r['summary']['m_60m']['xgb']['all_months'])"`.
   *Expected:* 10 monthly TSS values. Which month is worst? Compare it with the monthly flare counts in figure 03.
3. In the MLflow UI, open `flare-improve` → `E2` → `E2-m_60m` and plot `xgb_month_tss` over steps.
4. `pytest tests/test_improve.py -v`. *Expected:* 8 passed. Read `test_long_context_features_do_not_see_the_future`
   and explain why `ev_max_peak_6h` is 0 at the cut time.

## Break it on purpose
In `src/improve/protocol.py`, change `"cal_end": s_m - purge` to `"cal_end": s_m + pd.Timedelta(days=5)`, then run
`pytest tests/test_improve.py`. The protocol test fails, because thresholds would now peek into month m. Undo with
`git checkout -- src/improve/protocol.py`.

## Check yourself
1. Why do we score 10 months instead of the 4 validation months?
2. What would go wrong without the 120-min purge?
3. Why must the acceptance rule be written down before running experiments?
4. Why can a 30-day adaptive threshold be *worse* for M flares?
5. Why is the GOES experiment called an ablation, and what is its operational catch?

<details><summary>Answers</summary>

1. More, fresher evidence. Validation was already used many times, and 10 months show how stable a gain is.
2. Labels near the end of the threshold month would include flares from the scored month: information from the
   future.
3. Otherwise you can unconsciously choose the rule that makes your favourite idea win.
4. 30 days hold only a handful of M flares, so the max-TSS threshold jumps around from day to day.
5. It measures skill with vs without one input. The catch: the GOES list that defines our labels comes from the
   same XRS instrument, and real-time GOES data arrive with some latency; our L2 science files are reprocessed later.
</details>

## Questions to discuss with my tutor
- Is "≥ 6 of 10 months" a strict enough rule, or should we use a paired statistical test across months?
- Is using GOES XRS as an input acceptable in a project about Aditya-L1, given that the labels come from GOES?
- How should we choose thresholds when a month has very few M flares?

## Key numbers to remember
- 10 scored months (Aug 2025 – May 2026), 120-min purge, 1 seed. Rule: mean up AND ≥ 6/10 months better.
- Reference under the rolling protocol (mean ± std of monthly TSS): c_60m 0.189 ± 0.102, m_60m 0.261 ± 0.174,
  now 0.701 ± 0.035, c_30m 0.155 ± 0.101, m_30m 0.258 ± 0.178. That's lower than the reused validation block
  (m_60m 0.47), so the old numbers were optimistic.
- Best single idea: E2 long context for ≥C 30 min, 0.155 → 0.191 (9/10 months).
- E1 adaptive thresholds for M: mean 0.26 → 0.34, but only 4/10 months, so dropped.
- Operating point C (FAR ≤ 0.80) for M targets: POD only 0.00–0.04, so not usable.
- E5 spectral (temperature proxy): kept for 4 targets, each at exactly 6/10 months (borderline).
- E6 GOES: correlation with SoLEXS 0.98; adds almost nothing.
- Final candidate on the original validation block: ≥C 30 min 0.208 → 0.290 [0.23, 0.35]; the other targets are flat.
- 54 MLflow runs in `flare-improve`, 8 new tests, 10 new DVC stages.
