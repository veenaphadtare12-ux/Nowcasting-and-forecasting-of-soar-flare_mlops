"""Behaviour of the GOES-style detector on synthetic 1-minute light curves."""
import numpy as np
import pandas as pd
import pytest

from src.detection import detector

T0 = pd.Timestamp("2025-04-10", tz="UTC")
S = detector.DetectorSettings()  # library defaults; the tests do not depend on tuned values


def _minutes(rate: np.ndarray, seed: int = 0) -> pd.Series:
    """Minute means of Poisson 1 s counts with the given per-minute mean rate (labels = minute END)."""
    rng = np.random.default_rng(seed)
    m = rng.poisson(np.repeat(rate, 60)).reshape(-1, 60).mean(axis=1)
    return pd.Series(m, index=pd.date_range(T0 + pd.Timedelta(minutes=1), periods=len(rate), freq="min"))


def _flare(n=1440, bg=20.0, start=600, rise=6, amp=200.0, tau=15.0):
    rate = np.full(n, bg)
    k = np.arange(n - start)
    shape = np.where(k < rise, (k + 1) / rise, np.exp(-(k - rise + 1) / tau))
    rate[start:] += amp * shape
    return rate


def test_onset_is_start_of_sustained_rise():
    """Onset = first minute of the sustained rise. Walking back a strictly increasing run can absorb a few noise
    minutes that happen to rise, so the error is checked over many noise realisations, not one."""
    true_onset = T0 + pd.Timedelta(minutes=600)  # minute 600 is the first elevated minute (its START)
    errs = []
    for seed in range(20):
        ev = detector.detect_series(_minutes(_flare(), seed=seed), S)
        assert len(ev) == 1
        assert ev.loc[0, "trigger_time"] >= ev.loc[0, "onset"] + pd.Timedelta(minutes=1)
        errs.append((ev.loc[0, "onset"] - true_onset).total_seconds() / 60)
    errs = np.array(errs)
    assert np.median(np.abs(errs)) <= 1.0
    assert errs.min() >= -4 and errs.max() <= 1  # never late by more than a minute; rarely a few minutes early


def test_end_is_halfway_decay():
    rate = _flare(amp=400.0, tau=20.0)
    ev = detector.detect_series(_minutes(rate), S)
    peak_min = 600 + 6 - 1
    # excess falls to half the peak after tau*ln2 minutes of decay
    expected = T0 + pd.Timedelta(minutes=peak_min + 20 * np.log(2))
    assert abs((ev.loc[0, "end"] - expected).total_seconds()) <= 3 * 60


def test_background_is_frozen_during_event():
    rate = _flare(amp=800.0, tau=60.0)
    ev = detector.detect_series(_minutes(rate), S)
    assert ev.loc[0, "bg_counts_s"] == pytest.approx(20.0, rel=0.15)  # pre-flare level, not inflated by the flare


def test_trigger_is_causal():
    m = _minutes(_flare())
    full = detector.detect_series(m, S)
    trig = full.loc[0, "trigger_time"]
    cut = detector.detect_series(m[m.index <= trig + pd.Timedelta(minutes=3)], S)
    assert cut.loc[0, "trigger_time"] == trig and cut.loc[0, "onset"] == full.loc[0, "onset"]


def test_double_peak_split_by_dip():
    # second flare starts while the first has decayed to ~60 % of its excess (a 40 % dip, above the halfway end)
    rate = _flare(amp=300.0, tau=40.0) + np.r_[np.zeros(625), _flare(n=1440 - 625, bg=0.0, start=0, amp=300.0, tau=40.0)]
    m = _minutes(rate)
    split = detector.detect_series(m, detector.DetectorSettings(dip_frac=0.3))
    merged = detector.detect_series(m, detector.DetectorSettings(dip_frac=0.9))
    assert len(split) == len(merged) + 1
    assert split["was_split"].any()


def test_max_duration_cap():
    rate = np.full(1440, 20.0)
    rate[300:305] = np.linspace(40, 200, 5)
    rate[305:] = 200.0  # never decays: a level shift, not a flare
    ev = detector.detect_series(_minutes(rate), detector.DetectorSettings(max_duration_s=3 * 3600))
    assert ev["hit_cap"].any()
    assert ev["duration_s"].max() <= 3 * 3600


def test_noise_only_gives_no_events():
    assert detector.detect_series(_minutes(np.full(1440, 20.0)), S).empty


# ---- split detections are known only when the whole detection has ended (fix of 2026-11-13)
def _truncation_check(m: pd.Series, s, cuts) -> int:
    """For every cut c, rebuild the catalogue from data <= c only. Every event the full catalogue shows as triggered by c
    must exist (same onset) in the cut catalogue, and every event whose end it shows as known by c must exist there
    with the same onset AND end. Returns how many (event, cut) pairs were checked."""
    full = detector.detect_series(m, s)
    n = 0
    for c in cuts:
        cut = detector.detect_series(m[m.index <= c], s)
        onsets = set(cut["onset"])
        ends = set(zip(cut["onset"], cut["end"]))
        for _, e in full[full["trigger_time"] <= c].iterrows():
            assert e["onset"] in onsets, f"event with onset {e['onset']} visible at {c} before the detector knew it"
            n += 1
        for _, e in full[full["end_known_time"] <= c].iterrows():
            assert (e["onset"], e["end"]) in ends, f"end of event {e['onset']} counted as known at {c} too early"
    return n


def test_split_segments_are_not_known_before_the_detection_ends():
    rate = _flare(amp=300.0, tau=40.0) + np.r_[np.zeros(625), _flare(n=1440 - 625, bg=0.0, start=0, amp=300.0, tau=40.0)]
    m = _minutes(rate)
    s = detector.DetectorSettings(dip_frac=0.3)
    full = detector.detect_series(m, s)
    assert full["was_split"].any() and (full["segment"] > 0).any()
    later = full[full["segment"] > 0]
    assert (later["trigger_time"] == later["end_known_time"]).all()
    assert full.groupby("trigger_time").size().max() >= 1
    t0, t1 = full["trigger_time"].min(), full["end_known_time"].max() + pd.Timedelta(minutes=5)
    assert _truncation_check(m, s, pd.date_range(t0, t1, freq="min")) > 0


def test_unsplit_events_keep_the_usual_end_rule():
    ev = detector.detect_series(_minutes(_flare()), S)
    assert len(ev) == 1 and ev.loc[0, "segment"] == 0
    assert ev.loc[0, "end_known_time"] == ev.loc[0, "end"] + pd.Timedelta(minutes=S.end_confirm_min)


def test_real_split_detections_pass_the_truncation_check():
    """Real SoLEXS data: the first three split detections of the tune period, cut at every minute of their life."""
    from src import config

    proc = config.processed_dir()
    if not (proc / "events.parquet").exists():
        pytest.skip("processed data not available")
    s = detector.DetectorSettings.from_params(config.load_params()["flare_detection"])
    ev = pd.read_parquet(proc / "events.parquet")
    if "segment" not in ev.columns:
        pytest.skip("catalogue predates the fix; run dvc repro")
    m = pd.read_parquet(proc / "solexs_minute.parquet")["m"]
    starts = ev.loc[ev["segment"] > 0, "onset"].head(3)
    assert len(starts)
    checked = 0
    for on in starts:
        w = m[(m.index > on - pd.Timedelta(hours=6)) & (m.index <= on + pd.Timedelta(hours=6))]
        full = detector.detect_series(w, s)
        near = full[(full["onset"] <= on) & (full["end_known_time"] >= on)]
        cuts = pd.date_range(near["trigger_time"].min(), near["end_known_time"].max() + pd.Timedelta(minutes=3), freq="min")
        checked += _truncation_check(w, s, cuts)
    assert checked > 0
