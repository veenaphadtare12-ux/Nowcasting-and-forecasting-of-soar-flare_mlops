# INTERVIEW PREP: questions and answers

Short, honest answers you can say out loud. Numbers come from `docs/PRESENTATION_FACTS.md` and `docs/REPORT.md`.

## The problem and the data
**Q: What does the system do, in one sentence?**
Every 10 seconds it reads Aditya-L1's soft X-ray light curve and says whether a flare is happening now and whether a C- or
M-class flare will start within 30 or 60 minutes.

**Q: Why TSS and not accuracy?**
Flares are rare (≥M within 60 min is 2.8 % of rows). A model that always says "no flare" has 97 % accuracy and zero skill.
TSS = hit rate − false-alarm rate does not depend on the class balance, so it is the standard in flare forecasting.

**Q: Where do the labels come from?**
The NOAA SWPC GOES flare list (start, peak, end, class). Our own detector is only used to refine the start time when it
matched a GOES flare, and as a real-time feature with strict causal rules.

**Q: Why is HEL1OS optional?**
It overlaps usable SoLEXS data only 4.7 % of the time, so a model that needs it would be silent most of the day.

## Leakage and evaluation
**Q: How did you prevent data leakage?**
Chronological splits only; all features use trailing windows; forecast labels start strictly after the input window; a
future-perturbation test changes the future and checks that no feature moves; thresholds are tuned on the tuning period
only; the test and holdout2 were each scored exactly once after the choice was frozen in git.

**Q: Tell me about a bug you found.**
Split detector segments became visible up to a median 18 minutes before the detection was actually finished: a causal
ordering leak. I fixed it at the source (events count from `trigger_time`, their peak only once the end is confirmed),
added truncation tests, rebuilt the catalogue, and froze the old test so it is never re-scored with the fix.

**Q: Are your forecasts good?**
The nowcast is: TSS 0.76 on the test and on holdout2, every GOES-matched flare detected. The forecasts mostly recognise the
activity level; on holdout2 a one-number current-flux rule does almost as well, and the M results there are underpowered
(7 flares). I report the baselines and intervals so it is not over-claimed.

## MLOps choices
**Q: Why DVC and MLflow both?**
DVC versions the data and the pipeline (37 stages, cached, reproducible with `dvc repro`); MLflow tracks the 767 runs and
holds the registry with the `champion` alias. Git ties them together: `dvc.lock` hash and git commit are tags on each model.

**Q: How does a model get to production?**
The champions are exported to a model bundle (models, thresholds, SHA-256). The API image contains the bundle, so the
image tag (git SHA) fully identifies code + models. Retraining (`flows/retrain_candidate.py`) can only register a
challenger; it asserts that the champion did not move.

**Q: What happens every night?**
Prefect runs `daily_ingest` at 02:15 UTC: new SoLEXS day → pandera contracts → the same feature code as training → five
champions → predictions store; the API serves it at `/production/latest`. `check_drift` (Evidently) runs at 03:30 UTC.

**Q: How do you know training and serving compute the same features?**
The API uses the pipeline's feature code, and a test checks that features from raw counts equal the training features for
the same day; on 2026-02-21 the production path reproduced the bundle predictions exactly.

**Q: How do you monitor it?**
The API exports Prometheus metrics (requests, latency, errors, open streams, alerts and mean probability per target).
Grafana shows them; two alert rules: API down (2 min) and 5xx ratio above 5 % (5 min). Both were proven by drills:
`scripts/alert_drill.ps1` stops the API or injects 503s through an opt-in switch that cannot run in production.

**Q: Why Docker Compose and Kubernetes?**
Compose is the simple way to run the whole product on one machine and in CI. Kubernetes (kind locally and in CI, k3s on a
server) adds rolling updates, probes, resource limits and rollback. Both run the same images.

**Q: Explain your rolling update and rollback.**
The API deployment has 2 replicas, `maxSurge 1`, `maxUnavailable 0` and readiness probes, so a new pod must be ready before
an old one stops: the CI demo counts zero failed requests during an update. A bad image never becomes ready, the rollout
times out, the old pods keep serving, and `kubectl rollout undo` restores the previous revision. `deploy.sh` does that
automatically in CD.

**Q: How are secrets handled?**
Nothing secret is in git. Locally an uncommitted `.env`; in Kubernetes the Grafana password is a Secret created by the
deploy script from a GitHub secret (or random); the SSH key, host and user are GitHub repository secrets.

**Q: What does CI check?**
Five jobs: lint + unit tests; the whole Compose stack end to end (`scripts/e2e.sh`); the manifests deployed to kind with a
smoke test, rolling update and rollback; Terraform fmt + validate; security scans (pip-audit, npm audit, trivy fails on
CRITICAL).

**Q: How is the API protected?**
`POST /predict` needs an `X-API-Key` (several keys at once, so rotation has no downtime; with no key configured it refuses
everything). A sliding one-minute rate limit answers 429, bodies over 4 MB get 413, CORS is an allow-list. Only Caddy is
public; `/metrics` is never served through the website.

**Q: What did the load test find?**
At 50 users the replay endpoint re-parsed a whole day per request and starved `/health`, which in Kubernetes would have
restarted healthy pods. I cached each prepared day per store version (responses byte-identical) and made `/health` async.
After: 5,950 requests, 0 % errors, p95 8.3 ms against an SLO of 300 ms.

**Q: How do you back up and restore?**
`scripts/backup.ps1` pauses the writers for a few seconds and archives every volume with SHA-256 checksums; restore verifies
the checksums first. I restored into fresh volumes and the MLflow registry and 68,933 prediction rows were identical.

**Q: Why Terraform if you did not apply it?**
It documents the server as code (VM, firewall, k3s via cloud-init) so it can be recreated in minutes; applying it costs money,
so that is a deliberate decision for the owner.

## Trade-offs and what I would do next
- PVCs are ReadWriteOnce on a single node; a multi-node cluster would need ReadWriteMany storage or an object store.
- SQLite for Prefect and MLflow is fine for one server; Postgres for anything larger.
- M forecasts need a cost-based or false-alarm-capped threshold before real use.
- Next: a fresh one-time evaluation on new production days before any champion change; calibrated probabilities in the API.

## Numbers to remember
424 usable SoLEXS days · 44 base features · 37 DVC stages · 767 MLflow runs · 5 champions · nowcast TSS 0.758 (test),
0.760 (holdout2) · 146 tests · 5 CI jobs · alerts fire after 135 s (down) and with a 0.51 error ratio (errors) · load
test p95 8.3 ms at 50 users.
