# Lesson 03 — Flare detection: rolling background, noise, GOES-style onset/end, GOES matching, tuning in MLflow

## What we built

We built an automatic flare detector for the SoLEXS light curve. It works on 1-minute averages. It decides when a
flare starts and ends using the same rules NOAA uses for the GOES satellites. Every detection is then checked
against NOAA's official flare list, and only that list gives a flare its class (B, C, M, X). Finally, we tested
300 combinations of detector settings on the tuning period only and recorded every trial in MLflow.

## Why it matters

Our models need *labels*: "was there a flare at this time?" A smoke alarm is a good comparison. Too sensitive, and
it goes off every time you make toast (false alarms, low precision). Not sensitive enough, and it stays quiet
during a small fire (misses, low recall). Tuning the detector means choosing how sensitive the alarm is, and
checking it against a trusted record of real fires (the NOAA GOES list) instead of our own guess.

The first detector had real problems:
- Some "flares" lasted up to 15 hours (218 events over 2 h).
- Onsets were often an hour early.
- Separate flares were merged into one.

The new detector fixed these.

## Concepts

**Minute means.** We average the 1-second counts in each minute. This reduces noise and matches GOES's 1-minute
cadence. A minute with fewer than 30 valid seconds becomes NaN (missing).

**Background.** The "quiet Sun" level that a flare sits on. It changes slowly over hours.

**Rolling (trailing) window.** A calculation over the last *N* points only: "the last 60 minutes up to now".
*Trailing* means it never looks into the future; a *centered* window would look 30 minutes ahead, which is
cheating for anything a live system must compute.

**Quantile.** The 0.2 quantile (20th percentile) is the value that 20% of the data lies below. We use the
20th percentile of the last 60 minutes as background. A short flare only pushes up the *high* values, so a low
quantile ignores it. That makes this a **robust** estimate: it isn't fooled by spikes.

**Noise and the threshold.**
- **Counting noise:** X-ray counts follow Poisson statistics, so the noise of an average of 60 one-second
  samples is about √(bg / 60). That's the `threshold_sigma * sqrt(bg/60)` part of the threshold.
- **MAD (Median Absolute Deviation):** another common robust noise estimate. You take the median of
  |x − median(x)|, and 1.4826 × MAD estimates the standard deviation even when spikes are present. **Our
  detector does not use MAD.** It uses the Poisson formula above, plus two practical floors.
- **The trigger:** a minute triggers when `minute − background > max(5·√(bg/60), 1.0·bg, 12 counts/s)`.
  At a background of 20 counts/s the threshold is 20, so counts must at least double.

**GOES-style onset.** NOAA defines a flare start as the first minute of a run of 4 minutes, each brighter than
the one before (3 increases), where the last is at least 1.4× the first. After a trigger we walk *backwards*
along the strictly increasing run to find where it began. That point is the onset.

**GOES-style end.** A flare ends when the flux has decayed halfway back to the pre-flare background (or below the
threshold). This must hold for 2 minutes in a row, so a single noisy minute doesn't end it.

**Frozen background.** While a flare is active, the background is held at its value just before the onset.
Otherwise the rolling background would rise with the flare and the "end" would be judged against a moving target.

**Splitting merged flares.** If the light curve dips by at least 30% between two peaks, it's treated as two flares.
We find peaks with `scipy.signal.find_peaks` using **prominence**: how far a peak stands above the lowest point
between it and a higher neighbour.

**Duration cap.** No event may exceed 3 hours. Events that hit the cap are flagged and counted. These are usually
background level shifts, not flares.

**Causal vs catalogue.** The *trigger* uses only data up to that minute: it is causal. The onset, peak and end use
the finished event (you can't know the end until it has happened), so they belong to the offline *catalogue*.
Catalogue values may be used for labels, never as model inputs.

**GOES cross-match.** SoLEXS measures counts, not GOES's W/m², so we must never assign a class from counts. A
detection is "matched" when its `[onset, end]` overlaps a GOES flare's `[begin − 5 min, end + 5 min]`. Its class
is the strongest overlapping GOES flare.

**Precision and recall** (with GOES as the truth):
- **Precision (match rate):** of the flares *we* detected, what share are in the GOES list?
- **Recall:** of the GOES flares SoLEXS actually observed, what share did we detect?
- **F1 = 2PR / (P + R):** one number that is only high when *both* are high.

**Hyperparameter tuning / grid search.** We try every combination from a list of settings (a "grid"), score each,
and keep the best. We do this **only on the tuning period**. Validation is used once afterwards as an honest check,
and the test period is never touched.

**Experiment tracking.** Saving every trial's settings and results so you can compare, reproduce and explain
choices later. MLflow does this for us.

## Tools used

| Tool | What it is | What it did here | Most useful commands |
|---|---|---|---|
| **pandas rolling** | Moving-window calculations | Trailing 60-min background | `s.rolling(60, min_periods=10).quantile(0.2)` |
| **scipy.signal** | Signal-processing library | Peak finding for splitting | `find_peaks(x, prominence=p)` |
| **MLflow** | Experiment tracking | Logged 2 tuning runs (108 and 300 trials) to `mlflow.db` | `mlflow ui --backend-store-uri sqlite:///mlflow.db`, `mlflow.start_run()`, `mlflow.log_params()`, `mlflow.log_metrics()` |
| **concurrent.futures** | Parallel execution in Python | Ran 6 trials at a time | `ProcessPoolExecutor(6).map(fn, items)` |
| **NOAA SWPC event reports** | Official daily flare lists | Ground truth for matching | downloaded by `python -m src.pipeline fetch_goes` |

## Code walkthrough

### `src/detection/detector.py`

```python
def trailing_background(m, window_min, q):                                    # line 74
    return m.rolling(window_min, min_periods=max(10, window_min // 6)).quantile(q)
```
The rolling 20th percentile of the last 60 minutes. `rolling()` is trailing by default; there's no `center=True`.

```python
def _threshold(bg, s):                                                        # line 79
    return max(s.threshold_sigma * np.sqrt(max(bg, 1.0) / 60.0), s.min_excess_frac * bg, s.min_excess_abs)
```
The trigger level: the largest of the noise rule, the "must double" rule (frac = 1.0) and the 12 counts/s floor.

```python
    while j - 1 >= lo and np.isfinite(mv[j - 1]) and mv[j] > mv[j - 1]:      # line 93
        j -= 1
```
`_rise_start`: walk back while each minute is strictly brighter than the one before it. Where the walk stops
is the onset.

```python
        if not (np.isfinite(mv[k]) and np.isfinite(bv[k])) or mv[k] - bv[k] <= _threshold(bv[k], s):   # line 122
            k += 1; continue
        st, steps = _rise_start(mv, k, s)                                     # line 125
        ratio_ok = mv[k] / max(mv[st], 1e-9) >= s.min_rise_ratio              # line 126
        if not ((steps >= s.rise_steps and ratio_ok) or impulsive):           # line 128
```
- **Line 122:** skip minutes that are missing or not far enough above background.
- **Lines 125–128:** a trigger only becomes an event if the rise was sustained (≥ 3 increases) and big enough
  (≥ 1.4×). This rejects noise blips.

```python
        bg0 = bv[st - 1] if st > 0 and np.isfinite(bv[st - 1]) else bv[st]  # line 132
            elif j > pk and (v <= bg0 + s.end_halfway_frac * (P - bg0) or v <= bg0 + thr0):   # line 148
                below += 1
                if below >= s.end_confirm_min:                                # line 151
                    end = first; break
```
- **Line 132:** the background is *frozen* at the minute before the onset.
- **Line 148:** after the peak, check "halfway back to background" or "below threshold".
- **Line 151:** only end after 2 consecutive qualifying minutes. The end time is the first of them.

```python
        cuts = _split(mv, st, end, bg0, thr0, s)                              # line 160
            hit_cap = (end_t - onset_t).total_seconds() > s.max_duration_s    # line 169
```
Split at deep dips, then apply the 3-hour cap and record whether it was hit.

### `src/detection/matching.py`

```python
            hit = np.where((gb <= ee[k]) & (ge >= eo[k]))[0]                  # line 43
                ev.at[k, "goes_class"] = g.at[hit[np.argmax(flux[hit])], "goes_class"]   # line 47
```
- **Line 43:** the interval-overlap test. GOES begins before our end, and GOES ends after our onset.
- **Line 47:** the class comes from the **strongest** overlapping GOES flare. It never comes from our counts.

### `src/detection/tune.py`

```python
    m = m[(m.index > lo) & (m.index <= hi)]                                   # line 31
    assert m.index.min() > lo and m.index.max() <= hi, "tuning must only see the tune period"
...
    f1 = 2 * p * rec / (p + rec) if p + rec else 0.0                          # line 43
    return f1 - cfg["penalty_long_event"] * frac_long - cfg["penalty_onset_per_min"] * onset   # line 45
```
- **Line 31:** the data is cut to the tuning period *before* anything else, and the assert proves it.
- **Lines 43–45:** score = F1(match rate, C-and-above recall), minus a penalty for events longer than 2 h and a
  small penalty for onset error.

## Hands-on

Activate the venv and work from the project folder.

**1. Look at one day's catalogue.**
```
python -c "import pandas as pd; e=pd.read_parquet('data/processed/events.parquet'); d=e[e.onset.dt.strftime('%Y-%m-%d')=='2025-04-10']; print(len(d), d.is_goes_matched.sum()); print(d[['onset','end','excess_counts_s','goes_class']])"
```
*Expected:* `12 7`: 12 detections, 7 matched to GOES (C2.3, C3.2, C3.1, C5.3, C2.7, C1.5, C3.7). The 5
unmatched ones have smaller excess. Are they false alarms, or flares too small for the GOES list?

**2. Change the sensitivity in a Python session (no files edited).**
```
python
>>> import pandas as pd
>>> from src import config
>>> from src.detection import detector
>>> m = pd.read_parquet('data/processed/solexs_minute.parquet')['m']['2025-04-09 22:00':'2025-04-11 00:00']
>>> P = config.load_params()['flare_detection']
>>> for ov in ({}, {'min_excess_abs': 5.0, 'min_excess_frac': 0.5}):
...     ev = detector.detect_series(m, detector.DetectorSettings.from_params(P, **ov))
...     print(ov, (ev.onset.dt.strftime('%Y-%m-%d') == '2025-04-10').sum())
```
*Expected:* `{} 12` and the more sensitive setting gives `15`. Three more detections, but (if you match them
against GOES) no extra GOES flares. That's lower precision for no recall gain on this day.

**3. Open the tuning experiments in MLflow.**
```
mlflow ui --backend-store-uri sqlite:///mlflow.db
```
Open http://127.0.0.1:5000 → experiment **detector-tuning**. *Expected:* two parent runs (the first 108-trial
grid and the widened 300-trial grid) with nested trial runs, 410 runs in total. Sort the trials by `score`.
Stop the server with Ctrl+C.

**4. Find the trade-off in the results table.**
```
python -c "import pandas as pd; t=pd.read_csv('reports/tuning_results.csv'); print(t.head(3)[['min_excess_frac','min_excess_abs','score','match_rate_all','recall_C_plus']]); print(t.sort_values('recall_C_plus').tail(1)[['min_excess_frac','min_excess_abs','score','match_rate_all','recall_C_plus']])"
```
*Expected:* the best score is about 0.799, with match rate 0.76 and C+ recall 0.865. The highest-recall row
reaches recall about 0.945 but a match rate of only about 0.56, so its score is lower.

**5. Compute F1 yourself.** Using the best row (P = 0.762, R = 0.865), work out `2*P*R/(P+R)` on paper, then
check with Python. *Expected:* about 0.810. The score is 0.799 because the penalties are subtracted.

**6. Read the before/after figure.** Open `docs/figures/before_after_examples.png`. For each of the 6 panels,
write one sentence: what did the legacy detector (orange) do wrong, and did the new one (blue) fix it? *Hint:*
panel 4 shows the price we paid.

## Break it on purpose

Demand an unrealistically long rise and watch recall collapse. Do this in a Python session; no files change.

1. Repeat exercise 2 with `{'rise_steps': 10}` (10 consecutive increases).
2. *Expected:* only **5** events on 2025-04-10 instead of 12, and only **2** of them match GOES. Most real flares
   rise for fewer than 10 straight minutes.
3. Undo: just exit Python. `params.yaml` was never touched; check with `git status`.

## Check yourself

1. Why is the background a *low quantile of a trailing window*, not the mean of a centered window?
2. Our threshold uses √(bg/60). What is MAD, and does our detector use it?
3. Why is the background frozen during a flare?
4. Why can't SoLEXS assign a GOES class by itself?
5. The tuned detector has GOES B-class recall of only 0.18. Why did the tuning accept that?

## Questions to discuss with my tutor

1. Our score weights match rate and C+ recall equally (F1). For a flare *warning* system, should missing a flare
   cost more than a false alarm? How would you put that into the score (for example F-beta)?
2. GOES itself misses or merges flares. How does using an imperfect "truth" affect our measured precision and recall?
3. We picked the single best of 300 trials, and the top 10 scores differ by less than 0.003. Is that difference
   real or noise, and how could we check (for example by bootstrapping over days)?

## Key numbers

| Metric | Legacy (tune) | New (tune) | New (val) |
|---|---|---|---|
| Detections | 2,725 | 1,830 | 676 |
| Match rate (precision vs GOES, all) | 0.51 | 0.76 | 0.76 |
| Precision for detections ≥ 50 counts/s | 0.80 | 0.83 | 0.87 |
| GOES recall, C and above | 0.98 | 0.865 | 0.887 |
| GOES recall, B | 0.99 | 0.18 | 0.18 |
| Onset error vs GOES, median / p90 | 5.8 / 76 min | 1 / 10 min | 1 / 9 min |
| Events longer than 2 h | 218 | 5 | 2 |

- **Chosen settings (tuned on tune period only):** `min_excess_frac 1.0`, `min_excess_abs 12`, `rise_steps 3`,
  `dip_frac 0.3`, `impulsive_factor 0`.
- **Tuning:** 300-trial grid; best score 0.799; MLflow holds 410 runs.
- **Whole catalogue:** 3,126 events, of which 2,380 are matched to GOES.
- **Missing GOES truth:** NOAA has no report for 2025-12-30 and 2025-12-31, so those days are excluded.

---

<details>
<summary><b>Answers (spoiler — try first!)</b></summary>

1. A low quantile ignores short flare spikes (it is robust), and a *trailing* window uses only past data, so the
   same calculation could run live. A centered window looks into the future.
2. MAD is the median of |x − median(x)|, a robust noise estimate (1.4826 × MAD ≈ standard deviation). Our detector
   does **not** use it. It uses Poisson counting noise √(bg/60), plus a relative floor (1× background) and an
   absolute floor (12 counts/s).
3. Otherwise the rolling background would climb with the flare, the "halfway back to background" end level would
   keep moving, and ends would be wrong.
4. SoLEXS measures counts in its own energy band and units. GOES classes are defined from GOES's 1–8 Å flux in
   W/m². There is no exact conversion, so a class may only come from the GOES list.
5. The score only counts recall for C and above, because our labels are ≥C and ≥M forecasts. The higher threshold
   removed many small events, raising the match rate. B flares are mostly below the doubling threshold, a
   deliberate trade-off.

</details>
