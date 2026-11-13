"""FastAPI service: replays demo days, serves frozen results, predictions, drift and pipeline status.

    uvicorn src.serving.api:app --port 8000

Models and replay data come ONLY from the demo bundle (FLARE_BUNDLE_DIR); features for raw inputs are computed with the
pipeline's feature code (src/serving/features.py). Nothing here trains, tunes, or scores an evaluation period.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

from src.ops import replay, runs
from src.serving import bundle as B
from src.serving import features as sf
from src.settings import get_settings

log = logging.getLogger("flare.api")
DAY_RE = r"^\d{4}-\d{2}-\d{2}$"
BASE_ONLY = None  # targets whose model needs only the 44 base features: computed from the manifest at startup

# ---------------------------------------------------------------- Prometheus metrics (own registry: no global state clash)
REGISTRY = CollectorRegistry()
REQUESTS = Counter("flare_api_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY)
LATENCY = Histogram(
    "flare_api_request_seconds",
    "Request latency",
    ["method", "route"],
    registry=REGISTRY,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
ERRORS = Counter("flare_api_errors_total", "Responses with status >= 500", ["route"], registry=REGISTRY)
ALERTS = Counter("flare_alerts_total", "Alerts (p >= threshold A) emitted to clients", ["target"], registry=REGISTRY)
PROB = Gauge("flare_probability_mean", "Mean flare probability of the last served batch", ["target"], registry=REGISTRY)
PROB_HIST = Histogram(
    "flare_probability",
    "Served flare probabilities",
    ["target"],
    registry=REGISTRY,
    buckets=(0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
STREAMS = Gauge("flare_active_streams", "Open replay streams", registry=REGISTRY)
BUNDLE_INFO = Gauge("flare_bundle_info", "Loaded bundle (value 1)", ["bundle_version", "git_sha"], registry=REGISTRY)


def observe(target: str, p: np.ndarray, alerts: np.ndarray) -> None:
    if len(p):
        PROB.labels(target).set(float(np.mean(p)))
        for v in p[:: max(1, len(p) // 200)]:  # sample: a day has 8640 values
            PROB_HIST.labels(target).observe(float(v))
        ALERTS.labels(target).inc(int(np.sum(alerts)))


# ---------------------------------------------------------------- schemas
class Health(BaseModel):
    status: Literal["ok"]
    bundle_version: str
    bundle_git_sha: str
    image_git_sha: str
    environment: str
    models_loaded: list[str]
    replay_days: int


class ModelInfo(BaseModel):
    target: str
    registry_name: str
    version: str
    alias: str
    learner: str | None
    ideas: list[str]
    n_features: int
    features: list[str]
    thresholds: dict[str, float | None]
    fit_dates: str | None
    threshold_block: str | None
    test_tss_A: str | None
    inputs: Literal["Aditya-only", "includes GOES XRS"]
    challenger: dict | None


class DayInfo(BaseModel):
    day: str
    note: str
    goes_counts: dict[str, int]
    hel1os: bool
    rows: int
    in_fit_period: bool


class PredictRows(BaseModel):
    target: str
    rows: list[dict[str, float | None]] = Field(..., min_length=1, max_length=10000, description="feature name -> value")


class PredictRaw(BaseModel):
    target: str
    time: list[str] = Field(..., min_length=10, description="ISO UTC timestamps of 1-s SoLEXS counts (valid seconds)")
    counts: list[float] = Field(..., min_length=10)
    hel1os: dict[str, list[float | None]] | None = Field(
        None, description="optional 1-s HEL1OS channels: cdte_lo, cdte_hi, czt_lo, czt_hi"
    )
    last_minutes: int = Field(10, ge=1, le=1440, description="return predictions for this many trailing minutes")


class Prediction(BaseModel):
    target: str
    model: str
    model_version: str
    threshold: float
    time: list[str]
    p_flare: list[float]
    alert: list[bool]
    features_source: str


# ---------------------------------------------------------------- app
@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    logging.basicConfig(level=s.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    b = B.load(str(s.bundle_dir))
    bad = b.verify()
    if bad:
        raise RuntimeError(f"demo bundle is corrupt: {bad}")
    for t in b.manifest["models"]:
        b.model(t)  # load + SHA-256 check at startup, not on the first request
    global BASE_ONLY
    base = set(b.model_meta("now")["features"])
    BASE_ONLY = {t for t, m in b.manifest["models"].items() if set(m["features"]) <= base}
    BUNDLE_INFO.labels(b.version, b.manifest["git_sha"][:12]).set(1)
    log.info("bundle %s loaded: %d models, %d replay days", b.version, len(b.manifest["models"]), len(b.days))
    yield


app = FastAPI(
    title="Aditya-L1 flare nowcast/forecast API",
    version="1.0.0",
    lifespan=lifespan,
    description="Replays development days with the frozen champion models. Not an operational alert service.",
)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_list, allow_methods=["GET", "POST"], allow_headers=["*"])


@app.middleware("http")
async def log_and_measure(request: Request, call_next):
    t0 = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        dt = time.perf_counter() - t0
        REQUESTS.labels(request.method, path, str(status)).inc()
        LATENCY.labels(request.method, path).observe(dt)
        if status >= 500:
            ERRORS.labels(path).inc()
        if path != "/metrics":
            log.info("%s %s -> %d (%.1f ms)", request.method, request.url.path, status, dt * 1000)


def bundle() -> B.Bundle:
    return B.load(str(get_settings().bundle_dir))


def _iso(ts) -> list[str]:
    return [t.strftime("%Y-%m-%dT%H:%M:%SZ") for t in pd.DatetimeIndex(ts)]


def _num(a) -> list[float | None]:
    return [None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v) for v in np.asarray(a, dtype="float64")]


def _day(day: str) -> pd.Timestamp:
    b = bundle()
    if day not in b.days:
        raise HTTPException(404, f"{day} is not a replay day; see /replay/days")
    return pd.Timestamp(day, tz="UTC")


def _until(day0: pd.Timestamp, until: str | None) -> pd.Timestamp:
    if until is None:
        return day0 + pd.Timedelta(days=1)
    try:
        u = pd.Timestamp(until)
    except ValueError as e:
        raise HTTPException(422, f"bad 'until': {e}") from e
    u = u.tz_localize("UTC") if u.tzinfo is None else u.tz_convert("UTC")
    return min(max(u, day0), day0 + pd.Timedelta(days=1))


def _predictions(day: str) -> tuple[pd.DataFrame, str, dict]:
    s = get_settings()
    store = replay.read_store(day, s.predictions_dir)
    if store is not None:
        return store, "store", runs.load(s.predictions_dir).get("score_replay", {})
    return bundle().table(day, "predictions"), "bundle", {"bundle_version": bundle().version}


@lru_cache(maxsize=16)
def _day_events(bundle_version: str, day: str) -> tuple[list, list]:
    b = bundle()
    return b.json(f"replay/{day}/goes_flares.json"), b.json(f"replay/{day}/detector_events.json")


def _known_events(day: str, until: pd.Timestamp) -> tuple[list, list]:
    """Causal view: a GOES flare appears at its begin time, its class once its peak has passed, its end once ended.
    A detector event appears at its trigger time; its peak/end/class once its end is confirmed."""
    all_goes, all_det = _day_events(bundle().version, day)
    goes = []
    for g in all_goes:
        begin, peak, end = (pd.Timestamp(g[k]) if g[k] else None for k in ("begin", "peak", "end"))
        if begin is None or begin > until:
            continue
        done_peak = peak is not None and peak <= until
        goes.append(
            {
                "begin": g["begin"],
                "peak": g["peak"] if done_peak else None,
                "end": g["end"] if end and end <= until else None,
                "goes_class": g["goes_class"] if done_peak else None,
                "class_letter": g["class_letter"] if done_peak else None,
                "in_progress": not (end and end <= until),
            }
        )
    det = []
    for e in all_det:
        trig, known = pd.Timestamp(e["trigger_time"]), pd.Timestamp(e["end_known_time"])
        if trig > until:
            continue
        ended = known <= until
        det.append(
            {
                "trigger_time": e["trigger_time"],
                "ended": ended,
                "onset": e["onset"] if ended else None,
                "peak": e["peak"] if ended else None,
                "end": e["end"] if ended else None,
                "peak_counts_s": e["peak_counts_s"] if ended else None,
                "goes_class": e["goes_class"] if ended else None,
            }
        )
    return goes, det


@app.get("/health", response_model=Health)
def health() -> Health:
    b, s = bundle(), get_settings()
    return Health(
        status="ok",
        bundle_version=b.version,
        bundle_git_sha=b.manifest["git_sha"],
        image_git_sha=s.git_sha,
        environment=s.environment,
        models_loaded=sorted(b._models),
        replay_days=len(b.days),
    )


@app.get("/models", response_model=list[ModelInfo])
def models() -> list[ModelInfo]:
    out = []
    for t, m in bundle().manifest["models"].items():
        out.append(
            ModelInfo(
                target=t,
                n_features=len(m["features"]),
                inputs="includes GOES XRS" if any(f.startswith("gx_") for f in m["features"]) else "Aditya-only",
                **{
                    k: m.get(k)
                    for k in (
                        "registry_name",
                        "version",
                        "alias",
                        "learner",
                        "ideas",
                        "features",
                        "thresholds",
                        "fit_dates",
                        "threshold_block",
                        "test_tss_A",
                        "challenger",
                    )
                },
            )
        )
    return out


@app.get("/replay/days", response_model=list[DayInfo])
def replay_days() -> list[DayInfo]:
    return [DayInfo(day=d, **v) for d, v in bundle().days.items()]


@app.get("/replay/{day}")
def replay_day(day: str, until: str | None = None, step: int = Query(1, ge=1, le=60), targets: str | None = None) -> dict:
    """Everything known about a replay day up to `until` (default: end of day): light curves, predictions, events."""
    d0 = _day(day)
    u = _until(d0, until)
    b = bundle()
    lc = b.table(day, "lightcurve")
    lc = lc[lc.index <= u].iloc[::step]
    pred, source, run = _predictions(day)
    pred = pred[pred["time"] <= u]
    want = set(targets.split(",")) if targets else set(b.manifest["models"])
    series = {}
    for t, g in pred.groupby("target"):
        if t not in want:
            continue
        g = g.sort_values("time").iloc[::step]
        series[t] = {
            "model": g["model"].iloc[0],
            "model_version": str(g["model_version"].iloc[0]),
            "threshold": float(g["threshold"].iloc[0]),
            "time": _iso(g["time"]),
            "p_flare": _num(g["p_flare"]),
            "alert": [bool(x) for x in g["alert"]],
        }
        observe(t, g["p_flare"].to_numpy(), g["alert"].to_numpy())
    goes, det = _known_events(day, u)
    return {
        "day": day,
        "until": u.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": b.days[day]["note"],
        "in_fit_period": b.days[day]["in_fit_period"],
        "source": source,
        "run": run,
        "lightcurve": {"time": _iso(lc.index), **{c: _num(lc[c]) for c in lc.columns}},
        "predictions": series,
        "goes_flares": goes,
        "detector_events": det,
    }


@app.get("/replay/{day}/stream")
async def replay_stream(
    request: Request, day: str, speed: float = Query(60.0, gt=0), start: str | None = None, step: int = Query(1, ge=1, le=360)
):
    """Server-sent events: one frame per 10-s step (or `step` steps), paced at `speed` replay-seconds per second."""
    s = get_settings()
    d0 = _day(day)
    speed = min(speed, s.max_replay_speed)
    b = bundle()
    lc = b.table(day, "lightcurve")
    pred, source, _ = _predictions(day)
    wide = pred.pivot_table(index="time", columns="target", values="p_flare")
    thr = pred.groupby("target")["threshold"].first().to_dict()
    t0 = _until(d0, start) if start else d0
    frames = lc[lc.index > t0].iloc[::step].join(wide, how="left")
    frames = frames.iloc[: s.stream_max_frames]
    delay = 10.0 * step / speed

    async def gen():
        STREAMS.inc()
        seen_g, seen_d = 0, 0
        try:
            yield f"event: meta\ndata: {json.dumps({'day': day, 'source': source, 'thresholds': thr, 'speed': speed, 'frames': len(frames)})}\n\n"
            for t, row in frames.iterrows():
                if await request.is_disconnected():
                    break
                goes, det = _known_events(day, t)
                p = {k: (None if pd.isna(row.get(k)) else float(row[k])) for k in thr}
                alerts = {k: (v is not None and v >= thr[k]) for k, v in p.items()}
                for k, v in p.items():
                    if v is not None:
                        observe(k, np.array([v]), np.array([alerts[k]]))
                frame = {
                    "t": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "solexs_rate": None if pd.isna(row["solexs_rate"]) else float(row["solexs_rate"]),
                    "hx_czt_lo": None if pd.isna(row.get("hx_czt_lo", np.nan)) else float(row["hx_czt_lo"]),
                    "hx_cdte_lo": None if pd.isna(row.get("hx_cdte_lo", np.nan)) else float(row["hx_cdte_lo"]),
                    "p": p,
                    "alerts": alerts,
                    "new_goes": goes[seen_g:],
                    "new_detector": det[seen_d:],
                    "goes": goes,
                    "detector_events": det,
                }
                seen_g, seen_d = len(goes), len(det)
                yield f"event: frame\ndata: {json.dumps(frame)}\n\n"
                await asyncio.sleep(delay)
            yield "event: end\ndata: {}\n\n"
        finally:
            STREAMS.dec()

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.post("/predict", response_model=Prediction)
def predict(body: PredictRows | PredictRaw) -> Prediction:
    """Feature rows -> probabilities; or a raw 1-s SoLEXS window -> features with the pipeline code -> probabilities."""
    b = bundle()
    if body.target not in b.manifest["models"]:
        raise HTTPException(404, f"unknown target {body.target}")
    m = b.model_meta(body.target)
    if isinstance(body, PredictRows):
        X = pd.DataFrame(body.rows)
        missing = [f for f in m["features"] if f not in X.columns]
        if missing:
            raise HTTPException(422, f"missing features: {missing[:10]}{' ...' if len(missing) > 10 else ''}")
        X = X[m["features"]].astype("float32")
        times, src = [""] * len(X), "client feature rows"
    else:
        if body.target not in BASE_ONLY:
            raise HTTPException(
                422,
                f"{body.target} needs long-context/spectral/GOES features that a raw SoLEXS window cannot "
                "provide; use feature rows or a base-feature target (" + ", ".join(sorted(BASE_ONLY)) + ")",
            )
        if len(body.time) != len(body.counts):
            raise HTTPException(422, "time and counts must have the same length")
        idx = pd.DatetimeIndex(pd.to_datetime(body.time, utc=True))
        counts = pd.Series(body.counts, index=idx, dtype="float64").sort_index()
        hel = None
        if body.hel1os:
            hel = pd.DataFrame(body.hel1os, index=idx).astype("float64").sort_index()
        end = counts.index.max().ceil("10s")
        start = end - pd.Timedelta(minutes=body.last_minutes)
        X = sf.window_features(counts, hel, start, end)
        if X.empty:
            raise HTTPException(
                422, "no feature rows: the window needs at least ~5 min of valid 1-s data before the requested minutes"
            )
        times, src = _iso(X.index), "pipeline feature code (src/features.py) on the posted counts"
        X = X[m["features"]]
    p = np.clip(b.model(body.target).predict_proba(X)[:, 1].astype(float), 0, 1)
    thr = float(m["thresholds"]["A"])
    observe(body.target, p, p >= thr)
    return Prediction(
        target=body.target,
        model=m["registry_name"],
        model_version=m["version"],
        threshold=thr,
        time=times,
        p_flare=[float(x) for x in p],
        alert=[bool(x) for x in p >= thr],
        features_source=src,
    )


@app.get("/results")
def results() -> dict:
    return bundle().json("model_card.json")


@app.get("/drift/latest")
def drift_latest() -> dict:
    b = bundle()
    live = get_settings().drift_file
    src = live if live.exists() else b.path / "drift" / "latest.json"
    if not src.exists():
        raise HTTPException(404, "no drift report yet: run python -m flows.check_drift")
    d = json.loads(src.read_text(encoding="utf-8"))
    d["source"] = "live reports/drift/latest.json" if src == live else f"bundle {b.version}"
    return d


@app.get("/pipeline/status")
def pipeline_status() -> dict:
    s = get_settings()
    b = bundle()
    st = b.json("pipeline/status.json")
    live = runs.load(s.predictions_dir)
    st["flow_runs"] = {**st.get("flow_runs", {}), **live}
    db = Path(s.predictions_dir) / "predictions.db"
    st["predictions_store"] = {
        "path": str(db),
        "exists": db.exists(),
        "days": sorted(d for d in b.days if replay.read_store(d, s.predictions_dir) is not None) if db.exists() else [],
    }
    st["bundle"] = {"version": b.version, "git_sha": b.manifest["git_sha"], "created_at": b.manifest["created_at"]}
    return st


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
