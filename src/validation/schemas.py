"""pandera data contracts for the pipeline tables. A broken table raises DataContractError with a short, readable report.

Tables: SoLEXS minute series, HEL1OS session coverage + session counts, GOES events (matched list), the 10-s feature
dataset, and model predictions (score_replay output).
"""

from __future__ import annotations


import numpy as np
import pandas as pd
import pandera.pandas as pa
from pandera.errors import SchemaErrors

CLASS_RE = r"^[ABCMX]\d+(\.\d+)?$"
LABELS = ["y_now", "y_c_30m", "y_m_30m", "y_c_60m", "y_m_60m", "y_c_120m", "y_m_120m"]
OK_FLAGS = ["ok_now", "ok_30m", "ok_60m", "ok_120m"]
TARGETS = ["now", "c_30m", "c_60m", "c_120m", "m_30m", "m_60m", "m_120m"]
PERIODS = ["tune", "val", "test"]


class DataContractError(ValueError):
    """A table broke its data contract. The message lists the failed checks (column, check, examples)."""


def _utc(idx) -> bool:
    return isinstance(idx, pd.DatetimeIndex) and str(idx.tz) == "UTC"


def _index_checks(step_s: int) -> list[pa.Check]:
    return [
        pa.Check(lambda df: _utc(df.index), error="index must be a UTC DatetimeIndex"),
        pa.Check(lambda df: df.index.is_unique, error="index has duplicate timestamps"),
        pa.Check(lambda df: df.index.is_monotonic_increasing, error="index is not sorted in time"),
        pa.Check(
            lambda df: bool((df.index.as_unit("ns").asi8 % (step_s * 10**9) == 0).all()) if _utc(df.index) else False,
            error=f"timestamps are not aligned to a {step_s}-s grid",
        ),
    ]


# ---------------------------------------------------------------- SoLEXS minute series (solexs_clean)
SOLEXS_MINUTE = pa.DataFrameSchema(
    {
        "m": pa.Column(float, pa.Check.ge(0), nullable=True, description="1-min mean counts/s; NaN = too few valid seconds"),
        "n": pa.Column("int32", pa.Check.in_range(0, 60), description="valid seconds in the minute"),
    },
    checks=_index_checks(60)
    + [
        pa.Check(lambda df: bool(df.loc[df["n"] == 0, "m"].isna().all()), error="a minute with 0 valid seconds has a value"),
    ],
    strict=True,
    coerce=False,
    name="solexs_minute",
)

# ---------------------------------------------------------------- HEL1OS (hel1os_index)
HEL1OS_COVERAGE = pa.DataFrameSchema(
    {
        "session": pa.Column(str, pa.Check.str_matches(r"^HLS_\d{8}_\d{6}_\d+sec_lev1_V\d+$"), unique=True),
        "version": pa.Column(int, pa.Check.gt(0)),
        "nominal_duration_s": pa.Column(int, pa.Check.gt(0)),
        "start": pa.Column(str),
        "end": pa.Column(str),
        "rows": pa.Column(int, pa.Check.ge(0)),
        "span_s": pa.Column(float, pa.Check.ge(0), nullable=True),
        "coverage_of_nominal": pa.Column(float, pa.Check.in_range(0, 1.01), nullable=True),
        "coverage_of_span": pa.Column(float, pa.Check.in_range(0, 1.01), nullable=True),
        "gap_count": pa.Column(int, pa.Check.ge(0)),
        "max_gap_s": pa.Column(float, pa.Check.ge(0), nullable=True),
        "bands": pa.Column(int, pa.Check.ge(0)),
    },
    checks=[
        pa.Check(
            lambda df: bool((pd.to_datetime(df["end"], utc=True) >= pd.to_datetime(df["start"], utc=True)).all()),
            error="a session ends before it starts",
        )
    ],
    strict=True,
    name="hel1os_coverage",
)

HEL1OS_COUNTS = pa.DataFrameSchema(
    {r"^(cdte|czt)[12]_[0-9.]+-[0-9.]+keV(_err)?$": pa.Column("float32", pa.Check.ge(0), nullable=True, regex=True)},
    checks=_index_checks(1)
    + [
        pa.Check(
            lambda df: "czt1_20-40keV" in df.columns, error="missing column czt1_20-40keV (needed for the Neupert/hx features)"
        ),
    ],
    strict=True,
    name="hel1os_counts",
)

# ---------------------------------------------------------------- GOES events (match_goes -> goes_matched.parquet)
GOES_EVENTS = pa.DataFrameSchema(
    {
        "begin": pa.Column("datetime64[us, UTC]", coerce=True),
        "peak": pa.Column("datetime64[us, UTC]", nullable=True, coerce=True),
        "end": pa.Column("datetime64[us, UTC]", coerce=True),
        "goes_class": pa.Column(str, pa.Check.str_matches(CLASS_RE)),
        "class_letter": pa.Column(str, pa.Check.isin(list("ABCMX"))),
        "n_solexs_matches": pa.Column(int, pa.Check.ge(0)),
        "obs": pa.Column(str, nullable=True),
        "region": pa.Column(str, nullable=True),
        "integrated_flux": pa.Column(str, nullable=True),
    },
    checks=[
        pa.Check(lambda df: bool((df["end"] >= df["begin"]).all()), error="an event ends before it begins"),
        pa.Check(
            lambda df: bool(((df["peak"] >= df["begin"]) & (df["peak"] <= df["end"]) | df["peak"].isna()).all()),
            error="an event peak lies outside [begin, end]",
        ),
        pa.Check(
            lambda df: bool((df["goes_class"].str[0] == df["class_letter"]).all()), error="class_letter disagrees with goes_class"
        ),
    ],
    strict=True,
    name="goes_events",
)


# ---------------------------------------------------------------- 10-s feature dataset (build_dataset)
def dataset_schema(feature_columns: list[str], period: str | None = None) -> pa.DataFrameSchema:
    cols = {
        f: pa.Column(
            "float32",
            nullable=True,
            required=True,
            checks=pa.Check(lambda s: bool(~np.isinf(s.to_numpy()).any()), error="infinite values"),
        )
        for f in feature_columns
    }
    cols |= {y: pa.Column("int8", pa.Check.isin([0, 1])) for y in LABELS}
    cols |= {k: pa.Column(bool) for k in OK_FLAGS}
    cols["flare_in_progress_at_t"] = pa.Column("int8", pa.Check.isin([0, 1]))
    cols["period"] = pa.Column(str, pa.Check.isin([period] if period else PERIODS))
    nested = [
        ("y_m_30m", "y_c_30m"),
        ("y_m_60m", "y_c_60m"),
        ("y_m_120m", "y_c_120m"),
        ("y_c_30m", "y_c_60m"),
        ("y_c_60m", "y_c_120m"),
        ("y_m_30m", "y_m_60m"),
        ("y_m_60m", "y_m_120m"),
    ]
    checks = _index_checks(10) + [
        pa.Check(lambda df, a=a, b=b: bool((df[a] <= df[b]).all()), error=f"{a} = 1 but {b} = 0 (labels must be nested)")
        for a, b in nested
    ]
    return pa.DataFrameSchema(cols, checks=checks, strict=True, name=f"dataset_{period or 'any'}")


# ---------------------------------------------------------------- predictions (score_replay)
PREDICTIONS = pa.DataFrameSchema(
    {
        "time": pa.Column("datetime64[ns, UTC]", coerce=True),
        "target": pa.Column(str, pa.Check.isin(TARGETS)),
        "model": pa.Column(str),
        "model_version": pa.Column(str),
        "p_flare": pa.Column(float, pa.Check.in_range(0, 1)),
        "threshold": pa.Column(float, pa.Check.in_range(0, 1)),
        "alert": pa.Column(bool),
    },
    checks=[
        pa.Check(
            lambda df: bool((df["alert"] == (df["p_flare"] >= df["threshold"])).all()),
            error="alert disagrees with p_flare >= threshold",
        ),
        pa.Check(
            lambda df: not df.duplicated(["time", "target", "model", "model_version"]).any(), error="duplicate prediction rows"
        ),
    ],
    strict=True,
    name="predictions",
)


def validate(df: pd.DataFrame, schema: pa.DataFrameSchema, where: str = "") -> pd.DataFrame:
    """Validate lazily (all failures at once). Raises DataContractError with a compact summary."""
    try:
        return schema.validate(df, lazy=True)
    except SchemaErrors as e:
        fc = e.failure_cases
        lines = [f"Data contract '{schema.name}' broken{(' in ' + where) if where else ''}: {len(fc)} failure(s)"]
        for (col, check), g in fc.groupby(["column", "check"], dropna=False, sort=False):
            ex = ", ".join(map(str, g["failure_case"].head(3).tolist()))
            lines.append(f"  - column {col!s}: {check!s}  (e.g. {ex})")
            if len(lines) > 25:
                lines.append("  - ...")
                break
        raise DataContractError("\n".join(lines)) from None
