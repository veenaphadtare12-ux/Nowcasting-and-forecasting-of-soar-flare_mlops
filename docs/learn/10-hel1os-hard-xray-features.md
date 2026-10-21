# Lesson 10 — Hard X-rays: a parser bug, causal HEL1OS features, and missing data by design

## What we built

After extracting 77 more HEL1OS sessions, we found and fixed a bug that had silently thrown away most of the hard
X-ray data. Then we added 17 causal hard X-ray features (rates, hardness ratios, lags and a "Neupert" correlation).
They exist only while HEL1OS is observing; at all other times they are honestly *missing*. The models were taught
to handle that: XGBoost natively, logistic regression with a missing flag.

## Why it matters

**The bug.** Imagine merging four class registers where each teacher wrote arrival times with slightly different
watches (one at 08:00:00.79, another at 08:00:00.86). If you merge on the exact time, almost nobody matches, and if
you then keep only "the first record per second", you lose most students. That's what happened to our energy bands.

**Missing by design.** HEL1OS observes only part of each day, and about 2% of our rows. A weather station that's
switched off at night shouldn't report "0 °C" at night. It should report "no reading". Filling the gap with zeros
would teach the model a fake signal.

## Concepts

**Hard vs soft X-rays.** SoLEXS sees soft X-rays (about 2–20 keV): hot plasma that brightens and cools slowly.
HEL1OS sees hard X-rays (about 5–150 keV): fast electrons hitting the solar atmosphere, short impulsive bursts at
the start of a flare.

**Energy band and channel.** HEL1OS reports separate light curves per energy band and detector (CdTe 1/2, CZT 1/2).
We combine them into 4 channels:
- **CdTe 5–20 keV** (`cdte_lo`)
- **CdTe 20–40 keV** (`cdte_hi`)
- **CZT 20–40 keV** (`czt_lo`)
- **CZT 40–150 keV** (`czt_hi`)

For each band, the two detectors are averaged where both exist.

**Sub-second offsets.** Each band's 1-second bins start at its own fraction of a second. Bands must be put on a
common whole-second grid *each on its own* before being joined.

**Hardness ratio.** The high-energy rate divided by the low-energy rate. A higher ratio means a "harder" spectrum
(more energetic photons).

**Lag features.** The value 5 or 10 minutes *ago* (a positive shift). This lets a model see "has the hard X-ray
level been rising?" while staying causal.

**Neupert effect.** Hard X-ray flux tracks the *time derivative* of soft X-ray flux: electrons heat the plasma, and
the heated plasma then glows in soft X-rays. Our feature is a trailing 10-minute correlation between the hard X-ray
rate and the rate of change of SoLEXS.

**Availability flag.** `hel1os_available = 1` when at least 30 of the last 60 seconds have HEL1OS data. It's
computed from the past only.

**Missing-value handling.**
- **XGBoost** learns a default branch for missing values at every split, so NaN is fine.
- **Logistic regression** cannot use NaN. Its pipeline therefore uses `SimpleImputer(strategy="median",
  add_indicator=True)`, which fills a typical value *and* adds a 0/1 "was missing" column. It's fitted on training
  rows only, inside the pipeline, so validation never influences the fill value.

## Tools used

| Tool | What it is | What it did here | Most useful commands |
|---|---|---|---|
| **astropy.io.fits** | FITS reader/writer | Read band extensions; wrote a synthetic file for the regression test | `fits.open(p)`, `fits.BinTableHDU.from_columns(cols, name=...)`, `.writeto(p)` |
| **pandas** | Time series | Per-band rounding, channel sums, 10-s bins, trailing windows, lags | `pd.to_datetime(np.round(secs), unit="s")`, `.rolling(n).corr(other)`, `.shift(+k)` |
| **scikit-learn SimpleImputer** | Missing-value filler | Median fill plus missing indicators for logistic regression | `SimpleImputer(strategy="median", add_indicator=True)` |
| **DVC** | Pipeline | `build_dataset` now depends on `data/processed/hel1os` | `dvc repro build_dataset`, `dvc status` |

## Code walkthrough

### `src/hel1os.py` — the fix

```python
            # Round EACH band to whole seconds before bands are combined: bands of one file start at different
            # sub-second offsets (e.g. .793 s vs .858 s), so joining on raw stamps would misalign them.
            t = pd.to_datetime(np.round(secs), unit="s", utc=True).as_unit("s")
```
Before, the code joined the bands on millisecond timestamps and rounded *afterwards*. Then
`out[~out.index.duplicated(keep="first")]` kept only the first band at each second, so the other bands' values
became NaN. One session dropped from about 43,000 rows per band to about 110.

### `src/features.py` — hard X-ray features

```python
HX_CHANNELS = {"cdte_lo": ("cdte", ["5-20keV"]), "cdte_hi": ("cdte", ["20-30keV", "30-40keV"]),
               "czt_lo": ("czt", ["20-40keV"]), "czt_hi": ("czt", ["40-60keV", "60-80keV", "80-150keV"])}
...
    out["hel1os_available"] = (n_valid.rolling(per_min, min_periods=1).sum() >= 30).astype("int8")   # causal
    out["hx_hr_czt"] = m1["czt_hi"] / (m1["czt_lo"] + 1.0)                                            # hardness
    out["hx_cdte_lo_lag5m"] = out["hx_cdte_lo_log_mean_1m"].shift(5 * per_min)                        # past value
    out["hx_neupert_corr_10m"] = b["czt_lo"].rolling(10 * per_min, min_periods=5 * per_min).corr(dsxr)
    for c in HX_FEATURES[1:]:
        out.loc[~avail, c] = np.nan            # no reading -> missing, never 0
```
Every window is trailing and every shift is positive, so the existing AST leakage test also covers this code.

### `src/models/train.py` — logistic regression with missing flags
```python
        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
```

### Tests (`tests/test_leakage.py`, `tests/test_pipeline.py`)
- `test_hel1os_features_unchanged_when_future_is_altered[...]`: future HEL1OS data is scrambled; past features are identical.
- `test_hel1os_features_missing_outside_sessions_and_optional`: NaN outside sessions, and no columns at all without HEL1OS.
- `test_hel1os_bands_with_different_subsecond_offsets_are_not_lost`: the regression test for the bug.

## Hands-on

Activate the venv and work from the project folder.

**1. See the bug's fingerprint in the raw file.**
```
python -c "from astropy.io import fits; h=fits.open(r'D:\MLOPS_CP\Data\HELIOS\2025\04\10\HLS_20250410_000008_43184sec_lev1_V112\cdte\lightcurve_cdte1.fits'); [print(e.name, len(e.data), e.data['ISOT'][0]) for e in h[1:]]"
```
*Expected:* about 43,000 rows per band, with first timestamps ending in `.793` for some bands and `.858`/`.476`/`.527`
for others. Those different sub-second offsets are the root of the bug.

**2. Check that the parser now keeps every band.**
```
python -c "from src import hel1os; s=[x for x in hel1os.newest_per_session(hel1os.list_sessions()) if x.name.startswith('HLS_20250410_000008')][0]; df=hel1os.read_session(s); print(df.filter(regex='keV$').notna().sum().describe())"
```
*Expected:* min about 42,865 and max about 43,176 non-missing values per band.

**3. Look at the hard X-ray features.**
```
python -c "import pandas as pd; v=pd.read_parquet('data/processed/dataset/val.parquet'); a=v[v.hel1os_available==1]; print(len(a), round(len(a)*10/3600,1), 'hours'); print(a.filter(like='hx_').describe().T[['count','mean','50%']].round(3))"
```
*Expected:* 51,667 rows = 143.5 hours with HEL1OS in validation; every `hx_*` column is filled on these rows.

**4. Count the missing values.** Using the same `v`, run `print(v['hx_hr_czt'].isna().mean())`.
*Expected:* about 0.94, so 94% of validation rows have no hard X-ray reading.

**5. Run the HEL1OS tests.**
```
pytest -q -k "hel1os"
```
*Expected:* all selected tests pass.

## Break it on purpose

Bring the bug back and let the regression test catch it.

1. In `src/hel1os.py`, change `pd.to_datetime(np.round(secs), unit="s", utc=True).as_unit("s")` to
   `pd.to_datetime(np.round(secs, 3), unit="s", utc=True).as_unit("ms")`. That keeps the sub-second offsets.
2. Run `pytest -q tests/test_pipeline.py -k offsets`.
3. *Expected:* `test_hel1os_bands_with_different_subsecond_offsets_are_not_lost` fails. The two bands don't share
   timestamps any more: the frame doubles in length, and each band is NaN on the other band's rows.
4. Undo: `git checkout -- src/hel1os.py`, then rerun. Expected: passed.

## Check yourself

1. Why did joining bands on exact timestamps lose data, and why did 2024 sessions look fine?
2. Why must hard X-ray features be NaN, not 0, when HEL1OS is not observing?
3. How does logistic regression deal with those NaNs, and why must the imputer be fitted inside the pipeline?
4. What is the Neupert effect, and how does our feature measure it causally?
5. Is `hx_cdte_lo_lag5m` causal? Explain using the sign of the shift.

## Questions to discuss with my tutor

1. Our availability rule is "at least 30 of the last 60 seconds". How would a different rule change which rows the
   models see as "hard X-ray rows"?
2. HEL1OS covers about 2% of rows. Is it better to train one model with missing values, or separate models for "with
   HEL1OS" and "without"?
3. The bug was invisible in the 2024 files and only appeared with new data versions. What monitoring would catch such
   format changes automatically (for example pandera schemas with row-count checks)?

## Key numbers

| What | Value |
|---|---|
| HEL1OS sessions | 104 on disk → 98 after the newest-version rule; 4.06 M one-second rows (was 23 sessions, 0.87 M) |
| Bug impact | one band from ~43,000 to ~110 rows; after the fix 42,865–43,176 per band |
| New features | 17 (`hel1os_available` + 16 `hx_*`); the dataset now has 44 features |
| HEL1OS on dataset rows | tune 77,625 rows (215.6 h); val 51,667 rows (143.5 h); about 94% of val rows have no HEL1OS |
| Tests | 57 passed after this task |

---

<details>
<summary><b>Answers (spoiler — try first!)</b></summary>

1. Bands had different sub-second offsets, so their timestamps almost never matched exactly. After rounding,
   several rows fell on the same second and "keep first" discarded the other bands' values. The 2024 files happened
   to have equal offsets for all bands.
2. 0 would be a real (fake) measurement saying "no hard X-rays", which a model could learn from. NaN says "unknown",
   which is the truth.
3. `SimpleImputer(median, add_indicator=True)` fills the median and adds a "was missing" column. Inside the
   pipeline it's fitted on training rows only, so validation and test data never influence the fill values (no
   leakage).
4. Hard X-ray flux follows the rate of change of soft X-ray flux. The feature is the correlation, over the trailing
   10 minutes, between the hard X-ray rate and the change in SoLEXS rate. It uses only past data.
5. Yes. `shift(+30)` (5 min at 10-s rows) moves values *down* the table, so each row gets the value from 5 minutes
   earlier. A negative shift would bring future values back, which the AST test forbids.

</details>
