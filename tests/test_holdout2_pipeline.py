"""Dry run of the holdout2 input builder on DEVELOPMENT days: it must reproduce the development dataset.

src/holdout2/evaluate.build_inputs builds SoLEXS/HEL1OS features, detector events, labels, the activity flag and the
extra feature blocks from raw files, exactly as the development pipeline does. Run on development days (never on
holdout2), its rows must equal the rows in data/processed/dataset, and its extra blocks must equal src/dev2/run's.
"""
import numpy as np
import pandas as pd
import pytest

from src import config
from src.dev2 import protocol as pr
from src.dev2 import run as rn
from src.final import features as ff
from src.models import train

LO, HI = pd.Timestamp("2026-08-20", tz="UTC"), pd.Timestamp("2026-08-23", tz="UTC")
BLOCKS = ["long", "spectral", "goes", "ax", "gc", "srs"]


@pytest.fixture(scope="module")
def dry():
    proc = config.processed_dir()
    if not (proc / "dataset" / "test.parquet").exists():
        pytest.skip("processed data not available")
    from src.holdout2 import evaluate as ev

    qc = pd.read_csv(proc / "solexs_qc.csv")
    usable = set(qc.loc[qc["usable"], "date"])
    xrs = sorted((config.PROJECT_ROOT / "data" / "external" / "goes_xrs_test").glob("*.nc"))
    inp = ev.build_inputs(LO, HI, usable, config.PROJECT_ROOT / "data" / "external" / "goes_events", xrs, [])
    return ev, inp


def _close(a: pd.Series, b: pd.Series) -> bool:
    a, b = a.astype("float64").to_numpy(), b.astype("float64").to_numpy()
    return bool(np.all((np.isnan(a) & np.isnan(b)) | np.isclose(a, b, rtol=1e-5, atol=1e-6)))


def test_features_labels_and_flag_match_the_development_dataset(dry):
    _, inp = dry
    df = inp["df"]
    dev = pr.load(None)
    dev = dev[(dev.index > LO) & (dev.index < HI)]
    common = df.index.intersection(dev.index)
    assert len(common) > 0.95 * len(dev)
    for c in ff.base_features():
        assert _close(df.loc[common, c], dev.loc[common, c]), c
    assert (df.loc[common, train.FLAG].to_numpy() == dev.loc[common, train.FLAG].to_numpy()).all()
    for t in ("now", "c_30m", "c_60m", "m_60m", "m_120m"):
        y, ok = train.TARGETS[t]
        both = df.loc[common, ok].astype(bool) & dev.loc[common, ok].astype(bool)
        assert both.sum() > 0
        assert (df.loc[common][both][y].astype(bool).to_numpy() == dev.loc[common][both][y].astype(bool).to_numpy()).all(), t


def test_extra_blocks_match_the_development_builders(dry):
    ev, inp = dry
    h2, feats = ev.add_blocks(inp, BLOCKS)
    base = rn.base_frame()
    sub = base[(base.index > LO) & (base.index < HI)]
    dv, feats2 = rn.add_blocks(sub, BLOCKS)
    assert feats == feats2
    common = h2.index.intersection(dv.index)
    for c in feats[len(ff.base_features()):]:
        assert _close(h2.loc[common, c], dv.loc[common, c]), c
