"""Data contracts for the production pipeline (daily_ingest): raw 1-s SoLEXS counts and the feature table without labels.

Kept apart from schemas.py, which the DVC data stages depend on (editing it would mark those stages as changed).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandera.pandas as pa

from src.validation.schemas import _index_checks

RAW_COUNTS = pa.DataFrameSchema(
    {
        "counts": pa.Column(
            float, [pa.Check.ge(0), pa.Check(lambda s: bool(np.isfinite(s.to_numpy()).all()), error="non-finite counts")]
        )
    },
    checks=_index_checks(1) + [pa.Check(lambda df: len(df) >= 600, error="fewer than 10 minutes of valid 1-s data")],
    strict=True,
    name="raw_solexs_counts",
)


def features_schema(feature_columns: list[str]) -> pa.DataFrameSchema:
    cols = {
        f: pa.Column(
            "float32",
            nullable=True,
            required=True,
            checks=pa.Check(lambda s: bool(~np.isinf(s.to_numpy()).any()), error="infinite values"),
        )
        for f in feature_columns
    }
    checks = _index_checks(10) + [
        pa.Check(lambda df: bool(df["rate"].notna().all()), error="feature rows without a SoLEXS rate"),
        pa.Check(lambda df: bool((df["hel1os_available"].isin([0, 1])).all()), error="hel1os_available must be 0/1"),
    ]
    return pa.DataFrameSchema(cols, checks=checks, strict=True, name="production_features")


def counts_frame(counts: pd.Series) -> pd.DataFrame:
    return counts.astype("float64").rename("counts").to_frame()
