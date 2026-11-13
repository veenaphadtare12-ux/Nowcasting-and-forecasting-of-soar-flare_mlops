"""Production pipeline (src/ops/production.py, flows/daily_ingest.py) and its API endpoints.

The inbox is fed with the 1-s counts of a model-bundle development day, with the production start moved to that day
for the test only. The default production start must stay after holdout2.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-02-21"  # no HEL1OS that day: production (which has no HEL1OS input) sees exactly the pipeline's inputs


@pytest.fixture
def prod(tmp_path, monkeypatch):
    from src.serving import bundle as B
    from src.settings import get_settings

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    b = B.Bundle(ROOT / "model_bundle")
    b.table(DAY, "inputs_solexs_1s").astype("float64").to_parquet(inbox / f"{DAY}.parquet")
    monkeypatch.setenv("FLARE_INBOX_DIR", str(inbox))
    monkeypatch.setenv("FLARE_PREDICTIONS_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("FLARE_DRIFT_FILE", str(tmp_path / "drift" / "latest.json"))
    monkeypatch.setenv("FLARE_PRODUCTION_START", DAY)
    monkeypatch.setenv("FLARE_BUNDLE_DIR", str(ROOT / "model_bundle"))
    monkeypatch.delenv("FLARE_RAW_SOLEXS_DIR", raising=False)
    get_settings.cache_clear()
    B.load.cache_clear()
    yield b
    get_settings.cache_clear()
    B.load.cache_clear()


def test_default_production_start_is_after_holdout2():
    from src import config
    from src.settings import Settings

    h_end = pd.Timestamp(config.load_params()["holdout2"]["end"])
    assert pd.Timestamp(Settings().production_start) > h_end


def test_production_scores_a_new_day_exactly_like_the_pipeline(prod):
    from src.ops import production, replay
    from src.settings import get_settings

    assert production.pending_days() == [DAY]
    s = production.run_day(DAY, fetch_goes=False)
    assert set(s["targets"]) == {"now", "c_60m", "m_60m"} and set(s["not_scored"]) == {"c_30m", "m_30m"}
    assert production.pending_days() == [] and production.scored_days() == [DAY]
    got = replay.read_store(DAY, get_settings().predictions_dir)
    ref = prod.table(DAY, "predictions")
    for t in ("now", "c_60m", "m_60m"):
        a = got[got["target"] == t].set_index("time")["p_flare"]
        r = ref[ref["target"] == t].set_index("time")["p_flare"]
        assert a.index.as_unit("ns").equals(r.index.as_unit("ns"))
        np.testing.assert_allclose(a.to_numpy(), r.to_numpy(), rtol=1e-6, atol=1e-7)


def test_production_refuses_days_before_the_start(prod, monkeypatch):
    from src.ops import production
    from src.settings import get_settings

    monkeypatch.setenv("FLARE_PRODUCTION_START", "2026-11-13")
    get_settings.cache_clear()
    assert production.pending_days() == []  # the inbox day is before the real production start
    with pytest.raises(PermissionError):
        production.run_day(DAY, fetch_goes=False)


def test_broken_raw_counts_stop_the_pipeline(prod, tmp_path):
    from src.ops import production
    from src.settings import get_settings
    from src.validation.schemas import DataContractError

    bad = prod.table(DAY, "inputs_solexs_1s").astype("float64")
    bad.iloc[100, 0] = -3.0
    bad.to_parquet(Path(get_settings().inbox_dir) / f"{DAY}.parquet")
    with pytest.raises(DataContractError, match="raw_solexs_counts"):
        production.run_day(DAY, fetch_goes=False)
    assert production.scored_days() == []


def test_daily_ingest_flow_scores_pending_days(prod, tmp_path, monkeypatch):
    monkeypatch.setenv("PREFECT_HOME", str(tmp_path / "prefect"))
    from flows.daily_ingest import daily_ingest
    from src.ops import runs

    out = daily_ingest(dvc=False)
    assert out["production"]["scored_now"] == [DAY] and out["production"]["latest_scored_day"] == DAY
    assert runs.load()["daily_ingest"]["info"]["production_scored"] == [DAY]


def test_production_api_endpoints(prod):
    from fastapi.testclient import TestClient

    from src.ops import production
    from src.serving.api import app

    with TestClient(app) as c:
        r = c.get("/production/latest").json()
        assert r["status"] == "no_data" and r["freshness"]["pending_days"] == [DAY]
        production.run_day(DAY, fetch_goes=False)
        r = c.get("/production/latest").json()
        assert r["status"] == "ok" and r["day"] == DAY and set(r["predictions"]) == {"now", "c_60m", "m_60m"}
        assert r["summary"]["rows"] == len(r["lightcurve"]["time"])
        assert c.get("/production/days").json()["scored_days"] == [DAY]
        assert c.get(f"/production/{DAY}").status_code == 200 and c.get("/production/2030-01-01").status_code == 404
        st = c.get("/pipeline/status").json()
        assert st["production"]["latest_scored_day"] == DAY and st["prefect"] == {"configured": False}


def test_check_drift_bundle_mode(prod):
    from src.ops import drift, production
    from src.settings import get_settings

    s = drift.run_bundle()
    assert s["mode"] == "bundle" and s["current_label"].startswith("development window")
    production.run_day(DAY, fetch_goes=False)
    s2 = drift.run_bundle()
    assert s2["current_label"].startswith("production")
    assert json.loads(Path(get_settings().drift_file).read_text())["mode"] == "bundle"
