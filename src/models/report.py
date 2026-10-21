"""Validation results tables (reports/validation_table.md). Validation period only; the test period is never read."""
from __future__ import annotations

from src import config

NAMES = {"climatology": "Climatology", "persistence": "Persistence", "rule": "Rule", "logreg": "LogReg", "xgb": "XGBoost"}
TARGET_NAMES = {"now": "nowcast", "c_30m": "≥C in 30 min", "c_60m": "≥C in 60 min", "c_120m": "≥C in 120 min",
                "m_30m": "≥M in 30 min", "m_60m": "≥M in 60 min", "m_120m": "≥M in 120 min"}


def _cell(a: dict) -> str:
    sd = f" ± {a['tss_std']:.3f}" if a["n_seeds"] > 1 else ""
    return f"{a['tss_mean']:.3f}{sd} [{a['tss_ci_low']:.2f}, {a['tss_ci_high']:.2f}]"


def tss_table(summary: dict, subset: str) -> list[str]:
    models = list(NAMES)
    lines = ["| Target | " + " | ".join(NAMES[m] for m in models) + " | Selected |",
             "|---|" + "---|" * (len(models) + 1)]
    for t, d in summary["targets"].items():
        cells = []
        for m in models:
            c = _cell(d["models"][m]["summary"]["A"][subset])
            cells.append(f"**{c}**" if m == d["selected"] else c)
        lines.append(f"| {TARGET_NAMES.get(t, t)} | " + " | ".join(cells) + f" | {NAMES[d['selected']]} |")
    return lines


def operating_point_table(summary: dict) -> list[str]:
    lines = ["| Target | Model | A: POD | A: FAR | A: TSS | A: HSS | B: POD | B: FAR | B: TSS | B: HSS |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for t, d in summary["targets"].items():
        for m in ("persistence", "rule", "logreg", "xgb"):
            s = d["models"][m]["summary"]
            a, b = s["A"]["all"], s["B"]["all"]
            row = [f"{x[k]:.2f}" for x in (a, b) for k in ("pod_mean", "far_mean", "tss_mean", "hss_mean")]
            lines.append(f"| {TARGET_NAMES.get(t, t)} | {NAMES[m]} | " + " | ".join(row) + " |")
    return lines


def write_tables(summary: dict) -> None:
    sp = summary["split"]
    out = [
        "# Validation results",
        "",
        f"Validation period {sp['val_start'][:10]} to {sp['val_end'][:10]} ({summary['val_days']} days). Models fitted on "
        f"the tune period before {sp['fit_end'][:10]}; thresholds chosen on {sp['cal_start'][:10]} to {sp['cal_end'][:10]}. "
        "The test period was not opened.",
        "",
        "Cells: TSS mean ± std over 3 seeds (LogReg, XGBoost; other models are deterministic) "
        "[95 % interval from 1000 bootstrap resamples of validation days]. Operating point A (threshold = max TSS on "
        "calibration). **Bold** = model selected for that target (highest mean TSS among Rule, LogReg, XGBoost).",
        "",
        "## All rows",
        "",
        *tss_table(summary, "all"),
        "",
        "## Quiet-start rows (no flare in progress at t)",
        "",
        *tss_table(summary, "quiet"),
        "",
        "## Operating points (all rows, mean over seeds)",
        "",
        "A = threshold maximising TSS on calibration; B = threshold maximising HSS on calibration (fewer false alarms).",
        "POD = share of flares warned; FAR = share of alerts that were false.",
        "",
        *operating_point_table(summary),
        "",
        "Climatology always forecasts the training positive rate, so it never crosses a threshold: TSS = 0 by construction.",
        "",
    ]
    path = config.PROJECT_ROOT / "reports" / "validation_table.md"
    if path.exists():
        path.chmod(0o666)
        path.unlink()
    path.write_text("\n".join(out), encoding="utf-8", newline="\n")
