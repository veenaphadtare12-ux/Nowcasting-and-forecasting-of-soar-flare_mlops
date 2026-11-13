"""Holdout2 setup (run once, before any holdout2 feature or label exists). No model is run, no feature is built.

    python -m src.holdout2.ingest fetch    # GOES events, GOES-19 XRS 1-min, NOAA SRS for the holdout2 days
    python -m src.holdout2.ingest report   # usable SoLEXS days + GOES flares by class -> reports/holdout2/ingest.json
    python -m src.holdout2.ingest lock     # SHA-256 of every holdout2 file -> docs/HOLDOUT2_LOCK.md (+ full list)

This module and src/holdout2/evaluate.py (the one final DVC stage) are the only code allowed to touch holdout2 days or
files (tests/test_holdout2_lock.py). The report reads SoLEXS light curves only to count usable seconds (the same QC
as the pipeline) and the GOES event lists only to count flares by class, as the task asks.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src import config, goes, noaa, solexs

REPORT_DIR = config.PROJECT_ROOT / "reports" / "holdout2"
LOCK_DOC = config.PROJECT_ROOT / "docs" / "HOLDOUT2_LOCK.md"
LOCK_LIST = REPORT_DIR / "lock_sha256.txt"
BUNDLES = ["solexs_2026Nov13T044625368.zip", "hel1os_2026Nov13T032230627.zip", "hel1os_2026Nov13T042414593.zip"]


def H() -> dict:
    return config.load_params()["holdout2"]


def bounds() -> tuple[pd.Timestamp, pd.Timestamp]:
    """[start, end) in UTC; end = the day after the last holdout2 day."""
    h = H()
    return pd.Timestamp(h["start"], tz="UTC"), pd.Timestamp(h["end"], tz="UTC") + pd.Timedelta(days=1)


def ext_dir() -> Path:
    p = Path(H()["external_dir"])
    return p if p.is_absolute() else config.PROJECT_ROOT / p


def days() -> pd.DatetimeIndex:
    lo, hi = bounds()
    return pd.date_range(lo, hi - pd.Timedelta(days=1), freq="D")


def solexs_days() -> list[solexs.SolexsDay]:
    lo, hi = bounds()
    return [d for d in solexs.list_days(detector=config.load_params()["solexs"]["detector"]) if lo <= d.date < hi]


def hel1os_session_dirs() -> list[Path]:
    lo, hi = bounds()
    out = []
    for f in sorted(config.hel1os_root().glob("*/*/*/HLS_*")):
        t = pd.Timestamp(f.name.split("_")[1], tz="UTC")
        if lo <= t < hi:
            out.append(f)
    return out


# ---------------------------------------------------------------------------------------------------
def fetch() -> dict:
    e = ext_dir()
    jobs = []
    for d in days():
        jobs.append((noaa.EVENTS_URL.format(d=d), e / "goes_events" / f"{d:%Y%m%d}events.txt"))
        jobs.append((noaa.SRS_URL.format(d=d), e / "srs" / f"{d:%Y%m%d}SRS.txt"))
        jobs.append((noaa.xrs_url("goes19", d), e / "goes_xrs" / noaa.xrs_name("goes19", d)))
    res = noaa.fetch_many(jobs)
    missing = [Path(j[1]).name for j, r in zip(jobs, res) if r is None]
    out = {"requested": len(jobs), "missing_on_server": missing}
    print(out)
    return out


def report() -> dict:
    sx = config.load_params()["solexs"]
    lo, hi = bounds()
    rows = []
    for d in solexs_days():
        if not d.complete:
            rows.append({"date": f"{d.date:%Y-%m-%d}", "usable": False, "valid_fraction": 0.0, "reason": "incomplete"})
            continue
        _, qc = solexs.clean_day(d)
        rows.append({"date": qc["date"], "usable": bool(qc["valid_fraction"] >= sx["min_valid_fraction"]),
                     "valid_fraction": round(qc["valid_fraction"], 4)})
    e = ext_dir()
    no_report = [f"{d:%Y-%m-%d}" for d in goes.missing_days(lo, hi, e / "goes_events")]
    usable = [r["date"] for r in rows if r["usable"] and r["date"] not in no_report]
    g = goes.load_flare_list(events_path=e / "goes_events")
    g = g[(g["begin"] >= lo) & (g["begin"] < hi)]
    g["day"] = g["begin"].dt.strftime("%Y-%m-%d")
    by_class = {k: int(v) for k, v in g["class_letter"].value_counts().sort_index().items()}
    on_usable = g[g["day"].isin(usable)]
    by_class_usable = {k: int(v) for k, v in on_usable["class_letter"].value_counts().sort_index().items()}
    n_m = int(on_usable["class_letter"].isin(["M", "X"]).sum())
    xrs = sorted((e / "goes_xrs").glob("*.nc"))
    out = {
        "holdout2_days": [str(lo.date()), str((hi - pd.Timedelta(days=1)).date())],
        "calendar_days": len(days()),
        "solexs_day_folders": len(rows),
        "solexs_days": rows,
        "goes_days_without_report": no_report,
        "usable_days": len(usable),
        "usable_day_list": usable,
        "goes_flares_all_days": by_class,
        "goes_flares_on_usable_days": by_class_usable,
        "m_or_larger_on_usable_days": n_m,
        "m_flares_on_usable_days_by_day": on_usable[on_usable["class_letter"].isin(["M", "X"])].groupby("day").size().to_dict(),
        "min_m_flares": H()["min_m_flares"],
        "m_results_underpowered": bool(n_m < H()["min_m_flares"]),
        "goes_xrs_files": len(xrs),
        "hel1os_sessions": [p.name for p in hel1os_session_dirs()],
        "note": "No model was run and no feature or label was built. Counts by GOES begin time.",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "ingest.json").write_text(json.dumps(out, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in out.items() if k not in ("solexs_days",)}, indent=1))
    return out


# ---------------------------------------------------------------------------------------------------
def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def lock_files() -> dict[str, list[Path]]:
    arch = config.path("archive_root") / "downloads_bundles"
    return {
        "SoLEXS day folders (raw L1)": sorted(p for d in solexs_days() for p in d.folder.rglob("*") if p.is_file()),
        "HEL1OS sessions (extracted light curves + aux)": sorted(p for s in hel1os_session_dirs() for p in s.rglob("*") if p.is_file()),
        "Original download bundles": [arch / b for b in BUNDLES],
        "NOAA files (GOES events, GOES-19 XRS, SRS)": sorted(p for p in ext_dir().rglob("*") if p.is_file()),
    }


def lock() -> str:
    groups = lock_files()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines, summary = [], []
    for name, files in groups.items():
        hs = [(p, _sha(p)) for p in files]
        lines += [f"{h}  {p.as_posix()}" for p, h in hs]
        combined = hashlib.sha256("".join(h for _, h in hs).encode()).hexdigest()
        summary.append((name, len(hs), sum(p.stat().st_size for p, _ in hs), combined))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    LOCK_LIST.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    ing = json.loads((REPORT_DIR / "ingest.json").read_text(encoding="utf-8"))
    md = [
        "# Holdout2 lock",
        "",
        f"*Locked at **{stamp}**, before any holdout2 feature or label existed and before any model saw these days.*",
        "",
        f"- Holdout2 = {ing['holdout2_days'][0]} .. {ing['holdout2_days'][1]} (UTC days). Usable SoLEXS days: "
        f"**{ing['usable_days']}** ({', '.join(ing['usable_day_list'])}).",
        f"- GOES flares on usable days: {ing['goes_flares_on_usable_days']}; ≥M: **{ing['m_or_larger_on_usable_days']}** "
        f"(< {ing['min_m_flares']}: every M result on holdout2 is **UNDERPOWERED**)." if ing["m_results_underpowered"] else
        f"- GOES flares on usable days: {ing['goes_flares_on_usable_days']}; ≥M: {ing['m_or_larger_on_usable_days']}.",
        "- Rules: holdout2 features and labels are built and opened only by the final DVC stage `evaluate_holdout2`, "
        "and only after `docs/FINAL_CHOICE_2.md` is committed. `tests/test_holdout2_lock.py` checks the code; the "
        "checksums below let anyone verify the files did not change.",
        "",
        "| Group | Files | Bytes | SHA-256 of the concatenated file hashes |",
        "|---|---|---|---|",
    ]
    md += [f"| {n} | {k} | {b:,} | `{c}` |" for n, k, b, c in summary]
    md += ["", f"Full per-file list: `{LOCK_LIST.relative_to(config.PROJECT_ROOT).as_posix()}` "
           f"(`sha256sum -c` compatible). Verify with `python -m src.holdout2.ingest verify`.", ""]
    LOCK_DOC.write_text("\n".join(md), encoding="utf-8", newline="\n")
    print("\n".join(md))
    return stamp


def verify() -> bool:
    bad = []
    for line in LOCK_LIST.read_text(encoding="utf-8").splitlines():
        h, p = line.split("  ", 1)
        if not Path(p).exists() or _sha(Path(p)) != h:
            bad.append(p)
    print("holdout2 files unchanged" if not bad else f"CHANGED or missing: {bad}")
    return not bad


if __name__ == "__main__":
    {"fetch": fetch, "report": report, "lock": lock, "verify": verify}[sys.argv[1]]()
