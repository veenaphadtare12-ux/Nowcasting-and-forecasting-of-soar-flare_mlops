"""Integration contract (docs/ARCHITECTURE.md): one source of truth for features and models.

- Features the API computes (src/serving/features.py = the pipeline's src/features.py code) equal the pipeline's own
  dataset rows, for every model-bundle day (runs in CI: everything comes from the committed bundle).
- The bundle is intact (SHA-256), its stored predictions are what its models produce, and (locally) its model versions
  are the registry champions.
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.serving import bundle as B
from src.serving import features as sf

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = B.Bundle(ROOT / "model_bundle")
DAYS = list(BUNDLE.days)


@pytest.mark.parametrize("day", DAYS)
def test_api_features_equal_pipeline_features(day):
    counts = BUNDLE.table(day, "inputs_solexs_1s")["counts"]
    hel = BUNDLE.table(day, "inputs_hel1os_1s")
    pipe = BUNDLE.table(day, "features_pipeline")
    feats = BUNDLE.model_meta("now")["features"]
    api = sf.day_features(counts, pd.Timestamp(day, tz="UTC"), hel)[feats]
    ref = pipe[feats]
    assert api.index.equals(ref.index)
    pd.testing.assert_frame_equal(api, ref, check_exact=True, check_freq=False)


def test_bundle_files_match_the_manifest():
    assert BUNDLE.verify() == []
    size = sum(p.stat().st_size for p in (ROOT / "model_bundle").rglob("*") if p.is_file())
    assert size < 50e6


def test_bundle_holds_no_holdout_or_test_days():
    from src import config

    for d in DAYS:
        t = pd.Timestamp(d, tz="UTC")
        assert config.period_bounds("tune")[0] <= t < config.period_bounds("val")[1], d


@pytest.mark.parametrize("day", DAYS[:2])
def test_stored_predictions_are_what_the_bundle_models_produce(day):
    pred = BUNDLE.table(day, "predictions")
    for target in BUNDLE.manifest["models"]:
        X = BUNDLE.model_input(day, target)
        p = BUNDLE.model(target).predict_proba(X)[:, 1]
        stored = pred[pred["target"] == target].set_index("time")["p_flare"]
        np.testing.assert_allclose(stored.to_numpy(), np.clip(p, 0, 1), rtol=1e-6, atol=1e-7)


def test_a_tampered_model_file_is_refused(tmp_path):
    import shutil

    shutil.copytree(ROOT / "model_bundle", tmp_path / "b")
    f = tmp_path / "b" / BUNDLE.model_meta("now")["file"]
    f.write_bytes(f.read_bytes() + b"x")
    with pytest.raises(RuntimeError, match="SHA-256"):
        B.Bundle(tmp_path / "b").model("now")


@pytest.mark.data
def test_bundle_models_are_the_registry_champions():
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    from mlflow import MlflowClient

    from src import config

    c = MlflowClient(tracking_uri=config.mlflow_uri())
    for target, m in BUNDLE.manifest["models"].items():
        mv = c.get_model_version_by_alias(m["registry_name"], "champion")
        assert str(mv.version) == m["version"] and mv.run_id == m["run_id"], target


@pytest.mark.data
def test_api_features_equal_the_dvc_dataset_directly():
    from src import config

    day = "2026-04-24"
    feats = BUNDLE.model_meta("now")["features"]
    ds = pd.read_parquet(config.processed_dir() / "dataset" / "val.parquet", columns=feats)
    t = pd.Timestamp(day, tz="UTC")
    ref = ds[(ds.index > t) & (ds.index <= t + pd.Timedelta(days=1))]
    api = sf.day_features(BUNDLE.table(day, "inputs_solexs_1s")["counts"], t, BUNDLE.table(day, "inputs_hel1os_1s"))[feats]
    pd.testing.assert_frame_equal(api, ref, check_exact=True, check_freq=False)
