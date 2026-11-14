# Service level objectives (API, measured with k6)

## Objectives
| SLO | Target | Measured how |
|---|---|---|
| Latency | p95 < 300 ms for the website mix (health, models, replay windows, results, predict) | k6 `http_req_duration` threshold |
| Errors | < 1 % failed requests (status not 200) for legitimate traffic within the rate limit | k6 `http_req_failed` threshold |
| Availability (target, not yet measured over time) | 99 % per month for `/health` | Prometheus `up{job="flare-api"}`; alert `FlareApiDown` after 2 min |

The SLOs are encoded in `loadtest/k6.js`; the run fails when one is broken.

## Results (2026-11-14, laptop: Docker Engine in WSL, API container limited to 2 CPUs / 1.5 GB)
Command: `.\scripts\loadtest.ps1` (50 virtual users, 2 minutes, through nginx like a browser, valid API key).

| Run | Requests | Req/s | Errors | p50 | p95 | p99 | max | SLOs |
|---|---|---|---|---|---|---|---|---|
| 50 users, 2 min, **before** the replay cache (image `730ff84`) | — | — | many 60-s timeouts; `/health` stopped answering | — | — | — | — | **FAIL** |
| 50 users, 2 min, **after** the fix (image `300e162`) | 5,950 | 49.0 | **0 %** | 2.2 ms | **8.3 ms** | 20.5 ms | 136 ms | **PASS** |
| 200 users, 1 min (stress) | 12,053 | 196.3 | 25.3 % — all HTTP 429 from the per-key limit (6000/min) | 1.8 ms | 16.0 ms | 154.8 ms | 362 ms | latency PASS; errors are the rate limiter by design |

Saved summaries: `reports/loadtest/baseline.json` (the passing 50-user run).

## What the first run taught us
At 50 users every `GET /replay/{day}` re-read SQLite and re-formatted about 10,000 timestamps (0.5–1 s of CPU). Requests
queued in the thread pool, and `/health` (a sync endpoint) queued behind them, so a Kubernetes liveness probe would have
restarted healthy pods. Fixes: replay days are prepared once per predictions-store version and sliced per request
(responses byte-identical, checked on 4 queries), `/results` and `/models` are cached per bundle version, `/health` and
`/metrics` are `async`. Test: `tests/test_api.py::test_replay_cache_key_follows_the_store`.

## Capacity note
One API container handles about 200 requests/s of this mix with p95 16 ms; beyond one client's 100 requests/s the rate
limiter answers 429. For more traffic: more replicas (Kubernetes `api` has 2) and a shared rate-limit store.
