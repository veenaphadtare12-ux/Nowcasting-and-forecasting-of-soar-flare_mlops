"""Run a data contract on a stage output. Used inside the DVC stages: a broken table stops `dvc repro` with a clear message.

python -m src.validation.check solexs_minute | hel1os | goes_events | dataset
"""

from __future__ import annotations

import json
import sys

import pandas as pd

from src import config
from src.validation import schemas as S


def solexs_minute() -> None:
    S.validate(pd.read_parquet(config.processed_dir() / "solexs_minute.parquet"), S.SOLEXS_MINUTE, "solexs_minute.parquet")


def hel1os() -> None:
    d = config.processed_dir() / "hel1os"
    S.validate(pd.read_csv(d / "coverage.csv", dtype={"start": str, "end": str}), S.HEL1OS_COVERAGE, "hel1os/coverage.csv")
    S.validate(pd.read_parquet(d / "sessions.parquet"), S.HEL1OS_COUNTS, "hel1os/sessions.parquet")


def goes_events() -> None:
    S.validate(pd.read_parquet(config.processed_dir() / "goes_matched.parquet"), S.GOES_EVENTS, "goes_matched.parquet")


def dataset() -> None:
    feats = json.loads((config.PROJECT_ROOT / "reports" / "dataset_summary.json").read_text(encoding="utf-8"))["feature_columns"]
    for f in sorted((config.processed_dir() / "dataset").glob("*.parquet")):
        S.validate(pd.read_parquet(f), S.dataset_schema(feats, f.stem), f"dataset/{f.name}")


CHECKS = {"solexs_minute": solexs_minute, "hel1os": hel1os, "goes_events": goes_events, "dataset": dataset}


def main(argv: list[str]) -> int:
    try:
        for name in argv:
            CHECKS[name]()
            print(f"data contract OK: {name}")
    except S.DataContractError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
