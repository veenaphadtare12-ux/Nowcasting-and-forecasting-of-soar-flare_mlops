"""Validation skill figure for the model comparison (docs/model_figures/). Val period only; never test."""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from src import config  # noqa: E402

# categorical slots 1-3 of the validated reference palette, in fixed order
COLORS = {"rule": "#2a78d6", "logreg": "#eb6834", "xgb": "#1baf7a"}
LABELS = {"rule": "1-feature rule", "logreg": "logistic regression", "xgb": "XGBoost"}
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#ecebe6"
OUT_DIR = config.PROJECT_ROOT / "docs" / "model_figures"


def skill_figure() -> None:
    m = json.loads((config.PROJECT_ROOT / "reports" / "model_metrics.json").read_text())
    targets = list(m["targets"])
    models = ["rule", "logreg", "xgb"]
    x = np.arange(len(targets))
    fig, axes = plt.subplots(2, 1, figsize=(10, 6.2), sharex=True, constrained_layout=True)
    for ax, metric in zip(axes, ("tss", "hss")):
        for i, mod in enumerate(models):
            vals = [m["targets"][t][mod]["val"][metric] for t in targets]
            ax.bar(x + (i - 1) * 0.27, vals, width=0.25, color=COLORS[mod], label=LABELS[mod], zorder=3)
        for xi, t in zip(x, targets):  # mark the selected model per target
            sel = m["targets"][t]["selected"]
            i = models.index(sel)
            v = m["targets"][t][sel]["val"][metric]
            ax.text(xi + (i - 1) * 0.27, v + 0.01, "★", ha="center", va="bottom", fontsize=8, color=INK)
        ax.set_ylabel(metric.upper() + " (validation)", color=INK)
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.grid(axis="y", color=GRID, lw=0.6, zorder=0)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(colors=MUTED)
    axes[0].legend(frameon=False, ncol=3, loc="upper right", fontsize=8)
    axes[1].set_xticks(x, ["nowcast" if t == "now" else f"≥{t[0].upper()} in {t.split('_')[1]}" for t in targets])
    fig.suptitle("Validation skill by target and model (★ = selected on validation TSS)", x=0.01, ha="left",
                 color=INK, fontweight="bold", fontsize=10)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "val_skill.png"
    if out.exists():
        out.chmod(0o666)
        out.unlink()
    fig.savefig(out, dpi=130)
    plt.close(fig)
