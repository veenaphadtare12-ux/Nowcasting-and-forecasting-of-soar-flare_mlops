# Lesson 04 — Labels and features: nowcast vs forecast, ok flags, 27 causal features at 10 s cadence

## What we built

We turned the cleaned light curve and the flare catalogue into a machine-learning table. Each row is one moment
in time, every 10 seconds. The *features* describe what the Sun looked like up to that moment (27 numbers). The
*labels* say whether a flare is happening now, or will start in the next 30, 60 or 120 minutes. Each label has an
`ok` flag that says whether we can trust it. The table is saved as three Parquet files, one per period.

## Why it matters

Think of a weather forecaster. They may only use today's and earlier measurements (the features) to predict
tomorrow, and they're graded on what actually happened tomorrow (the label). If the forecaster could peek at
tomorrow's newspaper while making the forecast, they would look brilliant in practice and fail in real life.
That peeking is called **data leakage**. This lesson is about building the table so peeking is impossible.

## Concepts

**Sample / row.** One moment `t` in time. We create one every 10 seconds (the **cadence**). The 1-second data is
averaged into 10-second bins first, which keeps the files small without losing flare shapes.

**Feature.** A number computed from data at or before `t`, for example "the mean count rate over the last 5 minutes".

**Label (target).** The answer we want the model to learn. We have two kinds:
- **Nowcast (`y_now`):** is a GOES-matched flare *in progress* at `t`? That means `onset ≤ t < end`.
- **Forecast (`y_c_{h}m`, `y_m_{h}m`):** will a GOES-matched flare of class ≥ C (or ≥ M) *start* in the window
  `(t, t + h]`, for h = 30, 60 or 120 minutes?

**Strictly after.** The forecast window is `(t, t+h]`. The round bracket means `t` itself is *excluded*: a flare
starting exactly at `t` does not count for the row at `t`. Otherwise the label would describe the present, not
the future.

**Only matched flares are positives.** A SoLEXS detection that GOES didn't list is never a positive. Its class
would be unknown, and it might be a false alarm.

**Causal feature.** A feature that uses only the past and present:
- **Trailing window:** "the last N rows up to now". This is pandas `rolling(N)`.
- **Centered window:** `center=True` looks forward as well. That's forbidden for features.
- **Shift:** `shift(+k)` looks *back* k rows, which is allowed. `shift(-k)` looks forward, which is forbidden.

**Right-closed bins.** The 10-second bin labelled `t` holds the seconds in `(t − 10 s, t]`, the ones that have
*already happened*. A left-labelled bin would carry data from the next 10 seconds: leakage.

**`ok` flags (label validity).** A forecast label is only meaningful if we could actually see the future window.
`ok_{h}m` is False when:
- the window `(t, t+h]` runs past the end of the row's period (that would leak into the next period); or
- less than 90% of that window has SoLEXS data (a flare could be hiding in the gap); or
- the window touches a day with no GOES report (2025-12-30 and 2025-12-31).

`ok_now` is False on those two no-GOES days. Training code must *filter* on these flags. It must not treat
"not ok" rows as negatives.

**Class imbalance.** Flares are rare. Only about 3% of tuning rows have an M-class flare starting within
60 minutes. A model that always says "no" would be 97% accurate and completely useless. That's why our project
rule says: report **TSS/HSS**, never accuracy alone.

## Tools used

| Tool | What it is | What it did here | Most useful commands |
|---|---|---|---|
| **pandas resample** | Groups time series into fixed bins | 1 s → 10 s right-closed bins | `s.resample("10s", label="right", closed="right").mean()` |
| **pandas rolling** | Trailing-window statistics | mean/max/std/slope over 1, 5, 15, 60 min | `s.rolling(30).mean()`, `.max()`, `.std()`, `.cov(t)`, `.quantile(0.2)` |
| **numpy searchsorted** | Fast "where would this value go in a sorted list?" | Counts flare onsets inside `(t, t+h]` for 2 million rows at once | `np.searchsorted(sorted_onsets, t, side="right")` |
| **Parquet + zstd** | Compressed columnar files | `dataset/{tune,val,test}.parquet` | `df.to_parquet(path, compression="zstd")`, `pd.read_parquet(path, columns=[...])` |

## Code walkthrough

### `src/features.py`

```python
    r = counts.resample(f"{cadence_s}s", label="right", closed="right")      # line 20
```
10-second bins that include their right edge and are named after it. This is the right-closed rule.

```python
    for w in windows_min:                                                     # line 36
        k = w * per_min
        roll = rate.rolling(k, min_periods=max(1, k // 2))                    # line 38
        f[f"mean_{w}m"] = roll.mean()
        f[f"max_{w}m"] = roll.max()
        if w >= 5:
            f[f"std_{w}m"] = roll.std()
            f[f"slope_{w}m"] = rate.rolling(k, min_periods=k // 2).cov(tsec) / tsec.rolling(k, min_periods=k // 2).var() * 60.0   # line 44
        f[f"valid_frac_{w}m"] = n.rolling(k, min_periods=1).sum() / (k * cadence_s)   # line 45
```
- **Line 36:** windows of 1, 5, 15 and 60 minutes (from `params.yaml`). With 6 rows per minute, the 5-min window is 30 rows.
- **Line 38:** a trailing window over the last `k` rows. `min_periods` lets it produce a value after a gap.
- **Line 44:** the least-squares slope, which is covariance(rate, time) ÷ variance(time). It's the trend in
  counts/s per minute; a rising flare gives a big positive slope.
- **Line 45:** how complete the window was, so the model knows when it's looking at partial data.

```python
    bg = rate.rolling(kb, min_periods=kb // 6).quantile(BG_QUANTILE)          # line 47
    f["ratio_1m_bg"] = f["mean_1m"] / bg.clip(lower=1.0)                      # line 50
    f["accel_5m"] = f["slope_5m"] - f["slope_5m"].shift(5 * per_min)          # line 55
```
- **Line 47:** the same trailing 60-min 20th-percentile background idea as the detector, computed again here.
  It's causal and doesn't use the detector's catalogue.
- **Line 50:** "how many times brighter than background". `clip(lower=1.0)` avoids dividing by zero.
- **Line 55:** acceleration = the change in slope versus 5 minutes *ago*. A positive shift only looks back.

### `src/labels.py`

```python
    lo = np.searchsorted(onsets_ns, t, side="right")                          # line 47
    hi = np.searchsorted(onsets_ns, t + h, side="right")                      # line 48
    return (hi > lo).astype(np.int8)                                          # line 49
```
- **Line 47:** the position after all onsets ≤ t. `side="right"` is what makes an onset exactly at `t` *not* count.
- **Line 48:** the position after all onsets ≤ t+h.
- **Line 49:** if the positions differ, at least one onset lies in `(t, t+h]`, so the label is 1.

```python
    inside = (t + h) <= _ns(period_end)                                       # line 59
    observed = n_valid >= min_valid_frac * horizon_min                        # line 64
        ok &= ~((t < d1) & (t + h >= d0))  # window touches a day without GOES truth   # line 69
```
The three reasons a label can be "not ok": it leaves the period, the window is under-observed, or it touches a
day with no GOES report.

### `src/dataset.py`

`build_all()` loops over cleaned days, adding the previous day's last 130 minutes as warm-up so the 60-minute
windows are full right after midnight. It then:
- keeps rows with at least 80% valid data in the last 5 minutes
- assigns each row to tune/val/test by timestamp
- adds labels
- writes one file per period

For the test period it deliberately writes **no label statistics** in the summary.

## Hands-on

Activate the venv and work from the project folder.

**1. Count features and labels.**
```
python -c "import pandas as pd; from src import dataset; t=pd.read_parquet('data/processed/dataset/tune.parquet'); f=dataset.feature_columns(t); print(t.shape, len(f)); print([c for c in t.columns if c not in f])"
```
*Expected:* `(1936953, 39) 27`, then the 12 non-feature columns: `y_now, ok_now`, `y_c_/y_m_/ok_` for 30, 60
and 120 min, and `period`.

**2. Watch labels change around a real flare.** The C5.3 flare on 2025-04-10 has its catalogue onset at 07:41.
```
python -c "import pandas as pd; t=pd.read_parquet('data/processed/dataset/tune.parquet', columns=['mean_1m','y_now','y_c_30m','y_m_30m','ok_30m']); print(t.loc['2025-04-10 07:40':'2025-04-10 07:44'].iloc[::6].round(1))"
```
*Expected:*
- `y_c_30m = 1` until 07:40:50, because the 07:41 onset is still in the future.
- At 07:41:00 `y_now` turns to 1 and `y_c_30m` drops to 0, because the onset is no longer strictly after `t`.
- From 07:43:00 `y_c_30m` is 1 again, because the *next* C flare (C2.7, onset 08:13) enters the 30-minute window.

Also notice that `mean_1m` is still about 20 counts/s at 07:41. The label turns on before the features show
much. That's the real difficulty of nowcasting.

**3. See why ok flags matter.**
```
python -c "import pandas as pd; t=pd.read_parquet('data/processed/dataset/tune.parquet', columns=['y_c_60m','ok_60m','ok_30m']); print(round(t.y_c_60m.mean(),4), round(t.loc[t.ok_60m,'y_c_60m'].mean(),4)); print(t.loc['2026-01-31 23:25':].iloc[::6][['ok_30m','ok_60m']])"
```
*Expected:* `0.2234 0.2255` (positive rate over all rows vs over ok rows only). At the very end of the tune period,
`ok_30m` turns False after 23:30, because the window would cross into val.

**4. Class imbalance.**
```
python -c "import pandas as pd; t=pd.read_parquet('data/processed/dataset/tune.parquet'); ok=t.ok_60m; print('now', round(t.loc[t.ok_now,'y_now'].mean(),3), 'C60', round(t.loc[ok,'y_c_60m'].mean(),3), 'M60', round(t.loc[ok,'y_m_60m'].mean(),3))"
```
*Expected:* `now 0.084 C60 0.226 M60 0.03`. What accuracy would an "always no M-flare" model get?

**5. Prove causality yourself (notebook).** Take one cleaned day, compute
`features.solexs_features(features.bin_counts(counts, 10), [1,5,15,60])` twice: once on the full day, once after
multiplying all counts after 12:00 by 10. Compare the rows up to 12:00 with `pd.testing.assert_frame_equal`.
*Expected:* no error (identical), while rows after 12:00 differ.

## Break it on purpose

Add a forbidden centered window and let the leakage tests catch it.

1. In `src/features.py` line 38, change `rate.rolling(k, min_periods=max(1, k // 2))` to
   `rate.rolling(k, min_periods=max(1, k // 2), center=True)`.
2. Run `pytest tests/test_leakage.py -q`.
3. *Expected:* `4 failed, 11 passed`. The three `test_features_unchanged_when_future_is_altered[...]` cases fail
   (the features now change when the future changes), and `test_no_centered_windows_or_negative_shifts_in_feature_code`
   fails (the code check finds `center=True`).
4. Undo: `git checkout -- src/features.py`, then rerun. Expected: `15 passed`.

## Check yourself

1. What is the difference between `y_now` and `y_c_30m`?
2. A flare starts exactly at 07:41:00. What is `y_c_30m` for the row at 07:41:00, and why?
3. Why does the 10-second bin labelled 12:00:10 contain seconds 12:00:01–12:00:10 and not 12:00:10–12:00:19?
4. Give two reasons why `ok_60m` can be False.
5. Why must training code drop rows with `ok = False` instead of treating them as label 0?

## Questions to discuss with my tutor

1. Neighbouring 10-second rows are almost identical. Does this autocorrelation make "1.9 million samples" look
   bigger than it really is, and how should that affect validation or metric confidence intervals?
2. Our labels come from our own detector matched to GOES. Missed flares become negative labels. How much label
   noise can a model tolerate, and could we use the GOES list directly as labels instead?
3. Is 10-second cadence right for a 30–120 minute forecast, or would 1-minute rows with longer feature windows be
   better? How would you decide experimentally?

## Key numbers

| What | tune | val | test |
|---|---|---|---|
| Rows (10 s cadence) | 1,936,953 | 816,920 | 792,482 |
| File size (Parquet, zstd) | 118.5 MB | 49.3 MB | 47.1 MB |
| Nowcast positive rate (ok rows) | 8.4% | 7.0% | not looked at |
| ≥C within 60 min (ok rows) | 22.6% | 19.2% | not looked at |
| ≥M within 60 min (ok rows) | 3.0% | 2.3% | not looked at |

- **Features:** 27, all causal (trailing windows of 1, 5, 15 and 60 min).
- **Labels:** 1 nowcast + 6 forecast (C and M × 30/60/120 min), plus 4 ok flags.
- **HEL1OS:** adds `hel_*` feature columns only when its data overlaps; currently it never does.

---

<details>
<summary><b>Answers (spoiler — try first!)</b></summary>

1. `y_now` says a matched flare is *in progress* at `t`. `y_c_30m` says a matched ≥C flare will *start* in `(t, t+30 min]`.
2. 0 (unless another qualifying flare starts within the next 30 minutes). The window `(t, t+h]` excludes `t`
   itself, so a flare starting at `t` is "now", not "future".
3. The bins are right-closed and right-labelled: the bin named 12:00:10 contains data that already exists at
   12:00:10. A bin holding 12:00:10–12:00:19 would let the row "see" 9 seconds of the future.
4. Any two of: the window `(t, t+60]` runs past the period end; less than 90% of the window has SoLEXS data; the
   window touches a day with no GOES report.
5. For those rows we don't *know* the answer: a flare could have happened unseen. Calling them 0 would teach the
   model wrong answers, and near period ends it would leak information across the split.

</details>
