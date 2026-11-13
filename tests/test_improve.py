"""Leakage tests for the improvement experiments (rolling protocol + new features)."""
import numpy as np
import pandas as pd
import pytest

from src import config
from src.improve import features_extra as fx
from src.improve import protocol as pr

P = config.load_params()


# ---------------------------------------------------------------- protocol
def test_rolling_protocol_never_uses_month_m_to_fit_or_set_thresholds():
    idx = pd.date_range("2025-04-09", "2026-05-31 23:59", freq="1min", tz="UTC")
    purge = pd.Timedelta(minutes=P["improve"]["purge_min"])
    for m in P["improve"]["months"]:
        s_m = pr.month_start(m)
        s_prev = s_m - pd.offsets.MonthBegin(1)
        mk = pr.fold_masks(idx, m, P["improve"]["purge_min"])
        fit, cal, sc = idx[mk["fit"]], idx[mk["cal"]], idx[mk["score"]]
        assert fit.max() < s_prev - purge                      # fit ends a purge gap before the threshold month
        assert cal.min() >= s_prev and cal.max() < s_m - purge  # threshold month, purged at its end
        assert sc.min() >= s_m and sc.max() < s_m + pd.offsets.MonthBegin(1)
        assert not (mk["fit"] & mk["score"]).any() and not (mk["cal"] & mk["score"]).any()
        # nothing used for fitting or thresholds lies inside month m or within a label window of it
        assert max(fit.max(), cal.max()) < s_m - purge


def test_adaptive_threshold_windows_stay_in_the_past_and_after_the_fit_data():
    purge = P["improve"]["purge_min"]
    for m in P["improve"]["months"]:
        s_m = pr.month_start(m)
        days = pd.date_range(s_m, s_m + pd.offsets.MonthBegin(1) - pd.Timedelta(minutes=1), freq="1h", tz="UTC")
        for d, w0, w1 in pr.rolling_windows(days, pr.fold_bounds(m, purge)["cal_start"], P["improve"]["rolling_days"], purge):
            assert w1 == d - pd.Timedelta(minutes=purge) and w1 < d    # only labels resolved before the day
            assert w0 >= pr.fold_bounds(m, purge)["cal_start"]        # never the in-sample fit rows


def test_far_cap_threshold_matches_brute_force():
    rng = np.random.default_rng(1)
    y = rng.random(4000) < 0.05
    s = np.round(rng.random(4000) + 0.6 * y, 2)
    thr = pr.thr_far_cap(y, s, 0.8)
    ok = [t for t in np.unique(s) if (s >= t).sum() and ((~y) & (s >= t)).sum() / (s >= t).sum() <= 0.8 and (y & (s >= t)).sum()]
    assert thr == pytest.approx(min(ok))


@pytest.mark.data
def test_improve_loader_never_returns_test_rows():
    d = pr.load(["rate"])
    assert d.index.max() < config.period_bounds("val")[1]


# ---------------------------------------------------------------- future perturbation of every new feature
T_CUT = pd.Timestamp("2025-06-03 13:37", tz="UTC")


def _minutes(days=4, seed=0):
    idx = pd.date_range("2025-06-01 00:01", periods=days * 1440, freq="1min", tz="UTC")
    rng = np.random.default_rng(seed)
    return idx, rng


def _same_up_to_cut(a: pd.DataFrame, b: pd.DataFrame):
    a, b = a[a.index <= T_CUT], b[b.index <= T_CUT]
    pd.testing.assert_frame_equal(a, b, check_freq=False)


def test_long_context_features_do_not_see_the_future():
    idx, rng = _minutes()
    m = pd.Series(10 + rng.random(len(idx)) * 5, index=idx)
    ev = pd.DataFrame({"trigger_time": pd.to_datetime(["2025-06-02 03:00", "2025-06-03 12:00", "2025-06-03 15:00"], utc=True),
                       "end": pd.to_datetime(["2025-06-02 03:30", "2025-06-03 14:00", "2025-06-03 15:40"], utc=True),
                       "peak_counts_s": [80.0, 300.0, 500.0], "hit_cap": False, "ended_by_gap": False})
    full = fx.long_context_grid(m, ev, P["improve"], P["flare_detection"])
    # future changed: data after the cut scrambled, event triggered after the cut removed, and the event still
    # running at the cut gets a different (future) end and peak
    m2 = m.copy()
    m2[m2.index > T_CUT] = rng.random((m2.index > T_CUT).sum()) * 1000
    ev2 = ev[ev["trigger_time"] <= T_CUT].copy()
    ev2.loc[1, ["end", "peak_counts_s"]] = [pd.Timestamp("2025-06-03 20:00", tz="UTC"), 9999.0]
    cut = fx.long_context_grid(m2, ev2, P["improve"], P["flare_detection"])
    _same_up_to_cut(full, cut)
    assert full.loc[T_CUT, "ev_n_6h"] == 1 and full.loc[T_CUT, "ev_max_peak_6h"] == 0  # triggered but not yet confirmed


def test_spectral_and_goes_features_do_not_see_the_future():
    idx, rng = _minutes()
    sp = pd.DataFrame({"low": 300 + rng.random(len(idx)) * 50, "high": 10 + rng.random(len(idx)) * 5}, index=idx)
    sp["total"] = sp["low"] + sp["high"] + 50
    x = pd.DataFrame({"xrsa": 1e-7 * (1 + rng.random(len(idx))), "xrsb": 1e-6 * (1 + rng.random(len(idx)))}, index=idx)
    for fn, frame in ((fx.spectral_grid, sp), (fx.goes_grid, x)):
        f2 = frame.copy()
        f2[f2.index > T_CUT] = f2[f2.index > T_CUT] * 50
        _same_up_to_cut(fn(frame), fn(f2))


def test_drift_normalised_features_do_not_see_the_future():
    idx = pd.date_range("2025-06-01", periods=4 * 8640, freq="10s", tz="UTC")
    rng = np.random.default_rng(2)
    df = pd.DataFrame({c: 5 + rng.random(len(idx)) for c in fx.LEVEL_FEATURES + fx.SIGNED_FEATURES}, index=idx)
    d2 = df.copy()
    d2[d2.index > T_CUT] = 1000.0
    _same_up_to_cut(fx.drift_normalise(df, 7), fx.drift_normalise(d2, 7))


def test_asof_join_only_uses_grid_points_at_or_before_the_row():
    g = pd.DataFrame({"v": [1.0, 2.0]}, index=pd.to_datetime(["2025-06-01 00:01", "2025-06-01 00:02"], utc=True))
    rows = pd.to_datetime(["2025-06-01 00:01:00", "2025-06-01 00:01:50", "2025-06-01 00:02:00"], utc=True)
    assert fx.asof_rows(g, pd.DatetimeIndex(rows))["v"].tolist() == [1.0, 1.0, 2.0]
