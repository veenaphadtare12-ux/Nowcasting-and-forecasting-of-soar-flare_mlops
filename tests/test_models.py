"""Model-stage tests: verification metrics are correct, and training cannot touch the test period."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.models import metrics, train

ROOT = Path(__file__).resolve().parents[1]


def test_tss_hss_on_known_table():
    c = {"tp": 50, "fn": 50, "fp": 10, "tn": 890}
    assert metrics.tss(c) == pytest.approx(0.5 - 10 / 900)
    # HSS = 2(TP*TN - FN*FP) / ((TP+FN)(FN+TN) + (TP+FP)(FP+TN))
    assert metrics.hss(c) == pytest.approx(2 * (50 * 890 - 50 * 10) / (100 * 940 + 60 * 900))


def test_perfect_and_no_skill_forecasts():
    y = np.r_[np.ones(100), np.zeros(900)].astype(bool)
    assert metrics.tss(metrics.contingency(y, y)) == pytest.approx(1.0)
    assert metrics.tss(metrics.contingency(y, np.zeros_like(y))) == pytest.approx(0.0)  # "never a flare" = no skill
    assert metrics.evaluate(y, np.zeros(1000), 0.5)["accuracy"] == pytest.approx(0.9)  # 90 % accurate, zero skill


def test_best_threshold_matches_brute_force():
    rng = np.random.default_rng(0)
    y = rng.random(2000) < 0.1
    s = np.round(rng.random(2000) + 0.6 * y, 2)  # ties on purpose
    thr, val = metrics.best_threshold(y, s, "tss")
    brute = max(metrics.tss(metrics.contingency(y, s >= t)) for t in np.unique(s))
    assert val == pytest.approx(brute)
    assert metrics.tss(metrics.contingency(y, s >= thr)) == pytest.approx(brute)


def test_training_refuses_the_test_period():
    with pytest.raises(ValueError):
        train.load_period("test")


def test_model_code_never_names_the_test_file():
    for f in (ROOT / "src" / "models").glob("*.py"):
        assert "test.parquet" not in f.read_text(encoding="utf-8"), f


def test_inner_split_is_chronological_with_purge():
    idx = pd.date_range("2025-11-29", "2025-12-03", freq="10s", tz="UTC")
    df = pd.DataFrame({"x": np.arange(len(idx))}, index=idx)
    fit, cal = train.split_tune(df, "2025-12-01", purge_min=120)
    cut = pd.Timestamp("2025-12-01", tz="UTC")
    assert fit.index.max() < cut - pd.Timedelta(minutes=120)
    assert cal.index.min() >= cut
    assert len(fit) + len(cal) < len(df)  # the purge gap really drops rows
