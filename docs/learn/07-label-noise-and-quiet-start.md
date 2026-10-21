# Lesson 07 — Label noise and quiet-start evaluation: GOES-direct labels and a causal activity flag

## What we built

Two improvements to *what we teach* the model and *how we grade* it.

1. **Labels from GOES.** Forecast labels ("will a ≥C/≥M flare start in the next 30/60/120 min?") now come from the
   NOAA GOES flare list directly. Before, they came only from flares our detector had caught, so every flare the
   detector missed was wrongly taught as "no flare coming".
2. **Activity flag.** A new column, `flare_in_progress_at_t`, says whether the detector, using only data up to
   that moment, believes a flare is in progress. We use it to grade models separately on **quiet-start** moments,
   when the Sun is not already flaring.

## Why it matters

**Label noise.** Imagine learning to spot birds from a field guide where a third of the photos labelled "no bird"
actually contain a bird the guide's author overlooked. You'd learn to ignore small birds. Our old labels had the
same problem: the tuned detector catches about 86% of C-and-above flares, so the rest became false "no" labels.
The GOES list is the reference the whole field uses, so we take the labels from it.

**Quiet-start evaluation.** Flares cluster: during a big flare, another one often follows. A forecaster who simply
says "it's flaring now, so more is coming" gets many hits for free. That's not wrong, but it's easy. The useful
question is whether the model can see a flare coming *when the Sun looks quiet*. Grading on quiet-start rows
answers that, like testing a weather forecaster on days when it isn't already raining.

## Concepts

**Label noise.** Some training labels are wrong. Here the wrong ones were mostly false negatives (missed flares),
which push a model toward "never predict a flare". Fixing the source of labels is better than hoping the model
copes.

**Ground truth vs. our detector.** Our detector is a tool we built; GOES is the community standard. For labels
we trust GOES. For timing we still use our detector where we can, because its onset is more precise (median error
1 min).

**The onset rule.**
- **Primary match.** Every detection has one *primary* GOES flare: the overlapping one whose start is closest to
  the detection's onset. That GOES flare uses the SoLEXS onset.
- **Everything else** keeps its own GOES start time. This covers flares the detector missed *and* the second flare
  of two that the detector merged into one.

**Old vs new labels.** We count, on rows with `ok = True`:
- **gained:** positives under the new rules that were negatives before (mostly missed flares)
- **lost:** positives before that are negatives now (mostly onset shifts, see below)

**Causal flag vs catalogue interval.** The nowcast label uses the catalogue: `onset ≤ t < end`, where the onset is
found by looking *back* and the end needs the future. The activity flag must be honest about what was knowable at `t`:
- **Start:** it turns on at the **trigger time**, the end of the minute whose data confirmed the rise.
- **End:** it turns off when the end is **confirmed**, which is 2 quiet minutes after the end minute. For an event
  cut by the 3-hour cap it's the cap time; for an event ended by a data gap, once the gap has lasted 10 minutes.

**Meta column vs feature.** The flag is stored next to the features but is *not* given to the models. It's used
to build the persistence baseline (lesson 08) and to split the evaluation. Keeping it out of the features means
the rule "catalogue fields are never features" stays simple and easy to check.

**Quiet-start rows.** Rows where `flare_in_progress_at_t = 0`. Every forecast metric is now reported twice: on all
rows and on quiet-start rows.

## Tools used

| Tool | What it is | What it did here | Most useful commands |
|---|---|---|---|
| **pandas groupby / idxmin** | Group rows and pick the smallest per group | Chooses each detection's primary GOES flare | `df.loc[df.groupby("event")["d"].idxmin()]`, `drop_duplicates("goes")` |
| **numpy searchsorted + cumsum** | Fast interval marking | Sets the flag for 2.7 M rows from about 3,000 intervals | `np.searchsorted(t, starts)`, `np.add.at(diff, a, 1)`, `np.cumsum(diff)` |
| **pytest parametrize** | Run one test with several inputs | Causality test at 5 cut points | `@pytest.mark.parametrize("cut_min", [598, 605, ...])` |
| **DVC params dependency** | Re-run a stage when a param changes | `build_dataset` now depends on `flare_detection.end_confirm_min` and `gap_end_min` | `dvc status`, `dvc params diff` |

## Code walkthrough

### `src/labels.py` → `goes_onsets`

```python
    g = goes[goes["goes_class"].astype(str).map(goes_flux) >= goes_flux(min_class)]   # (1)
    onset = g["begin"].copy()                                                         # (2)
        pr["d"] = (pr["ev_onset"] - pr["g_begin"]).abs()                              # (3)
        prim = pr.loc[pr.groupby("event")["d"].idxmin()]                              # (4)
        prim = prim.sort_values("d").drop_duplicates("goes")                          # (5)
        onset.loc[idx] = prim.loc[idx].to_numpy()                                     # (6)
    return np.sort(_ns(onset.dropna()))
```
1. Keep GOES flares at or above the class (C1.0 or M1.0). The class comes from GOES only.
2. By default, every flare's onset is its GOES start.
3. For every (detection, GOES flare) match, how far apart are the two start times?
4. Each detection's primary GOES flare is the one with the smallest gap.
5. If one GOES flare is primary for two detections, keep the closer one.
6. Primary flares take the more precise SoLEXS onset. All others, including missed flares, keep the GOES start.

### `src/labels.py` → `make_labels(..., goes=goes_list, pairs=pairs)`
With `goes` given, the forecast onsets come from `goes_onsets`. Without it, the old detector-only method runs. We
keep the old method so `src/dataset.py` can compute `reports/label_comparison.json` (tune and val only).

### `src/activity.py`

```python
    end[normal] = end[normal] + pd.Timedelta(minutes=end_confirm_min)                # (1)
    end[gap] = end[gap] + pd.Timedelta(minutes=gap_end_min)                          # (2)
    a = np.searchsorted(t, _ns(events["trigger_time"]), side="left")                 # (3)
    b = np.searchsorted(t, _ns(end_known_time(events, end_confirm_min, gap_end_min)), side="left")
    np.add.at(diff, a, 1); np.add.at(diff, b, -1)                                    # (4)
    return (np.cumsum(diff[:-1]) > 0).astype(np.int8)                                # (5)
```
1. A normal event's end is only *known* after the confirmation minutes.
2. A gap-ended event is only known to have ended once the gap is long enough.
3. Where each event's active interval begins and ends in the row timeline.
4. +1 at each start and −1 at each end (a "difference array").
5. The running sum tells how many events are active at each row. More than 0 means a flare is in progress.

### `tests/test_leakage.py`

- `test_goes_flare_missed_by_detector_still_gives_positive_forecast`: no detections at all, one GOES C2.0 flare,
  so the rows before it are positive.
- `test_goes_onset_uses_primary_solexs_onset_and_keeps_merged_flares`: one detection overlapping two GOES flares
  gives two onsets, the SoLEXS one and the second flare's own start.
- `test_flare_in_progress_flag_is_causal` (5 cut points): the flag up to time T is identical whether or not the
  data after T exists.

## Hands-on

Activate the venv and work from the project folder.

**1. How many labels changed?**
```
python -c "import json; d=json.load(open('reports/label_comparison.json')); [print(p, k, v['old_pos'], '->', v['new_pos'], '+', v['gained'], '-', v['lost']) for p in d for k, v in d[p].items()]"
```
*Expected:* for example `tune y_c_30m 235984 -> 281541 + 49649 - 4092` and `val y_m_60m 18896 -> 19420 + 1328 - 804`.
*Worked if* you can explain why C gains a lot while M barely changes in total.

**2. Count onsets both ways.**
```
python -c "import pandas as pd; from src import labels; e=pd.read_parquet('data/processed/events.parquet'); g=pd.read_parquet('data/processed/goes_matched.parquet'); p=pd.read_parquet('data/processed/events_pairs.parquet'); print(len(labels.goes_onsets(g,e,p,'C1.0')), len(labels.qualifying_onsets(e,'C1.0'))); print(len(labels.goes_onsets(g,e,p,'M1.0')), len(labels.qualifying_onsets(e,'M1.0')))"
```
*Expected:* `3613 2321` and `431 332`. The GOES list has 3,613 C-or-above flares over the whole range; the old
method knew only 2,321 starts.

**3. Look at a flare the detector missed.** GOES lists a C2.1 flare starting 2026-02-06 17:48 that our detector did not catch.
```
python -c "import pandas as pd; v=pd.read_parquet('data/processed/dataset/val.parquet', columns=['mean_1m','y_c_30m','flare_in_progress_at_t']); print(v.loc['2026-02-06 17:38':'2026-02-06 17:48'].iloc[::12].round(1))"
```
*Expected:* `y_c_30m = 1` up to 17:46 and `0` at 17:48 (the start is not strictly after t), with
`flare_in_progress_at_t = 0` throughout. Under the old labels these rows would not have counted this flare.

**4. How often is the Sun already flaring?**
```
python -c "import json; d=json.load(open('reports/dataset_summary.json')); print(d['periods']['tune']['flare_in_progress_frac'], d['periods']['val']['flare_in_progress_frac'])"
```
*Expected:* about `0.088` and `0.073`, so roughly 1 row in 12 starts during a detected flare.

**5. Does an ongoing flare make the next one more likely?**
```
python -c "import pandas as pd; v=pd.read_parquet('data/processed/dataset/val.parquet', columns=['flare_in_progress_at_t','y_c_60m','y_m_60m','ok_60m']); print(v[v.ok_60m].groupby('flare_in_progress_at_t')[['y_c_60m','y_m_60m']].mean().round(4))"
```
*Expected:* ≥M within 60 min is about 0.022 when quiet and 0.053 while a flare is in progress, more than double.
That's flare clustering, and the reason quiet-start scores matter.

**6. Run the new tests only.**
```
pytest tests/test_leakage.py -q -k "goes or progress"
```
*Expected:* `11 passed, 12 deselected`. `-k` matches words in test *names*, so besides the 2 new GOES-label tests
and the 6 activity-flag tests (5 cut points plus the trigger test) it also picks up three older tests whose names
contain "goes" or "progress" (`test_class_thresholds_come_from_goes_match`,
`test_nowcast_label_is_in_progress_window`, `test_label_not_ok_without_goes_truth_or_data`). Add `--collect-only`
to see the list without running it.

## Break it on purpose

Make the activity flag cheat by starting it at the catalogue onset instead of the trigger.

1. In `src/activity.py`, change `_ns(events["trigger_time"])` to `_ns(events["onset"])`.
2. Run `pytest tests/test_leakage.py -q -k progress`.
3. *Expected:* `2 failed, 5 passed`. `test_flare_in_progress_starts_at_trigger_not_onset` fails, and so does
   `test_flare_in_progress_flag_is_causal[598]`: with data only up to minute 598 the flare hasn't triggered yet,
   but the onset-based flag (computed from the full data) is already on. That's leakage: the flag "knew" about
   the flare before the data could show it. The onset is found by looking back from the trigger.
4. Undo: `git checkout -- src/activity.py`, then rerun. Expected: `7 passed`.

## Check yourself

1. Why were the old forecast labels biased toward "no flare"?
2. A detection overlaps two GOES flares that start at 06:24 and 06:38. Which onsets go into the forecast labels, and why?
3. Why does the activity flag start at `trigger_time` and not at `onset`?
4. Why is `flare_in_progress_at_t` kept out of the model features?
5. What extra information does a quiet-start score give you that the all-rows score hides?

## Questions to discuss with my tutor

1. GOES is itself an instrument with its own detection rules and gaps. Are we just swapping one label noise for
   another, and how could we measure the noise in GOES labels?
2. Some GOES flares happen while SoLEXS has no data. Should those rows be dropped, or is it fine to learn
   "a flare will come" from the data before the gap?
3. Is it fair to give the model the activity flag as a feature in a real-time system? What would change in the
   evaluation if we did?

## Key numbers

**Forecast positives on ok rows, old → new (gained / lost):**

| Label | tune | val |
|---|---|---|
| ≥C in 30 min | 235,984 → 281,541 (+49,649 / −4,092) | 84,784 → 97,164 (+13,862 / −1,482) |
| ≥C in 120 min | 715,775 → 809,914 (+95,831 / −1,692) | 259,077 → 281,172 (+23,301 / −1,206) |
| ≥M in 60 min | 57,052 → 57,826 (+3,474 / −2,700) | 18,896 → 19,420 (+1,328 / −804) |

**GOES flares (whole range):**
- **C-or-above flares in the GOES list:** 3,613. 1,173 of them have no matching detection (many fall in SoLEXS
  data gaps; in valid time recall is 86%).
- **Starts known to the old labels:** 2,321 C-or-above starts.

**Activity flag:**
- **Share of rows with a flare in progress:** 8.8% of tune rows, 7.3% of val rows.
- **Flare clustering (val):** ≥M within 60 min is 2.2% when quiet vs 5.3% while a flare is in progress.

**Old models re-scored on the new labels (validation TSS):**
- **≥C in 30 / 60 / 120 min:** 0.199 / 0.193 / 0.279 (was 0.181 / 0.177 / 0.233)

---

<details>
<summary><b>Answers (spoiler — try first!)</b></summary>

1. They only counted flares our detector caught. The detector misses about 14% of C-and-above flares (more in
   data gaps), so those flares' "coming soon" rows were labelled 0, teaching the model to ignore them.
2. 06:24 is the primary match (closest to the detection's onset), so it takes the SoLEXS onset. The 06:38 flare
   keeps its own GOES start (06:38). Giving it the detection's earlier onset would put its start before it happened.
3. The onset is found by walking *back* from the trigger once the rise is confirmed. At the onset time itself,
   nobody could yet know a flare had started. Only the trigger is knowable in real time.
4. It's derived from the detector's event catalogue. Keeping it a meta column makes the "catalogue never as a
   feature" rule simple and testable, and its purpose here is grading (baseline and split), not prediction.
5. Whether the model can foresee a flare when the Sun isn't already flaring. On all rows, much of the skill can
   come from "a flare is happening, so more will follow", which persistence gets for free.

</details>
