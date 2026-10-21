"""Validation skill figure for the model comparison (docs/model_figures/). Val period only; never test."""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from src import config  # noqa: E402

# categorical slots 1-5 of the validated reference palette, in fixed order (colour follows the model, never rank)
COLORS = {"climatology": "#2a78d6", "persistence": "#eb6834", "rule": "#1baf7a", "logreg": "#eda100", "xgb": "#e87ba4"}
LABELS = {"climatology": "climatology", "persistence": "persistence", "rule": "1-feature rule",
          "logreg": "logistic regression", "xgb": "XGBoost"}
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#ecebe6"
OUT_DIR = config.PROJECT_ROOT / "docs" / "model_figures"


def skill_figure() -> None:
    m = json.loads((config.PROJECT_ROOT / "reports" / "model_metrics.json").read_text(encoding="utf-8"))
    targets = list(m["targets"])
    models = list(COLORS)
    x = np.arange(len(targets))
    w = 0.16
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.6), sharex=True, constrained_layout=True)
    for ax, subset, title in zip(axes, ("all", "quiet"), ("All validation rows", "Quiet-start rows (no flare in progress at t)")):
        for i, mod in enumerate(models):
            s = [m["targets"][t]["models"][mod]["summary"]["A"][subset] for t in targets]
            mean = np.array([v["tss_mean"] for v in s])
            lo = mean - np.array([v["tss_ci_low"] for v in s])
            hi = np.array([v["tss_ci_high"] for v in s]) - mean
            ax.bar(x + (i - 2) * w, mean, width=w * 0.9, color=COLORS[mod], label=LABELS[mod], zorder=3)
            ax.errorbar(x + (i - 2) * w, mean, yerr=[np.clip(lo, 0, None), np.clip(hi, 0, None)], fmt="none",
                        ecolor=INK, elinewidth=0.8, capsize=2, zorder=4)
        ax.set_title(title, loc="left", color=INK, fontsize=9, fontweight="bold")
        ax.set_ylabel("TSS (validation)", color=INK)
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.grid(axis="y", color=GRID, lw=0.6, zorder=0)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.tick_params(colors=MUTED)
    axes[0].legend(frameon=False, ncol=5, loc="upper right", fontsize=8)
    axes[1].set_xticks(x, ["nowcast" if t == "now" else f"≥{t[0].upper()} in {t.split('_')[1]}" for t in targets])
    fig.suptitle("Validation TSS by target and model (threshold A; bars = mean over seeds, whiskers = 95 % day-bootstrap interval)",
                 x=0.01, ha="left", color=INK, fontsize=10)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "val_skill.png"
    if out.exists():
        out.chmod(0o666)
        out.unlink()
    fig.savefig(out, dpi=130)
    plt.close(fig)
