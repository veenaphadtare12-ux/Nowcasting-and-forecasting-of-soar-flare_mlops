"""Slide-ready figures for the project review (docs/presentation_figures/). Tune + validation data only.

    python -m src.presentation_figures

1920 x 1080 px (16:9), large fonts (axis labels >= 20 pt), light background, no titles (added on the slide).
Colours: SoLEXS / soft X-ray = orange #E07A1F; HEL1OS / hard X-ray = blue #2B5DA8; everything else grey or near-black.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import json  # noqa: E402

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from src import config, eda  # noqa: E402
from src.detection import plots as dplots  # noqa: E402
from src.detection.matching import goes_flux  # noqa: E402

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


CLASS_RAMP = {"B": "#F3CDA6", "C": "#EAA25C", "M": "#E07A1F", "X": "#7E3F0C"}  # soft X-ray class: light -> dark orange
TARGET_LABEL = {"now": "Nowcast", "c_30m": "≥C 30 min", "c_60m": "≥C 60 min", "c_120m": "≥C 120 min",
                "m_30m": "≥M 30 min", "m_60m": "≥M 60 min", "m_120m": "≥M 120 min"}
MODEL_LABEL = {"climatology": "Climatology", "persistence": "Persistence", "rule": "1-feature rule",
               "logreg": "LogReg", "xgb": "XGBoost"}
MODEL_SHORT = {"climatology": "climatology", "persistence": "persistence", "rule": "rule",
               "logreg": "LogReg", "xgb": "XGB"}


def _period_divider(ax, x, ytext, transform=None) -> None:
    ax.axvline(x, color=INK, lw=1.8, ls=(0, (5, 4)))
    kw = {"color": INK, "fontsize": 18, "va": "top"}
    if transform is not None:
        kw["transform"] = transform
    ax.text(x, ytext, "  validation", **kw)
    ax.text(x, ytext, "tuning  ", ha="right", **kw)


def monthly_flares(g: pd.DataFrame) -> None:
    gm = g.assign(month=g["peak"].fillna(g["begin"]).dt.tz_localize(None).dt.to_period("M"))
    counts = gm.groupby(["month", "class_letter"]).size().unstack(fill_value=0).reindex(columns=list("BCMX"), fill_value=0)
    fig = _fig()
    ax = fig.add_axes([0.08, 0.12, 0.90, 0.76])
    x = np.arange(len(counts))
    bottom = np.zeros(len(counts))
    for cls in "BCMX":
        v = counts[cls].to_numpy()
        ax.bar(x, v, bottom=bottom, color=CLASS_RAMP[cls], width=0.78, zorder=3,
               label=f"{cls}-class ({int(v.sum())})")
        bottom += v
    for xi, tot in zip(x, bottom):
        ax.text(xi, tot + 4, f"{int(tot)}", ha="center", va="bottom", fontsize=16, color=INK)
    ax.set_xticks(x, [p.strftime("%b\n%Y") if p.month in (1, 4) or i == 0 else p.strftime("%b") for i, p in enumerate(counts.index)])
    ax.set_ylabel("GOES flares per month")
    ax.set_ylim(top=bottom.max() * 1.12)
    ax.grid(axis="x", visible=False)
    vx = int(np.flatnonzero(counts.index == pd.Period(config.period_bounds("val")[0].strftime("%Y-%m"), "M"))[0]) - 0.5
    _period_divider(ax, vx, 0.99, transform=ax.get_xaxis_transform())
    fig.legend(*ax.get_legend_handles_labels(), loc="upper center", bbox_to_anchor=(0.53, 0.995), ncol=4,
               columnspacing=2.5)
    _save(fig, "03_monthly_flares_by_class.png")


def flare_profiles(m: pd.Series, ev: pd.DataFrame, pre: int = 30, post: int = 120) -> dict:
    """Superposed epoch on the SoLEXS onset, same normalisation as the EDA figure 04 (median and 25-75 % band)."""
    e = ev[ev["is_goes_matched"].astype(bool)].copy()
    e["cls"] = e["goes_class"].astype(str).str[0]
    lags = np.arange(-pre, post + 1)
    mv, t_ns = m.to_numpy(), m.index.as_unit("ns").asi8
    fig = _fig()
    ax = fig.add_axes([0.08, 0.11, 0.90, 0.80])
    n = {}
    for cls in "CMX":
        curves = []
        for _, r in e[e["cls"] == cls].iterrows():
            i0 = np.searchsorted(t_ns, (r["onset"] + pd.Timedelta(minutes=1)).value)
            if i0 - pre < 0 or i0 + post >= len(mv):
                continue
            seg = mv[i0 - pre: i0 + post + 1]
            amp = r["peak_counts_s"] - r["bg_counts_s"]
            if not np.isfinite(seg).mean() > 0.8 or amp <= 0:
                continue
            curves.append((seg - r["bg_counts_s"]) / amp)
        n[cls] = len(curves)
        c = np.vstack(curves)
        col = CLASS_RAMP[cls]
        ax.fill_between(lags, np.nanpercentile(c, 25, 0), np.nanpercentile(c, 75, 0), color=col, alpha=0.18, lw=0)
        ax.plot(lags, np.nanmedian(c, 0), color=col, lw=4, label=f"GOES {cls}-class (n = {len(curves)})")
    ax.axvline(0, color=INK, lw=1.6, ls=(0, (5, 4)))
    ax.text(1.5, 0.97, "SoLEXS onset", transform=ax.get_xaxis_transform(), color=INK, fontsize=18, va="top")
    ax.set_xlim(-pre, post)
    ax.set_xlabel("Minutes from SoLEXS onset")
    ax.set_ylabel("SoLEXS rate above background\n(fraction of the flare's peak excess)")
    ax.legend(loc="upper right", title="Median; band = 25–75 %", title_fontsize=18)
    _save(fig, "04_flare_profiles_by_class.png")
    return n


def neupert_histogram(lags: np.ndarray) -> None:
    fig = _fig()
    ax = fig.add_axes([0.08, 0.13, 0.90, 0.80])
    edges = np.arange(-305, 306, 10)
    ax.hist(lags, bins=edges, color=HEL1OS, zorder=3, rwidth=0.88)
    ax.axvline(0, color=INK, lw=1.6, ls=(0, (5, 4)))
    med, q1, q3 = np.median(lags), *np.percentile(lags, [25, 75])
    ax.text(0.99, 0.97, f"n = {len(lags)} flares (GOES ≥C, peak correlation ≥ 0.3)\nmedian {med:.0f} s,  "
            f"middle half {q1:.0f} to {q3:+.0f} s", transform=ax.transAxes, ha="right", va="top", fontsize=20, color=INK)
    ax.set_xlim(-305, 305)
    ax.set_xticks(np.arange(-300, 301, 60))
    ax.set_xlabel("Lag of d(SoLEXS)/dt behind HEL1OS 20–40 keV (seconds; bin width 10 s = data resolution)")
    ax.set_ylabel("Flares")
    ax.yaxis.get_major_locator().set_params(integer=True)
    _save(fig, "05_neupert_lag_histogram.png")


def stacked_example(d: pd.DataFrame, c10: pd.DataFrame, examples: list) -> str:
    """Strongest GOES-matched flare with a clear hard X-ray response (same pick rule as the EDA figure 09)."""
    cls, on, _ = max(examples, key=lambda x: goes_flux(str(x[0])))
    a, b = on - pd.Timedelta(minutes=20), on + pd.Timedelta(minutes=60)
    fig = _fig()
    ax1 = fig.add_axes([0.09, 0.53, 0.88, 0.40])
    ax2 = fig.add_axes([0.09, 0.10, 0.88, 0.40], sharex=ax1)
    s = d["rate"][(d.index >= a) & (d.index <= b)]
    ax1.plot(s.index, s.to_numpy(), color=SOLEXS, lw=2.6, label="SoLEXS soft X-rays")
    ax1.set_yscale("log")  # log: the gradual rise after the detector onset is invisible on a linear axis
    ax1.set_ylabel("SoLEXS\n(counts/s, log)")
    ax1.legend(loc="upper right")
    for c, shade, lab in (("cdte_lo", "#9DB5DD", "HEL1OS CdTe 5–20 keV"), ("czt_lo", HEL1OS, "HEL1OS CZT 20–40 keV"),
                          ("czt_hi", "#14305E", "HEL1OS CZT 40–150 keV")):
        seg = c10[c][(c10.index >= a) & (c10.index <= b)]
        ax2.plot(seg.index, seg.to_numpy(), color=shade, lw=2.2, label=lab)
    ax2.set_yscale("log")
    ax2.set_ylabel("HEL1OS\n(counts/s, log)")
    ax2.legend(loc="upper right")
    for ax in (ax1, ax2):
        ax.axvline(on, color=INK, lw=1.6, ls=(0, (5, 4)))
    ax1.text(on, 0.97, "  SoLEXS onset", transform=ax1.get_xaxis_transform(), color=INK, fontsize=18, va="top")
    ax1.tick_params(labelbottom=False)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz="UTC"))
    ax2.set_xlabel(f"Time (UTC) on {on:%d %b %Y}: GOES {cls} flare")
    ax2.set_xlim(a, b)
    _save(fig, "06_stacked_flare_example.png")
    return f"GOES {cls}, onset {on:%Y-%m-%d %H:%M} UTC"


def detector_before_after() -> list[str]:
    """Examples 1, 2 and 4 of the detector-evaluation figure (fixed selection rules in detection.plots.pick_examples)."""
    m, new, old, g = dplots._load()
    m = m[m.index < eda.HI]
    new, old = new[new["onset"] < eda.HI], old[old["onset"] < eda.HI]
    g = g[g["begin"] < eda.HI]
    ex = dplots.pick_examples(m, new, old, g)
    pick = [ex[0], ex[1], next(e for e in ex if e["title"].startswith("Merged"))]
    names = ["Early onset fixed", "Over-long event ended", "Merged flares separated"]
    fig = _fig()
    axes = [fig.add_axes([0.085 + i * 0.31, 0.22, 0.275, 0.70]) for i in range(3)]
    for ax, e, name in zip(axes, pick, names):
        pad = max(pd.Timedelta(minutes=40), (e["t1"] - e["t0"]) * 0.25)
        a, b = e["t0"] - pad, e["t1"] + pad
        seg = m[(m.index >= a) & (m.index <= b)]
        for _, f in g[(g["end"] >= a) & (g["begin"] <= b)].iterrows():
            ax.axvspan(f["begin"], f["end"], color=LIGHT, lw=0, zorder=0)
        ax.plot(seg.index - pd.Timedelta(seconds=30), seg.to_numpy(), color=SOLEXS, lw=2.0, zorder=3)
        y = float(np.nanmax(seg.to_numpy()))
        for frame, col, lev in ((old, GREY, 1.4), (new, INK, 1.95)):
            for _, r in frame[(frame["end"] >= a) & (frame["onset"] <= b)].iterrows():
                ax.plot([r["onset"], r["end"]], [y * lev] * 2, color=col, lw=6, solid_capstyle="butt", zorder=4)
                ax.plot([r["onset"]], [y * lev], marker="|", ms=22, mew=3, color=col, zorder=4)
        ax.set_yscale("log")
        ax.set_ylim(top=y * 3.0)
        ax.set_xlim(a, b)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=5))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz="UTC"))
        ax.set_xlabel(f"UTC, {a:%d %b %Y}")
        ax.text(0.0, 1.02, name, transform=ax.transAxes, fontsize=22, color=INK, va="bottom", fontweight="bold")
    axes[0].set_ylabel("SoLEXS count rate (counts/s, log)")
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    fig.legend(handles=[Line2D([], [], color=SOLEXS, lw=3, label="SoLEXS (1-min mean)"),
                        Line2D([], [], color=GREY, lw=6, label="Old detector event"),
                        Line2D([], [], color=INK, lw=6, label="New detector event"),
                        Patch(color=LIGHT, label="GOES flare (begin to end)")],
               loc="lower center", bbox_to_anchor=(0.5, 0.0), ncol=4, columnspacing=2.5)
    _save(fig, "07_detector_before_after.png")
    return [e["title"] for e in pick]


def _tss(s: dict) -> tuple[float, float, float]:
    return s["tss_mean"], s["tss_ci_low"], s["tss_ci_high"]


def model_skill(mm: dict) -> dict:
    """Operating point A. Per target: the selected model vs the best baseline (highest TSS among climatology,
    persistence and the 1-feature rule), chosen separately for all rows and for quiet-start rows."""
    targets = list(TARGET_LABEL)
    fig = _fig()
    axes = [fig.add_axes([0.07, 0.59, 0.92, 0.32]), fig.add_axes([0.07, 0.13, 0.92, 0.32])]
    out = {}
    for ax, sub, name in zip(axes, ("all", "quiet"), ("All rows", "Quiet start (no flare in progress)")):
        x = np.arange(len(targets))
        labels = []
        for i, t in enumerate(targets):
            ms = mm["targets"][t]["models"]
            sel = mm["targets"][t]["selected"]
            base = max(("climatology", "persistence", "rule"), key=lambda k: ms[k]["summary"]["A"][sub]["tss_mean"])
            for off, k, col in ((-0.19, sel, INK), (0.19, base, GREY)):
                v, lo, hi = _tss(ms[k]["summary"]["A"][sub])
                ax.bar(i + off, v, width=0.36, color=col, zorder=3)
                ax.errorbar(i + off, v, yerr=[[v - lo], [hi - v]], color="#B0B0B0" if col == INK else INK,
                            capsize=7, lw=2.2, capthick=2.2, zorder=4)
                ax.text(i + off, max(hi, 0) + 0.02, f"{v:.2f}", ha="center", va="bottom", fontsize=16, color=INK)
                out[f"{t}_{sub}_{k}"] = round(v, 3)
            labels.append(f"{TARGET_LABEL[t]}\n{MODEL_SHORT[sel]} vs {MODEL_SHORT[base]}")
        ax.set_xticks(x, labels, fontsize=17)
        ax.set_ylim(-0.05, 1.0)
        ax.set_ylabel("TSS (validation)")
        ax.axhline(0, color=GREY, lw=1.2)
        ax.grid(axis="x", visible=False)
        ax.text(0.0, 1.02, name, transform=ax.transAxes, fontsize=22, fontweight="bold", color=INK, va="bottom")
    from matplotlib.patches import Patch

    fig.legend(handles=[Patch(color=INK, label="Best model"), Patch(color=GREY, label="Best baseline"),
                        Line2D([], [], color=INK, lw=2.2, marker="_", ms=14, label="95 % interval (day bootstrap)")],
               loc="upper right", bbox_to_anchor=(0.99, 0.995), ncol=3, columnspacing=2.5)
    _save(fig, "08_model_skill_validation.png")
    return out


def ablation_chart(mm: dict) -> None:
    ab = mm["ablation"]
    targets = list(TARGET_LABEL)
    cols = {"soft": (SOLEXS, "Soft X-ray only (SoLEXS)"), "hard": (HEL1OS, "Hard X-ray only (HEL1OS)"),
            "combined": ("#5A5A5A", "Combined")}
    fig = _fig()
    axes = [fig.add_axes([0.07, 0.57, 0.92, 0.33]), fig.add_axes([0.07, 0.15, 0.92, 0.33])]
    thr = ab["min_positive_episodes"]
    for ax, learner in zip(axes, ("logreg", "xgb")):
        for i, t in enumerate(targets):
            tt = ab["targets"][t]
            few = tt["val_positive_episodes"] < thr
            for j, fs in enumerate(("soft", "hard", "combined")):
                v, lo, hi = _tss(tt["models"][learner][fs]["A"]["all"])
                ax.bar(i + (j - 1) * 0.26, v, width=0.24, color=cols[fs][0], alpha=0.35 if few else 1.0, zorder=3)
                ax.errorbar(i + (j - 1) * 0.26, v, yerr=[[v - lo], [hi - v]], color=INK, capsize=4, lw=1.6, zorder=4)
            if learner == "logreg":
                ax.text(i, 1.0, f"{tt['val_positive_episodes']} episodes" + ("\ntoo few" if few else ""),
                        ha="center", va="top", fontsize=16, color=GREY if few else INK)
        ax.set_xticks(range(len(targets)), [TARGET_LABEL[t] for t in targets])
        ax.set_ylim(-0.3, 1.0)
        ax.axhline(0, color=GREY, lw=1.2)
        ax.set_ylabel("TSS (validation)")
        ax.grid(axis="x", visible=False)
        ax.text(0.0, 1.02, MODEL_LABEL[learner], transform=ax.transAxes, fontsize=22, fontweight="bold", color=INK, va="bottom")
    from matplotlib.patches import Patch

    fig.legend(handles=[Patch(color=c, label=lab) for c, lab in cols.values()],
               loc="upper right", bbox_to_anchor=(0.99, 0.995), ncol=3, columnspacing=2.5)
    fig.text(0.07, 0.02, f"Only rows with HEL1OS data ({ab['rows']['val']:,} validation rows, {ab['val_days']} days); "
             f"operating point A; 95 % day-bootstrap intervals.\nFaded = fewer than {thr} positive episodes "
             f"in validation: too few for a meaningful comparison.", fontsize=17, color=GREY)
    _save(fig, "09_ablation.png")


def feature_importance(mm: dict, top: int = 15) -> list[tuple[str, float]]:
    """Permutation importance of the selected >=C 60 min model (seed 42), on the Dec-Jan calibration block of the
    tune period. Score = average precision; validation is not re-used."""
    import joblib
    from sklearn.inspection import permutation_importance

    from src.models import train

    P = config.load_params()["models"]
    t = "c_60m"
    sel = mm["targets"][t]["selected"]
    assert sel == "logreg", "figure text assumes the selected model is logistic regression"
    feats = mm["features"]
    y_col, ok_col = train.TARGETS[t]
    tune = pd.read_parquet(config.processed_dir() / "dataset" / "tune.parquet", columns=feats + [y_col, ok_col])
    _, cal = train.split_tune(tune, P["inner_split"], P["purge_min"])
    cal = cal[cal[ok_col].astype(bool)].iloc[::P["train_stride"]]
    model = joblib.load(train.MODEL_DIR / f"{t}_logreg.joblib")
    r = permutation_importance(model, cal[feats], cal[y_col].astype(int), scoring="average_precision",
                               n_repeats=5, random_state=0, n_jobs=1)
    imp = pd.DataFrame({"mean": r.importances_mean, "std": r.importances_std}, index=feats).sort_values("mean", ascending=False)
    imp = imp.head(top).iloc[::-1]
    fig = _fig()
    ax = fig.add_axes([0.20, 0.16, 0.77, 0.81])
    colors = [HEL1OS if f.startswith("hx_") or f == "hel1os_available" else SOLEXS for f in imp.index]
    ax.barh(range(len(imp)), imp["mean"], xerr=imp["std"], color=colors, zorder=3, height=0.7,
            error_kw={"ecolor": INK, "capsize": 4, "lw": 1.6})
    ax.set_yticks(range(len(imp)), imp.index, fontsize=18)
    ax.set_xlabel("Drop in average precision when the feature is shuffled\n"
                  "(logistic regression, ≥C flare within 60 min; Dec 2025–Jan 2026 calibration rows)")
    ax.grid(axis="y", visible=False)
    from matplotlib.patches import Patch

    ax.legend(handles=[Patch(color=SOLEXS, label="SoLEXS feature"), Patch(color=HEL1OS, label="HEL1OS feature")],
              loc="lower right")
    _save(fig, "10_feature_importance.png")
    return [(f, round(float(v), 4)) for f, v in imp["mean"].iloc[::-1].items()]


def main() -> None:
    qc, m, g = eda.load_qc(), eda.load_minutes(), eda.load_goes()
    ev = eda.load_events()
    eda.check_no_test(qc, m, g, ev)  # tune + validation only
    coverage_heatmap(qc)
    longterm_lightcurve(m, g)
    monthly_flares(g)
    info = {"profiles_n": flare_profiles(m, ev)}
    d = eda.load_dataset(columns=["rate", "hel1os_available"])
    chan = eda.load_hel1os_channels()
    eda.check_no_test(d, chan)
    lags, examples, c10 = eda.neupert_lags(chan, d, ev)
    neupert_histogram(lags)
    info["stacked_example"] = stacked_example(d, c10, examples)
    info["detector_examples"] = detector_before_after()
    mm = json.loads((config.PROJECT_ROOT / "reports" / "model_metrics.json").read_text(encoding="utf-8"))
    info["skill"] = model_skill(mm)
    ablation_chart(mm)
    info["importance_top15"] = feature_importance(mm)
    p = config.PROJECT_ROOT / "reports" / "presentation_figures.json"
    p.write_text(json.dumps(info, indent=2, default=str), encoding="utf-8", newline="\n")
    print(json.dumps(info, indent=2, default=str))
    print("written to", OUT)


if __name__ == "__main__":
    main()
