"""daily_ingest logic: discover new raw days, validate, and re-run only the (unfrozen) data stages that changed.

New raw days are found by folder/zip NAME only. Days after the development end are reported as "locked" and never read.
Only data-processing stages may be re-run; every model/evaluation stage is frozen and also on an explicit deny list.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

import pandas as pd
import yaml

from src import config
from src.ops.locks import dev_window

log = logging.getLogger(__name__)
DATA_STAGES = (
    "fetch_goes",
    "solexs_clean",
    "hel1os_index",
    "detect_events",
    "legacy_events",
    "match_goes",
    "evaluate_detector",
    "build_dataset",
    "solexs_spectral",
    "goes_xrs_fetch",
    "goes_xrs_minute",
)
DAY_RE = re.compile(r"AL1_SLX_L1_(\d{8})_v")
SESSION_RE = re.compile(r"HLS_(\d{8})_\d{6}_")


def _dvc() -> list[str]:
    exe = config.PROJECT_ROOT / ".venv" / "Scripts" / "dvc.exe"
    return [str(exe)] if exe.exists() else ["dvc"]


def discover_days(root: Path | None = None, processed_qc: Path | None = None) -> dict:
    """SoLEXS day folders on disk vs days already processed. Returns lists of YYYY-MM-DD strings."""
    root = Path(root) if root else config.solexs_root()
    qc = Path(processed_qc) if processed_qc else config.processed_dir() / "solexs_qc.csv"
    on_disk = sorted({pd.Timestamp(m.group(1)).strftime("%Y-%m-%d") for p in root.iterdir() if (m := DAY_RE.match(p.name))})
    done = set(pd.read_csv(qc, usecols=["date"])["date"].astype(str).str[:10]) if qc.exists() else set()
    lo, hi = dev_window()
    in_dev = [d for d in on_disk if lo <= pd.Timestamp(d, tz="UTC") < hi]
    return {
        "new_in_development": [d for d in in_dev if d not in done],
        "locked_after_development_end": [d for d in on_disk if pd.Timestamp(d, tz="UTC") >= hi],
        "development_end": f"{hi:%Y-%m-%d}",
    }


def frozen_stages(dvc_yaml: Path | None = None) -> set[str]:
    st = yaml.safe_load((Path(dvc_yaml) if dvc_yaml else config.PROJECT_ROOT / "dvc.yaml").read_text(encoding="utf-8"))["stages"]
    return {n for n, s in st.items() if s.get("frozen")}


def changed_stages() -> list[str]:
    out = subprocess.run(
        _dvc() + ["status", "--json"], cwd=config.PROJECT_ROOT, capture_output=True, text=True, check=True
    ).stdout
    start = out.find("{")
    return sorted(json.loads(out[start:]) if start >= 0 else {})


def stages_to_run(changed: list[str], frozen: set[str]) -> list[str]:
    """Only unfrozen data-processing stages; anything else is refused loudly."""
    refused = [s for s in changed if s not in DATA_STAGES or s in frozen]
    if refused:
        log.warning("not re-running (frozen or not a data stage): %s", refused)
    return [s for s in changed if s in DATA_STAGES and s not in frozen]


def repro(stage: str) -> None:
    subprocess.run(_dvc() + ["repro", stage], cwd=config.PROJECT_ROOT, check=True)
