# Project report: solar-flare nowcasting and forecasting from Aditya-L1, end to end

Every number below comes from a committed output file; the source is given in `docs/PRESENTATION_FACTS.md` (generated
from those files) unless stated. The machine-learning phase is frozen: nothing here was retrained or re-scored.

## 1. Problem
Solar flares are sudden bursts of X-rays that disturb radio communication, navigation and satellites. India's Aditya-L1
watches the Sun continuously from the L1 point, 1.5 million km away. Two of its instruments see flares directly:
**SoLEXS** (soft X-rays, 1-s light curves) and **HEL1OS** (hard X-rays, 5-150 keV, during observing sessions).

Every 10 seconds the system answers five questions:
| Target | Question |
|---|---|
| `now` | Is a flare happening now? (nowcast) |
| `c_30m`, `c_60m` | Will a flare of class C or above start within 30 / 60 minutes? |
| `m_30m`, `m_60m` | Will a flare of class M or above start within 30 / 60 minutes? |

Truth comes from the NOAA SWPC GOES flare list. The primary metrics are TSS and HSS (never accuracy, because flares are
rare: ≥M within 60 min is 2.8 % of rows).

## 2. Data
- SoLEXS: 424 usable days (≥ 50 % valid) from 2025-04-09 to 2026-09-12, 1-s cadence, SDD2 detector; 3.3 GB uncompressed.
- HEL1OS: 98 sessions after de-duplication, but overlapping usable SoLEXS rows only 4.7 % of the time, so it stays optional.
- GOES flares in tune + val with SoLEXS data: C 2,018, M 222, X 15.
- Problems found and fixed: truncated downloads, days with < 50 % data (excluded, never filled), missing NOAA reports
  (excluded), a seconds/nanoseconds unit bug, CRLF rewrites that broke DVC hashes, a HEL1OS parser that dropped bands, and
  one data-deletion mistake that led to a permanent "never delete data without asking" rule.

## 3. Method
- **Chronological splits only:** tune 2025-04-09…2026-01-31, validation …2026-05-31, test …2026-09-12 (scored once),
  holdout2 2026-09-13…2026-11-12 (locked by SHA-256 before any feature existed, scored once).
- **Causal features:** 44 base features from trailing windows of the SoLEXS light curve (rates, excess over background,
  ratios, slopes, activity context), plus optional HEL1OS and real-time detector outputs. A future-perturbation test proves
  no feature looks ahead. A causal-ordering bug (split detector segments visible a median 18 min early) was found and
  fixed at the source before holdout2.
- **GOES-style detector:** onset within a median of 1 minute of NOAA times (300-trial grid search on the tuning period only).
- **Models:** logistic regression, XGBoost and ensembles, compared on a rolling monthly protocol against persistence,
  rule and current-flux baselines with bootstrap intervals. The choice was frozen in git (`docs/FINAL_CHOICE.md`,
  `docs/FINAL_CHOICE_2.md`) before each one-time evaluation.

## 4. Results
### One-time test (2026-06-01…2026-09-12), TSS at the operating point with 95 % interval
| Target | Model | Test TSS | Best baseline |
|---|---|---|---|
| now | XGBoost | **0.758** [0.74, 0.78] | +0.090 over persistence |
| c_30m | ensemble | **0.358** [0.29, 0.42] | +0.342 over persistence |
| c_60m | XGBoost | **0.304** [0.23, 0.37] | +0.277 over rule |
| m_30m | logistic regression | **0.518** [0.34, 0.63] | +0.463 over rule |
| m_60m | logistic regression | **0.494** [0.33, 0.60] | +0.414 over persistence |

### Holdout2 (2026-09-13…2026-11-12, 11 usable days, 7 M flares)
- Nowcast **0.760** [0.69, 0.81] against a current-flux baseline of 0.564: the nowcast generalises.
- C forecasts 0.49 / 0.60 (30 / 60 min), about equal to the one-number current-flux baseline (0.49 / 0.60).
- M forecasts: only 7 M flares, so the results are **underpowered** and no claim is made from them.

### What the numbers mean
The nowcast is reliable: it detected every GOES-matched flare in the test (C 363/363, M 83/83, X 4/4; median delay 1.8 min
for C and M). The forecasts mostly recognise how active the Sun is; a simple current-flux rule does almost as well on
holdout2. M-flare alerts behave like an "active period" warning, with many false alarms (5.4 false alert episodes per day
for `m_60m` on the test). This is reported, not hidden.

## 5. The MLOps system
```
SoLEXS L1 day ─► Prefect daily_ingest ─► pandera contracts ─► pipeline features ─► 5 champion models ─► predictions store
                                                                                                              │
     Grafana ◄─ Prometheus ◄─ /metrics ─ FastAPI (frozen bundle) ◄────────────────────────────────────────────┘
                                              │
                         nginx + React website (3D landing page, console: latest, replay, performance, drift)
```
| Need | Tool | Where |
|---|---|---|
| Data and pipeline versions | Git + DVC (37 stages, 24 frozen) | `dvc.yaml`, `dvc.lock` |
| Experiment tracking, registry | MLflow (767 runs; champions with alias `champion`) | `mlflow.db`, MLflow server |
| Data contracts | pandera, inside the DVC data stages and the production flow | `src/validation/` |
| Orchestration | Prefect 3 (daily ingest, drift check, replay, challenger retraining that never moves the champion) | `flows/` |
| Serving | FastAPI + model bundle (models, thresholds, SHA-256) | `src/serving/`, `model_bundle/` |
| Drift | Evidently, daily | `flows/check_drift.py` |
| Monitoring | Prometheus metrics, 2 alert rules (both proven by drills), Grafana dashboard | `monitoring/` |
| Website | React 19, TypeScript, Tailwind 4, ECharts, three.js + GSAP | `frontend/` |
| Packaging | Docker images tagged with the git SHA; Docker Compose for the whole stack | `docker/`, `docker-compose.yml` |
| Kubernetes | kustomize manifests (probes, limits, ConfigMaps, Secrets, PVCs), kind locally and in CI | `k8s/` |
| CI | GitHub Actions, 5 jobs: lint + tests, full Compose e2e, kind deploy + rollout/rollback, Terraform validate, security scans | `.github/workflows/ci.yml` |
| Edge and security | Caddy (HTTP/auto-HTTPS), API key + rate limit + size limit on the API, CORS allow-list, non-root containers | `docker/caddy/`, `src/serving/security.py` |
| Alert routing | Alertmanager (e-mail via SMTP from env, log-only otherwise) | `monitoring/alertmanager/` |
| Backups | volume archives with SHA-256 manifest, verified restore | `scripts/backup.*`, `scripts/restore.*` |
| Load testing | k6 with SLO thresholds | `loadtest/k6.js`, `docs/SLO.md` |
| CD | GHCR images (git SHA + version), SSH deploy to k3s with automatic rollback | `.github/workflows/cd.yml` |
| Infrastructure as code | Terraform: AWS VM + k3s (validated, not applied) | `infra/terraform/` |

Safety rules built into the code: no flow reads data after the development end, the old test is never re-scored,
retraining only registers a challenger, all evaluation stages are frozen, and fault injection for alert drills cannot run in
production.

## 6. Verification (2026-11-14)
- `pytest`: 145 passed, 1 skipped (146 tests); `ruff`: clean. CI: 5 of 5 jobs green.
- `scripts\e2e.ps1`: passed (raw day in the inbox → Prefect deployment → contracts → features → champions → store → API →
  website; replay, drift, Prometheus, Grafana).
- Alerts: FlareApiDown fired after 135 s with the API stopped; FlareApiHighErrorRate fired with a 0.51 error ratio under
  50 % injected 503s (`docs/screenshots/`).
- CI on GitHub runs the same e2e script and deploys the manifests to kind on every push.
- Hardening (v1.1.0): API key, rate limit (429), body limit (413), Caddy HTTPS mode (local CA test), Alertmanager
  (fake and real alert delivered), backup → restore → identical registry and predictions, k6 50 users p95 8.3 ms with 0 %
  errors (SLO p95 < 300 ms, errors < 1 %), trivy 0 CRITICAL. Full table: `docs/PRODUCTION_READINESS.md`.

## 7. Limitations and next steps
- Research and teaching system: NOAA SWPC issues official alerts.
- M forecasts have high false-alarm ratios; a cost-based or FAR-capped threshold is needed before real use.
- Trained near solar maximum; drift is monitored because skill will change in quieter years.
- HEL1OS overlap is small, so the soft-vs-hard comparison is underpowered.
- Next: a fresh one-time evaluation on new production days before any champion change; calibrated probabilities in the
  API (isotonic, already measured); a public deployment once a server is provided (`docs/DEPLOY_STEPS.md`).
- Operational limits: SoLEXS L1 days are downloaded from ISRO PRADAN by hand; one node; HEL1OS covers about 5 % of
  rows; forecasts mostly read the current activity level; the M-class holdout sample is small.
