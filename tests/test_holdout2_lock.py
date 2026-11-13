"""Holdout2 lock (docs/HOLDOUT2_LOCK.md): only the setup script and the one final stage may touch holdout2 days/files."""
import re
from pathlib import Path

import pandas as pd
import yaml

from src import config

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {"src/holdout2/ingest.py", "src/holdout2/evaluate.py"}
# reading holdout2 data needs one of these: the params block, its external folder, or the holdout2 modules
ACCESS = re.compile(r"""\[\s*["']holdout2["']\s*\]|external/holdout2|external_dir|from src\.holdout2|import src\.holdout2|src\.holdout2\.""")
FINAL_STAGE = "evaluate_holdout2"


def test_only_the_setup_script_and_the_final_stage_access_holdout2():
    for f in (ROOT / "src").rglob("*.py"):
        rel = f.relative_to(ROOT).as_posix()
        if ACCESS.search(f.read_text(encoding="utf-8")):
            assert rel in ALLOWED, f"{rel} accesses holdout2"


def test_only_one_dvc_stage_reads_holdout2():
    stages = yaml.safe_load((ROOT / "dvc.yaml").read_text(encoding="utf-8"))["stages"]
    readers = {n for n, s in stages.items()
               if any("holdout2" in str(d) for d in s.get("deps", [])) or "holdout2" in str(s.get("params", ""))
               or "src.holdout2" in s["cmd"]}
    assert readers <= {FINAL_STAGE}
    if FINAL_STAGE in stages:
        assert "src.holdout2.evaluate" in stages[FINAL_STAGE]["cmd"]


def test_holdout2_comes_after_every_development_period():
    h = config.load_params()["holdout2"]
    assert pd.Timestamp(h["start"], tz="UTC") >= config.period_bounds("test")[1]
    assert pd.Timestamp(h["end"]) >= pd.Timestamp(h["start"])


def test_shared_processed_files_hold_no_holdout2_minutes():
    start = pd.Timestamp(config.load_params()["holdout2"]["start"], tz="UTC")
    proc = config.processed_dir()
    m = pd.read_parquet(proc / "solexs_minute.parquet", columns=["m"])
    assert m.index.max() <= start  # the minute labelled 00:00 of the first holdout2 day ends the test period
    ev = pd.read_parquet(proc / "events.parquet", columns=["onset"])
    assert ev["onset"].max() < start


def test_the_final_stage_refuses_to_run_before_final_choice_2_is_committed():
    ev = ROOT / "src" / "holdout2" / "evaluate.py"
    if ev.exists():
        txt = ev.read_text(encoding="utf-8")
        assert "require_final_choice_committed()" in txt and "FINAL_CHOICE_2.md" in txt


def test_lock_files_exist():
    assert (ROOT / "docs" / "HOLDOUT2_LOCK.md").exists()
    lst = (ROOT / "reports" / "holdout2" / "lock_sha256.txt").read_text(encoding="utf-8").splitlines()
    assert len(lst) > 50 and all(re.fullmatch(r"[0-9a-f]{64}  .+", x) for x in lst)
