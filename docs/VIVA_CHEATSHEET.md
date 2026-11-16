# Viva cheat sheet (one page)

## Architecture in 5 lines
1. **Data → models (frozen):** Aditya-L1 SoLEXS (+ optional HEL1OS) → DVC pipeline (37 stages, pandera contracts, causal
   features) → models tracked in MLflow (767 runs) → 5 champions exported to a signed model bundle.
2. **Serving:** FastAPI (frozen bundle, API key, rate limit) behind nginx and Caddy (HTTPS); React website with a 3D landing page.
3. **Operations:** Prefect runs ingest → contracts → features → champions → store nightly; Evidently checks drift daily.
4. **Monitoring:** Prometheus (2 alert rules, both proven firing) → Alertmanager (e-mail) and Grafana.
5. **Delivery:** Docker images tagged with the git SHA → Compose locally, kind in CI, k3s via CD (GHCR, automatic
   rollback); Terraform for the server.

## 10 likely questions
1. **Why TSS, not accuracy?** Flares are rare (≥M within 60 min = 2.8 % of rows); TSS = hit rate − false-alarm rate ignores the imbalance.
2. **How did you avoid leakage?** Time splits only, trailing features, labels after the input window, a future-perturbation test, test and holdout2 scored once after freezing the choice in git.
3. **Results?** Test TSS: nowcast 0.758, c_30m 0.358, c_60m 0.304, m_30m 0.518, m_60m 0.494. Holdout2 nowcast 0.760 [0.69, 0.81]; M underpowered (7 flares).
4. **Are the forecasts useful?** The nowcast clearly is; the forecasts mostly read the activity level, and a current-flux baseline is close on holdout2. I say so.
5. **What happens when new data arrives?** Prefect `daily_ingest`: contracts → same feature code as training → champions → store → website. Proven end to end by `e2e.ps1`.
6. **How is a model promoted?** Never automatically: retraining registers a challenger only (proven: challenger v4, champion still v1); promotion needs a fresh one-time evaluation.
7. **How do you know it is healthy?** Prometheus scrapes `/metrics`; FlareApiDown fired after 135 s and the error-rate alert at a 0.51 ratio in drills; Alertmanager received them.
8. **How do you deploy safely?** maxUnavailable 0 + readiness probes + preStop: 67 requests, 0 failed during an update; a bad image never goes live and `rollout undo` runs automatically.
9. **How is it secured?** API key on `/predict`, 429 rate limit, 413 size limit, CORS allow-list, only Caddy public, non-root containers, secrets only in GitHub/.env, trivy 0 CRITICAL.
10. **What would you improve?** Terraform-applied infrastructure (blocked by the free plan's SCP), zero-downtime deploys on the server, MLflow upgrade (3 accepted CVEs), automatic PRADAN download, multi-node storage, calibrated probabilities in the API.

## Demo order (10 minutes)
Live site: **https://veena-flare.duckdns.org** (start the EC2 instance ~3 minutes before if it was stopped).
1. `.\scripts\up.ps1 -NoBuild` then `.\scripts\smoke_test.ps1` (before the viva).
2. http://localhost → landing page, scroll to the X-class day.
3. http://localhost/replay → play a day. http://localhost/performance → results with baselines.
4. http://localhost:4200 Prefect runs → http://localhost:5000 MLflow champions.
5. http://localhost:3000 Grafana → http://localhost:9090/alerts → http://localhost:9093 Alertmanager.
6. GitHub Actions: 5 green jobs. `docs/PRODUCTION_READINESS.md`: PASS / FAIL / NOT RUN with proof.
Fallback: `docs/screenshots/`.

## Numbers
424 SoLEXS days · 44 base features · 146 tests · 5 CI jobs · load test 50 users p95 8.3 ms, 0 % errors · backup 8 volumes
restored identical.
