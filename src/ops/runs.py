"""Last run of each operational flow, for /pipeline/status (data/predictions/flow_runs.json, shared with the API)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.settings import get_settings


def record(flow: str, status: str, info: dict | None = None, store: Path | None = None) -> dict:
    d = Path(store) if store else get_settings().predictions_dir
    d.mkdir(parents=True, exist_ok=True)
    f = d / "flow_runs.json"
    runs = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    runs[flow] = {"status": status, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "info": info or {}}
    f.write_text(json.dumps(runs, indent=1, default=str), encoding="utf-8", newline="\n")
    return runs[flow]


def load(store: Path | None = None) -> dict:
    f = (Path(store) if store else get_settings().predictions_dir) / "flow_runs.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
