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


def test_rolling_origin_folds_train_only_on_the_past():
    idx = pd.date_range("2025-06-01", "2025-11-30 20:00", freq="10min", tz="UTC")
    df = pd.DataFrame({"x": np.arange(len(idx))}, index=idx)
    folds = train.cv_folds(df, ["2025-08", "2025-09", "2025-10", "2025-11"], purge_min=120)
    assert [f[2] for f in folds] == ["2025-08", "2025-09", "2025-10", "2025-11"]
    for tr, va, m in folds:
        start = pd.Timestamp(m + "-01", tz="UTC")
        assert tr.index.max() < start - pd.Timedelta(minutes=120)        # purge gap before the scored month
        assert va.index.min() >= start and va.index.max() < start + pd.offsets.MonthBegin(1)
    assert len(folds[-1][0]) > len(folds[0][0])                           # the training window grows (rolling origin)


def test_cv_months_lie_inside_the_fit_part_of_tune():
    from src import config

    P = config.load_params()["models"]
    split = pd.Timestamp(P["inner_split"], tz="UTC")
    for m in P["cv"]["fold_months"]:
        assert pd.Timestamp(m + "-01", tz="UTC") + pd.offsets.MonthBegin(1) <= split  # never touches Dec-Jan or val


def test_hss_operating_point_matches_brute_force():
    rng = np.random.default_rng(3)
    y = rng.random(3000) < 0.05
    s = np.round(rng.random(3000) + 0.5 * y, 2)
    thr, val = metrics.best_threshold(y, s, "hss")
    brute = max(metrics.hss(metrics.contingency(y, s >= t)) for t in np.unique(s))
    assert val == pytest.approx(brute)


def test_day_bootstrap_interval_brackets_the_estimate_and_is_reproducible():
    rng = np.random.default_rng(0)
    n_days, per_day = 60, 200
    day = np.repeat(np.arange(n_days), per_day)
    y = rng.random(n_days * per_day) < 0.1
    yhat = np.where(rng.random(len(y)) < 0.7, y, ~y)
    dc = metrics.daily_counts(y, yhat, day, n_days)
    point = metrics.tss(metrics.contingency(y, yhat))
    assert metrics.tss_from_counts(dc.sum(axis=0)) == pytest.approx(point)
    idx = metrics.bootstrap_indices(n_days, 500, seed=0)
    lo, hi = metrics.bootstrap_mean_tss([dc], idx)
    assert lo < point < hi
    assert (lo, hi) == metrics.bootstrap_mean_tss([dc], metrics.bootstrap_indices(n_days, 500, seed=0))


def test_climatology_and_persistence_baselines():
    y_cal = np.array([0, 1, 0, 0]); y_val = np.array([0, 1, 1, 0, 0, 0])
    flag = np.array([0, 1, 0, 1, 0, 0], dtype=float)
    days = np.zeros(6, dtype=int)
    quiet = flag == 0
    ops = {"A": "tss", "B": "hss"}
    clim = train._score_block(y_cal, np.full(4, 0.25), y_val, np.full(6, 0.25), quiet, days, 1, ops, fixed_threshold=0.25 + 1e-12)
    assert clim["A"]["all"]["tss"] == 0.0 and clim["A"]["all"]["tp"] + clim["A"]["all"]["fp"] == 0  # never alerts
    pers = train._score_block(y_cal, np.zeros(4), y_val, flag, quiet, days, 1, ops, fixed_threshold=0.5)
    assert pers["A"]["all"]["tp"] == 1 and pers["A"]["all"]["fp"] == 1        # alerts exactly where the flag is on
    assert pers["A"]["quiet"]["tp"] + pers["A"]["quiet"]["fp"] == 0          # no alerts on quiet-start rows


def test_ablation_feature_sets_and_positive_episodes():
    from src.models import ablation

    feats = ["rate", "mean_5m", "hel1os_available", "hx_czt_lo_max_5m", "hx_hr_cdte"]
    s = ablation.feature_sets(feats)
    assert s["soft"] == ["rate", "mean_5m"]
    assert s["hard"] == ["hx_czt_lo_max_5m", "hx_hr_cdte"]
    assert s["combined"] == s["soft"] + s["hard"]
    assert "hel1os_available" not in s["combined"]        # constant (=1) on the ablation rows
    t0 = pd.Timestamp("2026-04-01", tz="UTC")
    t = pd.DatetimeIndex([t0 + pd.Timedelta(seconds=x) for x in (0, 10, 20, 30, 40, 400, 410)])
    d = pd.DataFrame({"y": [1, 1, 0, 1, 1, 1, 1]}, index=t)
    # a short negative blip (<= 60 s) does not split an episode (conservative count); a 6-minute gap does
    assert ablation.positive_episodes(d, "y") == 2
