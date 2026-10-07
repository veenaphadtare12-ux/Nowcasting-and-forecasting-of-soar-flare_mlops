"""Leakage tests (CLAUDE.md rules 1-3): causal features, labels strictly after the window, chronological splits."""
import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import config, dataset, features, labels
from src.detection import tune

ROOT = Path(__file__).resolve().parents[1]
T0 = pd.Timestamp("2025-04-10", tz="UTC")


def _counts(n=6 * 3600, seed=0) -> pd.Series:
    rng = np.random.default_rng(seed)
    rate = np.full(n, 20.0)
    rate[4 * 3600 : 4 * 3600 + 900] += 150 * np.exp(-np.arange(900) / 200)
    s = pd.Series(rng.poisson(rate).astype(float), index=pd.date_range(T0, periods=n, freq="s"))
    return s.drop(s.index[rng.choice(n, n // 50, replace=False)])  # some missing seconds


def _features(counts):
    return features.solexs_features(features.bin_counts(counts, 10), [1, 5, 15, 60], 10)


# ---------------------------------------------------------------- features are causal
@pytest.mark.parametrize("cut_h", [1.5, 4.05, 4.2])
def test_features_unchanged_when_future_is_altered(cut_h):
    c = _counts()
    t_cut = T0 + pd.Timedelta(hours=cut_h)
    altered = c.copy()
    fut = altered.index > t_cut
    altered[fut] = altered[fut] * 7.0 + 1000.0  # wildly different future
    a, b = _features(c), _features(altered)
    rows = a.index <= t_cut
    pd.testing.assert_frame_equal(a[rows], b[rows])
    assert not a[~rows].equals(b[~rows])  # sanity: the future change is visible after the cut


def test_feature_bins_are_right_closed():
    c = pd.Series([1.0, 2.0, 3.0], index=pd.DatetimeIndex([T0 + pd.Timedelta(seconds=s) for s in (1, 10, 11)]))
    b = features.bin_counts(c, 10)
    assert b.loc[T0 + pd.Timedelta(seconds=10), "rate"] == pytest.approx(1.5)  # (0, 10] holds seconds 1 and 10
    assert b.loc[T0 + pd.Timedelta(seconds=20), "rate"] == pytest.approx(3.0)


def test_no_centered_windows_or_negative_shifts_in_feature_code():
    """Inspect the code (AST), not the text, so docstrings mentioning the rule do not count."""
    import ast

    tree = ast.parse(inspect.getsource(features))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                assert not (kw.arg == "center" and isinstance(kw.value, ast.Constant) and kw.value.value is True)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "shift" and node.args:
                a = node.args[0]
                assert not (isinstance(a, ast.UnaryOp) and isinstance(a.op, ast.USub)), "negative shift = future data"
                if isinstance(a, ast.Constant):
                    assert a.value >= 0


def test_feature_columns_exclude_labels_and_catalogue():
    cols = dataset.feature_columns(pd.DataFrame(columns=["rate", "mean_5m", "y_now", "ok_now", "y_c_30m", "period"]))
    assert cols == ["rate", "mean_5m"]
    forbidden = {"onset", "peak", "end", "goes_class", "is_goes_matched", "trigger_time", "excess_counts_s"}
    assert not forbidden & set(_features(_counts()).columns)


# ---------------------------------------------------------------- labels are strictly after the window
def _events(onsets, ends, classes, matched):
    return pd.DataFrame({"onset": pd.DatetimeIndex(onsets), "end": pd.DatetimeIndex(ends), "goes_class": classes,
                         "is_goes_matched": matched})


def test_forecast_label_uses_only_onsets_strictly_after_t():
    t = pd.date_range(T0, periods=4, freq="10min")
    on = labels.qualifying_onsets(_events([t[1]], [t[1] + pd.Timedelta(minutes=5)], ["C2.0"], [True]), "C1.0")
    y = labels.forecast_label(t, on, 30)
    # t0: onset at +10 min is within (t0, t0+30] -> 1; t1: onset == t1 is NOT after t1 -> 0
    assert list(y) == [1, 0, 0, 0]


def test_unmatched_detections_are_never_positive():
    t = pd.date_range(T0, periods=6, freq="10min")
    ev = _events([t[2]], [t[4]], [pd.NA], [False])
    assert labels.nowcast_label(t, ev).sum() == 0
    assert labels.forecast_label(t, labels.qualifying_onsets(ev, None), 60).sum() == 0


def test_class_thresholds_come_from_goes_match():
    t = pd.date_range(T0, periods=3, freq="10min")
    ev = _events([t[1], t[2]], [t[2], t[2] + pd.Timedelta(minutes=5)], ["B9.0", "M1.2"], [True, True])
    assert list(labels.forecast_label(t, labels.qualifying_onsets(ev, "C1.0"), 30)) == [1, 1, 0]
    assert list(labels.forecast_label(t, labels.qualifying_onsets(ev, "M1.0"), 30)) == [1, 1, 0]
    assert list(labels.forecast_label(t[:1], labels.qualifying_onsets(ev, "M1.0"), 10)) == [0]


def test_nowcast_label_is_in_progress_window():
    t = pd.date_range(T0, periods=6, freq="5min")
    ev = _events([t[1]], [t[3]], ["C1.0"], [True])
    assert list(labels.nowcast_label(t, ev)) == [0, 1, 1, 0, 0, 0]  # onset <= t < end


def test_label_window_never_crosses_period_end():
    t = pd.date_range(T0, periods=12, freq="10min")
    valid = pd.Series(True, index=pd.date_range(T0, periods=600, freq="min") + pd.Timedelta(minutes=1))
    end = pd.Series(T0 + pd.Timedelta(minutes=60), index=t)
    ok = labels.future_ok(t, 30, valid, end, [], 0.9)
    assert list(ok) == [True, True, True, True, False, False, False, False, False, False, False, False]


def test_label_not_ok_without_goes_truth_or_data():
    t = pd.date_range(T0, periods=3, freq="h")
    valid = pd.Series(True, index=pd.date_range(T0, periods=600, freq="min") + pd.Timedelta(minutes=1))
    end = pd.Series(T0 + pd.Timedelta(days=2), index=t)
    assert not labels.future_ok(t, 30, valid, end, [T0], 0.9).any()  # whole day has no GOES report
    gappy = valid.copy()
    gappy.iloc[60:120] = False  # no data 01:00-02:00
    assert list(labels.future_ok(t, 30, gappy, end, [], 0.9)) == [True, False, True]


# ---------------------------------------------------------------- splits & tuning
def test_periods_are_chronological_and_disjoint():
    config.validate_periods()
    b = [config.period_bounds(p) for p in config.PERIOD_NAMES]
    assert b[0][1] <= b[1][0] and b[1][1] <= b[2][0]
    assert list(config.assign_period(pd.DatetimeIndex([b[0][1] - pd.Timedelta(seconds=1), b[0][1]]))) == ["tune", "val"]


def test_tuner_only_reads_the_tune_period():
    src = inspect.getsource(tune)
    assert 'period_bounds("tune")' in src and '"val"' not in src and '"test"' not in src


@pytest.mark.skipif(not (config.processed_dir() / "dataset" / "tune.parquet").exists(), reason="dataset not built")
def test_built_dataset_files_are_chronological():
    spans = {}
    for p in config.PERIOD_NAMES:
        idx = pd.read_parquet(config.processed_dir() / "dataset" / f"{p}.parquet", columns=["period"]).index
        lo, hi = config.period_bounds(p)
        assert idx.min() >= lo and idx.max() < hi + pd.Timedelta(seconds=10)
        spans[p] = (idx.min(), idx.max())
    assert spans["tune"][1] < spans["val"][0] and spans["val"][1] < spans["test"][0]
