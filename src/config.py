"""Single source of truth for paths and parameters (reads params.yaml)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARAMS_FILE = PROJECT_ROOT / "params.yaml"


@lru_cache(maxsize=1)
def load_params(path: str | None = None) -> dict:
    with open(path or PARAMS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _resolve(p: str) -> Path:
    """Absolute paths are used as-is; relative paths are relative to the project root."""
    path = Path(p)
    return path if path.is_absolute() else PROJECT_ROOT / path


def path(key: str) -> Path:
    return _resolve(load_params()["paths"][key])


def solexs_root() -> Path:
    return path("data_root_solexs")


def hel1os_root() -> Path:
    return path("data_root_hel1os")


def processed_dir() -> Path:
    return path("processed_dir")
