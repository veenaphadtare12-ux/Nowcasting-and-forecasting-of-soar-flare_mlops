"""Test-lock and final-stage tests: only evaluate_test may read test.parquet; the frozen models never see test rows."""
import ast
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src import config, labels
from src.final import analysis, freeze

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_TEST_READERS = {"src/dataset.py", "src/final/evaluate_test.py"}  # writer + the one-time scorer
# the test dataset file itself; a name like goes_xrs_minute_test.parquet must not match
TEST_FILE = re.compile(r"(?<![A-Za-z0-9_])test[.]parquet")


def test_the_test_file_pattern_matches_only_the_test_dataset():
    assert TEST_FILE.search("dataset/test.parquet") and TEST_FILE.search('"test.parquet"')
    assert not TEST_FILE.search("goes_xrs_minute_test.parquet") and not TEST_FILE.search("test_scores.parquet")


def test_only_evaluate_test_names_the_test_file():
    for f in (ROOT / "src").rglob("*.py"):
        rel = f.relative_to(ROOT).as_posix()
        if TEST_FILE.search(f.read_text(encoding="utf-8")):
            assert rel in ALLOWED_TEST_READERS, f"{rel} names test.parquet"
    assert TEST_FILE.search((ROOT / "src" / "final" / "evaluate_test.py").read_text(encoding="utf-8"))


def test_only_the_evaluate_test_stage_depends_on_test_period_outputs():
    stages = yaml.safe_load((ROOT / "dvc.yaml").read_text(encoding="utf-8"))["stages"]
    test_outputs = {"data/processed/final/solexs_spectral_minute_test.parquet",
                    "data/processed/final/goes_xrs_minute_test.parquet", "data/processed/final/test_scores.parquet"}
    readers = {name for name, s in stages.items() if test_outputs & set(s.get("deps", []))}
    # Since 2026-11-13 the old test period is development data (docs/IMPROVEMENTS.md section 9): the dev2 stages may read
    # its INPUTS, but its one-time test SCORES stay readable only by test_analysis (never re-reported or re-scored).
    assert readers - {n for n in stages if n.startswith("dev2_")} == {"evaluate_test", "test_analysis"}
    score_readers = {name for name, s in stages.items() if "data/processed/final/test_scores.parquet" in s.get("deps", [])}
    assert score_readers == {"test_analysis"}
    assert all(stages[n].get("frozen") for n in ("evaluate_test", "test_analysis", "final_models"))
    assert not TEST_FILE.search(json.dumps(stages))  # the file is read only by the evaluate_test code


def test_frozen_fit_and_threshold_blocks_end_before_the_test_period():
    F = config.load_params()["final"]
    idx = pd.date_range("2025-04-09", "2026-09-12", freq="10min", tz="UTC")
    b = freeze.blocks(idx)
    test_start = config.period_bounds("test")[0]
    assert idx[b["fit"]].max() < pd.Timestamp(F["threshold_block"][0], tz="UTC") - pd.Timedelta(minutes=F["purge_min"]) + pd.Timedelta(minutes=10)
    assert idx[b["block"]].max() < test_start - pd.Timedelta(minutes=F["purge_min"])
    assert not (b["fit"] & b["block"]).any()


def test_final_choice_is_complete_and_matches_the_registry_names():
    F = config.load_params()["final"]
    for t, s in F["targets"].items():
        assert s["model"] in ("logreg", "xgb", "ensemble") and s["registry"].startswith("flare-")
        assert set(s["ideas"]) <= {"E2", "E3", "E4", "E5", "E6"}
    assert (ROOT / "docs" / "FINAL_CHOICE.md").exists()


@pytest.mark.data
def test_flare_starts_match_the_label_rule():
    proc = config.processed_dir()
    g = pd.read_parquet(proc / "goes_matched.parquet")
    e = pd.read_parquet(proc / "events.parquet")
    p = pd.read_parquet(proc / "events_pairs.parquet")
    fl = analysis.flare_starts(g, e, p)
    for cls in ("C1.0", "M1.0"):
        mine = np.sort(fl.loc[fl["flux"] >= analysis.goes_flux(cls), "start"].dropna().to_numpy(dtype="datetime64[ns]").astype("int64"))
        assert np.array_equal(mine, labels.goes_onsets(g, e, p, cls))


def test_threshold_helpers():
    rng = np.random.default_rng(0)
    y = rng.random(3000) < 0.1
    s = rng.random(3000) + 0.5 * y
    th = freeze.thresholds(y, s, 0.8)
    assert set(th) == {"A", "B", "C"}
    assert freeze.ece(y.astype(float), np.full(3000, y.mean())) == pytest.approx(0.0, abs=1e-12)


def test_analysis_never_reads_the_test_dataset():
    tree = ast.parse((ROOT / "src" / "final" / "analysis.py").read_text(encoding="utf-8"))
    names = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not any(TEST_FILE.search(v) for v in names)
