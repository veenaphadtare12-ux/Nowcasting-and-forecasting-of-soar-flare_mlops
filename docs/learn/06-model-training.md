# Lesson 06 — Model training: time splits, three models, TSS/HSS, thresholds, MLflow, and a DVC train stage

> **Update (lesson 08):** the training stage has since been rebuilt. XGBoost now uses rolling-origin
> cross-validation instead of early stopping on Dec–Jan; climatology and persistence baselines, 3 seeds,
> two operating points and bootstrap intervals were added; and forecast labels now come from GOES directly
> (lesson 07). The concepts here (time split, purge, thresholds, TSS/HSS) still apply, but the numbers and
> some code lines below describe the first version. For current results see `reports/validation_table.md`.

## What we built

We trained three kinds of model for each of our 7 targets (1 nowcast + 6 forecasts):
- a one-feature rule
- logistic regression
- XGBoost

Every model is fitted on the first part of the tuning period. Its alert threshold is chosen on the last two
months of the tuning period. Then it is scored once on the validation period with **TSS** and **HSS**. All 21
runs go to MLflow, and the whole step is a new DVC stage called `train`. The test period is never opened.

## Why it matters

Think of training for an exam with past papers:
- You study from old papers: the **fit** part.
- You take one practice paper to decide how confident you must be before writing an answer: the **calibration**
  part, where the threshold is chosen.
- You sit a mock exam you've never seen: **validation**, used to pick the best study method.
- The real exam stays sealed until the end: **test**.

If you peek at the real exam to decide how to study, your mock score lies to you. Every rule in this lesson keeps
those papers separate.

## Concepts

**Chronological split with a purge gap.** The tuning period is cut in time at 2025-12-01:
- **fit:** 2025-04-09 to 2025-11-30 (minus the purge gap)
- **calibration:** 2025-12-01 to 2026-01-31

Rows in the last 120 minutes before the cut are dropped (the **purge**). Their 120-minute forecast window would
reach into the calibration months, so their labels would carry information from the part we score on.

**Stride (thinning).** Neighbouring 10-second rows are almost identical. Training on every 6th row (one per minute)
gives 248k fit rows instead of 1.49M: about 6× faster, with very little lost.

**Model types.**
- **One-feature rule.** "Alert if the 1-minute rate is more than X times the background." It's the simplest
  sensible baseline; a model that can't beat it isn't worth its complexity.
- **Logistic regression.** It weighs every feature, adds them up and squashes the sum into a probability between
  0 and 1. It's simple, fast and hard to overfit.
- **XGBoost (gradient-boosted trees).** It builds many small decision trees one after another, each fixing the
  previous ones' mistakes. It's powerful and handles missing values itself, but it can overfit.

**Preprocessing pipeline (logistic regression only).** Two steps before the model:
- `SimpleImputer`: fills the few NaNs with the median.
- `QuantileTransformer`: reshapes each feature to a bell curve, so very bright flares don't dominate.

Both are fitted on fit rows only, inside a scikit-learn `Pipeline`.

**Class imbalance.** Only 1–4% of rows have an M flare coming. Without correction, a model learns "always say no".
- `class_weight="balanced"` (logistic regression) makes each missed flare count more.
- `scale_pos_weight = negatives / positives` does the same for XGBoost.

**Early stopping.** XGBoost keeps adding trees while the calibration score improves, and stops after 100 rounds
without improvement. It's a guard against overfitting. But with few positives in the calibration months it can
stop *very* early (after 1 tree for ≥M in 30 min). We saw exactly that.

**Probability → yes/no alert.** Models give a probability. An alert needs a **threshold** ("alert if p ≥ 0.46").
We choose the threshold that maximises TSS on the calibration part, then freeze it for validation.

**Contingency table and skill scores.**

| | flare happened | no flare |
|---|---|---|
| **alert** | TP (hit) | FP (false alarm) |
| **no alert** | FN (miss) | TN (correct quiet) |

- **POD (probability of detection)** = TP / (TP + FN): the share of flares we warned about.
- **FAR (false alarm ratio)** = FP / (TP + FP): the share of alerts that were wrong.
- **TSS** = POD − FP / (FP + TN), the hit rate minus the false-alarm *rate*. It's 0 for "always no" or random
  guessing, 1 for perfect, and it doesn't depend on how rare flares are. That's why space-weather papers use it.
- **HSS:** improvement over random chance, given how often you say yes. It *does* punish many false alarms when
  events are rare.
- **Accuracy trap:** "never a flare" is 98.7% accurate for ≥M in 30 min and has TSS = 0. That's why accuracy is
  never reported alone.

**Model selection.** For each target we keep the model with the best *validation* TSS. That is what validation is
for. The test period is reserved for one final, honest score.

## Tools used

| Tool | What it is | What it did here | Most useful commands |
|---|---|---|---|
| **scikit-learn** | Classic ML library | Logistic regression, preprocessing pipeline, AUC/AP/Brier metrics | `Pipeline([...])`, `.fit(X, y)`, `.predict_proba(X)[:, 1]`, `roc_auc_score`, `average_precision_score` |
| **XGBoost** | Gradient-boosted trees | The tree models with early stopping | `XGBClassifier(...)`, `.fit(X, y, eval_set=[(Xc, yc)])`, `.best_iteration`, `.save_model("m.json")`, `.load_model(...)` |
| **joblib** | Saves Python objects to disk | Stores the logistic-regression pipelines | `joblib.dump(obj, path)`, `joblib.load(path)` |
| **MLflow** | Experiment tracking | Experiment `flare-models`: one run per target × model with params, cal/val metrics, model file, feature importance | `mlflow ui --backend-store-uri sqlite:///mlflow.db`, `mlflow.start_run`, `log_params`, `log_metrics`, `log_artifact` |
| **DVC** | Pipeline + data versioning | New `train` stage; `models/` is cached | `dvc repro train`, `dvc metrics show`, `dvc params diff` |

## Code walkthrough

### `src/models/train.py`

```python
def load_period(name: str) -> pd.DataFrame:                                   # line 40
    if name not in ALLOWED_PERIODS:
        raise ValueError(f"training code may not read the '{name}' period")   # line 43
```
A hard guard: only `tune` and `val` can be loaded. A test checks that `load_period("test")` fails.

```python
    fit = df[df.index < cut - pd.Timedelta(minutes=purge_min)]                # line 50
    cal = df[df.index >= cut]                                                 # line 51
```
The chronological split with the 120-minute purge gap.

```python
        d = d.iloc[::stride]                                                  # line 59
```
Every 6th row, only for *fitting*. Calibration and validation use every row.

```python
        ("scale", QuantileTransformer(n_quantiles=1000, output_distribution="normal", ...)),   # line 66
        ("clf", LogisticRegression(C=cfg["C"], max_iter=cfg["max_iter"], class_weight="balanced")),   # line 67
```
Preprocessing and the model live in one Pipeline, so the scaler is fitted only on fit rows and re-used
unchanged on calibration and validation rows. No leakage from later data into the scaling.

```python
    pos_weight = float((yf == 0).sum() / max((yf == 1).sum(), 1))             # line 108
        early_stopping_rounds=cfg["early_stopping_rounds"], eval_metric="aucpr", tree_method="hist",   # line 75
```
Imbalance correction for XGBoost, plus early stopping watched on precision–recall AUC.

```python
    thr, _ = metrics.best_threshold(yc, pc)                                   # line 112
        best = max(res, key=lambda r: r["val"]["tss"])                        # line 169
```
- **Line 112:** the threshold comes from the **calibration** part (`yc`, `pc`), never from validation.
- **Line 169:** model selection on validation TSS.

### `src/models/metrics.py`

```python
    order = np.argsort(-s, kind="mergesort")                                  # line 42
    tp = np.cumsum(y_sorted); fp = np.cumsum(~y_sorted)
    last = np.r_[np.nonzero(np.diff(s_sorted))[0], len(s_sorted) - 1]        # line 46
        val = tp / max(P, 1) - fp / max(N, 1)                                 # line 51
```
- **Line 42:** sort the scores from high to low.
- Walking down that list, the running count of true and false positives *is* the contingency table for every
  possible threshold at once.
- **Line 46:** keep one point per distinct score, so tied scores aren't split.
- **Line 51:** TSS at every threshold; take the maximum. A test compares this against brute force.

### `dvc.yaml` → stage `train`

It depends on the model code and `data/processed/dataset`. Its params are the `models` and `periods` sections.
Its outputs are `models/` (cached), `docs/model_figures/` and `reports/model_metrics.json` (in git).

## Hands-on

Activate the venv and work from the project folder.

**1. Read the results table.**
```
python -c "import json; m=json.load(open('reports/model_metrics.json')); [print(t, d['selected'], round(d[d['selected']]['val']['tss'],3), round(d[d['selected']]['val']['hss'],3)) for t,d in m['targets'].items()]"
```
*Expected:* `now xgb 0.722 0.515`, `c_30m logreg 0.181 0.106`, … `m_30m logreg 0.477 0.045`. Then open
`docs/model_figures/val_skill.png` and find the same numbers in the bars.

**2. Re-score a saved model yourself.**
```
python
>>> import json, pandas as pd, xgboost as xgb
>>> from src import dataset
>>> from src.models import metrics
>>> v = pd.read_parquet('data/processed/dataset/val.parquet'); ok = v[v.ok_now]
>>> m = xgb.XGBClassifier(); m.load_model('models/now_xgb.json')
>>> thr = json.load(open('models/thresholds.json'))['now']['xgb']
>>> p = m.predict_proba(ok[dataset.feature_columns(v)])[:, 1]
>>> round(metrics.evaluate(ok.y_now.values, p, thr)['tss'], 3)
```
*Expected:* `0.722`, the same as the report. That proves the saved model plus threshold reproduce the result.

**3. The accuracy trap.** In the same session:
```
>>> import numpy as np; okm = v[v.ok_30m]
>>> metrics.evaluate(okm.y_m_30m.values, np.zeros(len(okm)), 0.5)
```
*Expected:* `accuracy` ≈ 0.987 and `tss` = 0.0. Write one sentence for your review explaining this.

**4. Explore MLflow.**
```
mlflow ui --backend-store-uri sqlite:///mlflow.db
```
In http://127.0.0.1:5000 open experiment **flare-models**. Each pipeline run adds 21 runs; you'll see more than 21
because the pipeline ran several times while it was being built. Use the *Compare* button on the three `m_60m-*`
runs and compare `val_tss`, `val_far` and `cal_tss`.

**5. Calibration vs validation.** In `reports/model_metrics.json`, compare `cal.tss` with `val.tss` for the M
targets. *Expected:* validation is *higher* (for example 0.226 → 0.477 for `m_30m` logreg). *Hint:* how many M
flares were there in Dec–Jan versus Feb–May?

**6. Run only the model tests.**
```
pytest tests/test_models.py -v
```
*Expected:* 6 passed, including `test_training_refuses_the_test_period`.

## Break it on purpose

Train on far less data and watch DVC re-run only the train stage.

1. In `params.yaml` under `models:`, change `train_stride: 6` to `train_stride: 60` (one row every 10 minutes).
2. `dvc status`: *expected:* only `train` is listed (`params.yaml: modified: models`).
3. `dvc repro`: *expected:* every other stage says `didn't change, skipping`, and only `Running stage 'train'`
   runs (about 2 minutes). Then compare with `git diff reports/model_metrics.json` or run exercise 1 again. The
   scores change, mostly for the rare M targets.
4. Undo: `git checkout -- params.yaml reports docs/model_figures`, then `dvc repro` (re-runs train) and check with
   `dvc status` → `Data and pipelines are up to date.`

## Check yourself

1. Why do we drop the last 120 minutes before 2025-12-01 from the fit rows?
2. The threshold is chosen on the calibration months, not on validation. What would go wrong otherwise?
3. A model has POD 0.74 and FAR 0.96 for ≥M in 30 min. Explain both numbers to a non-expert.
4. Why can TSS be high (0.48) while HSS is low (0.045) for the same forecast?
5. Why does XGBoost lose to logistic regression on M-class targets here, while it wins the nowcast?

## Questions to discuss with my tutor

1. We pick the threshold that maximises TSS, which produces many false alarms for rare M flares. For a real
   operator, what threshold rule makes more sense (for example a fixed FAR, or a cost ratio of miss vs false
   alarm), and should it differ per target?
2. The calibration months (Dec–Jan) had only 27 M-class-or-stronger flares, so early stopping and thresholds are
   noisy. Would rolling-origin (walk-forward) validation be better, and how would you keep it leak-free?
3. Flares cluster: one active region produces many flares within days. Our rows are not independent. How would you
   put confidence intervals on TSS (for example a block bootstrap by day)?

## Key numbers

**Validation scores (all three models):**

| Target | Rule TSS | LogReg TSS | XGB TSS | Selected | Val TSS | Val HSS | POD | FAR |
|---|---|---|---|---|---|---|---|---|
| nowcast | 0.634 | 0.678 | **0.722** | XGB | 0.722 | 0.515 | 0.80 | 0.57 |
| ≥C in 30 min | 0.021 | **0.181** | 0.162 | LogReg | 0.181 | 0.106 | 0.43 | 0.83 |
| ≥C in 60 min | 0.026 | **0.177** | 0.173 | LogReg | 0.177 | 0.159 | 0.39 | 0.70 |
| ≥C in 120 min | 0.042 | 0.211 | **0.233** | XGB | 0.233 | 0.248 | 0.41 | 0.47 |
| ≥M in 30 min | 0.040 | **0.477** | 0.314 | LogReg | 0.477 | 0.045 | 0.74 | 0.96 |
| ≥M in 60 min | 0.136 | **0.426** | 0.353 | LogReg | 0.426 | 0.097 | 0.60 | 0.92 |
| ≥M in 120 min | 0.113 | **0.378** | 0.329 | LogReg | 0.378 | 0.144 | 0.54 | 0.88 |

**Training setup:**
- **Fit rows:** 247,800 (stride 6), from 2025-04-09 to 2025-11-30 21:59. Calibration: 2025-12-01 to 2026-01-31.
  Validation: 2026-02-01 to 2026-05-31.
- **XGBoost early stopping:** best iterations of 52 (nowcast), 36–85 (C targets) and 0–24 (M targets). It stops
  very early on M because the calibration months are thin.
- **Top nowcast features (XGBoost gain):** `excess_1m` 45%, `ratio_1m_bg` 17%, `ratio_1m_60m` 8%.
- **Top ≥M-in-60-min features:** `mean_1m`, `rate`, `bg_60m`. A brighter Sun means more M flares soon.
- **Saved models:** 14 files, 7.5 MB. One training run takes about 3 minutes.

---

<details>
<summary><b>Answers (spoiler — try first!)</b></summary>

1. Their 120-minute forecast windows end inside the calibration months. Keeping them would let the fit part
   "know" about flares that the calibration part is supposed to judge independently.
2. The threshold would be tuned on the very data used to score the model, so the validation TSS would be
   optimistically biased. Validation would no longer be an honest check.
3. POD 0.74: we warned before 74% of the M-flare windows. FAR 0.96: 96% of our alerts were not followed by an M
   flare, so only about 1 in 25 alerts was "real".
4. TSS divides false alarms by *all* quiet rows (a huge number, so the false-alarm rate stays small). HSS compares
   against chance given how often we alert, and with rare events many alerts drag it down. Same table, different
   denominators.
5. The nowcast has thousands of positive examples and a clear signal (the flare is visible right now), which trees
   exploit well. M-class forecasts have few positives, and the calibration months were thin, so XGBoost
   early-stopped after 0–24 trees and couldn't learn much. The simpler logistic regression generalises better
   with little data.

</details>
