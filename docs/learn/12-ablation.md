# Lesson 12 — Ablation: does adding hard X-rays help? (and how to say "we don't know")

## What we built

We retrained every model with the new HEL1OS features, then ran an **ablation**. On the rows where HEL1OS was
observing, the same models were trained three times:
- with only soft X-ray features (SoLEXS)
- with only hard X-ray features (HEL1OS)
- with both

We then compared their validation scores with intervals. For most targets the honest answer was "too few flares to
tell".

## Why it matters

To know whether a new ingredient improves a recipe, you bake the cake with and without it, and *everything else stays
the same*: oven, time, the same tasters. If you also changed the oven, you couldn't tell what made the difference.
An ablation is that controlled comparison: same rows, same model, same threshold rule, same seeds, same bootstrap.
Only the feature set changes. And if only three people tasted the cake, you shouldn't announce a winner.

## Concepts

**Ablation study.** Remove (or isolate) one component and measure the change. Here the component is a feature group:
soft, hard, or combined.

**Fair comparison = same rows.** HEL1OS covers 4.7% of tune+val rows (tune 4.0%, val 6.3%). Comparing "soft on all rows" with "hard on
HEL1OS rows" would mix two different questions. So every variant uses only `hel1os_available == 1` rows.

**Same threshold procedure, adapted.** Normally thresholds come from Dec–Jan, but no HEL1OS session falls there. The
ablation therefore fits on HEL1OS rows before Nov 2025 and picks thresholds on the Nov 2025 HEL1OS rows: the same
procedure (a later, held-out block of tune) on the available data.

**Positive episodes, not positive rows.** 10-s rows next to each other belong to the same flare. A run of positive
rows (with gaps of at most 60 s) counts as one *episode*. Episodes are the honest sample size.

**Statistical power.** The chance of detecting a real difference. With 12–17 positive episodes, intervals are so wide
(for example −0.02 to 0.57) that real differences would be invisible. We set a rule before looking: fewer than 30
validation episodes means "too few to conclude".

**Overlapping intervals.** If [0.31, 0.43] and [0.42, 0.48] barely touch, the difference is suggestive but not solid,
especially for one target, one model and 8 days.

## Tools used

| Tool | What it is | What it did here | Most useful commands |
|---|---|---|---|
| **scikit-learn / XGBoost** | Models | Same LogReg and XGBoost settings for all three feature sets | `make_logreg(...)`, `make_xgb(...)` (`src/models/train.py`) |
| **DVC** | Pipeline | `train` stage re-ran with the new dataset and `ablation.py` as a dependency | `dvc repro`, `dvc status` |
| **MLflow** | Tracking | Run `hel1os-ablation` with `ablation.json` as an artifact | `mlflow ui --backend-store-uri sqlite:///mlflow.db` |

## Code walkthrough (`src/models/ablation.py`)

```python
def feature_sets(feats):
    soft = [c for c in feats if not c.startswith("hx_") and c != "hel1os_available"]
    hard = [c for c in feats if c.startswith("hx_")]
    return {"soft": soft, "hard": hard, "combined": soft + hard}
```
`hel1os_available` is dropped because it's always 1 on these rows.

```python
    th = tune[tune["hel1os_available"] == 1]
    vh = val[val["hel1os_available"] == 1]
    fit_df = th[th.index < c0 - pd.Timedelta(minutes=mp["purge_min"])]
    cal_df = th[(th.index >= c0) & (th.index < c1)]
```
The same rows for every variant, with a purge gap before the calibration block.

```python
    gaps = np.diff(pos.as_unit("s").asi8) > gap_s
    return int(gaps.sum() + 1)
```
In `positive_episodes`, a new episode starts only after more than 60 s without a positive row.

```python
               "too_few_positives": bool(n_ep < ab["min_positive_episodes"]),
```
The 30-episode rule lives in `params.yaml` (`models.ablation.min_positive_episodes`), so it was fixed *before* seeing results.

## Hands-on

Activate the venv and work from the project folder.

**1. Read the ablation table.** Open `reports/validation_table.md` and scroll to "HEL1OS ablation".
*Expected:* `⚠ too few` on `c_120m` and all `m_*` rows. Which feature set wins for `c_60m` with logistic regression?

**2. Count episodes yourself.**
```
python -c "import json; a=json.load(open('reports/model_metrics.json'))['ablation']; [print(k, r['val_positive_episodes'], r['too_few_positives']) for k, r in a['targets'].items()]"
```
*Expected:* `now 69 False`, `c_30m 60 False`, `c_60m 44 False`, `c_120m 17 True`, `m_30m 15 True`, `m_60m 13 True`, `m_120m 12 True`.
Why does ≥C 120 min have fewer episodes than ≥C 30 min? *Hint:* long windows merge neighbouring flares into one run.

**3. Compare the quiet-start nowcast.**
```
python -c "import json; t=json.load(open('reports/model_metrics.json'))['ablation']['targets']['now']['models']['logreg']; [print(fs, round(t[fs]['A']['quiet']['tss_mean'],3), round(t[fs]['A']['quiet']['tss_ci_low'],2), round(t[fs]['A']['quiet']['tss_ci_high'],2)) for fs in ('soft','hard','combined')]"
```
*Expected:* soft 0.366 [0.31, 0.43], hard 0.336 [0.27, 0.40], combined 0.447 [0.42, 0.48]. Would you call this a result or a hint?

## Break it on purpose

Lower the bar and watch over-claiming appear.

1. In `params.yaml`, set `models.ablation.min_positive_episodes: 10`.
2. Run `dvc status`: *expected*, only `train` is listed. Don't re-run; just reason about the outcome.
3. With a bar of 10, every M target would lose its ⚠ and look "conclusive", although its intervals still span
   −0.07 to 0.57. The rule protects you from yourself.
4. Undo: `git checkout -- params.yaml`, then `dvc status` → up to date.

## Check yourself

1. Why must all three feature sets use exactly the same rows?
2. Why were ablation thresholds chosen on Nov 2025 instead of Dec–Jan?
3. What is a "positive episode", and why count episodes instead of rows?
4. Why was the "too few" threshold written into `params.yaml` before the results were known?
5. What *can* we honestly claim about hard X-rays from this ablation?

## Questions to discuss with my tutor

1. How many HEL1OS hours would we need to detect a TSS difference of 0.1 for ≥M forecasts? How would you estimate that?
2. Should HEL1OS models be trained only on HEL1OS rows (as here) or on all rows with missing values (as in the main models)?
3. The quiet-start nowcast gain is physically plausible (hard X-rays peak early). How would you test this hypothesis properly?

## Key numbers

| What | Value |
|---|---|
| Main models with 44 features (val TSS) | nowcast 0.727; ≥C 0.208 / 0.208 / 0.270; ≥M 0.468 / 0.468 / 0.388. All changes vs no-HEL1OS are inside the intervals |
| Ablation rows | fit 51,753; calibration 25,870 (Nov 2025); validation 51,667 (8 days) |
| Validation positive episodes | now 69; ≥C 60 / 44 / 17; ≥M 15 / 13 / 12 |
| Only visible gain | quiet-start nowcast, LogReg: combined 0.45 [0.42, 0.48] vs soft 0.37 [0.31, 0.43] |
| Hard X-rays alone, ≥C forecasts | TSS about 0.00–0.05: no skill |

---

<details>
<summary><b>Answers (spoiler — try first!)</b></summary>

1. Otherwise differences could come from *which rows* are scored (for example busier days), not from the features.
2. No HEL1OS session falls in Dec–Jan, so there would be no rows to choose thresholds on. Nov 2025 is the latest
   held-out block of tune with HEL1OS data.
3. A run of positive rows belonging to one flare situation. Neighbouring 10-s rows are not independent, so episodes
   are the real sample size.
4. Choosing the bar after seeing the results lets you move it to make results look significant. Fixing it first
   keeps the conclusion honest.
5. Hard X-rays alone don't forecast ≥C flares. Combined features don't beat SoLEXS for ≥C. There's a hint that they
   help the quiet-start nowcast. Nothing can be said about M flares: too few events.

</details>
