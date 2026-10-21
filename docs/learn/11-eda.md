# Lesson 11 — Exploratory data analysis (EDA): look before you model

## What we built

An executed notebook, `notebooks/01_eda.ipynb`, that looks at the data from nine angles: coverage, long-term
behaviour, activity trend, flare shapes, flare statistics, detector quality, features, label rates and hard X-rays.
It uses only the tune and validation periods. Its figures are saved in `docs/figures/eda/`, and the 10 key findings
are in `docs/EDA_SUMMARY.md`.

## Why it matters

A doctor doesn't prescribe before examining the patient. EDA is that examination for data. It finds:
- **problems:** gaps, drift, a parser bug, redundant features
- **facts that decide the method:** flares are rare, rows are correlated, the Sun's activity drifts
- **sanity checks:** the Neupert effect shows two instruments' clocks agree

Modelling without EDA is like tuning an engine without ever opening the bonnet.

## Concepts

**EDA.** Systematic, mostly visual, inspection of data *before* modelling. The goal is understanding: how big, how
complete, how variable, what relates to what. It's not about proving a model works.

**Why only tune + val?** If you look at the test period while exploring, your later choices (features, thresholds)
are influenced by it, and the final test score is no longer honest. The notebook's first cell asserts that no data
from the test period is loaded.

**How to read each plot:**
- **Calendar heatmap** (`01_coverage_calendar`): one row per month, one column per day of the month; colour =
  fraction of the day observed. Look for stripes (systematic) versus scattered white cells (random).
- **Gap-length histogram (log-log)** (`01_gap_lengths`): many short gaps plus a separate group of day-long gaps
  means two different causes.
- **Long-term light curve** (`02`): log y-axis, because values span 4 orders of magnitude. The thin line is the
  daily max, the thick line the daily median; markers show GOES M/X flares.
- **Monthly counts plus background** (`03`): two separate panels on purpose. Different units must never share one
  y-axis.
- **Superposed epoch** (`04`): line up many flares at their onset (time 0), rescale each to 0 = background and
  1 = peak, then plot the median and the 25–75% band. It shows the *typical* shape and how much flares vary.
- **Log-log scatter with fitted line** (`05_peak_vs_goes`): a straight line on log-log axes is a power law. The slope
  (1.34) says "10× more GOES flux gives about 22× more SoLEXS counts".
- **Overlaid histograms by class** (`07_feature_distributions`): if the two colours overlap almost completely, that
  feature alone can't tell the classes apart.
- **Correlation heatmap** (`07_feature_correlation`): red = move together, blue = opposite; |r| > 0.9 means
  near-duplicates.
- **Base rates** (`08`): the share of positive labels, overall, by month and by hour. These set expectations for
  every metric.
- **Neupert lag histogram** (`09_neupert_lag`): how many seconds the soft X-ray rise rate trails the hard X-rays.
  Physics predicts about 0.

**Takeaway cells.** After each plot, a short markdown cell says *what we saw* and *what it means for modelling*. EDA
without written conclusions is just pictures.

**Correlation is not causation.** The hour-of-day pattern in flare rates almost certainly reflects *when SoLEXS
observes*, not when the Sun flares. EDA findings need a physical or operational explanation before they shape the model.

## Tools used

| Tool | What it is | What it did here | Most useful commands |
|---|---|---|---|
| **Jupyter + nbconvert** | Notebooks and their command-line runner | Built and executed the notebook non-interactively, saving all outputs | `jupyter nbconvert --to notebook --execute --inplace notebooks/01_eda.ipynb` |
| **nbformat** | Read/write notebook files in Python | `notebooks/build_eda_notebook.py` creates the cells | `nbformat.v4.new_code_cell(src)`, `nbformat.read(path, as_version=4)` |
| **matplotlib** | Plotting | All 15 figures, using the project's colour palette | `plt.subplots`, `ax.hist`, `ax.imshow`, `ax.fill_between`, `fig.savefig` |
| **pandas** | Grouping and resampling | Daily, monthly and hourly summaries | `groupby(index.floor('D'))`, `.to_period('M')`, `.quantile(0.2)` |
| **numpy** | Fits and correlations | Power-law fit, Neupert cross-correlation | `np.polyfit(logx, logy, 1)`, `np.corrcoef` |

## Code walkthrough

### `notebooks/01_eda.ipynb`, first code cell (the guard)
```python
assert eda.HI == config.period_bounds('val')[1], 'EDA must stop at the end of validation'
assert eda.HI <= config.period_bounds('test')[0], 'EDA window reaches the test period'
qc, m, ev, g, pairs = eda.load_qc(), eda.load_minutes(), eda.load_events(), eda.load_goes(), eda.load_pairs()
eda.check_no_test(qc, m, ev, g)
```
Every loader in `src/eda.py` cuts data at `HI` (end of validation), and `check_no_test` re-checks every table.

### `src/eda.py` → `superposed_epoch`
```python
            i0 = np.searchsorted(t_ns, (r["onset"] + pd.Timedelta(minutes=1)).value)
            seg = mv[i0 - pre: i0 + post + 1]                          # 30 min before to 120 min after onset
            curves.append((seg - r["bg_counts_s"]) / amp)              # 0 = background, 1 = catalogue peak
        med, q1, q3 = np.nanmedian(c, 0), np.nanpercentile(c, 25, 0), np.nanpercentile(c, 75, 0)
```

### `src/eda.py` → Neupert lag
```python
        cc = [np.corrcoef(h[max(0, -k): len(h) - max(0, k)], dsv[max(0, k): len(dsv) - max(0, -k)])[0, 1]
              for k in range(-max_lag, max_lag + 1)]
        k_best = int(np.nanargmax(cc)) - max_lag                       # shift with the best agreement
        if np.nanmax(cc) < 0.3: continue                               # no clear relation for this flare
```
We slide the soft X-ray derivative against the hard X-rays by −5 to +5 minutes and keep the shift with the highest
correlation.

## Hands-on

Activate the venv and work from the project folder.

**1. Open and run the notebook yourself.**
```
jupyter lab notebooks/01_eda.ipynb
```
Pick the kernel **solar-flare**, then *Run All*. *Expected:* the same 15 figures, and a first-cell print of
`window: 2025-04-09 ... -> 2026-06-01 ...`.

**2. Test the guard (without touching real test data).** In a new notebook cell, run:
```
fake = pd.DataFrame({'x': [1]}, index=pd.DatetimeIndex(['2026-07-01'], tz='UTC'))
eda.check_no_test(fake)
```
*Expected:* `AssertionError: test-period data found`. A made-up row dated in the test period is enough to trip the
guard; we never open the real test file. Delete the cell afterwards.

**3. Find the 17th-of-month pattern in the raw QC file.**
```
python -c "import pandas as pd; q=pd.read_csv('data/processed/solexs_qc.csv'); q['dom']=pd.to_datetime(q.date).dt.day; print(q.groupby('dom').valid_fraction.mean().round(2).loc[15:19])"
```
*Expected:* day 17 about 0.15 (all days that have a folder), against 0.86–1.0 for days 15, 16, 18 and 19.

**4. Re-derive the power law.**
```
python -c "import json; d=json.load(open('reports/eda_numbers.json')); print(d['stats']['fit_slope'], d['stats']['fit_r'], d['stats']['n_matched_fit'])"
```
*Expected:* about `1.338 0.947 1905`. If GOES flux is 10× larger, how many times larger is the SoLEXS peak?

**5. Rebuild everything from scratch.**
```
python notebooks/build_eda_notebook.py
```
*Expected:* it rewrites and executes the notebook in about 3 minutes; `git diff --stat` shows the notebook changed
(only execution metadata) but no figures changed meaningfully.

## Break it on purpose

Make the EDA window reach into the test period and watch the guard stop it.

1. In `src/eda.py`, change `HI = config.period_bounds("val")[1]` to `HI = config.period_bounds("test")[1]`.
2. Run `python notebooks/build_eda_notebook.py`.
3. *Expected:* the first cell fails with `AssertionError: EDA must stop at the end of validation`, so no plot is drawn.
4. Undo: `git checkout -- src/eda.py`.

## Check yourself

1. Why is the test period excluded from EDA, even though EDA "doesn't train anything"?
2. In the superposed-epoch plot, why is each flare rescaled to 0 = background and 1 = peak?
3. What does a slope of 1.34 on the log-log peak-vs-GOES plot mean in words?
4. Two features have r = 0.999. Why is that a problem for logistic regression but not for XGBoost?
5. Base rates vary by hour of day. Why shouldn't we add "hour of day" as a feature without more thought?

## Questions to discuss with my tutor

1. The SoLEXS background drops by about 60% over 14 months. How can we tell solar-cycle decline from slow instrument
   degradation, and should the model correct for either?
2. We used the median and the 25–75% band for flare profiles. When would the mean be misleading here?
3. EDA findings can bias modelling decisions just like looking at the test set. Where is the line between "informed"
   and "overfitted to what we saw"?

## Key numbers

| What | Value |
|---|---|
| Tune + val days | 418 calendar days; 355 with folders; 331 usable; 23.7% of minutes missing |
| 17th-of-month | about 11% valid coverage vs about 80% on other days |
| Gaps | 140 total; 50 ≤ 5 min; 56 ≥ 1 day; longest 8 days |
| GOES flares in window | 3,359 (326 M, 21 X) |
| Background drift | about 12.8 → 5.2 counts/s (Apr 2025 → May 2026) |
| Median profile peak | 7 / 12 / 15 min after onset (C / M / X) |
| SoLEXS peak vs GOES flux | slope 1.34, r = 0.95 (1,905 flares) |
| Correlated feature pairs | 18 with \|r\| > 0.9 |
| Base rates | nowcast 8%; ≥C 30/60/120 min 14/25/41%; ≥M 1.5/2.8/5.3% |
| HEL1OS overlap | tune 215.6 h (13 days), val 143.5 h (8 days); Neupert lag median 0 s (IQR −10 to +20 s, 71 flares) |

---

<details>
<summary><b>Answers (spoiler — try first!)</b></summary>

1. Anything you see influences your later choices (features, thresholds, which model to trust). If those choices
   were shaped by the test data, the final test score is no longer an unbiased estimate.
2. Flares differ by orders of magnitude in size and sit on different backgrounds. Rescaling puts all of them on one
   scale, so we compare *shapes*.
3. SoLEXS peak counts grow like GOES flux to the power 1.34: 10× more GOES flux gives about 10^1.34 ≈ 22× more
   SoLEXS counts.
4. With almost identical columns, many coefficient combinations fit equally well, so the coefficients become unstable
   and can't be interpreted. Trees just pick one of the duplicates at each split.
5. The pattern probably comes from *when SoLEXS observes* (coverage), not from the Sun. A model could learn the
   observing schedule instead of solar physics, and that pattern could change with operations.

</details>
