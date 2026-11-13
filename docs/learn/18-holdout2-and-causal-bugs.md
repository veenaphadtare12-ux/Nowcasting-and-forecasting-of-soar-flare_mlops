# 18 — A second honest holdout, a hidden time-travel bug, and the baseline nobody tried

## What we built
- **Holdout2, a fresh untouched test set** (all data after 2026-09-12: 11 usable days). It is locked by SHA-256 checksums
  before any feature exists, and only one DVC stage may ever read it.
- **A fix for a "time-travel" bug in the flare detector.** Split flares were visible up to 155 minutes before the detector
  could know about them. There is a test that rebuilds the catalogue minute by minute to prove it is gone.
- **A 14-month rolling evaluation**, now including the old test months as ordinary training data. Every result is reported
  four ways: mean of months, pooled, worst month, and active vs quiet days.
- **Four new ideas, tested under a rule fixed in advance:**
  - R1: predicting a flare's class in its first minutes;
  - R2: context from past events and NOAA reports;
  - R3: pretraining on 8 years of GOES data;
  - R4: cost-based alarm thresholds.
- **FINAL_CHOICE_2 and one scoring.** A mechanical final choice was committed with model hashes, then holdout2 was scored
  exactly once.

## Why it matters (everyday analogy)
Think of a school exam. The old test was the paper the teacher already marked. Once you have seen your marks you may
study with it, but you can never again use it to *prove* you are ready. So a new, sealed paper is needed (holdout2). We
sealed it in an envelope with a fingerprint (SHA-256), wrote down in advance which answers we would give
(FINAL_CHOICE_2), and only then opened it.

The time-travel bug is like a stopwatch that sometimes records a runner's split time before the runner has passed the
marker. The final time can still be right, but anything computed from the split times "knew" the future.

## Concepts
- **Holdout / lock.** Data kept away from every decision. *Locking* means you can prove later that it did not change
  (checksums) and was not read early (code tests plus a stage that refuses to run).
- **SHA-256.** A 64-character fingerprint of a file. Change one byte and the fingerprint changes completely.
- **Causal / real-time knowledge.** A feature at time t may use only what was *knowable* at t. A value can lie in the past
  and still be unknowable at t: the detector decides to split a merged flare only after the whole event ends.
- **Truncation test.** Re-run the algorithm on data cut at time c, and check that everything the full run claims was
  "known by c" also appears in the cut run. This is the strongest general test for causality.
- **Rolling monthly protocol.** For each month m: fit on data before month m−1, choose the threshold on month m−1, score
  month m. A purge gap of 120 min keeps label windows from crossing blocks.
- **Pooled vs mean of months.** *Pooled* adds all months' counts, then computes TSS once. *Mean of months* computes TSS
  per month and averages. Quiet months with few flares pull the mean down, and a strong active/quiet contrast pushes the
  pooled value up.
- **Active vs quiet days.** A day is *active* if a ≥M flare ended in the 72 hours before it. This is used only to *split
  the evaluation*, never as an input.
- **Baseline: current flux.** Alert when today's X-ray level is above one threshold. If a model cannot beat this, it has
  learned "the Sun is bright", not "a flare is coming".
- **Acceptance rule.** "Mean monthly TSS up AND at least 60 % of months better", fixed before results. It protects
  against lucky averages.
- **Pretraining / zero-shot / fine-tuning.** Train on a big related dataset (GOES, 2017–2025):
  - zero-shot: apply that model unchanged to the new data;
  - fine-tuning: continue training it on the new data.
- **Background-normalised features.** Ratios like flux / background do not depend on the instrument's units. That is what
  lets a GOES-trained model read SoLEXS.
- **Cost-based threshold.** Choose the threshold that minimises FP + 10 × FN. A missed flare is assumed to cost as much as
  ten false alarms.
- **UNDERPOWERED.** Too few events (here 7 M flares) for a result to mean anything. The rule was written down *before*
  scoring.

## Tools used
- **Git:** commits as timestamps of decisions. The FINAL_CHOICE_2 commit (b5e2044) comes before the holdout2 run, and the
  scoring code checks this. Commands: `git log --oneline`, `git log -1 --format=%cI -- docs/FINAL_CHOICE_2.md`.
- **DVC:**
  - `dvc freeze <stage>` keeps a historical stage from ever re-running (the old test scoring).
  - `dvc add data/external/holdout2` versions the downloaded holdout2 files.
  - `dvc commit -f <stage>` records outputs that were produced by running the command directly.
  - `dvc repro evaluate_holdout2` runs the one stage allowed to read holdout2.
- **MLflow:** new experiments `flare-dev2` (development runs), `flare-final2` (frozen models) and `flare-holdout2` (the
  single scoring).
- **pytest:** `tests/test_holdout2_lock.py` (who may touch holdout2), `tests/test_holdout2_pipeline.py` (the holdout2 code
  rebuilds dev data exactly), and `tests/test_detector.py` (truncation tests).
- **NOAA public data:** GOES event reports, GOES-16/19 XRS science files and SRS active-region reports, downloaded by
  `src/noaa.py`.

## Code walkthrough
- **`src/holdout2/ingest.py`:** `report()` counts usable days and GOES flares (no model); `lock()` writes the checksums;
  `verify()` re-checks them.
- **`src/detection/detector.py` → `_realtime_times`:** the core of the fix.

  ```python
  known = max(_segment_end_known(r, s) for r in segs)     # when the WHOLE detection is known to be over
  r["trigger_time"] = trigger if i == 0 else known         # later pieces exist only from then on
  r["end_known_time"] = known                              # no piece's end is known earlier
  ```
- **`src/dev2/protocol.py`:**
  - `evaluate_scores` stores contingency counts (not just TSS), so pooled TSS can be rebuilt;
  - `active_day_flags` builds the evaluation-only split;
  - `thr_cost` picks the cost-based threshold.
- **`src/dev2/run.py` → `add_blocks`:** every extra feature block is joined with a *backward as-of join*. A row at t sees
  only grid values stamped ≤ t.
- **`src/dev2/early.py` (R1):**
  - `detections` keeps only real triggers (segment 0);
  - `features` reads values at trigger + k with `_at(series, tau)`;
  - `first_m1_time` finds NOAA's M1 moment.
- **`src/dev2/choose.py`:** the selection rule as code, written before results were read.
- **`src/holdout2/evaluate.py`:** `require_final_choice_committed()` checks git, the model SHA-256s and the lock, and only
  then builds holdout2.

## Hands-on
1. **Verify the lock yourself.**

   ```bash
   .venv\Scripts\python -m src.holdout2.ingest verify
   ```

   Expected: `holdout2 files unchanged`.
2. **See the order of events in git.**

   ```bash
   git log --oneline -8
   ```

   Expected: the lock commit (`3a6140c`) and the FINAL_CHOICE_2 commit (`b5e2044`) appear before the commit that adds
   `reports/holdout2/metrics.json`.
3. **Run the causality tests.**

   ```bash
   .venv\Scripts\python -m pytest -q tests/test_detector.py -k "split or truncation or unsplit"
   ```

   Expected: 4 passed.
4. **Compare the mean of months with pooled TSS** for m_60m: open `reports/dev2/ref.json` and find
   `summary.m_60m.logreg`. Expected: `mean_monthly_tss` ≈ 0.242, `pooled_tss` ≈ 0.409. Why are they so different?
5. **Find the baseline that nobody tried.** In the same file compare `summary.m_30m.logreg.pooled_tss` with
   `summary.m_30m.flux.pooled_tss`. Expected: 0.387 vs 0.399.
6. **Read the active-day effect on holdout2.** In `reports/holdout2/metrics.json`, look at
   `forecasts.c_60m.aditya.points.A.active_days`. Expected counts [TP, FP, FN, TN] ≈ [28588, 14246, 26, 22]. What does a
   model that alerts on almost every row score?

## Break it on purpose
Bring the bug back temporarily, without editing files:

```bash
.venv\Scripts\python -c "import sys; sys.path.insert(0,'tests'); import test_detector as td, pandas as pd; from src.detection import detector as d; o=d._realtime_times; d._realtime_times=lambda s,t,m,b,st:[{**r,'trigger_time':(r['onset']+pd.Timedelta(minutes=1) if r['segment'] else r['trigger_time'])} for r in o(s,t,m,b,st)]; td.test_split_segments_are_not_known_before_the_detection_ends()"
```

Expected: an `AssertionError`, because the later piece's trigger no longer equals the moment the whole detection is known.
To watch the minute-by-minute check fail as well, call `td._truncation_check(...)` the same way: it reports "event with
onset … visible at … before the detector knew it". Nothing is changed on disk, so there is nothing to undo.

## Check yourself
1. Why may the old test period now be used for training, but never again to *report* skill?
2. The detector's split decision uses only past data at the moment it is made. Why was it still a causality bug?
3. On holdout2, c_60m has pooled TSS 0.60, but TSS on active days ≈ 0. How can both be true?
4. Why does the acceptance rule need ≥ 9 of 14 months and not just "mean TSS up"?
5. R1 at k = 0 ties the current-flux baseline, yet its alerts come 2 min before NOAA's M1. Why is that still useful, and
   what does waiting until k = 3 buy and cost?

## Questions to discuss with my tutor
- Is "current flux level" the right minimum baseline for flare forecasts, and what would a fair stronger baseline be (for
  example persistence of yesterday's flare rate)?
- Is 60 % of months the right translation of "6 of 10" to 14 months, or should the rule be a paired statistical test?
- How could the forecast models learn *timing* inside an active period, rather than just "active or not"?
- With only 11 days and 7 M flares, was it worth spending a holdout at all, or should we have waited for more data?

## Key numbers to remember
- **Holdout2:** 11 days, 118 C and 7 M flares (UNDERPOWERED for M); 494 files locked.
- **Bug:** 41 of 3,126 events visible a median 18 min (max 155 min) too early.
- **Development, mean monthly TSS:** now 0.72, c_60m 0.21, m_60m 0.24. The current-flux baseline ties the M models.
- **Holdout2:**
  - nowcast 0.76 [0.69, 0.81] vs persistence 0.66;
  - c_60m 0.60 vs current flux 0.60.
- **R1, ≥M TSS:** 0.44 at the trigger → 0.64 three minutes later (flux 0.44 → 0.58).
- **R3 mapping:** SoLEXS ∝ GOES^1.42 (EDA 1.34); r = 0.97.

---

**Answers.**
1. Its scores were seen once. Any choice made after seeing them would be tuned to it, so it can no longer give an
   unbiased number. Training on it adds data without that problem.
2. The decision is made at the end of the merged event, but the code stamped the later pieces as known at "onset + 1 min",
   up to 155 min earlier than the decision.
3. Pooled TSS rewards separating quiet days (few alerts, few flares) from active days (alerts and flares). Inside the
   active days the model alerts almost always, so it cannot tell flare rows from non-flare rows there.
4. A mean can rise because of one lucky month. Requiring most months to improve demands consistency.
5. An early, rough warning still gives operators minutes before NOAA's alert. Waiting until k = 3 improves the TSS
   (0.44 → 0.64), but the alerts then arrive about a minute after NOAA's M1 instead of 2 minutes before.
