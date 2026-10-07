"""Before/after figures for the detector (docs/figures/). Examples are drawn from the TUNE period only.

Colours: categorical slots 1-2 of the validated reference palette (blue = new detector, orange = legacy),
GOES truth as a neutral grey band; text in neutral inks.
"""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import config  # noqa: E402
from src.detection.matching import goes_flux  # noqa: E402

NEW, OLD = "#2a78d6", "#eb6834"
GOES_FILL, INK, MUTED, GRID = "#d9d8d2", "#1f1f1e", "#6b6a63", "#ecebe6"
FIG_DIR = config.PROJECT_ROOT / "docs" / "figures"

plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.6, "legend.frameon": False, "axes.titlesize": 9, "axes.titleweight": "bold",
})


def _load():
    proc = config.processed_dir()
    m = pd.read_parquet(proc / "solexs_minute.parquet")["m"]
    new = pd.read_parquet(proc / "events.parquet")
    old = pd.read_parquet(proc / "legacy_events.parquet")
    g = pd.read_parquet(proc / "goes_matched.parquet")
    return m, new, old, g


def pick_examples(m, new, old, g) -> list[dict]:
    """Six examples from the tune period, chosen by fixed rules (no cherry-picking by outcome)."""
    lo, hi = config.period_bounds("tune")
    old_t = old[(old["onset"] >= lo) & (old["onset"] < hi)]
    g_t = g[(g["peak"] >= lo) & (g["peak"] < hi)].copy()
    # only flares SoLEXS actually observed (valid minute at the GOES peak)
    lab = g_t["peak"].dt.floor("min") + pd.Timedelta(minutes=1)
    g_t = g_t[lab.map(lambda t: bool(pd.notna(m.get(t, np.nan)))).to_numpy()]
    g_t["flux"] = g_t["goes_class"].map(goes_flux)
    ex = []
    # 1. the 2025-04-10 early-onset case (legacy onset ~05:14, GOES C3.2 begins 06:24)
    d = pd.Timestamp("2025-04-10 05:00", tz="UTC")
    e = old_t[(old_t["onset"] >= d) & (old_t["onset"] < d + pd.Timedelta(hours=1))].iloc[0]
    ex.append({"title": "Early legacy onset (2025-04-10)", "t0": e["onset"], "t1": e["end"]})
    # 2. the longest legacy event (> 6 h)
    e = old_t.loc[old_t["duration_s"].idxmax()]
    ex.append({"title": f"Longest legacy event ({e['duration_s'] / 3600:.1f} h)", "t0": e["onset"], "t1": e["end"]})
    # 3. the strongest GOES flare in the tune period
    e = g_t.loc[g_t["flux"].idxmax()]
    ex.append({"title": f"Strongest flare ({e['goes_class']})", "t0": e["begin"], "t1": e["end"]})
    # 4. first legacy event that the new detector splits into >= 2 matched flares, with an M-class among them
    for _, e in old_t[old_t["is_goes_matched"]].iterrows():
        inside = new[(new["onset"] >= e["onset"]) & (new["onset"] < e["end"]) & new["is_goes_matched"]]
        if len(inside) >= 2 and inside["goes_class"].astype(str).str[0].isin(["M", "X"]).any():
            ex.append({"title": "Merged flares, now separated", "t0": e["onset"], "t1": e["end"]})
            break
    # 5. first isolated C3-C5 flare in July 2025 (a typical case)
    jul = g_t[(g_t["begin"] >= pd.Timestamp("2025-07-01", tz="UTC")) & g_t["goes_class"].str.match(r"C[34]")]
    for _, e in jul.iterrows():
        near = g_t[(g_t["begin"] > e["begin"] - pd.Timedelta(hours=1)) & (g_t["begin"] < e["end"] + pd.Timedelta(hours=1))]
        if len(near) == 1:
            ex.append({"title": f"Typical isolated flare ({e['goes_class']})", "t0": e["begin"], "t1": e["end"]})
            break
    # 6. first B-class flare in October 2025 (small, near threshold)
    b = g_t[(g_t["begin"] >= pd.Timestamp("2025-10-01", tz="UTC")) & (g_t["class_letter"] == "B")].iloc[0]
    ex.append({"title": f"Small flare ({b['goes_class']})", "t0": b["begin"], "t1": b["end"]})
    return ex


def _panel(ax, m, new, old, g, t0, t1, title):
    pad = max(pd.Timedelta(minutes=40), (t1 - t0) * 0.25)
    a, b = t0 - pad, t1 + pad
    seg = m[(m.index >= a) & (m.index <= b)]
    last = None
    min_gap = (b - a) * 0.06  # skip a class label that would collide with the previous one
    for _, e in g[(g["end"] >= a) & (g["begin"] <= b)].sort_values("begin").iterrows():
        ax.axvspan(e["begin"], e["end"], color=GOES_FILL, lw=0, zorder=0)
        if last is None or e["begin"] - last >= min_gap:
            ax.text(max(e["begin"], a), 0.02, e["goes_class"], transform=ax.get_xaxis_transform(), fontsize=7,
                    color=MUTED, va="bottom", ha="left", zorder=5)
            last = e["begin"]
    ax.plot(seg.index - pd.Timedelta(seconds=30), seg.to_numpy(), color=INK, lw=1.0, zorder=3)
    y = np.nanmax(seg.to_numpy()) if len(seg) else 1
    for frame, col, lev, lab in ((old, OLD, 1.35, "legacy"), (new, NEW, 1.7, "new")):
        sel = frame[(frame["end"] >= a) & (frame["onset"] <= b)]
        for _, e in sel.iterrows():
            ax.plot([e["onset"], e["end"]], [y * lev] * 2, color=col, lw=2.5, solid_capstyle="round", zorder=4)
            ax.plot([e["onset"]], [y * lev], marker="|", ms=9, mew=2, color=col, zorder=4)
    ax.set_yscale("log")
    ax.set_ylim(top=y * 2.4)
    ax.set_xlim(a, b)
    ax.set_title(title, loc="left", color=INK)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz="UTC"))
    ax.set_ylabel("SoLEXS SDD2 counts/s (1-min mean)")
    ax.text(0.0, -0.16, f"{a:%Y-%m-%d} UTC", transform=ax.transAxes, fontsize=7, color=MUTED)


def examples_figure(m, new, old, g):
    ex = pick_examples(m, new, old, g)
    fig, axes = plt.subplots(3, 2, figsize=(11, 10), constrained_layout=True)
    for ax, e in zip(axes.flat, ex):
        _panel(ax, m, new, old, g, e["t0"], e["t1"], e["title"])
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    fig.legend(handles=[Line2D([], [], color=INK, lw=1, label="SoLEXS counts"),
                        Line2D([], [], color=OLD, lw=2.5, label="legacy detector event (bar: onset to end)"),
                        Line2D([], [], color=NEW, lw=2.5, label="new detector event (bar: onset to end)"),
                        Patch(color=GOES_FILL, label="GOES flare, begin to end (class at bottom)")],
               loc="upper center", ncol=4, bbox_to_anchor=(0.5, 1.035), fontsize=8)
    fig.suptitle("Flare detector before/after: six tune-period examples", x=0.01, ha="left", y=1.06, color=INK,
                 fontweight="bold")
    out = FIG_DIR / "before_after_examples.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    for i, e in enumerate(ex, 1):  # single-panel copies
        f1, ax = plt.subplots(figsize=(7, 3.4), constrained_layout=True)
        _panel(ax, m, new, old, g, e["t0"], e["t1"], e["title"])
        f1.savefig(FIG_DIR / f"example_{i}.png", dpi=130)
        plt.close(f1)
    return [{"title": e["title"], "t0": str(e["t0"]), "t1": str(e["t1"])} for e in ex]


def summary_figures():
    met = json.loads((config.PROJECT_ROOT / "reports" / "detection_metrics.json").read_text())
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.4), constrained_layout=True, sharey=False)
    for ax, per in zip(axes, ("tune", "val")):
        bins = list(met["new"][per]["duration_hist_min"])
        x = np.arange(len(bins))
        for off, ver, col in ((-0.2, "legacy", OLD), (0.2, "new", NEW)):
            vals = [met[ver][per]["duration_hist_min"][b] for b in bins]
            ax.bar(x + off, vals, width=0.38, color=col, label=ver, zorder=3)
        ax.set_xticks(x, [b + " min" for b in bins], rotation=0, fontsize=7)
        ax.set_title(f"Event duration, {per} period", loc="left")
        ax.set_ylabel("events")
        ax.legend(fontsize=8)
    fig.savefig(FIG_DIR / "duration_histogram.png", dpi=130)
    plt.close(fig)


def make_all():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    m, new, old, g = _load()
    ex = examples_figure(m, new, old, g)
    summary_figures()
    (FIG_DIR / "examples.json").write_text(json.dumps(ex, indent=2))
