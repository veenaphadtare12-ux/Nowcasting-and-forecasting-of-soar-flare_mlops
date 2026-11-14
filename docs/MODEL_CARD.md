# Model card — Aditya-L1 solar-flare nowcast and forecast models

> **Current state (2026-11-14, release v1.1.0).** This document is a dated record and its older counts are kept as they
> were. Today: 146 tests (145 pass, 1 skipped; CI runs 140 data-free ones), 37 DVC stages (24 frozen), 767 MLflow runs,
> 5 champions (alias `champion`, version 1). Final metrics are unchanged: test TSS nowcast 0.758, c_30m 0.358,
> c_60m 0.304, m_30m 0.518, m_60m 0.494; holdout2 nowcast 0.760 [0.69, 0.81] (M targets underpowered).
> Operations: `docs/PRODUCTION_READINESS.md`.

## Version 2 (added 2026-11-13): FINAL_CHOICE_2 models, scored once on holdout2

**What changed since v1.**
- **A0 audit:** the v1 isotonic calibrators, all thresholds and all feature/model choices were fitted or chosen on
  development data (May 2026 threshold block; rolling protocol 2025-08…2026-05). Nothing used the old test period, so
  the v1 test numbers below (including the calibrated Brier scores) stay valid.
- **Causal-ordering fix:** split detector events used to become visible a median 18 min (max 155 min) too early. Fixed at
  the source (`docs/IMPROVEMENTS.md` section 8). The v1 c_30m model used the affected E2 features, so its v1 test
  number carries this small defect. After the fix the same configuration still passes the acceptance rule (0.168 → 0.218,
  13 of 14 months), so the gain is real.
- **Development data now includes the old test months** (14 rolling months, 2025-08 … 2026-09).

| Target | Model (champion, `models_final2/<target>_aditya.joblib`) | Inputs | Development: mean monthly / pooled TSS | **Holdout2 TSS at A [95 %]** | Current-flux baseline on holdout2 |
|---|---|---|---|---|---|
| now | XGBoost | 44 base (Aditya-only) | 0.719 / 0.722 | **0.760** [0.69, 0.81] | 0.564 (persistence 0.661) |
| c_30m | LogReg + XGBoost average | 44 base + E2 + E3 + E5 = 67 | 0.218 / 0.237 | **0.486** [0.22, 0.67] | 0.493 |
| c_60m | XGBoost | 44 base | 0.214 / 0.229 | **0.603** [0.33, 0.78] | 0.596 |
| c_120m | XGBoost | 44 base | 0.222 / 0.239 | **0.729** [0.48, 0.87] | 0.706 |
| m_30m | Logistic regression | 44 base | 0.240 / 0.387 | 0.307 [−0.47, 0.50] — UNDERPOWERED | 0.350 |
| m_60m | Logistic regression | 44 base | 0.242 / 0.409 | 0.332 [−0.43, 0.54] — UNDERPOWERED | 0.392 |
| m_120m | XGBoost | 44 base | 0.233 / 0.359 | 0.448 [−0.27, 0.70] — UNDERPOWERED | 0.408 |

- **Training:**
  - Fit: development rows before 2026-08-01.
  - Isotonic calibration: August 2026.
  - Thresholds: 2026-09-01 … 09-12. A = max TSS; M targets also C (FAR ≤ 0.80) and K10 (cost). C and K10 never alert:
    this was known and stated before holdout2.
- **Where it is recorded:** frozen in `docs/FINAL_CHOICE_2.md` (commit b5e2044) with the SHA-256 of every model file.
  Code: `src/dev2/final.py`, DVC stage `dev2_final`. MLflow experiment `flare-final2`.
- **"With GOES" variants** (`*_with_goes.joblib`) are frozen too, for comparison. GOES-derived inputs never passed the
  acceptance rule on their own, and on holdout2 they change TSS only inside the noise.
- **Holdout2:**
  - 11 days (2026-09-13, 2026-10-30 … 11-10 without 11-03/04), with 118 C and 7 M flares.
  - Locked by SHA-256 before any feature existed (`docs/HOLDOUT2_LOCK.md`) and scored once by the stage
    `evaluate_holdout2` (`reports/holdout2/`).
- **R1, early class prediction** (`models_final2/r1_k<k>_<inputs>.joblib`): LogReg per k = 0, 1, 2, 3, 5 min after the
  detector trigger.
  - Development ≥M TSS 0.44 → 0.67 as k grows (current-flux baseline 0.44 → 0.65).
  - Holdout2 has only 7 ≥M triggers (UNDERPOWERED).

**How to read the v2 holdout2 numbers.** The 11 days are one quiet stretch and one very active stretch. Both the models
and a single "current flux" threshold separate the two:
- Pooled TSS is high: 0.49–0.73 for C.
- On active days alone TSS is about 0, because the models alert almost all the time there.
- November alone gives 0.31–0.56.

**The nowcast is the only clearly confirmed skill.** The forecasts do not beat the current-flux baseline on holdout2, and
on development data they beat it by only 0.01–0.04 TSS (≥C) or not at all (≥M). Calibration: raw M probabilities are far
too high (Brier 0.16–0.19 vs climatology 0.01–0.05). Use the isotonic outputs (Brier ≈ climatology).

---

## Version 1 (champions of `docs/FINAL_CHOICE.md`, one-time test 2026-06-01 → 2026-09-12)

## Models
| Registry name (alias `champion`) | Target | Model | Inputs |
|---|---|---|---|
| `flare-nowcast` | GOES-listed flare in progress now | XGBoost | 44 base features |
| `flare-forecast-c30` | ≥C flare starts within 30 min | LogReg + XGBoost probability average | 44 base + long-context (E2) + drift-normalised (E3) + spectral (E5) = 67 |
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
- **v1:** `dvc repro test_analysis` (the frozen models are cached; the stage is DVC-frozen since 2026-11-13). The test
  was scored by the single stage `evaluate_test`.
- **v2:** run `dvc repro dev2_final`. Holdout2 is scored only by `evaluate_holdout2`, which refuses to run unless
  `docs/FINAL_CHOICE_2.md` is committed, the model hashes match, and the holdout2 files match `docs/HOLDOUT2_LOCK.md`.
- **Tests:** `pytest tests/test_final.py tests/test_holdout2_lock.py tests/test_holdout2_pipeline.py`.
