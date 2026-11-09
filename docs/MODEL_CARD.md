# Model card — Aditya-L1 solar-flare nowcast and forecast models (champions, v1)

## Models
| Registry name (alias `champion`) | Target | Model | Inputs |
|---|---|---|---|
| `flare-nowcast` | GOES-listed flare in progress now | XGBoost | 44 base features |
| `flare-forecast-c30` | ≥C flare starts within 30 min | LogReg + XGBoost probability average | 44 base + long-context (E2) + drift-normalised (E3) + spectral (E5) = 64 |
| `flare-forecast-c60` | ≥C flare starts within 60 min | XGBoost | 44 base |
| `flare-forecast-m30` | ≥M flare starts within 30 min | Logistic regression | 44 base + spectral (E5) + GOES XRS (E6) = 56 |
| `flare-forecast-m60` | ≥M flare starts within 60 min | Logistic regression | 44 base |

**Training:**
- Fit on 2025-04-09 → 2026-04-30 (`ok` rows, 1 per minute, seed 42).
- Thresholds and isotonic calibration from May 2026.
- The choice was frozen before the test: `docs/FINAL_CHOICE.md`, commit `d31d6ab`.
- Code: `src/final/freeze.py`, DVC stage `final_models`.
- Registry: MLflow (`mlflow.db`). Every version carries tags for target, thresholds A/B/C, fit dates, git commit,
  `dvc.lock` hash and the test TSS, plus a signature and an input example.
- Load with `src/models/load_production.py` (`load_production(name, alias="champion")`). The output is
  `[P(no), P(yes)]`; alert when P(yes) ≥ the `thr_A` tag.

## Intended use
- **Research and teaching:** how much skill Aditya-L1 SoLEXS (plus optional HEL1OS) soft and hard X-ray data
  carry for short-term flare nowcasting and forecasting near solar maximum.
- **A decision aid** next to official services, e.g. a "heightened flare risk" indicator.

**Not intended** as an operational alert system. NOAA SWPC issues the official alerts, and these models were not
validated for operational use (see the limits below).

## Evaluation (one-time test, 2026-06-01 → 2026-09-12, 101 days; `reports/final/test_metrics.json`)
TSS at operating point A (threshold that maximised TSS in May 2026), with 95% day-bootstrap intervals (1,000
resamples).

| Target | Test TSS [95%] | Quiet-start TSS | HSS | POD | FAR | Share of time alerting | Best baseline TSS | Paired p vs baseline / vs runner-up |
|---|---|---|---|---|---|---|---|---|
| now | **0.758** [0.74, 0.78] | 0.548 | 0.457 | 0.87 | 0.64 | 17% | persistence 0.668 | ≤ 0.001 / ≤ 0.001 (+0.016) |
| c_30m | **0.358** [0.29, 0.42] | 0.372 | 0.177 | 0.69 | 0.79 | 37% | persistence 0.017 | ≤ 0.001 / ≤ 0.001 (+0.091) |
| c_60m | **0.304** [0.23, 0.37] | 0.311 | 0.196 | 0.74 | 0.70 | 49% | rule 0.027 | ≤ 0.001 / 0.61 (−0.007) |
| m_30m | **0.518** [0.34, 0.63] | 0.534 | 0.070 | 0.76 | 0.95 | 25% | rule 0.055 | ≤ 0.001 / 0.27 (+0.013) |
| m_60m | **0.494** [0.33, 0.60] | 0.497 | 0.103 | 0.78 | 0.91 | 31% | persistence 0.080 | ≤ 0.001 / 0.15 (+0.005) |

Notes:
- **Operating point B** (max HSS) roughly halves FAR for the M models, at lower POD (m_60m: POD 0.51, FAR 0.78).
- **Operating point C** (FAR ≤ 0.80) is degenerate: for C targets it alerts on everything, and for M targets it
  never alerts.
- Sources: `reports/final/test_metrics.json` → `targets.<t>.metrics.chosen.{A,B,C}`, `paired`.

**Per flare** (`reports/final/analysis.json` → `event_based`):

| Model | Flares (test) | Hit rate |
|---|---|---|
| m_60m | 79 M | 0.90 |
| m_60m | 3 X | 1.00 |
| c_60m | 434 C | 0.88 |
| c_60m | 79 M | 0.95 |
| nowcast | all GOES-matched detector events | 1.00, median delay about 2 min after onset |

**But most warnings were already on when the look-ahead window opened** (m_60m: 65 of 71 warned M flares). For the
few alerts that switched on inside the window, the median lead was about 50 min (m_60m, 6 flares).

**Lead over NOAA's M1 moment** (`operational_lead`):
- All 82 M/X flares with SoLEXS data were preceded by an m_60m alert within 2 h.
- 70 of those 82 alerts were part of an alert episode that was already running; the 12 new alerts came a median
  52 min before the M1 crossing.

**Calibration** (`calibration`):
- Raw probabilities are much too high, because training used class balancing (Brier score worse than climatology
  for every target).
- After isotonic calibration fitted on May 2026, Brier beats climatology for every target: e.g. m_60m 0.0315 vs
  0.0334, now 0.031 vs 0.065.
- Isotonic calibration doesn't change the alerts.

**Rolling 10-month evaluation, for comparison:** mean monthly TSS was lower (m_60m 0.26 ± 0.17), see
`docs/IMPROVEMENTS.md`.
- The test is close to the original validation-block numbers (m_60m 0.49 vs 0.47).
- The rolling mean is pulled down by a few months with almost no skill (m_60m: Aug 2025 0.01, Mar 2026 −0.05).
- So skill depends strongly on the month, and a single 3.5-month test cannot show how bad a quiet month can be.

## Limits and caveats
- **Many false alarms for M flares:** FAR 0.91–0.95 at A, about 5 false alert episodes per day, about 400 false-alarm
  hours over the 101-day test (`errors.alert_episodes`). The models mainly recognise *active periods*, not the
  specific minutes before a flare.
- **Impulsive flares from a quiet background are missed** (8 M flares, `docs/final_figures/missed_m_flares.png`).
  Nothing in the X-ray light curve precedes them.
- **Wide intervals for M targets** ([0.33, 0.60]): the test has few M flares, and they cluster in a few active weeks.
- **Solar-maximum data only:** skill and calibration will change in quieter years. Monitoring and recalibration
  would be needed.
- **External dependency:** `flare-forecast-m30` uses GOES XRS (E6), which arrives with a delay in real time; our
  test used reprocessed L2 data.
- **The labels come from the NOAA GOES flare list,** not from Aditya-L1 itself, and the activity flag comes from our
  own detector.
- **The 120-min models** (c_120m, m_120m) were not part of this release.

## Ethical and operational considerations
- **False reassurance is the main risk.** Missed impulsive flares mean "no alert" ≠ "no flare". Never use the
  model as the only basis for protecting satellites, aviation or communications.
- **Alert fatigue:** at operating point A the M models alert 25–31% of the time. Users should prefer operating
  point B or use calibrated probabilities.
- **No personal data is involved.** All inputs are public scientific data (ISRO, NOAA).

## How to reproduce
`dvc repro test_analysis` (the frozen models are cached). The test is scored by the single stage `evaluate_test`.
Tests: `pytest tests/test_final.py`.
