"""Exploratory data analysis helpers for notebooks/01_eda.ipynb. TUNE + VALIDATION periods only.

Every loader cuts data at the end of the validation period, and `check_no_test` asserts that nothing later slipped
through. Figures are written to docs/figures/eda/.
"""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import config, features, hel1os  # noqa: E402
from src.detection.matching import goes_flux  # noqa: E402

FIG = config.PROJECT_ROOT / "docs" / "figures" / "eda"
PROC = config.processed_dir()
LO = config.period_bounds("tune")[0]
HI = config.period_bounds("val")[1]          # exclusive end of validation: nothing at or after this is used
CLASS_COLORS = {"B": "#2a78d6", "C": "#eb6834", "M": "#1baf7a", "X": "#eda100"}   # palette slots 1-4, fixed order
INK, MUTED, GRID, BAND = "#1f1f1e", "#6b6a63", "#ecebe6", "#d9d8d2"
SERIES = "#2a78d6"

plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "legend.frameon": False, "axes.titlesize": 9, "axes.titleweight": "bold", "axes.titlelocation": "left",
})


def check_no_test(*objs) -> None:
    """Assert that no timestamp at or after the end of validation is present (the test period is never touched)."""
    for o in objs:
        idx = o.index if isinstance(o, (pd.Series, pd.DataFrame)) and isinstance(o.index, pd.DatetimeIndex) else None
        if idx is not None and len(idx):
            assert idx.max() < HI, "test-period data found"
        if isinstance(o, pd.DataFrame):
            for c in ("onset", "begin", "peak"):
                if c in o and len(o):
                    assert o[c].dropna().max() < HI, f"test-period data in column {c}"


def save(fig, name: str) -> str:
    FIG.mkdir(parents=True, exist_ok=True)
    p = FIG / f"{name}.png"
    if p.exists():
        p.chmod(0o666)
        p.unlink()
    fig.savefig(p, dpi=120, bbox_inches="tight")
    return str(p.relative_to(config.PROJECT_ROOT)).replace("\\", "/")


# ---------------------------------------------------------------- loaders (all cut at the end of validation)
def load_qc() -> pd.DataFrame:
    q = pd.read_csv(PROC / "solexs_qc.csv")
    q["date"] = pd.to_datetime(q["date"], utc=True)
    return q[(q["date"] >= LO) & (q["date"] < HI)].set_index("date")


def load_minutes() -> pd.Series:
    m = pd.read_parquet(PROC / "solexs_minute.parquet")["m"]
    return m[(m.index > LO) & (m.index < HI)]


def load_events() -> pd.DataFrame:
    e = pd.read_parquet(PROC / "events.parquet")
    return e[(e["onset"] >= LO) & (e["onset"] < HI)]


def load_goes() -> pd.DataFrame:
    g = pd.read_parquet(PROC / "goes_matched.parquet")
    p = g["peak"].fillna(g["begin"])
    g = g[(p >= LO) & (p < HI)].copy()
    g["flux"] = g["goes_class"].map(goes_flux)
    return g


def load_pairs() -> pd.DataFrame:
    return pd.read_parquet(PROC / "events_pairs.parquet")


def load_dataset(columns: list[str] | None = None) -> pd.DataFrame:
    parts = [pd.read_parquet(PROC / "dataset" / f"{p}.parquet", columns=columns) for p in ("tune", "val")]
    d = pd.concat(parts)
    return d[d.index < HI]


def load_hel1os_channels() -> pd.DataFrame | None:
    h = hel1os.load_optional()
    if h is None or h.empty:
        return None
    h = h[(h.index > LO) & (h.index < HI)]
    return features.hel1os_channels(h)


# ---------------------------------------------------------------- 1. coverage
def coverage(qc: pd.DataFrame, m: pd.Series) -> dict:
    days = pd.date_range(LO, HI - pd.Timedelta(days=1), freq="D")
    vf = qc["valid_fraction"].reindex(days).fillna(0.0)
    months = pd.period_range(days[0].strftime("%Y-%m"), days[-1].strftime("%Y-%m"), freq="M")
    grid = np.full((len(months), 31), np.nan)
    for d, v in vf.items():
        grid[months.get_loc(pd.Period(d.strftime("%Y-%m"), "M")), d.day - 1] = v
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), gridspec_kw={"width_ratios": [2.2, 1]}, constrained_layout=True)
    im = axes[0].imshow(grid, aspect="auto", cmap="Blues", vmin=0, vmax=1, interpolation="nearest")
    axes[0].set_yticks(range(len(months)), [str(p) for p in months])
    axes[0].set_xticks(range(0, 31, 2), range(1, 32, 2))
    axes[0].set_xlabel("day of month")
    axes[0].set_title("Valid SoLEXS coverage per day (white = no data; tune + val)")
    axes[0].grid(False)
    fig.colorbar(im, ax=axes[0], label="fraction of the day valid", shrink=0.85)
    by_dom = vf.groupby(vf.index.day).mean()
    axes[1].bar(by_dom.index, by_dom.values, color=SERIES, zorder=3)
    axes[1].set_title("Mean valid fraction by day of month")
    axes[1].set_xlabel("day of month")
    axes[1].set_ylim(0, 1)
    p1 = save(fig, "01_coverage_calendar")
    plt.close(fig)
    # gap lengths (runs of missing minutes)
    miss = m.isna().to_numpy()
    edges = np.diff(np.r_[0, miss.astype(int), 0])
    starts, ends = np.where(edges == 1)[0], np.where(edges == -1)[0]
    lengths = ends - starts
    fig, ax = plt.subplots(figsize=(7, 3.4), constrained_layout=True)
    bins = np.logspace(0, np.log10(max(lengths.max(), 2)), 40)
    ax.hist(lengths, bins=bins, color=SERIES, zorder=3)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("gap length (minutes, log)")
    ax.set_ylabel("number of gaps (log)")
    ax.set_title("Length of gaps in the 1-minute SoLEXS series")
    for x, lab in ((60, "1 h"), (1440, "1 day")):
        ax.axvline(x, color=MUTED, lw=0.8, ls="--")
        ax.text(x, ax.get_ylim()[1] * 0.6, " " + lab, color=MUTED, fontsize=8)
    p2 = save(fig, "01_gap_lengths")
    plt.close(fig)
    return {"fig_calendar": p1, "fig_gaps": p2, "days": len(days), "days_with_folder": int((vf > 0).sum()),
            "days_usable": int((vf >= 0.5).sum()), "mean_valid_fraction": float(vf.mean()),
            "valid_frac_17th": float(by_dom.get(17, np.nan)), "valid_frac_other": float(by_dom.drop(17).mean()),
            "n_gaps": int(len(lengths)), "gaps_le_5min": int((lengths <= 5).sum()),
            "gaps_ge_1day": int((lengths >= 1440).sum()), "longest_gap_days": float(lengths.max() / 1440),
            "missing_minute_fraction": float(miss.mean())}


# ---------------------------------------------------------------- 2. long-term light curve
def long_term(m: pd.Series, g: pd.DataFrame) -> dict:
    day = m.groupby(m.index.floor("D"))
    med, mx = day.median(), day.max()
    fig, ax = plt.subplots(figsize=(12, 4), constrained_layout=True)
    ax.plot(mx.index, mx.values, color=SERIES, lw=0.9, alpha=0.45, label="daily max (1-min mean)")
    ax.plot(med.index, med.values, color=SERIES, lw=1.6, label="daily median")
    ax.set_yscale("log")
    ax.set_ylabel("SoLEXS SDD2 counts/s")
    top = np.nanmax(mx.values) * 1.6
    for cls, mk in (("M", "v"), ("X", "*")):
        sel = g[g["class_letter"] == cls]
        ax.scatter(sel["peak"].fillna(sel["begin"]), np.full(len(sel), top * (1.0 if cls == "M" else 1.6)), marker=mk,
                   s=26 if cls == "M" else 60, color=CLASS_COLORS[cls], label=f"GOES {cls} flare ({len(sel)})", zorder=4)
    ax.axvline(config.period_bounds("val")[0], color=MUTED, lw=1, ls="--")
    ax.text(config.period_bounds("val")[0], top * 2.6, " validation →", color=MUTED, fontsize=8, va="bottom")
    ax.set_title("Long-term SoLEXS light curve with GOES M and X flares (tune + val)")
    ax.legend(loc="lower left", ncol=4, fontsize=8)
    p = save(fig, "02_long_term_lightcurve")
    plt.close(fig)
    return {"fig": p, "median_range": [float(np.nanpercentile(med, 5)), float(np.nanpercentile(med, 95))],
            "max_daily_peak": float(np.nanmax(mx)), "n_M": int((g["class_letter"] == "M").sum()),
            "n_X": int((g["class_letter"] == "X").sum())}


# ---------------------------------------------------------------- 3. activity trend
def activity_trend(m: pd.Series, g: pd.DataFrame) -> dict:
    gm = g.assign(month=g["peak"].fillna(g["begin"]).dt.tz_localize(None).dt.to_period("M"))
    counts = gm.groupby(["month", "class_letter"]).size().unstack(fill_value=0).reindex(columns=list("BCMX"), fill_value=0)
    bg = m.groupby(m.index.tz_localize(None).to_period("M")).quantile(0.2)
    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True, constrained_layout=True)
    x = np.arange(len(counts))
    bottom = np.zeros(len(counts))
    for cls in "BCMX":
        axes[0].bar(x, counts[cls].values, bottom=bottom, color=CLASS_COLORS[cls], label=cls, zorder=3, width=0.8)
        bottom += counts[cls].values
    axes[0].set_ylabel("GOES flares per month")
    axes[0].set_title("Monthly GOES flare counts by class")
    axes[0].legend(ncol=4, fontsize=8, loc="upper right")
    bgv = bg.reindex(counts.index)
    axes[1].plot(x, bgv.values, color=SERIES, marker="o", ms=4, lw=1.6, zorder=3)
    axes[1].set_ylabel("counts/s (20th percentile)")
    axes[1].set_title("Monthly SoLEXS background level (20th percentile of 1-min means)")
    axes[1].set_xticks(x, [str(p) for p in counts.index], rotation=45, ha="right")
    p = save(fig, "03_activity_trend")
    plt.close(fig)
    return {"fig": p, "monthly_counts": counts.astype(int).to_dict(orient="index"),
            "bg_first_last": [float(bgv.iloc[0]), float(bgv.iloc[-1])], "bg_min_max": [float(bgv.min()), float(bgv.max())],
            "flares_per_month_range": [int(counts.sum(axis=1).min()), int(counts.sum(axis=1).max())]}


# ---------------------------------------------------------------- 4. superposed epoch
def superposed_epoch(m: pd.Series, ev: pd.DataFrame, pre: int = 30, post: int = 120) -> dict:
    e = ev[ev["is_goes_matched"].astype(bool)].copy()
    e["cls"] = e["goes_class"].astype(str).str[0]
    lags = np.arange(-pre, post + 1)
    mv = m.to_numpy()
    t_ns = m.index.as_unit("ns").asi8
    out = {}
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6), sharey=True, constrained_layout=True)
    for ax, cls in zip(axes, "CMX"):
        sel = e[e["cls"] == cls]
        curves = []
        for _, r in sel.iterrows():
            i0 = np.searchsorted(t_ns, (r["onset"] + pd.Timedelta(minutes=1)).value)  # minute ending 1 min after onset start
            if i0 - pre < 0 or i0 + post >= len(mv):
                continue
            seg = mv[i0 - pre: i0 + post + 1]
            amp = r["peak_counts_s"] - r["bg_counts_s"]
            if not np.isfinite(seg).mean() > 0.8 or amp <= 0:
                continue
            curves.append((seg - r["bg_counts_s"]) / amp)
        out[cls] = len(curves)
        if not curves:
            continue
        c = np.vstack(curves)
        med, q1, q3 = np.nanmedian(c, 0), np.nanpercentile(c, 25, 0), np.nanpercentile(c, 75, 0)
        ax.fill_between(lags, q1, q3, color=CLASS_COLORS[cls], alpha=0.25, lw=0, label="25-75 %")
        ax.plot(lags, med, color=CLASS_COLORS[cls], lw=2, label="median")
        ax.axvline(0, color=MUTED, lw=0.8, ls="--")
        ax.set_title(f"GOES {cls} flares (n = {len(curves)})")
        ax.set_xlabel("minutes from SoLEXS onset")
        tpk = lags[np.nanargmax(med)]
        half = lags[(lags > tpk) & (med <= 0.5)]
        out[f"{cls}_median_peak_min"] = int(tpk)
        out[f"{cls}_median_half_decay_min"] = int(half[0] - tpk) if len(half) else None
    axes[0].set_ylabel("(counts − pre-flare bg) / peak excess")
    axes[0].legend(fontsize=8)
    out["fig"] = save(fig, "04_superposed_epoch")
    plt.close(fig)
    return out


# ---------------------------------------------------------------- 5. flare statistics
def flare_stats(ev: pd.DataFrame) -> dict:
    e = ev.copy()
    e["rise_min"] = (e["peak"] - e["onset"]).dt.total_seconds() / 60
    e["decay_min"] = (e["end"] - e["peak"]).dt.total_seconds() / 60
    e["dur_min"] = e["duration_s"] / 60
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.2), constrained_layout=True)
    for ax, col, lab in zip(axes, ("dur_min", "rise_min", "decay_min", "excess_counts_s"),
                            ("duration (min)", "rise time (min)", "decay time (min)", "peak excess (counts/s)")):
        v = e[col].clip(lower=0.5)
        ax.hist(v, bins=np.logspace(np.log10(v.min()), np.log10(v.max()), 35), color=SERIES, zorder=3)
        ax.set_xscale("log")
        ax.set_xlabel(lab + ", log")
        ax.set_title(f"median {e[col].median():.1f}")
    axes[0].set_ylabel("detected events")
    p1 = save(fig, "05_flare_distributions")
    plt.close(fig)
    mt = e[e["is_goes_matched"].astype(bool)].copy()
    mt["flux"] = mt["goes_class"].astype(str).map(goes_flux)
    mt = mt[mt["excess_counts_s"] > 0]
    lx, ly = np.log10(mt["flux"]), np.log10(mt["excess_counts_s"])
    slope, icpt = np.polyfit(lx, ly, 1)
    r = float(np.corrcoef(lx, ly)[0, 1])
    fig, ax = plt.subplots(figsize=(6, 4.4), constrained_layout=True)
    for cls in "BCMX":
        s = mt[mt["goes_class"].astype(str).str[0] == cls]
        ax.scatter(s["flux"], s["excess_counts_s"], s=9, alpha=0.6, color=CLASS_COLORS[cls], label=cls, lw=0)
    xx = np.logspace(lx.min(), lx.max(), 50)
    ax.plot(xx, 10 ** (icpt + slope * np.log10(xx)), color=INK, lw=1.4, label=f"fit: slope {slope:.2f}, r = {r:.2f}")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("GOES peak flux (W/m², from class)")
    ax.set_ylabel("SoLEXS peak excess (counts/s)")
    ax.set_title("SoLEXS peak vs GOES peak (matched detections)")
    ax.legend(fontsize=8)
    p2 = save(fig, "05_peak_vs_goes")
    plt.close(fig)
    return {"fig_dist": p1, "fig_scatter": p2, "n_events": len(e), "median_duration_min": float(e["dur_min"].median()),
            "median_rise_min": float(e["rise_min"].median()), "median_decay_min": float(e["decay_min"].median()),
            "decay_over_rise_median": float((e["decay_min"] / e["rise_min"].clip(lower=1)).median()),
            "fit_slope": float(slope), "fit_r": r, "n_matched_fit": len(mt)}


# ---------------------------------------------------------------- 6. detector vs GOES
def detector_vs_goes(m: pd.Series, ev: pd.DataFrame, g_all: pd.DataFrame, pairs: pd.DataFrame) -> dict:
    met = json.loads((config.PROJECT_ROOT / "reports" / "detection_metrics.json").read_text(encoding="utf-8"))["new"]
    ev_all = pd.read_parquet(PROC / "events.parquet")
    gmat = pd.read_parquet(PROC / "goes_matched.parquet")
    pr = pairs[pairs["event"].isin(ev.index) & pairs["goes"].isin(g_all.index)]
    err = (ev_all.loc[pr["event"], "onset"].to_numpy() - gmat.loc[pr["goes"], "begin"].to_numpy()).astype("timedelta64[s]").astype(float) / 60
    tmp = pd.DataFrame({"goes": pr["goes"].to_numpy(), "err": err})
    tmp = tmp.loc[tmp.assign(a=tmp["err"].abs()).groupby("goes")["a"].idxmin()]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.4), constrained_layout=True)
    axes[0].hist(tmp["err"].clip(-30, 30), bins=np.arange(-30.5, 31, 1), color=SERIES, zorder=3)
    axes[0].set_xlabel("SoLEXS onset − GOES start (min, clipped at ±30)")
    axes[0].set_ylabel("GOES flares")
    axes[0].set_title(f"Onset error: median {tmp['err'].median():.1f} min, |err| p90 {tmp['err'].abs().quantile(0.9):.0f} min")
    cls = list("BCMX")
    x = np.arange(len(cls))
    for i, (per, col) in enumerate((("tune", "#2a78d6"), ("val", "#eb6834"))):
        rc = met[per]["goes_recall_by_class"]
        axes[1].bar(x + (i - 0.5) * 0.38, [rc.get(c, {}).get("recall", np.nan) for c in cls], width=0.36, color=col,
                    label=per, zorder=3)
    axes[1].set_xticks(x, cls)
    axes[1].set_ylim(0, 1.05)
    axes[1].set_ylabel("recall (share of GOES flares detected)")
    axes[1].set_title("Detector recall by GOES class")
    axes[1].legend(fontsize=8)
    p1 = save(fig, "06_detector_vs_goes")
    plt.close(fig)
    # missed flares that SoLEXS was observing (valid minute at the GOES peak)
    miss = g_all[(g_all["n_solexs_matches"] == 0) & g_all["class_letter"].isin(["C", "M"])]
    lab = miss["peak"].fillna(miss["begin"]).dt.floor("min") + pd.Timedelta(minutes=1)
    miss = miss[lab.map(lambda t: bool(pd.notna(m.get(t, np.nan)))).to_numpy()]
    ex = pd.concat([miss[miss["class_letter"] == "M"].head(1), miss[miss["class_letter"] == "C"].head(2)])
    fig, axes = plt.subplots(1, len(ex), figsize=(4 * max(len(ex), 1), 3), constrained_layout=True, squeeze=False)
    for ax, (_, r) in zip(axes[0], ex.iterrows()):
        a, b = r["begin"] - pd.Timedelta(minutes=60), r["end"] + pd.Timedelta(minutes=60)
        seg = m[(m.index >= a) & (m.index <= b)]
        ax.axvspan(r["begin"], r["end"], color=BAND, lw=0)
        ax.plot(seg.index, seg.values, color=INK, lw=1)
        ax.set_title(f"missed {r['goes_class']}  {r['begin']:%Y-%m-%d %H:%M}")
        ax.tick_params(axis="x", labelrotation=30, labelsize=7)
    axes[0][0].set_ylabel("counts/s (1-min mean)")
    p2 = save(fig, "06_missed_examples")
    plt.close(fig)
    return {"fig": p1, "fig_missed": p2, "onset_err_median": float(tmp["err"].median()),
            "onset_abs_p90": float(tmp["err"].abs().quantile(0.9)),
            "recall_tune": {c: round(v["recall"], 3) for c, v in met["tune"]["goes_recall_by_class"].items()},
            "recall_val": {c: round(v["recall"], 3) for c, v in met["val"]["goes_recall_by_class"].items()},
            "missed_observed_C_M": int(len(miss)), "missed_examples": [f"{r.goes_class} {r.begin}" for r in ex.itertuples()]}


# ---------------------------------------------------------------- 7. features
SHOW = ["mean_1m", "ratio_1m_bg", "bg_60m", "max_60m", "slope_15m", "std_15m"]


def feature_eda(d: pd.DataFrame, soft: list[str]) -> dict:
    q = d[d["ok_60m"].astype(bool) & (d["flare_in_progress_at_t"] == 0)]
    q = q.iloc[::5]  # every 5th row (~1 per 50 s) keeps the plots fast
    pos, neg = q[q["y_c_60m"] == 1], q[q["y_c_60m"] == 0]
    fig, axes = plt.subplots(2, 3, figsize=(12, 6), constrained_layout=True)
    eff = {}
    for ax, f in zip(axes.flat, SHOW):
        lo, hi = np.nanpercentile(q[f], [1, 99])
        bins = np.linspace(lo, hi, 50)
        ax.hist(neg[f].clip(lo, hi), bins=bins, density=True, color="#2a78d6", alpha=0.55, label="no ≥C flare in 60 min")
        ax.hist(pos[f].clip(lo, hi), bins=bins, density=True, color="#eb6834", alpha=0.55, label="≥C flare within 60 min")
        ax.set_title(f)
        ax.set_yticks([])
        eff[f] = float((pos[f].median() - neg[f].median()) / (q[f].std() or 1))
    axes[0][0].legend(fontsize=7)
    p1 = save(fig, "07_feature_distributions")
    plt.close(fig)
    corr = d[soft].iloc[::20].corr()
    fig, ax = plt.subplots(figsize=(9.5, 8), constrained_layout=True)
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(soft)), soft, rotation=90, fontsize=7)
    ax.set_yticks(range(len(soft)), soft, fontsize=7)
    ax.grid(False)
    fig.colorbar(im, ax=ax, shrink=0.8, label="Pearson r")
    ax.set_title("Correlation between the 27 SoLEXS features")
    p2 = save(fig, "07_feature_correlation")
    plt.close(fig)
    up = corr.where(np.triu(np.ones(corr.shape, bool), 1)).stack()
    high = up[up.abs() > 0.9].sort_values(key=np.abs, ascending=False)
    return {"fig_dist": p1, "fig_corr": p2, "n_quiet_rows_used": len(q), "pos_share": float(len(pos) / max(len(q), 1)),
            "standardised_median_shift": {k: round(v, 3) for k, v in eff.items()},
            "high_corr_pairs": [(a, b, round(float(v), 3)) for (a, b), v in high.items()]}


# ---------------------------------------------------------------- 8. label base rates
TARGETS = [("y_now", "ok_now", "nowcast"), ("y_c_30m", "ok_30m", "≥C 30m"), ("y_c_60m", "ok_60m", "≥C 60m"),
           ("y_c_120m", "ok_120m", "≥C 120m"), ("y_m_30m", "ok_30m", "≥M 30m"), ("y_m_60m", "ok_60m", "≥M 60m"),
           ("y_m_120m", "ok_120m", "≥M 120m")]


def base_rates(d: pd.DataFrame) -> dict:
    rates = {lab: float(d.loc[d[ok].astype(bool), y].mean()) for y, ok, lab in TARGETS}
    ok = d["ok_60m"].astype(bool)
    dd = d[ok]
    month = dd.groupby(dd.index.tz_localize(None).to_period("M"))[["y_c_60m", "y_m_60m"]].mean()
    hour = dd.groupby(dd.index.hour)[["y_c_60m", "y_m_60m"]].mean()
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.4), constrained_layout=True)
    axes[0].bar(range(len(rates)), list(rates.values()), color=SERIES, zorder=3)
    axes[0].set_xticks(range(len(rates)), list(rates), rotation=30, ha="right")
    axes[0].set_title("Positive rate by target (ok rows)")
    for col, lab, c in (("y_c_60m", "≥C 60m", "#eb6834"), ("y_m_60m", "≥M 60m", "#1baf7a")):
        axes[1].plot(range(len(month)), month[col].values, marker="o", ms=3, color=c, label=lab)
        axes[2].plot(hour.index, hour[col].values, marker="o", ms=3, color=c, label=lab)
    axes[1].set_xticks(range(len(month)), [str(p) for p in month.index], rotation=45, ha="right", fontsize=7)
    axes[1].set_title("By month")
    axes[1].legend(fontsize=8)
    axes[2].set_title("By hour of day (UTC)")
    axes[2].set_xlabel("hour")
    p = save(fig, "08_label_base_rates")
    plt.close(fig)
    return {"fig": p, "rates": {k: round(v, 4) for k, v in rates.items()},
            "month_c60_range": [float(month["y_c_60m"].min()), float(month["y_c_60m"].max())],
            "month_m60_range": [float(month["y_m_60m"].min()), float(month["y_m_60m"].max())],
            "hour_c60_range": [float(hour["y_c_60m"].min()), float(hour["y_c_60m"].max())]}


# ---------------------------------------------------------------- 9. HEL1OS
def hel1os_eda(chan: pd.DataFrame | None, m: pd.Series, ev: pd.DataFrame, g: pd.DataFrame, d: pd.DataFrame) -> dict:
    if chan is None or "hel1os_available" not in d:
        return {"available": False}
    out = {"available": True, "per_period": {}}
    av = d["hel1os_available"] == 1
    for per in ("tune", "val"):
        lo, hi = config.period_bounds(per)
        dp = d[(d.index >= lo) & (d.index < hi)]
        a = dp[dp["hel1os_available"] == 1]
        hours = len(a) * 10 / 3600  # 10-s rows
        t_ns = a.index.as_unit("ns").asi8
        gp = g[(g["begin"] >= lo) & (g["begin"] < hi)]
        b_ns = gp["begin"].dt.as_unit("ns").astype("int64").to_numpy()
        j = np.searchsorted(t_ns, b_ns)
        near = np.zeros(len(b_ns), bool)
        for k in (j - 1, j):
            ok = (k >= 0) & (k < len(t_ns))
            near[ok] |= np.abs(t_ns[k[ok]] - b_ns[ok]) <= 10 * 1e9
        inside = gp[near]
        out["per_period"][per] = {"overlap_days": int(a.index.floor("D").nunique()), "overlap_hours": round(hours, 1),
                                  "goes_in_hel1os_time": inside["class_letter"].value_counts().reindex(list("CMX"), fill_value=0).astype(int).to_dict()}
    # Neupert lag: cross-correlate the hard X-ray rate with d(SXR)/dt around each matched >=C flare inside HEL1OS time
    c10 = chan.resample("10s", label="right", closed="right").mean()
    sx = d["rate"][av]
    e = ev[ev["is_goes_matched"].astype(bool) & ev["goes_class"].astype(str).str[0].isin(list("CMX"))]
    lags, examples = [], []
    max_lag = 30  # 10-s steps = +-5 min
    for _, r in e.iterrows():
        a, b = r["onset"] - pd.Timedelta(minutes=5), r["peak"] + pd.Timedelta(minutes=5)
        hx = c10["czt_lo"][(c10.index >= a) & (c10.index <= b)]
        s = sx[(sx.index >= a) & (sx.index <= b)]
        if len(hx) < 40 or hx.notna().mean() < 0.9 or len(s) < 40:
            continue
        ds = s.diff()
        j = pd.concat([hx.rename("hx"), ds.rename("ds")], axis=1).dropna()
        if len(j) < 40 or j["hx"].std() == 0:
            continue
        h, dsv = (j["hx"] - j["hx"].mean()).to_numpy(), (j["ds"] - j["ds"].mean()).to_numpy()
        cc = [np.corrcoef(h[max(0, -k): len(h) - max(0, k)], dsv[max(0, k): len(dsv) - max(0, -k)])[0, 1]
              for k in range(-max_lag, max_lag + 1)]
        k_best = int(np.nanargmax(cc)) - max_lag
        if np.nanmax(cc) < 0.3:
            continue  # no clear Neupert relation for this flare
        lags.append(k_best * 10)  # seconds; positive = d(SXR)/dt lags the hard X-rays
        examples.append((r["goes_class"], r["onset"], float(np.nanmax(cc))))
    lags = np.asarray(lags, float)
    fig, ax = plt.subplots(figsize=(6.5, 3.4), constrained_layout=True)
    ax.hist(lags / 60, bins=np.arange(-5.25, 5.3, 0.5), color=SERIES, zorder=3)
    ax.axvline(0, color=MUTED, lw=0.8, ls="--")
    ax.set_xlabel("lag of d(SXR)/dt behind hard X-rays (min)")
    ax.set_ylabel("flares")
    ax.set_title(f"Neupert lag (n = {len(lags)} flares with peak correlation ≥ 0.3)")
    out["fig_neupert"] = save(fig, "09_neupert_lag")
    plt.close(fig)
    out["neupert"] = {"n": int(len(lags)), "median_lag_s": float(np.median(lags)) if len(lags) else None,
                      "iqr_s": [float(np.percentile(lags, 25)), float(np.percentile(lags, 75))] if len(lags) else None}
    # hardness ratio before vs during flares
    hr = d["hx_hr_czt"]
    before, during = [], []
    for _, r in e.iterrows():
        b0 = hr[(hr.index >= r["onset"] - pd.Timedelta(minutes=15)) & (hr.index < r["onset"])].dropna()
        d0 = hr[(hr.index >= r["onset"]) & (hr.index <= r["peak"])].dropna()
        if len(b0) > 30 and len(d0) > 3:
            before.append(b0.median())
            during.append(d0.median())
    fig, ax = plt.subplots(figsize=(5, 3.6), constrained_layout=True)
    if before:
        ax.boxplot([before, during], tick_labels=["15 min before onset", "onset → peak"], widths=0.5,
                   medianprops={"color": INK}, patch_artist=True, boxprops={"facecolor": "#cde2fb", "edgecolor": MUTED})
    ax.set_ylabel("CZT hardness ratio (40-150 / 20-40 keV)")
    ax.set_title(f"Hardness before vs during flares (n = {len(before)})")
    out["fig_hardness"] = save(fig, "09_hardness")
    plt.close(fig)
    out["hardness"] = {"n": len(before), "median_before": float(np.median(before)) if before else None,
                       "median_during": float(np.median(during)) if during else None,
                       "share_harder_during": float(np.mean(np.array(during) > np.array(before))) if before else None}
    # stacked example: strongest matched flare inside HEL1OS time
    cand = [x for x in examples]
    if cand:
        best = max(cand, key=lambda x: goes_flux(str(x[0])))
        cls, on = best[0], best[1]
        a, b = on - pd.Timedelta(minutes=20), on + pd.Timedelta(minutes=60)
        fig, axes = plt.subplots(3, 1, figsize=(9, 6.4), sharex=True, constrained_layout=True)
        s = d["rate"][(d.index >= a) & (d.index <= b)]
        axes[0].plot(s.index, s.values, color=SERIES, lw=1)
        axes[0].set_ylabel("SoLEXS counts/s")
        axes[0].set_title(f"GOES {cls} flare, onset {on:%Y-%m-%d %H:%M} UTC: soft and hard X-rays")
        for c, col in (("cdte_lo", "#eb6834"), ("czt_lo", "#1baf7a"), ("czt_hi", "#eda100")):
            seg = c10[c][(c10.index >= a) & (c10.index <= b)]
            axes[1].plot(seg.index, seg.values, color=col, lw=1, label={"cdte_lo": "CdTe 5-20 keV", "czt_lo": "CZT 20-40 keV", "czt_hi": "CZT 40-150 keV"}[c])
        axes[1].set_ylabel("HEL1OS counts/s")
        axes[1].legend(fontsize=7, ncol=3)
        axes[2].plot(s.index, s.diff().values, color=SERIES, lw=1)
        axes[2].set_ylabel("d(SoLEXS)/dt")
        for ax in axes:
            ax.axvline(on, color=MUTED, lw=0.8, ls="--")
        out["fig_example"] = save(fig, "09_stacked_example")
        plt.close(fig)
        out["example"] = f"{cls} {on}"
    return out
