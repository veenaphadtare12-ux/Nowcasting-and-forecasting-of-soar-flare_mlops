# Lesson 08 — Honest model comparison: baselines, time-series CV, seeds, operating points, bootstrap intervals

## What we built

We rebuilt the training stage so every model is compared fairly:
- **Two baselines:** "climatology" (always forecast the usual flare rate) and "persistence" (forecast a flare
  whenever one is already in progress). These join the one-feature rule.
- **XGBoost settings** are chosen by **rolling-origin cross-validation** inside the tuning period, not by early
  stopping on two thin months.
- **Seeds:** logistic regression and XGBoost are trained with 3 random seeds.
- **Two operating points:** each model is scored at two alert thresholds.
- **Uncertainty:** every TSS gets a 95% interval from resampling validation days.

Results go to `reports/validation_table.md`, `docs/model_figures/val_skill.png` and MLflow (`flare-models-v2`).

## Why it matters

A runner who says "I ran 100 m in 11 seconds" tells you little until you know how others ran (baselines), whether
it was wind-assisted (fair conditions), whether they can repeat it (seeds), and how much their times vary from day
to day (intervals). Model scores are the same. Without baselines, you can't tell if 0.2 is good. Without intervals,
you can't tell if 0.45 really beats 0.33. Without a fair tuning procedure, the score may be luck.

## Concepts

**Baseline.** A simple, cheap forecast every real model must beat.
- **Climatology:** always forecast the long-run positive rate (for example "3% chance of an M flare in the next
  hour"). A constant never crosses a threshold differently on different rows, so its TSS is **exactly 0**. That
  makes it the zero point of the TSS scale.
- **Persistence:** forecast "yes" whenever `flare_in_progress_at_t = 1`. It exploits clustering, and it's a strong
  baseline for the nowcast (TSS 0.657).
- **One-feature rule:** forecast "yes" when `ratio_1m_bg` exceeds a threshold.

**Cross-validation (CV).** Estimating how well a setting works on data it wasn't trained on, by repeating
train-then-score on several splits. With a random split, rows from the future would train a model that is scored
on the past. That's leakage for time series.

**Rolling-origin (walk-forward) CV.** Folds respect time:

| Fold | Train on | Score on |
|---|---|---|
| 1 | Apr 9 – Jul 31 | August |
| 2 | Apr 9 – Aug 31 | September |
| 3 | Apr 9 – Sep 30 | October |
| 4 | Apr 9 – Oct 31 | November |

Each training window ends 120 minutes (the purge) before its scored month. The "origin" rolls forward and the
training window grows. All four folds lie *before* Dec–Jan, which stays reserved for thresholds.

**Hyperparameters tuned here.**
- **`n_estimators`:** the number of trees, 100 / 300 / 600.
- **`max_depth`:** how deep each tree may grow, 3 / 5.
- **`min_child_weight`:** the minimum evidence needed to split a node, 5 / 50.
- **`reg_lambda`:** L2 regularisation, which shrinks leaf values, 1 / 10.

**aucpr (average precision).** The area under the precision–recall curve. It suits rare events better than ROC AUC,
and it doesn't need a threshold.

**Trick: one fit, three tree counts.** XGBoost adds trees one by one, so a 600-tree model *contains* its first 100
and 300 trees. `predict_proba(..., iteration_range=(0, n))` scores those smaller models for free.

**Random seeds.** XGBoost samples rows and columns randomly (`subsample`, `colsample_bytree`), and the
QuantileTransformer subsamples too. Training with 3 seeds and reporting **mean ± std** shows how much a score
depends on luck in training. Here it's tiny: std 0.000–0.011.

**Operating point.** One choice of threshold, which fixes the trade-off between catching flares and raising false
alarms.
- **A = max TSS on calibration** (our main metric). It catches more flares but raises many false alarms for rare
  M flares.
- **B = max HSS on calibration.** It's stricter, with fewer false alarms, and usually a lower POD.

Both thresholds come from Dec–Jan. Validation only *measures* them.

**Bootstrap confidence interval.** We pretend validation is a sample from all possible days: resample its 114 days
*with replacement* 1,000 times, recompute TSS each time, and take the middle 95% of those values. We resample
**whole days**, not rows, because rows within a day are strongly linked (one active region, one flare's decay). The
same 1,000 day-samples are reused for every model, so the intervals are comparable. For multi-seed models we
average the seeds inside each resample, giving the interval of the *seed-mean* TSS.

**Overlapping intervals.** If two models' intervals overlap a lot, the data can't confidently say which is better.
For example ≥M in 60 min: LogReg 0.454 [0.28, 0.60] vs XGBoost 0.328 [0.21, 0.43].

**Re-using validation.** Every time we compare models on validation and pick a winner, the validation score becomes
a little optimistic. We have now done this twice (old labels and new labels). That's why the **test** period stays
sealed: it's the only fully unbiased score left.

## Tools used

| Tool | What it is | What it did here | Most useful commands |
|---|---|---|---|
| **XGBoost** | Gradient-boosted trees | CV grid plus final fits, no early stopping | `XGBClassifier(...).fit(X, y)`, `predict_proba(X, iteration_range=(0, n))` |
| **scikit-learn metrics** | Scoring functions | aucpr for CV | `average_precision_score(y, p)` |
| **numpy random Generator** | Reproducible random numbers | Day bootstrap | `np.random.default_rng(0).integers(0, n_days, size=(1000, n_days))`, `np.bincount`, `np.quantile` |
| **MLflow nested runs** | Parent/child runs | One parent run per target (CV table artifact) with 5 child runs (one per model) | `mlflow.start_run(nested=True)`, `mlflow.log_text(csv, "xgb_cv.csv")` |
| **DVC outs (cache: false)** | Git-tracked outputs | `reports/validation_table.md`, `reports/xgb_cv.csv` | `dvc repro`, `dvc metrics show` |

## Code walkthrough

### `src/models/train.py`

```python
def cv_folds(df, fold_months, purge_min):                                     # line 62
    for m in fold_months:
        lo = pd.Timestamp(m + "-01", tz="UTC")
        hi = lo + pd.offsets.MonthBegin(1)
        folds.append((df[df.index < lo - pd.Timedelta(minutes=purge_min)], df[(df.index >= lo) & (df.index < hi)], m))
```
Train on everything before the month (minus the purge gap); score on that month only.

```python
            m = make_xgb(mp["xgb"], {**g, "n_estimators": n_max}, ...).fit(tr[feats], ytr)
            for n in n_list:
                p = m.predict_proba(va[feats], iteration_range=(0, n))[:, 1]          # line 120
    best = {k: ... for k, v in summary.iloc[0][keys].items()}                          # line 126
```
- **Line 120:** score the 100-, 300- and 600-tree versions from one fit.
- **Line 126:** pick the setting with the best mean aucpr over the 4 months.

```python
    rate = float(yf.mean())                                                   # line 160
    ... blk(np.full(len(yc), rate), np.full(len(yv), rate), fixed=rate + 1e-12)
    ... blk(cal[FLAG]..., val[FLAG]..., fixed=0.5)
```
Climatology is a constant equal to the fit-period positive rate. Persistence is the activity flag with a fixed 0.5
threshold, so there's nothing to tune.

```python
        thr = fixed_threshold if fixed_threshold is not None else metrics.best_threshold(y_cal, s_cal, met)[0]   # line 135
        for subset, mask in (("all", np.ones(len(y_val), bool)), ("quiet", quiet)):                              # line 137
```
- **Line 135:** one threshold per operating point (`met` is `"tss"` for A, `"hss"` for B), always from calibration rows.
- **Line 137:** the same threshold is scored on all validation rows and on quiet-start rows.

```python
    for seed in mp["seeds"]:                                                  # line 172
        lr = make_logreg(mp["logreg"], seed).fit(fit[feats], yf)
        xg = make_xgb(mp["xgb"], xgb_params, seed, _pos_weight(yf)).fit(fit[feats], yf)
```
Three seeds per learner, with the CV-chosen XGBoost settings.

```python
        selected = max(candidates, key=lambda m: agg[m]["A"]["all"]["tss_mean"])   # line 255
```
Model selection: the highest mean validation TSS at operating point A among Rule, LogReg and XGBoost.

### `src/models/metrics.py`

```python
    return np.random.default_rng(seed).integers(0, n_days, size=(n_boot, n_days))   # line 94
    boot = np.mean([tss_from_counts(dc[idx].sum(axis=1)) for dc in day_counts_per_seed], axis=0)   # line 100
    return float(np.quantile(boot, a)), float(np.quantile(boot, 1 - a))              # line 102
```
- **Line 94:** 1,000 resamples × 114 day indices, with a fixed seed so results are reproducible.
- **Line 100:** for each resample, add up those days' TP/FP/FN/TN, compute each seed's TSS, then average over seeds.
- **Line 102:** the 2.5% and 97.5% quantiles form the 95% interval.

Per-day counts (`daily_counts`) are computed once with `np.bincount`, so 1,000 resamples take milliseconds.

### `src/models/report.py`
Builds `reports/validation_table.md`: TSS tables (all rows and quiet-start) and an operating-point table (POD, FAR,
TSS, HSS for A and B).

## Hands-on

Activate the venv and work from the project folder.

**1. Read the results table.** Open `reports/validation_table.md`.
*Expected:* nowcast XGBoost `0.726 ± 0.002 [0.71, 0.74]` beats persistence `0.657 [0.63, 0.68]`. For ≥M in 60 min,
LogReg is `0.454 ± 0.003 [0.28, 0.60]`. Do the LogReg and XGBoost intervals overlap for the M targets?

**2. Inspect the cross-validation.**
```
python -c "import pandas as pd; cv=pd.read_csv('reports/xgb_cv.csv'); print(cv[cv.target=='m_60m'].head(5).round(4))"
```
*Expected:* the best setting has a mean aucpr of about 0.062, with fold std about 0.038, and the top three differ
by less than 0.001. What does that tell you about how much the CV choice matters here?

**3. Compare operating points for one model.**
```
python -c "import json; m=json.load(open('reports/model_metrics.json')); s=m['targets']['m_120m']['models']['logreg']['summary']; [print(op, {k: round(s[op]['all'][k],2) for k in ('pod_mean','far_mean','tss_mean','hss_mean')}) for op in ('A','B')]"
```
*Expected:* A ≈ `pod 0.56, far 0.88, tss 0.38, hss 0.14` and B ≈ `pod 0.40, far 0.77, tss 0.34, hss 0.26`.
B gives fewer false alarms but warns of fewer flares.

**4. Build a bootstrap interval yourself (notebook).** Take `metrics.daily_counts` for any yes/no forecast on
validation, then:
- draw `metrics.bootstrap_indices(114, 1000, seed=0)`
- compute `metrics.tss_from_counts(dc[idx].sum(axis=1))`
- take the 2.5% and 97.5% quantiles

Change `seed=0` to `seed=1`: the interval should move by only about 0.01.

**5. Quiet-start vs all rows.** In the figure `docs/model_figures/val_skill.png`, compare the top and bottom panels.
*Expected:* persistence drops to exactly 0 on quiet-start rows. For the forecasts, LogReg and XGBoost hardly change.
Write one sentence on what that means.

**6. MLflow.**
```
mlflow ui --backend-store-uri sqlite:///mlflow.db
```
Open experiment **flare-models-v2**. *Expected:* 7 parent runs (one per target), each with 5 nested model runs (42
runs). Download `xgb_cv.csv` from a parent run's artifacts.

## Break it on purpose

Remove the seed variety and watch "± std" vanish.

1. In `params.yaml` under `models:`, change `seeds: [42, 43, 44]` to `seeds: [42]`.
2. `dvc status`: only `train` is listed.
3. Optional (about 15 minutes): `dvc repro`. Then `reports/validation_table.md` no longer shows a `± std` part for
   LogReg and XGBoost, because one seed has no spread. The bootstrap intervals barely change, because day-to-day
   variation, not seeds, is the main source of uncertainty.
4. Undo: `git checkout -- params.yaml reports docs/model_figures`, then `dvc repro` if you ran step 3, and confirm
   with `dvc status`.

## Check yourself

1. Why is climatology's TSS exactly 0, and why is it still useful to include?
2. In rolling-origin CV, why must the training window end before the scored month, and why add a purge gap?
3. Why do we resample whole days instead of individual rows in the bootstrap?
4. LogReg ≥M in 60 min: TSS 0.454 [0.28, 0.60]. XGBoost: 0.328 [0.21, 0.43]. Can you say LogReg is better? What would you say instead?
5. Validation has been used for model comparisons twice. Why does that make the test period more important?

## Questions to discuss with my tutor

1. The CV settings for M targets differ by less than 0.001 aucpr, far below the fold-to-fold spread (about 0.04).
   Is hyperparameter tuning worth it with this little data, or should we fix sensible defaults?
2. Operating point A or B? How would a space-weather forecaster choose: by cost of a miss vs a false alarm, by a
   maximum FAR, or by something else?
3. Our bootstrap treats days as independent, but active regions live for about two weeks. Would a block bootstrap
   by week give wider intervals, and which is more honest?

## Key numbers

**Validation TSS, operating point A, all rows:**

| Target | Climatology | Persistence | Rule | LogReg | XGBoost |
|---|---|---|---|---|---|
| nowcast | 0 | 0.657 | 0.634 | 0.678 | **0.726** [0.71, 0.74] |
| ≥C in 30 min | 0 | 0.016 | 0.034 | **0.196** [0.14, 0.25] | 0.151 |
| ≥C in 60 min | 0 | 0.013 | 0.031 | **0.194** [0.14, 0.25] | 0.192 |
| ≥C in 120 min | 0 | 0.026 | 0.032 | 0.263 | **0.263** [0.20, 0.33] |
| ≥M in 30 min | 0 | 0.108 | 0.050 | **0.478** [0.34, 0.58] | 0.423 |
| ≥M in 60 min | 0 | 0.089 | 0.139 | **0.454** [0.28, 0.60] | 0.328 |
| ≥M in 120 min | 0 | 0.076 | 0.113 | **0.382** [0.19, 0.55] | 0.342 |

**Other results:**
- **Quiet-start rows:** nowcast XGBoost 0.448 [0.43, 0.47]; ≥M in 30 min LogReg 0.475. The forecasts keep almost
  all their skill when the Sun isn't already flaring.
- **Seed std:** 0.000–0.011, much smaller than the bootstrap intervals (often ±0.1–0.2).
- **CV choices:**
  - nowcast: depth 5, 300 trees
  - ≥C in 30 min: depth 3, 600 trees, min_child_weight 50, lambda 10
  - ≥M in 30 min: depth 3, 100 trees
- **Operating point B:** fewer false alarms at lower POD. For example ≥M in 120 min LogReg: POD 0.56 → 0.40,
  FAR 0.88 → 0.77, HSS 0.14 → 0.26.
- **Run time:** CV tries 24 settings per target (8 regularisation combos × 3 tree counts) on 4 folds, giving 168 table rows over the 7 targets. The whole stage takes about 16 minutes. MLflow `flare-models-v2` has 42 runs.

---

<details>
<summary><b>Answers (spoiler — try first!)</b></summary>

1. A constant forecast is either always above or always below the threshold, so its hit rate equals its false-alarm
   rate (both 0 or both 1), and TSS = 0. It's the "no skill" reference point, and it shows that any positive TSS is
   real skill, not a property of the base rate.
2. Training on later data and scoring on earlier data uses the future, which is leakage. The purge gap removes rows
   whose label window (up to 120 min ahead) would reach into the scored month.
3. Rows within a day are strongly dependent (the same flare, the same active region). Resampling rows would pretend
   we have about 800k independent samples and give intervals that are far too narrow. Days are closer to
   independent units.
4. Not confidently: the intervals overlap substantially. Say "LogReg scored higher on validation, but the
   difference is within the day-to-day uncertainty."
5. Each comparison picks the winner on validation, so its validation score is slightly optimistic (selection bias),
   and the bias grows with each comparison. The test period has never influenced any choice, so it gives the only
   unbiased estimate.

</details>
