# Data card — Aditya-L1 solar-flare dataset (10-second rows)

## Summary
- **What one row is:** one 10-second time step, carrying:
  - **44 trailing features**: 27 from SoLEXS soft X-rays and 17 from HEL1OS hard X-rays (optional);
  - **labels**: is a GOES-listed flare in progress now, and will a ≥C or ≥M flare start within 30/60/120 min;
  - **"trust this label" flags** (`ok_*`) and a causal "flare in progress" flag.
- **Built by:** the DVC pipeline (`dvc.yaml`, stages `solexs_clean` → `build_dataset`).
- **Location:** `data/processed/dataset/{tune,val,test}.parquet`.

| Period | Dates (UTC) | Rows | Usable SoLEXS days | Use |
|---|---|---|---|---|
| tune | 2025-04-09 … 2026-01-31 | 1,936,953 | 231 | fit, detector tuning, thresholds |
| val | 2026-02-01 … 2026-05-31 | 816,920 | 100 | model selection, improvement experiments |
| test | 2026-06-01 … 2026-09-12 | 792,482 | 93 | **one** final evaluation (`evaluate_test`) |

Sources: `reports/dataset_summary.json`, `data/processed/solexs_qc.csv`.

## Sources
| Source | What | How it is used | Notes |
|---|---|---|---|
| Aditya-L1 **SoLEXS** SDD2 L1 (ISRO; downloaded archives kept in `D:/MLOPS_CP/Data/original_zips`) | 1-s light curves (`.lc`), good-time intervals (`.gti`), 1-s 340-channel spectra (`.pi`) | Features; flare detector; spectral temperature proxy (improvement idea E5) | Raw files are never modified. Days with < 50% valid seconds are excluded; the 17th of every month is only about 11% covered. |
| Aditya-L1 **HEL1OS** L1 (ISRO) | Hard X-ray light curves (CdTe 5–20 keV, CZT 20–40/40–150 keV) for observing sessions | Optional features (`hx_*`, `hel1os_available`) | Covers only 4.7% of tune+val rows. Missing values are kept missing (median imputer + missing indicator in LogReg). |
| **NOAA SWPC** daily event reports (`src/goes.py`, `data/external/goes_events`) | GOES flare list: begin, peak, end, class | **Labels only** | No report for 2025-12-30 and 2025-12-31: those days have `ok = 0` (excluded from evaluation). |
| **NOAA NCEI GOES-19 XRS L2** 1-min averages (`data/external/goes_xrs`, `goes_xrs_test`) | XRS-A/B flux (W/m²) | Improvement idea E6 (m_30m model only); NOAA M1-crossing time for the lead-time analysis | Quality flag 0 only; each minute is labelled at its end. Tune/val files and test files are separate downloads. |

## Labels
- **Nowcast `y_now`:** 1 while a GOES-matched detector event is in progress.
- **Forecast `y_c_*`, `y_m_*`:** 1 if a GOES flare of at least that class starts in (t, t + h].
  - Start = the SoLEXS onset of the detection the flare is the primary match of; otherwise the GOES begin time
    (`src/labels.py`, `goes_onsets`).
- **`ok_*` flags** mark rows whose label can be trusted:
  - full GOES coverage of the look-ahead window;
  - not crossing a period boundary;
  - not on a day without a NOAA report.

## Known issues and biases
- **Solar maximum:** 155–368 GOES flares per month (`reports/eda_numbers.json`). Models trained here may
  over-predict in quieter years.
- **Non-stationary data:** the background level drifts about 2.4× over the period, and flare rates change month to
  month.
- **Rare events:** ≥M within 60 min is about 2–4% of rows, and test-period M flares are few, so M results have wide
  intervals.
- **The labels come from GOES, a different instrument.** The detector misses most B flares (recall 0.18) and some
  C flares on a high background.
- **Coverage gaps:** 23.7% of minutes are missing in tune+val. Gaps are never filled.
- **Features are causal** (trailing windows only); future-perturbation tests check this for every feature.

## Access and licensing
- **Aditya-L1 data:** ISRO open data, obtained via ISRO's data portal. Follow ISRO's data-use terms when sharing.
- **NOAA data:** public US government products.
- **Not in git:** raw and processed data are tracked by DVC, with the cache on `D:/dvc-cache`.
