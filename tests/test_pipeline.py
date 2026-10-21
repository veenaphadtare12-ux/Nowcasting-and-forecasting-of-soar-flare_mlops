from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import goes, hel1os, solexs
from src.detection import matching

SAMPLE_EVENTS = """\
#Event    Begin    Max       End  Obs  Q  Type  Loc/Frq   Particulars       Reg#
5580       0446   0450      0454  G18  5   XRA  1-8A      C2.3    1.1E-03   4060
5590 +     0624   0628      0632  G19  5   XRA  1-8A      C3.2    7.6E-04   4055
5590 +     0627   0627      0632  LEA  3   FLA  N07W26    SF                4055
5640 +     2355   0002      0020  G19  5   XRA  1-8A      M1.5    2.3E-03
5650       0900   ////      0910  G19  5   XRA  1-8A      B9.0    1.0E-04
"""


def test_time_conversion_is_utc_epoch():
    t = pd.to_datetime(np.array([1744243200.0]), unit="s", utc=True)
    assert t[0] == pd.Timestamp("2025-04-10 00:00:00", tz="UTC")


def test_goes_parser_takes_only_xra_and_handles_midnight():
    rows = goes.parse_events_text(SAMPLE_EVENTS, pd.Timestamp("2025-04-10"))
    assert [r["goes_class"] for r in rows] == ["C2.3", "C3.2", "M1.5", "B9.0"]  # FLA/RSP lines ignored
    m = rows[2]
    assert m["end"] > m["begin"] and m["peak"] > m["begin"]  # wrapped past midnight
    assert pd.isna(rows[3]["peak"])


def test_gti_mask_is_unit_safe():
    idx = pd.to_datetime(np.arange(1744243200, 1744243210, dtype="float64"), unit="s", utc=True)  # datetime64[s]
    gti = pd.DataFrame(
        {"start": pd.to_datetime([1744243202.0], unit="s", utc=True), "stop": pd.to_datetime([1744243205.0], unit="s", utc=True)}
    )
    mask = solexs.gti_mask(idx, gti)
    assert mask.sum() == 4 and mask[2] and mask[5] and not mask[1] and not mask[6]


def test_goes_class_only_from_goes_match():
    t0 = pd.Timestamp("2025-04-10 05:00", tz="UTC")
    fl = pd.DataFrame(
        {
            "onset": [t0, t0 + pd.Timedelta(hours=5)],
            "peak": [t0 + pd.Timedelta(minutes=5), t0 + pd.Timedelta(hours=5, minutes=5)],
            "end": [t0 + pd.Timedelta(minutes=20), t0 + pd.Timedelta(hours=5, minutes=20)],
            "peak_counts_s": [500.0, 900.0],
        }
    )
    g = pd.DataFrame(
        {
            "begin": [t0 + pd.Timedelta(minutes=2)], "peak": [t0 + pd.Timedelta(minutes=6)],
            "end": [t0 + pd.Timedelta(minutes=12)], "goes_class": ["M2.0"], "class_letter": ["M"],
        }
    )
    m, gm, pairs = matching.match_goes(fl, g, tolerance_s=60)
    assert m.loc[0, "goes_class"] == "M2.0"
    assert pd.isna(m.loc[1, "goes_class"])  # bigger counts, but no GOES event -> no class assigned
    assert gm.loc[0, "n_solexs_matches"] == 1
    assert bool(m.loc[0, "is_goes_matched"]) and not bool(m.loc[1, "is_goes_matched"])
    assert list(pairs.itertuples(index=False, name=None)) == [(0, 0)]


def test_hel1os_keeps_newest_version_per_session():
    mk = lambda n, hms, dur, v: hel1os.Session(Path(n), pd.Timestamp(f"2024-08-12 {hms}", tz="UTC"), dur, v)
    a = mk("v211", "00:00:06", 43181, 211)
    b = mk("v311", "00:00:06", 43181, 311)
    c = mk("other", "12:00:02", 43195, 211)
    kept = hel1os.newest_per_session([a, b, c])
    assert [s.name for s in kept] == ["v311", "other"]


def test_hel1os_is_optional_downstream():
    base = pd.DataFrame({"counts": [1.0, 2.0]}, index=pd.date_range("2025-01-01", periods=2, freq="s", tz="UTC"))
    assert hel1os.attach_optional(base, None) is base


def test_tracked_text_files_use_lf_line_endings():
    """DVC hashes raw bytes: CRLF rewrites (git autocrlf, Python text mode on Windows) look like changes."""
    import subprocess

    root = Path(__file__).resolve().parents[1]
    files = subprocess.check_output(["git", "ls-files"], cwd=root, text=True).split()
    binary = (".png", ".parquet", ".db", ".joblib", ".gz", ".fits")
    # dvc.lock is written by DVC itself (CRLF on Windows); it is never a stage dependency, and git stores it as LF.
    skip = {"dvc.lock"}
    crlf = [f for f in files if not f.endswith(binary) and f not in skip and (root / f).exists()
            and b"\r\n" in (root / f).read_bytes()]
    assert not crlf, f"CRLF line endings in: {crlf}"


def test_hel1os_bands_with_different_subsecond_offsets_are_not_lost(tmp_path):
    """Regression: bands of one file start at different sub-second offsets; none may be dropped when combined."""
    from astropy.io import fits

    t0 = 60775.0  # MJD
    n = 100
    hdus = [fits.PrimaryHDU()]
    for k, (lo, hi, off) in enumerate([(5, 20, 0.793), (20, 30, 0.858)]):
        mjd = t0 + (np.arange(n) + off) / 86400.0
        cols = [fits.Column("MJD", "D", array=mjd), fits.Column("ISOT", "30A", array=np.array(["x"] * n)),
                fits.Column("CTR", "D", array=np.full(n, k + 1.0)), fits.Column("STAT_ERR", "D", array=np.ones(n))]
        hdus.append(fits.BinTableHDU.from_columns(cols, name=f"CDTE1_LC_BAND_{lo:.2f}KEV_TO_{hi:.2f}KEV"))
    f = tmp_path / "lightcurve_cdte1.fits"
    fits.HDUList(hdus).writeto(f)
    df = hel1os.read_lightcurve_file(f)
    assert df["cdte1_5-20keV"].notna().sum() == n
    assert df["cdte1_20-30keV"].notna().sum() == n
    assert len(df) <= n + 1  # both bands share (almost) the same whole-second grid
