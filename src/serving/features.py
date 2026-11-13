"""Features for one day, computed with the PIPELINE's feature code (src/features.py) exactly as src/dataset.py does.

The composition below mirrors `dataset.build_all` for a single day: previous-day warm-up of (max window + 70) min,
right-closed 10-s bins, SoLEXS features, optional HEL1OS features, row filter (rate present, valid_frac_5m >= the
params threshold), float32. tests/test_serving_features.py proves the result equals the pipeline's dataset rows.
"""

from __future__ import annotations

import pandas as pd

from src import config, features


def warmup() -> pd.Timedelta:
    fp = config.load_params()["features"]
    return pd.Timedelta(minutes=max(fp["windows_min"]) + 70)


def day_features(counts: pd.Series, day: pd.Timestamp, hel_channels: pd.DataFrame | None = None) -> pd.DataFrame:
    """counts: 1-s SoLEXS counts (valid seconds only, UTC index) covering (day - warm-up, day + 1 d]; hel_channels: the
    output of features.hel1os_channels for the same span (+80 min earlier), or None. Returns the base feature rows."""
    fp = config.load_params()["features"]
    cad, windows = fp["cadence_s"], fp["windows_min"]
    if hel_channels is None or hel_channels.empty:
        # The dataset was built with HEL1OS loaded for the whole period, so a day without sessions gets
        # hel1os_available = 0 and NaN hx_* columns (not missing columns). A placeholder row far outside the window
        # reproduces exactly that branch of features.hel1os_features.
        hel_channels = pd.DataFrame(
            {c: [float("nan")] for c in features.HX_CHANNELS}, index=pd.DatetimeIndex(["1970-01-01"], tz="UTC")
        )
    binned = features.bin_counts(counts.astype("float64"), cad)
    feat = features.solexs_features(binned, windows, cad)
    hf = features.hel1os_features(hel_channels, feat.index, cad, sxr_rate=binned["rate"])
    if hf.shape[1]:
        feat = feat.join(hf)
    feat = feat[(feat.index > day) & (feat.index <= day + pd.Timedelta(days=1))]
    feat = feat[feat["rate"].notna() & (feat["valid_frac_5m"] >= fp["min_valid_frac_5m"])]
    return feat.astype("float32")


def window_features(counts: pd.Series, hel_channels: pd.DataFrame | None, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Features for rows in (start, end] of one day: computed on the whole trailing history given (causal), then cut."""
    day = start.floor("D")
    f = day_features(counts[counts.index <= end], day, None if hel_channels is None else hel_channels[hel_channels.index <= end])
    return f[(f.index > start) & (f.index <= end)]
