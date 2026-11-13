"""Operational code (src/ops, flows): window locks, ingest planning, replay, drift and challenger registration.

Everything runs on the committed fixtures and a throwaway MLflow registry; the project's mlflow.db is never touched.
"""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

from src.ops import drift, ingest, locks, replay, retrain  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
FEATS = json.loads((FIX / "feature_columns.json").read_text(encoding="utf-8"))


@pytest.fixture
def registry(tmp_path):
    import mlflow

    uri = f"sqlite:///{(tmp_path / 'reg.db').as_posix()}"
    old = mlflow.get_tracking_uri()
    mlflow.set_tracking_uri(uri)
    for name in ("t", "flare-challengers"):
        mlflow.create_experiment(name, artifact_location=(tmp_path / f"art_{name}").as_uri())
    mlflow.set_experiment("t")
    yield uri
    mlflow.set_tracking_uri(old)


def fixture_frame() -> pd.DataFrame:
    return pd.read_parquet(FIX / "dataset_tune.parquet")


# ---------------------------------------------------------------- locks
def test_windows_after_the_development_end_are_locked():
    lo, hi = locks.dev_window()
    locks.check_window(lo, hi)
    with pytest.raises(locks.LockedPeriodError):
        locks.check_window(hi - pd.Timedelta(days=1), hi + pd.Timedelta(days=1))
    with pytest.raises(locks.LockedPeriodError):
        locks.check_window("2026-10-30", "2026-11-10")


def test_scoring_never_reaches_the_old_test_period():
    from src import config

    t0 = config.period_bounds("test")[0]
    locks.check_window("2026-04-01", "2026-04-08", kind="score")
    with pytest.raises(locks.LockedPeriodError):
        locks.check_window(t0 - pd.Timedelta(days=1), t0 + pd.Timedelta(days=1), kind="score")


def test_every_model_and_evaluation_stage_is_frozen():
    stages = yaml.safe_load((ROOT / "dvc.yaml").read_text(encoding="utf-8"))["stages"]
    unfrozen = {n for n, s in stages.items() if not s.get("frozen")}
    assert unfrozen <= set(ingest.DATA_STAGES) | {"srs_fetch", "r3_fetch"}, unfrozen - set(ingest.DATA_STAGES)
    for n in ("evaluate_holdout2", "evaluate_test", "final_models", "train", "dev2_final"):
        assert stages[n].get("frozen"), n


def test_data_stages_run_their_contract():
    stages = yaml.safe_load((ROOT / "dvc.yaml").read_text(encoding="utf-8"))["stages"]
    for stage, table in (
        ("solexs_clean", "solexs_minute"),
        ("hel1os_index", "hel1os"),
        ("match_goes", "goes_events"),
        ("build_dataset", "dataset"),
    ):
        assert f"src.validation.check {table}" in stages[stage]["cmd"]
        assert "src/validation/schemas.py" in stages[stage]["deps"]


# ---------------------------------------------------------------- ingest
def test_ingest_lists_new_days_and_never_reads_locked_ones(tmp_path):
    for d in ("20250501", "20250502", "20260920", "20261105"):
        (tmp_path / f"AL1_SLX_L1_{d}_v1.0").mkdir()
    qc = tmp_path / "qc.csv"
    pd.DataFrame({"date": ["2025-05-01"]}).to_csv(qc, index=False)
    out = ingest.discover_days(tmp_path, qc)
    assert out["new_in_development"] == ["2025-05-02"]
    assert out["locked_after_development_end"] == ["2026-09-20", "2026-11-05"]


def test_ingest_never_reruns_frozen_or_model_stages():
    frozen = {"train", "evaluate_holdout2"}
    assert ingest.stages_to_run(["solexs_clean", "train", "evaluate_holdout2", "dev2_ref"], frozen) == ["solexs_clean"]


# ---------------------------------------------------------------- replay (toy champion in a throwaway registry)
def _register_toy(uri: str, name: str, cols: list[str], alias: str, thr: float, frame: pd.DataFrame) -> str:
    import mlflow
    from mlflow import MlflowClient
    from mlflow.models import infer_signature
    from sklearn.linear_model import LogisticRegression

    X, y = frame[cols], frame["y_c_30m"].to_numpy()
    clf = LogisticRegression(max_iter=500).fit(X, y)
    with mlflow.start_run():
        info = mlflow.sklearn.log_model(
            clf,
            name="model",
            signature=infer_signature(X, clf.predict_proba(X)),
            input_example=X.head(5),
            serialization_format="cloudpickle",
            pyfunc_predict_fn="predict_proba",
            registered_model_name=name,
        )
    c = MlflowClient(tracking_uri=uri)
    v = info.registered_model_version
    c.set_registered_model_alias(name, alias, v)
    c.set_model_version_tag(name, v, "thr_A", str(thr))
    c.set_model_version_tag(name, v, "ideas", "none")
    return v


def test_score_replay_writes_valid_predictions(registry, tmp_path):
    import sqlite3

    f = fixture_frame()
    cols = [c for c in FEATS if f[c].notna().all()][:6]
    _register_toy(registry, "flare-nowcast", cols, "champion", 0.5, f)
    pred = replay.score(f.index.min(), f.index.max() + pd.Timedelta(seconds=10), ["now"], tracking_uri=registry, frame=f)
    assert len(pred) == len(f) and pred["p_flare"].between(0, 1).all()
    out = replay.store(pred, tmp_path / "pred")
    assert Path(out["parquet"]).exists()
    with sqlite3.connect(out["sqlite"]) as con:
        assert con.execute("select count(*) from predictions").fetchone()[0] == len(f)
    replay.store(pred, tmp_path / "pred")  # idempotent: replaying the same window does not duplicate rows
    with sqlite3.connect(out["sqlite"]) as con:
        assert con.execute("select count(*) from predictions").fetchone()[0] == len(f)


def test_score_replay_refuses_locked_windows(registry):
    with pytest.raises(locks.LockedPeriodError):
        replay.score("2026-06-01", "2026-06-08", ["now"], tracking_uri=registry, frame=fixture_frame())


# ---------------------------------------------------------------- drift
def test_drift_report_flags_a_shifted_window(tmp_path):
    f = fixture_frame()
    cols = [c for c in FEATS if f[c].notna().all()][:8]
    ref = f[cols]
    shifted = ref + 10 * ref.std().replace(0, 1)
    s = drift.drift_report(ref, shifted, cols, tmp_path, "shifted", max_rows=300)
    same = drift.drift_report(ref, ref, cols, tmp_path, "same", max_rows=300)
    assert s["drift_flag"] and not same["drift_flag"]
    assert s["per_feature_agrees_with_evidently"] and same["per_feature_agrees_with_evidently"]
    assert (tmp_path / "shifted.html").exists() and json.loads((tmp_path / "shifted.json").read_text())[
        "features_checked"
    ] == len(cols)


# ---------------------------------------------------------------- retrain: challenger only, champion never moves
def test_retrain_registers_a_challenger_and_never_moves_the_champion(registry):
    from mlflow import MlflowClient

    f = fixture_frame()
    cols = [c for c in FEATS if f[c].notna().all()][:6]
    champ_v = _register_toy(registry, "flare-forecast-c30", cols, "champion", 0.5, f)
    block = f.index[180]  # 30-min label: both classes before and after this split
    cand = retrain.fit_candidate(
        f, cols, "c_30m", "logreg", block, f.index.max() + pd.Timedelta(seconds=10), purge_min=0, stride=1
    )
    v = retrain.register_challenger(cand, "flare-forecast-c30", "c_30m", tracking_uri=registry)
    c = MlflowClient(tracking_uri=registry)
    assert int(c.get_model_version_by_alias("flare-forecast-c30", "challenger").version) == int(v)
    assert int(c.get_model_version_by_alias("flare-forecast-c30", "champion").version) == int(champ_v)
    assert np.isfinite(cand["thresholds"]["A"]) or cand["block_rows"] > 0


def test_retrain_refuses_locked_windows(registry):
    with pytest.raises(locks.LockedPeriodError):
        retrain.retrain("c_60m", "2026-09-01", "2026-10-15", "2026-10-01", tracking_uri=registry, frame=fixture_frame())


# ---------------------------------------------------------------- flows wiring
def test_flows_are_defined_with_retries():
    from flows import check_drift, daily_ingest, retrain_candidate, score_replay

    assert daily_ingest.daily_ingest.name == "daily_ingest" and daily_ingest.repro_stage.retries == 3
    assert score_replay.score_replay.name == "score_replay" and score_replay.score.retries == 1
    assert check_drift.check_drift.name == "check_drift"
    assert retrain_candidate.retrain_candidate.name == "retrain_candidate" and retrain_candidate.fit_and_register.retries == 1
