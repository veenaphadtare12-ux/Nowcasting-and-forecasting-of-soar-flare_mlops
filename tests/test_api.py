"""FastAPI service tests (TestClient). Everything comes from the committed model bundle; the store is a temp folder."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
X_DAY, QUIET_DAY = "2026-04-24", "2026-02-21"
API_KEY = "test-key-123"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from src.serving import bundle as B
    from src.settings import get_settings

    monkeypatch.setenv("FLARE_PREDICTIONS_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("FLARE_DRIFT_FILE", str(tmp_path / "no_live_drift.json"))
    monkeypatch.setenv("FLARE_BUNDLE_DIR", str(ROOT / "model_bundle"))
    monkeypatch.setenv("FLARE_MAX_REPLAY_SPEED", "1e9")  # tests: no real-time pacing
    monkeypatch.setenv("FLARE_API_KEYS", f"old-key,{API_KEY}")
    get_settings.cache_clear()
    B.load.cache_clear()
    from src.serving.api import app
    from src.serving.security import LIMITER

    LIMITER.reset()
    with TestClient(app, headers={"X-API-Key": API_KEY}) as c:
        yield c
    get_settings.cache_clear()


def test_health_and_models(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and len(h["models_loaded"]) == 5 and h["replay_days"] == 5
    m = {x["target"]: x for x in client.get("/models").json()}
    assert set(m) == {"now", "c_30m", "c_60m", "m_30m", "m_60m"}
    assert m["now"]["inputs"] == "Aditya-only" and m["m_30m"]["inputs"] == "includes GOES XRS"
    assert m["m_60m"]["thresholds"]["C"] is None  # FAR <= 0.80 unreachable: shown as null, never as Infinity


def test_replay_days(client):
    days = client.get("/replay/days").json()
    assert {d["day"] for d in days} == {"2026-04-24", "2025-04-13", "2025-11-04", "2026-05-16", "2026-02-21"}
    assert next(d for d in days if d["day"] == X_DAY)["goes_counts"]["X"] == 2


def test_replay_is_causal(client):
    until = f"{X_DAY}T08:05:00Z"  # the X2.5 flare starts ~08:01 and peaks later
    r = client.get(f"/replay/{X_DAY}", params={"until": until}).json()
    u = pd.Timestamp(until)
    assert r["source"] == "bundle"
    assert pd.Timestamp(r["lightcurve"]["time"][-1]) <= u
    for t in r["predictions"].values():
        assert pd.Timestamp(t["time"][-1]) <= u and len(t["time"]) == len(t["p_flare"]) == len(t["alert"])
    for g in r["goes_flares"]:
        assert pd.Timestamp(g["begin"]) <= u
        if g["peak"] is None:
            assert g["goes_class"] is None  # class not known before the peak
    full = client.get(f"/replay/{X_DAY}").json()
    assert len(full["goes_flares"]) > len(r["goes_flares"])
    assert all(e["ended"] or e["peak"] is None for e in r["detector_events"])


def test_unknown_day_is_404(client):
    assert client.get("/replay/2026-10-30").status_code == 404  # holdout2 day: never in the bundle
    assert client.get("/replay/2026-07-01").status_code == 404  # old test period: never in the bundle


def test_stream_sends_meta_frames_and_end(client):
    with client.stream("GET", f"/replay/{QUIET_DAY}/stream", params={"speed": 1e9, "step": 360}) as r:
        text = "".join(r.iter_text())
    events = [blk.split("\n") for blk in text.strip().split("\n\n")]
    kinds = [e[0].removeprefix("event: ") for e in events]
    assert kinds[0] == "meta" and kinds[-1] == "end" and kinds.count("frame") >= 10
    frame = json.loads(events[1][1].removeprefix("data: "))
    assert set(frame["p"]) == {"now", "c_30m", "c_60m", "m_30m", "m_60m"}


def test_predict_feature_rows_match_the_bundle(client):
    from src.serving import bundle as B

    b = B.load(str(ROOT / "model_bundle"))
    X = b.model_input(X_DAY, "c_60m").iloc[3000:3005]
    rows = [{k: (None if pd.isna(v) else float(v)) for k, v in r.items()} for r in X.to_dict(orient="records")]
    out = client.post("/predict", json={"target": "c_60m", "rows": rows}).json()
    stored = b.table(X_DAY, "predictions")
    ref = stored[(stored["target"] == "c_60m")].set_index("time").loc[X.index, "p_flare"].to_numpy()
    np.testing.assert_allclose(out["p_flare"], ref, rtol=1e-5)


def test_predict_raw_counts_uses_the_pipeline_feature_code(client):
    from src.serving import bundle as B

    b = B.load(str(ROOT / "model_bundle"))
    c = b.table(QUIET_DAY, "inputs_solexs_1s")["counts"]
    end = pd.Timestamp(f"{QUIET_DAY}T12:00:00Z")
    c = c[c.index <= end]
    body = {
        "target": "now",
        "time": [t.strftime("%Y-%m-%dT%H:%M:%SZ") for t in c.index],
        "counts": c.astype(float).tolist(),
        "last_minutes": 5,
    }
    out = client.post("/predict", json=body).json()
    assert out["features_source"].startswith("pipeline feature code")
    stored = b.table(QUIET_DAY, "predictions")
    ref = (
        stored[stored["target"] == "now"]
        .set_index("time")
        .loc[pd.DatetimeIndex(pd.to_datetime(out["time"], utc=True)), "p_flare"]
    )
    np.testing.assert_allclose(out["p_flare"], ref.to_numpy(), rtol=1e-5)


def test_predict_raw_refuses_targets_that_need_extra_inputs(client):
    body = {"target": "c_30m", "time": [f"2026-02-21T00:00:{s:02d}Z" for s in range(20)], "counts": [10.0] * 20}
    r = client.post("/predict", json=body)
    assert r.status_code == 422 and "long-context" in r.json()["detail"]


def test_results_drift_status_metrics(client):
    res = client.get("/results").json()
    assert (
        res["test"]["targets"]["now"]["ci95"][0] < res["test"]["targets"]["now"]["tss"] < res["test"]["targets"]["now"]["ci95"][1]
    )
    assert res["holdout2"]["targets"]["m_60m"]["underpowered"] is True
    d = client.get("/drift/latest").json()
    assert d["source"].startswith("bundle") and 0 <= d["drifted_share"] <= 1
    st = client.get("/pipeline/status").json()
    assert st["dvc"]["total"] >= 30 and st["dvc"]["frozen"] >= 20 and "now" in st["registry"]
    m = client.get("/metrics").text
    assert "flare_api_requests_total" in m and "flare_probability_mean" in m


def test_store_predictions_take_precedence_over_the_bundle(client, tmp_path):
    from src.ops import replay, runs
    from src.settings import get_settings

    pred = replay.score_bundle_day(X_DAY, ROOT / "model_bundle")
    replay.store(pred, get_settings().predictions_dir)
    runs.record("score_replay", "Completed", {"rows": len(pred)}, get_settings().predictions_dir)
    r = client.get(f"/replay/{X_DAY}", params={"until": f"{X_DAY}T06:00:00Z"}).json()
    assert r["source"] == "store" and r["run"]["status"] == "Completed"
    assert X_DAY in client.get("/pipeline/status").json()["predictions_store"]["days"]


def test_data_coverage_is_development_only(client):
    c = client.get("/data/coverage").json()
    assert c["days"][-1] <= "2026-09-12" and c["summary"]["usable_days"] == 424
    assert len(c["days"]) == len(c["valid_fraction"]) == len(c["usable"])
    assert all(m <= "2026-09" for m in c["goes_monthly"])


def test_fault_injection_is_off_by_default_and_counted_when_on(client, monkeypatch):
    from src.settings import get_settings

    assert client.get("/models").status_code == 200  # default rate 0: nothing injected
    monkeypatch.setenv("FLARE_FAULT_INJECT_RATE", "1")
    get_settings.cache_clear()
    assert client.get("/models").status_code == 503
    assert client.get("/health").status_code == 200  # probes are never affected
    metrics = client.get("/metrics").text
    assert 'flare_api_requests_total{method="GET",route="unmatched",status="503"}' in metrics
    monkeypatch.setenv("FLARE_ENVIRONMENT", "production")
    get_settings.cache_clear()
    assert client.get("/models").status_code == 200  # never in production


# ---------------------------------------------------------------- security: API key, rate limit, body size, CORS
def _rows(client):
    m = {x["target"]: x for x in client.get("/models").json()}["now"]
    return {"target": "now", "rows": [dict.fromkeys(m["features"], 0.0)]}


def test_predict_needs_a_valid_api_key(client):
    body = _rows(client)
    assert client.post("/predict", json=body, headers={"X-API-Key": ""}).status_code == 401
    assert client.post("/predict", json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/predict", json=body).status_code == 200  # fixture sends the valid key
    assert client.post("/predict", json=body, headers={"X-API-Key": "old-key"}).status_code == 200  # rotation: both valid
    assert client.get("/models", headers={"X-API-Key": ""}).status_code == 200  # read-only endpoints stay open


def test_predict_fails_closed_without_configured_keys(client, monkeypatch):
    from src.settings import get_settings

    monkeypatch.setenv("FLARE_API_KEYS", "")
    get_settings.cache_clear()
    assert client.post("/predict", json={"target": "now", "rows": []}).status_code == 401


def test_rate_limit_returns_429_and_spares_health(client, monkeypatch):
    from src.settings import get_settings

    monkeypatch.setenv("FLARE_RATE_LIMIT_PER_MINUTE", "5")
    get_settings.cache_clear()
    anon = {"X-API-Key": ""}
    codes = [client.get("/replay/days", headers=anon).status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]
    r = client.get("/replay/days", headers=anon)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert client.get("/health", headers=anon).status_code == 200  # probes are never limited
    assert client.get("/metrics", headers=anon).status_code == 200
    assert client.get("/replay/days").status_code == 200  # a valid key has its own, larger budget


def test_large_bodies_are_refused(client, monkeypatch):
    from src.settings import get_settings

    monkeypatch.setenv("FLARE_MAX_BODY_BYTES", "1000")
    get_settings.cache_clear()
    r = client.post("/predict", content=b"{" + b" " * 2000 + b"}", headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_cors_allow_list_never_wildcards(client, monkeypatch):
    from src.settings import Settings

    assert Settings(cors_origins="*,http://a.example").cors_list == ["http://a.example"]
    r = client.options(
        "/models", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert r.headers.get("access-control-allow-origin") is None



def test_replay_cache_key_follows_the_store(tmp_path):
    """Prepared replay days are cached per store version: rewriting predictions.db must change the key."""
    import os

    from src.serving.api import _store_key

    assert _store_key(tmp_path) == 0  # no store yet
    db = tmp_path / "predictions.db"
    db.write_bytes(b"v1")
    k1 = _store_key(tmp_path)
    os.utime(db, ns=(k1 + 10_000_000_000, k1 + 10_000_000_000))
    assert _store_key(tmp_path) != k1 and k1 != 0
