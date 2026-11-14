# Lesson 22: Hardening: API security, HTTPS (Caddy), Alertmanager, backups, load testing (k6), security scans

## What we built
- **API security** (`src/serving/security.py`): an API key on `POST /predict`, a sliding-window rate limit (429), a
  request-size limit (413), a strict CORS allow-list.
- **Caddy** in front of everything: plain HTTP on an IP, automatic HTTPS with a domain.
- **Alertmanager**: Prometheus alerts are routed to e-mail (SMTP settings from `.env`), or kept in its UI.
- **Backups**: every Docker volume archived with checksums, and a verified restore into fresh volumes.
- **k6 load test** with the SLOs written in as thresholds. It found a real bug: `/health` starved under 50 users.
- **Security scans in CI**: pip-audit (Python), npm audit (frontend), trivy (images, fail on CRITICAL).
- **Container hardening**: non-root users, healthchecks, limits, restart policies, pinned versions, only Caddy public.

## Why it matters
A shop that works is not yet a shop that is safe to open. You need a lock on the till (API key), a doorman who stops a
crowd from rushing in at once (rate limit), a sign that says "no parcels bigger than this" (size limit), a security
camera that rings your phone (Alertmanager), an insurance copy of the books in another building (backup you have actually
restored), and a rehearsal with a busy crowd before opening day (load test).

## Concepts
- **Authentication vs rate limiting:** the key says *who* may call; the limit says *how often*.
- **Fail closed:** with no key configured, the protected endpoint refuses everyone instead of letting everyone in.
- **Key rotation without downtime:** the server accepts several keys at once (`FLARE_API_KEYS=old,new`).
- **Sliding window:** keep the timestamps of the last minute per client; if there are already N, answer 429 with
  `Retry-After` (seconds until a slot frees).
- **Reverse proxy:** one front door (Caddy) that forwards to the right service; it is the only port open to the world.
- **ACME / Let's Encrypt:** Caddy proves to Let's Encrypt that it controls the domain and gets a free certificate,
  renewed automatically. A bare IP cannot get one, hence the two modes.
- **Alert routing:** Prometheus decides *that* something is wrong; Alertmanager decides *who hears about it*, groups
  repeats and silences known issues. An inhibit rule hides "high error rate" while "API down" is firing.
- **Consistent backup:** SQLite files copied while being written can be corrupt; pausing the writers for a few seconds
  makes the copy consistent. A backup only counts once a restore has been verified.
- **SLO:** a promise in numbers (p95 latency < 300 ms, errors < 1 %). **p95** = 95 % of requests were faster.
- **Thread-pool starvation:** synchronous FastAPI endpoints share a pool of threads; slow requests can occupy all of them
  so even `/health` waits. `async def` endpoints run on the event loop instead.
- **Docker layer cache:** a step is reused only if nothing before it changed. A git SHA declared at the top changed
  every build and invalidated the 2 GB pip layer each time.
- **CVE:** a published vulnerability ID. Scanners compare your package versions with CVE databases.

## Tools used
| Tool | What it did here | Useful commands |
|---|---|---|
| Caddy | public entry, HTTPS | `docker compose logs caddy`; `SITE_ADDRESS=your.domain` in `.env` |
| Alertmanager | routes alerts | http://localhost:9093; `curl -X POST localhost:9093/api/v2/alerts -d '[...]'` |
| k6 | load test | `.\scripts\loadtest.ps1 -Vus 50 -Duration 2m` |
| pip-audit | Python CVEs | `pip-audit -r requirements-serve.txt` |
| npm audit | JS CVEs | `cd frontend; npm audit` |
| trivy | image CVEs | CI job `security` (`aquasecurity/trivy-action`) |
| backup/restore scripts | volume archives | `.\scripts\backup.ps1`, `.\scripts\restore.ps1 -From <dir> -Prefix flare_restoretest` |

## Code walkthrough
- `src/serving/security.py`: `valid_key` compares with `hmac.compare_digest` (constant time, no timing leaks);
  `client_id` uses the key if valid, else the IP (first `X-Forwarded-For` hop, only because the API is reachable only
  through our proxy); `SlidingWindowLimiter.hit` keeps a deque per client; `check_request` runs before every request in
  the middleware.
- `src/serving/api.py`: `dependencies=[Depends(security.require_api_key)]` on `/predict`; `_prepared_day` caches one replay
  day per (bundle version, day, store mtime) and each request only slices it with `np.searchsorted`.
- `docker/caddy/Caddyfile`: `{$SITE_ADDRESS::80}` means "use SITE_ADDRESS, default :80".
- `monitoring/alertmanager/entrypoint.sh`: fills the template from environment variables, writes the SMTP password to a
  private file, never into the config.
- `scripts/backup.sh`: `docker compose pause`, one `tar` per volume through a tiny alpine container, SHA-256 into
  `manifest.json`, `unpause` in a `trap` so the stack resumes even on error.
- `loadtest/k6.js`: `thresholds` = the SLOs; `handleSummary` writes the numbers to `reports/loadtest/`.

## Hands-on
1. Without a key: `curl.exe -s -o NUL -w "%{http_code}" -X POST http://localhost:8000/predict -H "Content-Type: application/json" -d "{}"` → `401`.
2. See the rate limit: run `for ($i=0; $i -lt 320; $i++) { (Invoke-WebRequest http://localhost:8000/replay/days -UseBasicParsing -SkipHttpErrorCheck).StatusCode } | Group-Object` (PowerShell 7) → about 300 × 200 and the rest 429.
3. Send a fake alert (Alertmanager section of `docs/RUNBOOK.md`) and find it at http://localhost:9093.
4. Run `.\scripts\backup.ps1` and open the newest `manifest.json` under `D:\backups\flare`: one entry per volume with sha256.
5. Run `.\scripts\loadtest.ps1 -Vus 20 -Duration 30s` → p95 well under 300 ms, `slo_errors_lt_1pct: true`.

## Break it on purpose
Set `FLARE_RATE_LIMIT_KEY_PER_MINUTE=600` in `.env`, `.\scripts\up.ps1 -NoBuild`, run `.\scripts\loadtest.ps1 -Duration 1m`.
Expected: the error SLO fails with many 429s, because all k6 users share one key. Undo: remove the line, restart.

## Check yourself
1. Why must `/health` never be rate-limited or protected by the key?
2. Why can Caddy not get a certificate for `http://203.0.113.10`?
3. What makes a backup trustworthy?
4. What does p95 = 8 ms mean?
5. Why did moving `ARG GIT_SHA` lower in the Dockerfile save disk space?

## Questions to discuss with my tutor
- Is a per-process rate limit good enough, or should it live in Caddy/Redis?
- Which CVEs are acceptable to ship with, and who decides?
- How often should backups run, and how many should be kept?

## Key numbers to remember
Rate limit 300/min per IP, 6000/min per key · body limit 4 MB · load test 50 users: 5,950 requests, p95 8.3 ms, 0 % errors ·
backup 8 volumes, 29 MB · trivy 0 CRITICAL · 3 accepted MLflow CVEs.

---
Answers: 1. Probes and Prometheus must always get through, or healthy pods get restarted and monitoring goes blind.
2. Public certificates are issued for domain names that the CA can verify; a bare IP has no domain to verify.
3. A restore of it that was actually tested and compared with the original. 4. 95 % of requests finished in 8 ms or
less. 5. Docker reuses a layer only if everything before it is unchanged; the SHA changed every commit, so every later
layer, including the 2 GB pip install, was rebuilt and stored again.
