"""Data contracts: the committed fixtures pass, deliberately broken samples fail with a clear message."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.validation import schemas as S

FIX = Path(__file__).resolve().parent / "fixtures"
FEATS = json.loads((FIX / "feature_columns.json").read_text(encoding="utf-8"))


def fx(name: str) -> pd.DataFrame:
    if name.endswith(".csv"):
        return pd.read_csv(FIX / name, dtype={"start": str, "end": str})
    return pd.read_parquet(FIX / name)


def broken(df, schema, *expect):
    with pytest.raises(S.DataContractError) as e:
        S.validate(df, schema, "test sample")
    msg = str(e.value)
    for x in expect:
        assert x in msg, msg
    return msg


def predictions() -> pd.DataFrame:
    t = pd.date_range("2025-07-08", periods=6, freq="10s", tz="UTC")
    p = np.array([0.1, 0.5, 0.9, 0.2, 0.3, 0.8])
    return pd.DataFrame(
        {
            "time": t,
            "target": "now",
            "model": "flare-nowcast",
            "model_version": "1",
            "p_flare": p,
            "threshold": 0.4,
            "alert": p >= 0.4,
        }
    )


def test_committed_fixtures_meet_their_contracts():
    S.validate(fx("solexs_minute.parquet"), S.SOLEXS_MINUTE)
    S.validate(fx("hel1os_coverage.csv"), S.HEL1OS_COVERAGE)
    S.validate(fx("hel1os_sessions.parquet"), S.HEL1OS_COUNTS)
    S.validate(fx("goes_events.parquet"), S.GOES_EVENTS)
    S.validate(fx("dataset_tune.parquet"), S.dataset_schema(FEATS, "tune"))
    S.validate(predictions(), S.PREDICTIONS)


def test_broken_solexs_minute():
    m = fx("solexs_minute.parquet")
    bad = m.copy()
    bad.iloc[3, bad.columns.get_loc("m")] = -5.0
    broken(bad, S.SOLEXS_MINUTE, "column m", "greater_than_or_equal_to")
    bad = m.copy()
    bad.index = bad.index + pd.Timedelta(seconds=7)
    broken(bad, S.SOLEXS_MINUTE, "60-s grid")
    broken(pd.concat([m, m.iloc[:1]]), S.SOLEXS_MINUTE, "duplicate timestamps")
    bad = m.copy()
    bad.loc[bad.index[0], "n"] = 0
    bad.loc[bad.index[0], "m"] = 12.0
    broken(bad, S.SOLEXS_MINUTE, "0 valid seconds")


def test_broken_hel1os():
    c = fx("hel1os_coverage.csv")
    broken(c.assign(session="not-a-session"), S.HEL1OS_COVERAGE, "column session")
    bad = c.copy()
    bad.loc[0, "end"] = "2000-01-01 00:00:00+00:00"
    broken(bad, S.HEL1OS_COVERAGE, "ends before it starts")
    s = fx("hel1os_sessions.parquet")
    bad = s.copy()
    bad.iloc[0, 0] = np.float32(-1)
    broken(bad, S.HEL1OS_COUNTS, "greater_than_or_equal_to")
    broken(s.drop(columns=["czt1_20-40keV"]), S.HEL1OS_COUNTS, "czt1_20-40keV")


def test_broken_goes_events():
    g = fx("goes_events.parquet")
    bad = g.copy()
    bad.loc[0, "goes_class"] = "Q9.9"
    broken(bad, S.GOES_EVENTS, "column goes_class")
    bad = g.copy()
    bad.loc[0, "peak"] = bad.loc[0, "end"] + pd.Timedelta(hours=1)
    broken(bad, S.GOES_EVENTS, "peak lies outside")
    bad = g.copy()
    bad.loc[0, "end"] = bad.loc[0, "begin"] - pd.Timedelta(minutes=5)
    broken(bad, S.GOES_EVENTS, "ends before it begins")


def test_broken_feature_dataset():
    d = fx("dataset_tune.parquet")
    sch = S.dataset_schema(FEATS, "tune")
    broken(d.drop(columns=[FEATS[0]]), sch, FEATS[0])
    bad = d.copy()
    bad.iloc[0, bad.columns.get_loc("y_now")] = np.int8(2)
    broken(bad, sch, "column y_now")
    bad = d.copy()
    i = np.flatnonzero(bad["y_c_30m"].to_numpy() == 0)[0]
    bad.iloc[i, bad.columns.get_loc("y_m_30m")] = np.int8(1)
    broken(bad, sch, "labels must be nested")
    bad = d.copy()
    bad.iloc[0, bad.columns.get_loc(FEATS[1])] = np.float32(np.inf)
    broken(bad, sch, "infinite values")
    broken(d, S.dataset_schema(FEATS, "val"), "column period")
    bad = d.copy()
    bad[FEATS[2]] = bad[FEATS[2]].astype("float64")
    broken(bad, sch, FEATS[2])


def test_broken_predictions():
    p = predictions()
    bad = p.copy()
    bad.loc[0, "p_flare"] = 1.5
    broken(bad, S.PREDICTIONS, "column p_flare")
    bad = p.copy()
    bad.loc[0, "alert"] = True
    broken(bad, S.PREDICTIONS, "alert disagrees")
    broken(pd.concat([p, p.iloc[:1]], ignore_index=True), S.PREDICTIONS, "duplicate prediction rows")
    broken(p.assign(target="tomorrow"), S.PREDICTIONS, "column target")


def test_check_cli_reports_a_broken_table(tmp_path, monkeypatch, capsys):
    from src import config
    from src.validation import check

    bad = fx("solexs_minute.parquet")
    bad.iloc[0, 0] = -1.0
    bad.to_parquet(tmp_path / "solexs_minute.parquet")
    monkeypatch.setattr(config, "processed_dir", lambda: tmp_path)
    assert check.main(["solexs_minute"]) == 1
    assert "Data contract 'solexs_minute' broken" in capsys.readouterr().err


@pytest.mark.data
def test_processed_tables_meet_their_contracts():
    from src.validation import check

    assert check.main(["solexs_minute", "hel1os", "goes_events", "dataset"]) == 0
