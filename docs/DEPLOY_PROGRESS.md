# Deployment progress (resume here)

Contract: `docs/ARCHITECTURE.md`. ML phase frozen. Repo:
https://github.com/veenaphadtare12-ux/Nowcasting-and-forecasting-of-soar-flare_mlops

| Phase | Status |
|---|---|
| Ops-1: CI, contracts, flows, push | **done**: CI green on GitHub |
| 2: model bundle, API, Docker | **done** |
| 2b: full Compose stack + smoke test + e2e | **done**: `scripts\up.ps1`, `scripts\smoke_test.ps1`, `scripts\e2e.ps1` all pass (2026-11-13) |
| 3: frontend | **done**: dashboard (6 pages + pipeline panel) and the cinematic landing page at `/` (2026-11-14) |
| 4: monitoring | partly done: Prometheus, Grafana dashboard `flare-api` (9 panels), 2 alert rules, drift in the frontend. Remaining: check the alert fires, screenshots |
| 5: CI with full Compose + kind | not started |
| 6: Kubernetes (kind) | not started |
| 7: CD + Terraform | not started |
| 8: submission docs, v1.0.0 | not started |

## How to run
Docker Engine runs inside WSL Ubuntu (Docker Desktop is not used, see "Docker history" below). The scripts call
`wsl -d Ubuntu` themselves and start a hidden keep-alive so the WSL VM does not stop.
```
.\scripts\up.ps1            # build (git-SHA tag) + start the stack
.\scripts\smoke_test.ps1    # health, models, replay, predict, metrics, frontend
.\scripts\e2e.ps1           # inbox -> Prefect daily_ingest -> contracts -> champions -> store -> API -> frontend
.\scripts\down.ps1
```
| URL | What |
|---|---|
| http://localhost:8080 | Website: landing page `/`, console `/latest`, `/replay`, `/performance`, `/models`, `/data`, `/about` |
| http://localhost:8000/docs | FastAPI |
| http://localhost:4200 | Prefect UI (deployments `daily_ingest/daily` 02:15 UTC, `check_drift/daily` 03:30 UTC, `score_replay/on-demand`) |
| http://localhost:5000 | MLflow (registry seeded from the model bundle; the API only reads it) |
| http://localhost:9090 | Prometheus |
| http://localhost:3000 | Grafana (anonymous viewer; admin password from `GRAFANA_ADMIN_PASSWORD`) |

Frontend development without rebuilding the image: `cd frontend; npm run dev` → http://localhost:5173 (proxies
`/api` to :8000).

## Phase 2b: what was verified (e2e, 2026-11-13)
- A raw SoLEXS day dropped into the inbox is picked up by the Prefect deployment `daily_ingest`, which the worker
  container runs: pandera contracts → features → 5 champions → predictions store. `/production/latest` serves it.
  On 2026-02-21 the production path reproduces the bundle predictions exactly.
- `score_replay` writes to the store and the API switches to `source: store`; `check_drift` (bundle mode) writes
  `latest.json`; the frontend's `/api` proxy works; Prometheus has the API metrics and Grafana is healthy.
- With no data on or after the production start (2026-11-13), `/production/latest` correctly reports `no_data`.

## Phase 3: frontend
- **Dashboard** (`frontend/src/pages/`): React 19 + TypeScript + Tailwind 4 + ECharts 6, served by
  nginx-unprivileged (`docker/frontend.Dockerfile`, SSE location without buffering).
- **Landing page** (`frontend/src/landing/`, lazy-loaded at `/`):
  - **3D scene (three.js):** a rotating procedural Sun (GLSL noise granulation, sunspots, limb darkening), corona, flowing magnetic loops, flare flashes with shock rings, and solar-wind particles. Aditya-L1 is modelled with a gold bus and solar wing, plus Earth and Moon.
  - **Scroll:** a camera path driven by GSAP ScrollTrigger and Lenis.
  - **Sections, all on live API data:** the X-class day (scroll = time; light curve, three model probabilities with thresholds, alerts, counts jar), live pipeline badges, and holdout2 results beside the best baseline.
  - **Design and lesson:** design inspiration from The Reef Line and Rainy Day (Claude Website Library); see lesson `docs/learn/20-cinematic-landing-threejs-gsap.md`.
- **Checks (2026-11-14):**
  - `npm run build` passes (typecheck included);
  - no console errors or warnings on the landing page or dashboard;
  - checked at 1366×768, 1920×1080 and 390×844;
  - `prefers-reduced-motion` respected.
- **Screenshots:** `docs/screenshots/landing_*.jpg`.
- **OpenArt:** one image was generated (free plan, 10 credits), but it carries a large OpenArt watermark, so it is **not used**. The Sun is drawn procedurally instead. A paid plan would allow un-watermarked art.

## Problems met (and fixes)
- **Docker Desktop failed to start** on this Windows build: it could not rename its AF_UNIX socket files. After 3 attempts, the user installed Docker Engine inside WSL Ubuntu instead.
- **Git Bash mangles `$vars` and `/mnt/...` paths** in `wsl` calls: helper scripts go to `D:/tmp/wsl/*.sh` and run with `MSYS_NO_PATHCONV=1`. The PowerShell scripts use `_common.ps1` (`Invoke-Bash`, `Get-WslPath`).
- **The WSL VM stops** a few seconds after the last `wsl.exe` exits, taking Docker with it: a hidden `wsl ... sleep infinity` keep-alive (`Start-WslKeepAlive`).
- **Port 5000 was held** by the leftover Docker Desktop backend, which was stopped.
- **CI:**
  - the Prefect server needs FastAPI 0.142, so it is pinned in `requirements-ci.txt`;
  - one HEL1OS feature (`hx_cdte_lo_d5m`) differs by float32 rounding between Windows and Linux, so that test uses `rtol=1e-5`.
- **Python text mode on Windows writes CRLF:** the LF test caught it, and files were rewritten in binary mode.
- **RAM:** with the Docker VM and browsers running, the full-data tests can hit `MemoryError` (about 1 GB free of 15.7 GB). Rerunning them alone passes.

## Disk log
Rule: after every image build run `docker builder prune -f`; log C: and D: free space after every phase.
The WSL disk was moved to `D:\WSL\Ubuntu\ext4.vhdx` (17.6 GB file, about 13 GB used inside, **not sparse**, so space
freed inside WSL is not returned to D: until the disk is compacted or made sparse).

| Date | Point | C: free | D: free | Notes |
|---|---|---|---|---|
| 2026-11-14 | pre-flight before phase 4 | 39.0 GB | 9.69 GB | **STOP: D: below 15 GB.** Build cache 0 B, no dangling images. 4.69 GB is held by old, non-dangling image tags (`flare-api:6dbb958be90b`, `flare-api:7c9b20e183ef-dirty` and their frontends), which the prune rule does not cover. |
