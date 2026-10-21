# Lesson 02 — Ingestion: FITS files, astropy, SoLEXS/HEL1OS parsers, Unix time, Parquet, data gaps

## What we built

We wrote readers that open the satellite's raw files and turn them into clean pandas tables with proper UTC
timestamps. For SoLEXS this means one row per second, with bad seconds removed. For HEL1OS it means one column
per detector and energy band. The cleaned SoLEXS days are saved as Parquet files, together with a quality report
that says how much of each day is usable.

## Why it matters

Raw instrument files are like a box of receipts from many shops: different layouts, different date formats, some
torn or blank. Before you can do your accounts (train a model), someone has to read every receipt the same way,
write the dates in one format, throw out the blank ones, and note which days are missing. If this step is wrong,
for example dates shifted by a time zone, every later step is silently wrong too. It's "garbage in, garbage out".

## Concepts

**FITS (Flexible Image Transport System).** The standard file format in astronomy. A FITS file is a list of
**HDUs (Header/Data Units)**. Each HDU has two parts:
- a **header**: text cards like `TSTART = 1744243200.0`, metadata describing the data
- **data**: an image or a **binary table**, which is like a spreadsheet stored in binary

HDU 0 is the "primary" HDU, often empty. Our tables live in HDU 1 and later. HEL1OS puts one energy band in each
extra HDU.

**Light curve.** Brightness (here: X-ray counts) versus time. A flare shows up as a sharp rise and a slower decay.

**GTI (Good Time Interval).** A list of `[start, stop]` periods when the instrument was observing properly.
Data outside the GTIs must not be trusted.

**Unix time.** Seconds since 1970-01-01 00:00:00 UTC. SoLEXS `TIME` is Unix time: the header says
`MJDREFI = 40587`, and MJD 40587 *is* 1970-01-01. For example, 1744243200 seconds = 2025-04-10 00:00:00 UTC.

**MJD (Modified Julian Date).** Days since 1858-11-17, a decimal number. HEL1OS stores time as MJD, so we convert
it with `(MJD − 40587) × 86400` to get Unix seconds.

**UTC and time zones.** All our timestamps are UTC, never India time. A UTC-aware timestamp carries `+00:00`.
Mixing time zones is one of the most common data bugs.

**Time resolution trap (pandas 3).** pandas can store timestamps in seconds, milliseconds or nanoseconds. Our
SoLEXS index came out as `datetime64[s]`. The shortcut `.asi8` then returns *seconds*, while a Timestamp's
`.value` is always *nanoseconds*. Comparing the two silently matches nothing. That's why the code always
converts with `.as_unit("ns")` before comparing numbers.

**Data gap.** Missing time. We have three kinds:
- **Missing seconds:** NaN rows, or seconds outside the GTIs.
- **Low-coverage days:** for example the 17th of each month has only about 4 hours of data.
- **Missing days:** no folder at all.

We never fill gaps with invented values. Missing stays missing.

**Parquet.** A column-oriented, compressed file format for tables. Compared with CSV it is smaller, much faster to
read, and it keeps data types: a UTC timestamp stays a UTC timestamp, and float32 stays float32.

**Session versions (HEL1OS).** The same observation was sometimes processed twice (for example V211 and V311). We
keep only the newest version so the same seconds aren't counted twice.

## Tools used

| Tool | What it is | What it did here | Most useful commands |
|---|---|---|---|
| **astropy** | Core astronomy library | Opens FITS files, even `.gz` compressed ones | `fits.open(path)`, `hdul.info()`, `hdul[1].header`, `hdul[1].columns`, `hdul[1].data["TIME"]` |
| **numpy** | Fast arrays | Holds the columns and builds masks | `np.asarray`, `np.isnan`, boolean masks `a & b` |
| **pandas** | Tables with labelled rows/columns | UTC time index, cleaning, Parquet | `pd.to_datetime(t, unit="s", utc=True)`, `df.to_parquet()`, `pd.read_parquet()`, `df.index.dtype` |
| **pyarrow** | Engine behind Parquet in pandas | Writes and reads `.parquet` | used automatically by `to_parquet` |
| **re (regex)** | Pattern matching on text | Reads dates and versions from folder names | `re.compile(r"AL1_SLX_L1_(\d{8})_v([\d.]+)$")` |

## Code walkthrough

### `src/solexs.py`

```python
_DAY_RE = re.compile(r"AL1_SLX_L1_(\d{8})_v([\d.]+)$")                       # line 18
```
A regex that matches folder names like `AL1_SLX_L1_20250410_v1.0`. The first group captures the date
(`20250410`), the second the version (`1.0`).

```python
def read_lightcurve(path: Path) -> pd.DataFrame:                             # line 52
    with fits.open(path) as h:                                               # line 54
        d = h["RATE"].data                                                   # line 55
        t = np.asarray(d["TIME"], dtype="float64")                           # line 56
        c = np.asarray(d["COUNTS"], dtype="float64")
    idx = pd.to_datetime(t, unit="s", utc=True)                              # line 58
    return pd.DataFrame({"counts": c}, index=pd.DatetimeIndex(idx, name="time"))
```
- **Line 54:** `with` closes the file automatically, even if an error occurs. astropy reads `.gz` directly.
- **Line 55:** take the HDU named `RATE` (we checked the name with `hdul.info()` before writing this).
- **Line 56:** copy the column into a plain float64 numpy array.
- **Line 58:** the key line. Unix seconds become real UTC timestamps. `unit="s"` must match what the header
  says (`TIMEUNIT = 's'`).

```python
def gti_mask(index, gti):                                                    # line 73
    t = index.as_unit("ns").asi8                                             # line 75
    mask = np.zeros(len(index), dtype=bool)
    for s, e in zip(gti["start"].dt.as_unit("ns").astype("int64"), gti["stop"].dt.as_unit("ns").astype("int64")):
        mask |= (t >= s) & (t <= e)                                          # line 78
    return mask
```
- **Line 75:** the unit-trap fix. Both sides are converted to nanoseconds before comparing.
- **Line 78:** `|=` means "OR into the mask". A second is good if it lies in *any* GTI interval.

```python
    nan = lc["counts"].isna().to_numpy()                                     # line 91
    in_gti = gti_mask(lc.index, gti)
    valid = ~nan & in_gti                                                    # line 93
    out = lc.loc[valid].copy()                                               # line 94
    ...
        "valid_fraction": float(valid.sum() / 86400.0),                      # line 102
```
- **Line 93:** a second is valid only if it has a number *and* lies inside a GTI.
- **Line 94:** keep only valid seconds. Gaps become *absent rows*; nothing is filled in.
- **Line 102:** the share of the day that is usable. In `params.yaml`, `min_valid_fraction: 0.5` drops days below 50%.

### `src/hel1os.py`

```python
            secs = (np.asarray(d["MJD"], dtype="float64") - 40587.0) * 86400.0   # line 83
            t = pd.to_datetime(np.round(secs, 3), unit="s", utc=True).as_unit("ms")
            ...
            cols[f"{det}_{band}"] = s[~s.index.duplicated()]                    # line 87
```
- **Line 83:** MJD → Unix seconds. HEL1OS headers have no time-system keywords, so we use the MJD column itself.
- **Line 87:** one column per detector and band (for example `cdte1_5-20keV`), with any duplicate timestamps dropped.

```python
    for s in sorted(sessions, key=lambda x: (x.start, -x.version, -x.duration_s)):   # line 54
        dup = next((k for k in kept if abs((k.start - s.start).total_seconds()) <= same_start_tol_s), None)
```
`newest_per_session`: two folders starting within 60 s of each other are the same observation, and only the
higher version survives.

### `src/goes.py` (the NOAA flare list, used in lesson 03)

The NOAA report text is parsed with a regex that only accepts `XRA  1-8A` lines (X-ray flares) and captures
begin/max/end times and the class (for example `C3.2`). Line 89, `e += pd.Timedelta(days=1)`, handles flares that
end after midnight (the end time is "smaller" than the begin time).

### `src/pipeline.py` → stage `solexs_clean`

For every complete day in the three periods, this stage:
- cleans it
- writes `data/processed/solexs_clean/YYYYMMDD.parquet` with float32 counts
- appends a row to `solexs_qc.csv`

It also builds `solexs_minute.parquet`, a continuous 1-minute grid. Missing minutes are NaN rows, so later code
can see where the gaps are.

## Hands-on

Activate the venv first (`.venv\Scripts\Activate.ps1`) and work from the project folder.

**1. Look inside a raw FITS file.**
```
python -c "from astropy.io import fits; h=fits.open(r'D:\MLOPS_CP\Data\SoLEXS\AL1_SLX_L1_20250410_v1.0\SDD2\AL1_SOLEXS_20250410_SDD2_L1.lc.gz'); h.info(); print(repr(h[1].header)[:1200])"
```
*Expected:* `PRIMARY` plus `RATE ... 86400R x 2C [D, D]`, and header cards including `TIMESYS = 'UTC'`,
`MJDREFI = 40587` and `TSTART = 1744243200.0`. *Worked if* you can point to the card that proves TIME is Unix time.

**2. Convert Unix time by hand.**
```
python -c "import pandas as pd; print(pd.to_datetime(1744243200, unit='s', utc=True)); print(pd.to_datetime(60651.0 - 40587, unit='D', utc=True))"
```
*Expected:* `2025-04-10 00:00:00+00:00` and `2024-12-07 00:00:00+00:00` (the second line converts the HEL1OS MJD 60651).

**3. Use our reader and find the NaN seconds.**
```
python -c "from src import solexs; d=[x for x in solexs.list_days() if x.date.strftime('%Y%m%d')=='20250410'][0]; lc=solexs.read_lightcurve(d.lc); print(lc.shape, lc.index.dtype, lc.counts.isna().sum())"
```
*Expected:* `(86400, 1) datetime64[s, UTC] 2`, meaning one full day with 2 NaN seconds. Notice the `[s]`: that's the unit trap from Concepts.

**4. Read a cleaned Parquet day and compare file sizes.**
```
python -c "import pandas as pd; df=pd.read_parquet('data/processed/solexs_clean/20250410.parquet'); print(df.shape, df.dtypes.to_dict()); print(df.head(3))"
dir data\processed\solexs_clean\20250410.parquet
```
*Expected:* `(86398, 1)` (2 NaN seconds removed) with `counts: float32`. The file is about 0.7 MB, a little bigger than the 0.27 MB raw `.lc.gz`, because it stores a full UTC timestamp for every row.

**5. Find the data gaps in the quality report.**
```
python -c "import pandas as pd; q=pd.read_csv('data/processed/solexs_qc.csv'); print(len(q), q.usable.sum()); print(q[~q.usable][['date','valid_fraction']].head(8))"
```
*Expected:* `452 424`, then low-coverage days such as `2025-04-17` with `valid_fraction` about `0.167`. Do you
see a pattern in the dates?

**6. HEL1OS real coverage.**
```
python -c "import pandas as pd; c=pd.read_csv('data/processed/hel1os/coverage.csv'); print(c[['session','nominal_duration_s','coverage_of_nominal']].sort_values('coverage_of_nominal').head(5))"
```
*Expected:* 23 sessions in the file. The worst one covers only about 38% of the duration its folder name promises.

## Break it on purpose

Use the wrong time unit and watch the dates go wrong.

1. In `src/solexs.py` line 58, change `unit="s"` to `unit="ms"`.
2. Run exercise 3 again, adding `print(lc.index[0])`.
3. *Expected:* a date in **January 1970**, because the same numbers read as milliseconds land about 20 days after
   1970-01-01. Nothing crashes, which is what makes this bug dangerous.
4. Undo: `git checkout -- src/solexs.py`, then `pytest tests/test_pipeline.py -q` (6 passed).

## Check yourself

1. What is an HDU, and in which HDU did we find the SoLEXS light-curve table?
2. Which header card tells you SoLEXS `TIME` is Unix time, and why?
3. Why does the code call `.as_unit("ns")` before comparing timestamps as integers?
4. Why do we drop invalid seconds instead of filling them with the average value?
5. Two HEL1OS folders `HLS_20240812_000006_..._V211` and `..._V311` exist. Which one do we keep, and why keep only one?

## Questions to discuss with my tutor

1. The 17th of every month has only about 4 hours of SoLEXS data. What could cause such a regular pattern, and
   how should a model treat these partial days?
2. We trust the GTI files completely. How could we check that a GTI file is itself correct?
3. Parquet versus a database (for example PostgreSQL or a time-series DB) for 40 million rows: when does each make
   sense in production?

## Key numbers

| What | Value |
|---|---|
| SoLEXS day folders on disk | 458 (2024-10-01 to 2026-09-13) |
| Day folders inside the three periods | 452 of 522 calendar days (70 days have no folder) |
| Usable days (≥ 50% valid) | 424 (28 low-coverage days dropped) |
| Rows per full day | 86,400 (1 per second) |
| Valid minutes on the 1-min grid | 591,660 of 751,680 (about 79%) |
| Cleaned SoLEXS Parquet | about 287 MB for 424 days |
| HEL1OS sessions | 27 found → 23 after keeping the newest version; mean coverage 90%, worst 38% |
| SoLEXS and HEL1OS overlap | **none** (HEL1OS stops at 2024-12-22) |
| Light curves exist for | SDD2 only |

---

<details>
<summary><b>Answers (spoiler — try first!)</b></summary>

1. A Header/Data Unit: a header of metadata cards plus a data block. The light curve is in HDU 1, named `RATE`.
2. `MJDREFI = 40587` (with `MJDREFF = 0`) sets time zero at MJD 40587, which is 1970-01-01 00:00 UTC, the Unix
   epoch. `TIMEUNIT = 's'` says the unit is seconds.
3. The SoLEXS index is stored in seconds, so `.asi8` returns seconds, while other values are in nanoseconds.
   Comparing different units silently gives wrong (empty) results.
4. Invented values would look like real observations. A model could learn from fake data and flares could be
   hidden or created. Missing data must stay visibly missing.
5. V311 is the newer processing. Keeping both would count the same seconds twice and mix two calibrations.

</details>
