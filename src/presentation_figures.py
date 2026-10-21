"""Slide-ready figures for the project review (docs/presentation_figures/). Tune + validation data only.

    python -m src.presentation_figures

1920 x 1080 px (16:9), large fonts (axis labels >= 20 pt), light background, no titles (added on the slide).
Colours: SoLEXS / soft X-ray = orange #E07A1F; HEL1OS / hard X-ray = blue #2B5DA8; everything else grey or near-black.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from src import config, eda  # noqa: E402

OUT = config.PROJECT_ROOT / "docs" / "presentation_figures"
SOLEXS, HEL1OS = "#E07A1F", "#2B5DA8"
INK, GREY, LIGHT = "#1F1F1F", "#7A7A7A", "#E6E6E6"

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
    "font.size": 20, "axes.labelsize": 22, "xtick.labelsize": 18, "ytick.labelsize": 18, "legend.fontsize": 18,
    "axes.edgecolor": GREY, "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": LIGHT, "grid.linewidth": 1.0,
    "legend.frameon": False,
})


def _fig():
    return plt.figure(figsize=(19.2, 10.8), dpi=100)


def _save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    if p.exists():
        p.unlink()
    fig.savefig(p, dpi=100)  # exactly 1920 x 1080: no bbox_inches="tight"
    plt.close(fig)


def coverage_heatmap(qc: pd.DataFrame) -> None:
    days = pd.date_range(eda.LO, eda.HI - pd.Timedelta(days=1), freq="D")
    vf = qc["valid_fraction"].reindex(days).fillna(0.0)
    months = pd.period_range(days[0].strftime("%Y-%m"), days[-1].strftime("%Y-%m"), freq="M")
    grid = np.full((len(months), 31), np.nan)
    for d, v in vf.items():
        grid[months.get_loc(pd.Period(d.strftime("%Y-%m"), "M")), d.day - 1] = v
    cmap = LinearSegmentedColormap.from_list("solexs", ["#FFFFFF", SOLEXS])
    cmap.set_bad("#FFFFFF")
    fig = _fig()
    ax = fig.add_axes([0.11, 0.12, 0.74, 0.82])
    im = ax.imshow(grid, aspect="auto", cmap=cmap, vmin=0, vmax=1, interpolation="nearest")
    # days that do not exist in a month (e.g. 30-31 Feb) in light grey, so they are not read as "missing data"
    nonexist = np.array([[0.0 if d <= p.days_in_month else 1.0 for d in range(1, 32)] for p in months])
    ax.imshow(np.where(nonexist == 1, 1.0, np.nan), aspect="auto", cmap=LinearSegmentedColormap.from_list("g", [LIGHT, LIGHT]),
              vmin=0, vmax=1, interpolation="nearest")
    ax.set_yticks(range(len(months)), [p.strftime("%b %Y") for p in months])
    ax.set_xticks(range(0, 31, 2), range(1, 32, 2))
    ax.set_xlabel("Day of month")
    ax.set_ylabel("Month")
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.axvline(16, color=INK, lw=2, ls=(0, (4, 3)))  # day 17 (index 16): the regular low-coverage day
    ax.text(16, -0.75, "17th", ha="center", va="bottom", color=INK, fontsize=18)
    cax = fig.add_axes([0.875, 0.12, 0.02, 0.82])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label("Fraction of the day with valid SoLEXS data")
    cb.outline.set_visible(False)
    _save(fig, "01_coverage_heatmap.png")


def longterm_lightcurve(m: pd.Series, g: pd.DataFrame) -> None:
    day = m.groupby(m.index.floor("D"))
    med, mx = day.median(), day.max()
    fig = _fig()
    ax = fig.add_axes([0.09, 0.10, 0.88, 0.76])
    ax.plot(mx.index, mx.values, color=SOLEXS, lw=1.2, alpha=0.45, label="SoLEXS daily maximum")
    ax.plot(med.index, med.values, color=SOLEXS, lw=2.6, label="SoLEXS daily median")
    ax.set_yscale("log")
    ax.set_ylabel("SoLEXS count rate (counts/s)")
    top = float(np.nanmax(mx.values))
    for cls, mk, col, size, y in (("M", "v", GREY, 70, top * 2.2), ("X", "*", INK, 260, top * 4.5)):
        sel = g[g["class_letter"] == cls]
        ax.scatter(sel["peak"].fillna(sel["begin"]), np.full(len(sel), y), marker=mk, s=size, color=col,
                   label=f"GOES {cls}-class flare ({len(sel)})", zorder=4, linewidths=0)
    ax.set_ylim(top=top * 9)
    v0 = config.period_bounds("val")[0]
    ax.axvline(v0, color=INK, lw=1.8, ls=(0, (5, 4)))
    ax.text(v0, top * 7, "  validation", color=INK, fontsize=18, va="center")
    ax.text(v0, top * 7, "tuning  ", color=INK, fontsize=18, va="center", ha="right")
    fig.legend(*ax.get_legend_handles_labels(), loc="upper center", bbox_to_anchor=(0.53, 0.995), ncol=4,
               handlelength=2.2, columnspacing=2.0)
    _save(fig, "02_longterm_lightcurve.png")


def main() -> None:
    qc, m, g = eda.load_qc(), eda.load_minutes(), eda.load_goes()
    eda.check_no_test(qc, m, g)  # tune + validation only
    coverage_heatmap(qc)
    longterm_lightcurve(m, g)
    print("written to", OUT)


if __name__ == "__main__":
    main()
