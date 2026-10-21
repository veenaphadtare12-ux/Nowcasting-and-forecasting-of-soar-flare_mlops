# Validation results

Validation period 2026-02-01 to 2026-05-31 (114 days). Models fitted on the tune period before 2025-11-30; thresholds chosen on 2025-12-01 to 2026-01-31. The test period was not opened.

Cells: TSS mean ± std over 3 seeds (LogReg, XGBoost; other models are deterministic) [95 % interval from 1000 bootstrap resamples of validation days]. Operating point A (threshold = max TSS on calibration). **Bold** = model selected for that target (highest mean TSS among Rule, LogReg, XGBoost).

## All rows

| Target | Climatology | Persistence | Rule | LogReg | XGBoost | Selected |
|---|---|---|---|---|---|---|
| nowcast | 0.000 [0.00, 0.00] | 0.657 [0.63, 0.68] | 0.634 [0.61, 0.66] | 0.678 ± 0.000 [0.66, 0.70] | **0.726 ± 0.002 [0.71, 0.74]** | XGBoost |
| ≥C in 30 min | 0.000 [0.00, 0.00] | 0.016 [-0.00, 0.04] | 0.034 [0.01, 0.06] | **0.196 ± 0.002 [0.14, 0.25]** | 0.151 ± 0.007 [0.10, 0.19] | LogReg |
| ≥C in 60 min | 0.000 [0.00, 0.00] | 0.013 [-0.00, 0.03] | 0.031 [0.01, 0.06] | **0.194 ± 0.002 [0.14, 0.25]** | 0.192 ± 0.005 [0.13, 0.25] | LogReg |
| ≥C in 120 min | 0.000 [0.00, 0.00] | 0.026 [0.01, 0.04] | 0.032 [0.01, 0.06] | 0.263 ± 0.001 [0.20, 0.33] | **0.263 ± 0.003 [0.20, 0.33]** | XGBoost |
| ≥M in 30 min | 0.000 [0.00, 0.00] | 0.108 [0.06, 0.16] | 0.050 [0.01, 0.08] | **0.478 ± 0.001 [0.34, 0.58]** | 0.423 ± 0.009 [0.29, 0.52] | LogReg |
| ≥M in 60 min | 0.000 [0.00, 0.00] | 0.089 [0.05, 0.13] | 0.139 [0.08, 0.20] | **0.454 ± 0.003 [0.28, 0.60]** | 0.328 ± 0.007 [0.21, 0.43] | LogReg |
| ≥M in 120 min | 0.000 [0.00, 0.00] | 0.076 [0.04, 0.11] | 0.113 [0.06, 0.16] | **0.382 ± 0.000 [0.19, 0.55]** | 0.342 ± 0.005 [0.17, 0.50] | LogReg |

## Quiet-start rows (no flare in progress at t)

| Target | Climatology | Persistence | Rule | LogReg | XGBoost | Selected |
|---|---|---|---|---|---|---|
| nowcast | 0.000 [0.00, 0.00] | 0.000 [0.00, 0.00] | 0.297 [0.26, 0.33] | 0.406 ± 0.000 [0.38, 0.43] | **0.448 ± 0.003 [0.43, 0.47]** | XGBoost |
| ≥C in 30 min | 0.000 [0.00, 0.00] | 0.000 [0.00, 0.00] | 0.019 [-0.00, 0.04] | **0.193 ± 0.003 [0.14, 0.25]** | 0.155 ± 0.007 [0.11, 0.20] | LogReg |
| ≥C in 60 min | 0.000 [0.00, 0.00] | 0.000 [0.00, 0.00] | 0.018 [-0.00, 0.04] | **0.193 ± 0.002 [0.14, 0.25]** | 0.192 ± 0.005 [0.13, 0.25] | LogReg |
| ≥C in 120 min | 0.000 [0.00, 0.00] | 0.000 [0.00, 0.00] | 0.010 [-0.01, 0.04] | 0.263 ± 0.001 [0.20, 0.33] | **0.263 ± 0.003 [0.20, 0.33]** | XGBoost |
| ≥M in 30 min | 0.000 [0.00, 0.00] | 0.000 [0.00, 0.00] | 0.026 [-0.00, 0.05] | **0.475 ± 0.001 [0.32, 0.60]** | 0.407 ± 0.011 [0.26, 0.52] | LogReg |
| ≥M in 60 min | 0.000 [0.00, 0.00] | 0.000 [0.00, 0.00] | 0.070 [0.03, 0.12] | **0.438 ± 0.003 [0.25, 0.60]** | 0.314 ± 0.007 [0.19, 0.42] | LogReg |
| ≥M in 120 min | 0.000 [0.00, 0.00] | 0.000 [0.00, 0.00] | 0.067 [0.01, 0.12] | **0.377 ± 0.000 [0.18, 0.55]** | 0.338 ± 0.006 [0.17, 0.49] | LogReg |

## Operating points (all rows, mean over seeds)

A = threshold maximising TSS on calibration; B = threshold maximising HSS on calibration (fewer false alarms).
POD = share of flares warned; FAR = share of alerts that were false.

| Target | Model | A: POD | A: FAR | A: TSS | A: HSS | B: POD | B: FAR | B: TSS | B: HSS |
|---|---|---|---|---|---|---|---|---|---|
| nowcast | Persistence | 0.68 | 0.34 | 0.66 | 0.64 | 0.68 | 0.34 | 0.66 | 0.64 |
| nowcast | Rule | 0.77 | 0.71 | 0.63 | 0.36 | 0.70 | 0.60 | 0.62 | 0.46 |
| nowcast | LogReg | 0.80 | 0.67 | 0.68 | 0.40 | 0.67 | 0.52 | 0.62 | 0.52 |
| nowcast | XGBoost | 0.81 | 0.57 | 0.73 | 0.51 | 0.66 | 0.30 | 0.64 | 0.66 |
| ≥C in 30 min | Persistence | 0.09 | 0.86 | 0.02 | 0.02 | 0.09 | 0.86 | 0.02 | 0.02 |
| ≥C in 30 min | Rule | 0.23 | 0.86 | 0.03 | 0.03 | 0.21 | 0.86 | 0.03 | 0.02 |
| ≥C in 30 min | LogReg | 0.45 | 0.81 | 0.20 | 0.12 | 0.19 | 0.78 | 0.10 | 0.11 |
| ≥C in 30 min | XGBoost | 0.33 | 0.80 | 0.15 | 0.12 | 0.14 | 0.78 | 0.07 | 0.09 |
| ≥C in 60 min | Persistence | 0.08 | 0.75 | 0.01 | 0.02 | 0.08 | 0.75 | 0.01 | 0.02 |
| ≥C in 60 min | Rule | 0.21 | 0.76 | 0.03 | 0.03 | 0.21 | 0.76 | 0.03 | 0.03 |
| ≥C in 60 min | LogReg | 0.41 | 0.65 | 0.19 | 0.18 | 0.25 | 0.62 | 0.14 | 0.16 |
| ≥C in 60 min | XGBoost | 0.37 | 0.64 | 0.19 | 0.19 | 0.27 | 0.61 | 0.15 | 0.17 |
| ≥C in 120 min | Persistence | 0.09 | 0.57 | 0.03 | 0.03 | 0.09 | 0.57 | 0.03 | 0.03 |
| ≥C in 120 min | Rule | 0.36 | 0.63 | 0.03 | 0.03 | 0.36 | 0.63 | 0.03 | 0.03 |
| ≥C in 120 min | LogReg | 0.50 | 0.47 | 0.26 | 0.27 | 0.49 | 0.46 | 0.26 | 0.27 |
| ≥C in 120 min | XGBoost | 0.48 | 0.46 | 0.26 | 0.27 | 0.47 | 0.45 | 0.26 | 0.27 |
| ≥M in 30 min | Persistence | 0.18 | 0.97 | 0.11 | 0.03 | 0.18 | 0.97 | 0.11 | 0.03 |
| ≥M in 30 min | Rule | 0.08 | 0.96 | 0.05 | 0.03 | 0.07 | 0.96 | 0.04 | 0.03 |
| ≥M in 30 min | LogReg | 0.76 | 0.96 | 0.48 | 0.04 | 0.39 | 0.87 | 0.35 | 0.18 |
| ≥M in 30 min | XGBoost | 0.70 | 0.97 | 0.42 | 0.04 | 0.38 | 0.94 | 0.30 | 0.08 |
| ≥M in 60 min | Persistence | 0.16 | 0.95 | 0.09 | 0.05 | 0.16 | 0.95 | 0.09 | 0.05 |
| ≥M in 60 min | Rule | 0.28 | 0.95 | 0.14 | 0.04 | 0.05 | 0.95 | 0.03 | 0.03 |
| ≥M in 60 min | LogReg | 0.64 | 0.92 | 0.45 | 0.10 | 0.59 | 0.91 | 0.44 | 0.12 |
| ≥M in 60 min | XGBoost | 0.58 | 0.95 | 0.33 | 0.06 | 0.21 | 0.88 | 0.17 | 0.13 |
| ≥M in 120 min | Persistence | 0.15 | 0.92 | 0.08 | 0.06 | 0.15 | 0.92 | 0.08 | 0.06 |
| ≥M in 120 min | Rule | 0.43 | 0.94 | 0.11 | 0.03 | 0.18 | 0.92 | 0.09 | 0.05 |
| ≥M in 120 min | LogReg | 0.56 | 0.88 | 0.38 | 0.14 | 0.40 | 0.77 | 0.34 | 0.26 |
| ≥M in 120 min | XGBoost | 0.54 | 0.89 | 0.34 | 0.12 | 0.31 | 0.78 | 0.26 | 0.22 |

Climatology always forecasts the training positive rate, so it never crosses a threshold: TSS = 0 by construction.
