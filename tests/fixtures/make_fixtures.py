"""Rebuild the small committed fixture tables (tests/fixtures/*.parquet) from the local DVC outputs.

    python tests/fixtures/make_fixtures.py

Development data only (tune period, 2025-07-08 around an M flare), a few hundred rows each, so CI can run data-contract and flow tests
without the DVC cache. Holdout data is never touched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src import config  # noqa: E402

OUT = Path(__file__).resolve().parent
T0, T1 = pd.Timestamp("2025-07-08 02:56", tz="UTC"), pd.Timestamp("2025-07-08 03:46", tz="UTC")


def main() -> None:
    proc = config.processed_dir()
    m = pd.read_parquet(proc / "solexs_minute.parquet")
    m[(m.index >= T0 - pd.Timedelta(hours=4)) & (m.index < T1)].to_parquet(OUT / "solexs_minute.parquet")
    g = pd.read_parquet(proc / "goes_matched.parquet")
    g[(g["begin"] >= pd.Timestamp("2025-07-06", tz="UTC")) & (g["begin"] < pd.Timestamp("2025-07-10", tz="UTC"))].reset_index(
        drop=True
    ).to_parquet(OUT / "goes_events.parquet")
    cov = pd.read_csv(proc / "hel1os" / "coverage.csv", dtype={"start": str, "end": str})
    cov.head(5).to_csv(OUT / "hel1os_coverage.csv", index=False, lineterminator="\n")
    s = pd.read_parquet(proc / "hel1os" / "sessions.parquet")
    s.iloc[1000:1300].to_parquet(OUT / "hel1os_sessions.parquet")
    d = pd.read_parquet(proc / "dataset" / "tune.parquet")
    d[(d.index >= T0) & (d.index < T1)].to_parquet(OUT / "dataset_tune.parquet")
    feats = json.loads((ROOT / "reports" / "dataset_summary.json").read_text(encoding="utf-8"))["feature_columns"]
    (OUT / "feature_columns.json").write_text(json.dumps(feats, indent=0), encoding="utf-8", newline="\n")
    for f in sorted(OUT.glob("*")):
        print(f.name, f.stat().st_size)


if __name__ == "__main__":
    main()
