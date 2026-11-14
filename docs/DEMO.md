# DEMO: 10-minute live demo script

Before the audience arrives (5 minutes):
```
.\scripts\up.ps1 -NoBuild        # or .\scripts\up.ps1 if the code changed
.\scripts\smoke_test.ps1         # must end with "all checks passed"
```
Open these tabs in order: http://localhost:8080, http://localhost:8080/replay, http://localhost:4200/runs,
http://localhost:5000/#/models, http://localhost:3000, http://localhost:9090/alerts, the GitHub Actions page.
Fallback if anything fails live: the screenshots in `docs/screenshots/`.

| Time | Show | Say |
|---|---|---|
| 0:00 | Landing page `/`, scroll slowly | "Aditya-L1 sits 1.5 million km away. SoLEXS and HEL1OS measure the Sun's X-rays. Every 10 seconds our models say whether a flare is happening and whether one is coming in 30 or 60 minutes." |
| 1:00 | Keep scrolling to the X-class day | "This is 24 April 2026, an X-class day, replayed from the real data: the light curve, the model probabilities, the thresholds, and the alerts. Scrolling moves time." |
| 2:00 | Pipeline and results sections | "The pipeline badges are live from the API. The results are the frozen one-time scores next to the best simple baseline: we never hide the baseline." |
| 3:00 | Console → Replay, press play | "The console replays any development day minute by minute with the frozen champions. It is a demo, not an evaluation." |
| 4:00 | Console → Performance, Data & drift | "Nowcast TSS 0.76 on the test and on holdout2. Forecasts mostly recognise the activity level; M results on holdout2 are underpowered and we say so. Drift is checked every day with Evidently." |
| 5:00 | Prefect runs | "Prefect runs the production flow every night: data contracts, features, champions, predictions store. Here are the runs from the end-to-end test." |
| 6:00 | MLflow registry | "Five registered models, each with the alias champion. Retraining can only register a challenger; promotion is a manual decision after a fresh evaluation." |
| 7:00 | Grafana | "Prometheus scrapes the API: request rate, latency, errors, alerts per target. You can see the two alert drills we ran on purpose." |
| 8:00 | Prometheus alerts, `docs/screenshots/prometheus_alert_*.jpg` | "Both alert rules were proven: we stopped the API and FlareApiDown fired after about two minutes; we injected 50 % errors and FlareApiHighErrorRate fired. `scripts\alert_drill.ps1` repeats it." |
| 9:00 | GitHub Actions | "Every push: lint and tests, the whole stack end to end in Docker Compose, and a Kubernetes deployment on kind with a rolling update and a rollback. CD publishes the images to GHCR tagged with the version and git SHA and deploys to k3s with automatic rollback." |
| 9:40 | Close | "All three start commands are in the README. Questions?" |

Optional live extras (if time):
- `.\scripts\alert_drill.ps1 -Rule down` (about 3 minutes, restores itself).
- `.\scripts\k8s_kind.ps1 -Demo` (needs kind and kubectl in WSL; about 6 GB of disk while the cluster exists).
- `.\scripts\e2e.ps1` (about 5 minutes).
