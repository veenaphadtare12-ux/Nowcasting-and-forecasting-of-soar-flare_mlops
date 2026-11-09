"""Stage test_analysis: precision pack on the one-time test results (nothing re-tuned; the test dataset file is not read).

    python -m src.final.analysis

Inputs: data/processed/final/test_scores.parquet (per-row scores from evaluate_test), models_final/thresholds.json,
the GOES flare list + detector events (flare starts, same rule as the labels), GOES-19 XRS test flux (NOAA M1 moment),
SoLEXS minute series (figures). Outputs: reports/final/analysis.json, docs/final_figures/*.png.
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
from src.final.freeze import MODEL_DIR, REPORT, _fresh  # noqa: E402

FIG = config.PROJECT_ROOT / "docs" / "final_figures"
SOLEXS, HEL1OS, INK, GREY, LIGHT = "#E07A1F", "#2B5DA8", "#1F1F1F", "#7A7A7A", "#E6E6E6"
HORIZON = {"c_30m": 30, "c_60m": 60, "m_30m": 30, "m_60m": 60}
MIN_CLASS = {"c_30m": "C", "c_60m": "C", "m_30m": "M", "m_60m": "M"}
plt.rcParams.update({"font.size": 12, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                     "grid.color": LIGHT, "legend.frameon": False})


def _save(fig, name: str) -> str:
    FIG.mkdir(parents=True, exist_ok=True)
    p = _fresh(FIG / f"{name}.png")
    fig.savefig(p, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return str(p.relative_to(config.PROJECT_ROOT)).replace("\\", "/")


def flare_starts(goes: pd.DataFrame, events: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """Every GOES flare with its start time by the label rule (src/labels.goes_onsets): the SoLEXS onset of the
    detection it is the primary match of, otherwise its GOES begin."""
    out = goes[["begin", "peak", "end", "goes_class", "class_letter"]].copy()
    out["start"] = out["begin"]
    if len(pairs):
        pr = pairs.copy()
        pr["ev_onset"] = events.loc[pr["event"], "onset"].to_numpy()
        pr["g_begin"] = goes.loc[pr["goes"], "begin"].to_numpy()
        pr["d"] = (pr["ev_onset"] - pr["g_begin"]).abs()
        prim = pr.loc[pr.groupby("event")["d"].idxmin()].sort_values("d").drop_duplicates("goes").set_index("goes")["ev_onset"]
        idx = out.index.intersection(prim.index)
        out.loc[idx, "start"] = prim.loc[idx].to_numpy()
    out["flux"] = out["goes_class"].astype(str).map(goes_flux)
    return out


def _alerts(sc: pd.DataFrame, col: str, thr: float, ok_col: str | None = None) -> pd.Series:
    a = sc[col] >= thr
    if ok_col:
        a &= sc[ok_col]
    return a


# ---------------------------------------------------------------- calibration
def calibration(sc: pd.DataFrame, targets: list[str]) -> dict:
    fig, axes = plt.subplots(1, len(targets), figsize=(4 * len(targets), 4), constrained_layout=True)
    out = {}
    for ax, t in zip(axes, targets):
        s = sc[sc[f"ok_{t}"]]
        y = s[f"y_{t}"].to_numpy()
        for col, colr, lab in ((f"s_{t}_chosen", SOLEXS, "raw"), (f"s_{t}_calibrated", HEL1OS, "isotonic (May)")):
            p = s[col].to_numpy()
            q = np.quantile(p, np.linspace(0, 1, 11))
            k = np.clip(np.searchsorted(q, p, side="right") - 1, 0, 9)
            xs = [p[k == b].mean() for b in range(10) if (k == b).any()]
            ys = [y[k == b].mean() for b in range(10) if (k == b).any()]
            ax.plot(xs, ys, "o-", color=colr, label=lab)
            out.setdefault(t, {})[lab] = {"mean_pred": [float(v) for v in xs], "obs_rate": [float(v) for v in ys]}
        ax.plot([0, 1], [0, 1], color=GREY, ls="--", lw=1)
        ax.set_title(t)
        ax.set_xlabel("predicted probability (decile mean)")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
    axes[0].set_ylabel("observed frequency")
    axes[0].legend(loc="upper left")
    out["figure"] = _save(fig, "reliability")
    return out


# ---------------------------------------------------------------- event-based evaluation
def event_eval(sc: pd.DataFrame, fl: pd.DataFrame, events: pd.DataFrame, thr: dict, F: dict) -> dict:
    t0, t1 = config.period_bounds("test")
    fl = fl[(fl["start"] >= t0) & (fl["start"] < t1)]
    tns = sc.index.as_unit("ns").asi8
    out = {}
    per_flare = []
    for t, h in HORIZON.items():
        if t not in F["targets"]:
            continue
        a = _alerts(sc, f"s_{t}_chosen", thr[t]["chosen"]["A"], f"ok_{t}").to_numpy()
        okv = sc[f"ok_{t}"].to_numpy()
        sel = fl[fl["flux"] >= goes_flux(MIN_CLASS[t] + "1.0")]
        rows = []
        for i, f in sel.iterrows():
            w0, w1 = (f["start"] - pd.Timedelta(minutes=h)).value, f["start"].value
            lo, hi = np.searchsorted(tns, w0, "left"), np.searchsorted(tns, w1, "left")
            cov = okv[lo:hi].sum() / (h * 6)
            if cov < F["event_eval"]["min_coverage"]:
                continue
            hit = np.flatnonzero(a[lo:hi])
            lead = (w1 - tns[lo + hit[0]]) / 6e10 if len(hit) else np.nan
            rows.append({"cls": f["class_letter"], "warned": bool(len(hit)), "lead_min": lead})
            per_flare.append({"target": t, "goes_class": f["goes_class"], "start": str(f["start"]), "warned": bool(len(hit)),
                              "lead_min": None if np.isnan(lead) else round(float(lead), 1)})
        r = pd.DataFrame(rows)
        out[t] = {}
        for cls in sorted(r["cls"].unique()) if len(r) else []:
            g = r[r["cls"] == cls]
            ld = g["lead_min"].dropna()
            out[t][cls] = {"flares": int(len(g)), "warned": int(g["warned"].sum()), "hit_rate": float(g["warned"].mean()),
                           "lead_median_min": float(ld.median()) if len(ld) else None,
                           "lead_q25_min": float(ld.quantile(0.25)) if len(ld) else None,
                           "lead_q75_min": float(ld.quantile(0.75)) if len(ld) else None}
    # nowcast: GOES-matched detector events in the test period, alert between onset and end
    a = _alerts(sc, "s_now_chosen", thr["now"]["chosen"]["A"], "ok_now").to_numpy()
    okv = sc["ok_now"].to_numpy()
    ev = events[events["is_goes_matched"].astype(bool) & (events["onset"] >= t0) & (events["onset"] < t1)]
    rows = []
    for _, e in ev.iterrows():
        lo, hi = np.searchsorted(tns, e["onset"].value, "left"), np.searchsorted(tns, e["end"].value, "left")
        if hi <= lo or okv[lo:hi].mean() < F["event_eval"]["min_coverage"]:
            continue
        hit = np.flatnonzero(a[lo:hi])
        rows.append({"cls": str(e["goes_class"])[0], "warned": bool(len(hit)),
                     "delay_min": (tns[lo + hit[0]] - e["onset"].value) / 6e10 if len(hit) else np.nan})
    r = pd.DataFrame(rows)
    out["now"] = {}
    for cls in sorted(r["cls"].unique()) if len(r) else []:
        g = r[r["cls"] == cls]
        d = g["delay_min"].dropna()
        out["now"][cls] = {"flares": int(len(g)), "detected": int(g["warned"].sum()), "hit_rate": float(g["warned"].mean()),
                           "delay_median_min": float(d.median()) if len(d) else None,
                           "delay_q25_min": float(d.quantile(0.25)) if len(d) else None,
                           "delay_q75_min": float(d.quantile(0.75)) if len(d) else None}
    pf = pd.DataFrame(per_flare)
    if len(pf):
        fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), constrained_layout=True)
        for ax, t in zip(axes, ("c_60m", "m_60m")):
            g = pf[(pf["target"] == t) & pf["warned"]]
            for cls, col in (("C", "#EAA25C"), ("M", SOLEXS), ("X", "#7E3F0C")):
                v = g[g["goes_class"].str[0] == cls]["lead_min"]
                if len(v):
                    ax.hist(v, bins=np.arange(0, HORIZON[t] + 10, 10 if HORIZON[t] > 30 else 5), alpha=0.7, color=col,
                            label=f"{cls} (n={len(v)})")
            ax.set_title(f"{t}: lead time of warned flares")
            ax.set_xlabel("minutes between first alert and flare start")
            ax.legend()
        axes[0].set_ylabel("flares")
        out["figure_lead"] = _save(fig, "event_lead_times")
    return out, pf


# ---------------------------------------------------------------- operational lead vs NOAA M1 crossing
def operational_lead(sc: pd.DataFrame, fl: pd.DataFrame, gx: pd.DataFrame, thr: dict, F: dict) -> dict:
    L = F["lead_time"]
    t0, t1 = config.period_bounds("test")
    big = fl[(fl["flux"] >= goes_flux("M1.0")) & (fl["begin"] >= t0) & (fl["begin"] < t1)]
    xb = gx["xrsb"]
    tns = sc.index.as_unit("ns").asi8
    rows = []
    for _, f in big.iterrows():
        seg = xb[(xb.index > f["begin"]) & (xb.index <= f["end"] + pd.Timedelta(minutes=1))]
        cross = seg[seg >= L["m1_flux"]]
        if cross.empty:
            rows.append({"goes_class": f["goes_class"], "begin": str(f["begin"]), "t_m1": None})
            continue
        tm1 = cross.index[0]          # minute END = when NOAA could know the M1 crossing
        row = {"goes_class": f["goes_class"], "begin": str(f["begin"]), "t_m1": str(tm1)}
        for t in L["models"]:
            a = (sc[f"s_{t}_chosen"] >= thr[t]["chosen"]["A"]).to_numpy()
            lo = np.searchsorted(tns, (tm1 - pd.Timedelta(minutes=L["window_before_min"])).value, "left")
            hi = np.searchsorted(tns, (tm1 + pd.Timedelta(minutes=L["window_after_min"])).value, "right")
            hit = np.flatnonzero(a[lo:hi])
            if hi <= lo:
                row[t] = None                 # no SoLEXS rows in the window
            elif len(hit):
                row[t] = round((tm1.value - tns[lo + hit[0]]) / 6e10, 1)
                row[f"{t}_active_at_window_start"] = bool(a[lo])
            else:
                row[t] = "no alert"
        rows.append(row)
    df = pd.DataFrame(rows)
    out = {"flares": rows, "summary": {}}
    for t in L["models"]:
        if t not in df:
            continue
        v = pd.to_numeric(df[t], errors="coerce")
        scored = df[t].notna()
        out["summary"][t] = {"m_x_flares_with_m1_crossing": int(df["t_m1"].notna().sum()),
                             "with_solexs_rows": int(scored.sum()), "alerted": int(v.notna().sum()),
                             "alerted_before_m1": int((v > 0).sum()),
                             "lead_median_min": float(v.median()) if v.notna().any() else None,
                             "lead_q25_min": float(v.quantile(0.25)) if v.notna().any() else None,
                             "lead_q75_min": float(v.quantile(0.75)) if v.notna().any() else None,
                             "alert_already_on_at_window_start": int(df.get(f"{t}_active_at_window_start", pd.Series(dtype=bool)).fillna(False).sum())}
    if len(df):
        fig, ax = plt.subplots(figsize=(8, 3.8), constrained_layout=True)
        for t, col in zip(L["models"], (SOLEXS, "#7E3F0C", HEL1OS)):
            v = pd.to_numeric(df.get(t), errors="coerce").dropna()
            if len(v):
                ax.hist(v, bins=np.arange(-30, 125, 10), alpha=0.55, color=col, label=f"{t} (n={len(v)})")
        ax.axvline(0, color=INK, ls="--", lw=1)
        ax.set_xlabel("minutes our first alert came BEFORE the GOES M1 crossing (negative = after)")
        ax.set_ylabel("M/X flares")
        ax.legend()
        out["figure"] = _save(fig, "operational_lead_m1")
    return out


# ---------------------------------------------------------------- error analysis
def error_analysis(sc: pd.DataFrame, fl: pd.DataFrame, pf: pd.DataFrame, minute: pd.Series, thr: dict, F: dict) -> dict:
    out = {}
    t = "m_60m"
    h = HORIZON[t]
    th = thr[t]["chosen"]["A"]
    missed = pf[(pf["target"] == t) & ~pf["warned"]].copy()
    out["missed_m_flares"] = missed.to_dict(orient="records")
    if len(missed):
        n = min(len(missed), 12)
        cols = 4
        rws = int(np.ceil(n / cols))
        fig, axes = plt.subplots(rws, cols, figsize=(4.2 * cols, 3.0 * rws), squeeze=False, constrained_layout=True)
        for ax, (_, r) in zip(axes.flat, missed.head(n).iterrows()):
            s0 = pd.Timestamp(r["start"])
            a, b = s0 - pd.Timedelta(hours=3), s0 + pd.Timedelta(hours=1)
            seg = minute[(minute.index >= a) & (minute.index <= b)]
            ax.plot(seg.index, seg.to_numpy(), color=SOLEXS, lw=1)
            ax.set_yscale("log")
            ax2 = ax.twinx()
            p = sc.loc[(sc.index >= a) & (sc.index <= b), f"s_{t}_chosen"]
            ax2.plot(p.index, p.to_numpy(), color=HEL1OS, lw=0.8)
            ax2.axhline(th, color=HEL1OS, ls=":", lw=1)
            ax2.set_ylim(0, 1)
            ax.axvspan(s0 - pd.Timedelta(minutes=h), s0, color=LIGHT, zorder=0)
            ax.axvline(s0, color=INK, ls="--", lw=1)
            ax.set_title(f"{r['goes_class']}  {s0:%m-%d %H:%M}", fontsize=10)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz="UTC"))
        for ax in axes.flat[n:]:
            ax.axis("off")
        fig.suptitle("Missed M flares (m_60m): SoLEXS (orange, log) and P(M flare within 60 min) (blue, threshold dotted); "
                     "grey = warning window", fontsize=11)
        out["figure_missed"] = _save(fig, "missed_m_flares")
    # false-alarm clusters: alert episodes (gaps < merge min) with no >=M flare start in [episode start, episode end + h]
    a = (sc[f"s_{t}_chosen"] >= th) & sc[f"ok_{t}"]
    times = sc.index[a.to_numpy()]
    merge = pd.Timedelta(minutes=F["event_eval"]["false_alarm_merge_min"])
    eps = []
    if len(times):
        start = prev = times[0]
        for tt in times[1:]:
            if tt - prev > merge:
                eps.append((start, prev))
                start = tt
            prev = tt
        eps.append((start, prev))
    starts = np.sort(fl.loc[fl["flux"] >= goes_flux("M1.0"), "start"].to_numpy(dtype="datetime64[ns]"))
    rec = []
    for s0, s1 in eps:
        lo = np.searchsorted(starts, np.datetime64(s0.tz_convert(None)), "left")
        hi = np.searchsorted(starts, np.datetime64((s1 + pd.Timedelta(minutes=h)).tz_convert(None)), "right")
        rec.append({"start": s0, "end": s1, "minutes": (s1 - s0).total_seconds() / 60 + 1 / 6, "true": bool(hi > lo)})
    ep = pd.DataFrame(rec)
    if len(ep):
        fa = ep[~ep["true"]]
        out["alert_episodes"] = {"episodes": int(len(ep)), "false_episodes": int(len(fa)), "true_episodes": int(ep["true"].sum()),
                                 "false_episode_minutes_median": float(fa["minutes"].median()) if len(fa) else None,
                                 "false_alarm_hours": float(fa["minutes"].sum() / 60),
                                 "false_episodes_per_test_day": float(len(fa) / sc.index.floor("D").nunique())}
        fig, ax = plt.subplots(figsize=(12, 3.6), constrained_layout=True)
        day = sc[f"s_{t}_chosen"].resample("1h").max()
        ax.plot(day.index, day.to_numpy(), color=GREY, lw=0.6, label="P(M within 60 min), hourly max")
        ax.axhline(th, color=INK, ls=":", lw=1, label="threshold A")
        for _, e in fa.iterrows():
            ax.axvspan(e["start"], e["end"], color="#D04040", alpha=0.35, lw=0)
        mm = fl[(fl["flux"] >= goes_flux("M1.0")) & (fl["start"] >= sc.index.min()) & (fl["start"] <= sc.index.max())]
        ax.scatter(mm["start"], np.full(len(mm), 1.02), marker="v", color=SOLEXS, s=25, label=f"GOES ≥M flare start ({len(mm)})", clip_on=False)
        ax.set_ylim(0, 1.05)
        ax.set_ylabel("probability")
        ax.legend(loc="upper left", ncol=3, fontsize=9)
        ax.set_title("m_60m test period: false-alarm episodes in red")
        out["figure_false_alarms"] = _save(fig, "false_alarm_timeline")
    return out


def shap_figure(rep: dict) -> str | None:
    p = config.processed_dir() / "final" / "shap_nowcast_sample.parquet"
    if not p.exists():
        return None
    s = pd.read_parquet(p)
    feats = list(dict.fromkeys(s["feature"]))[::-1]
    fig, axes = plt.subplots(1, 2, figsize=(13, 6), gridspec_kw={"width_ratios": [1, 1.6]}, constrained_layout=True)
    imp = pd.Series(rep["mean_abs_shap"])[feats]
    axes[0].barh(feats, imp.to_numpy(), color=SOLEXS)
    axes[0].set_xlabel("mean |SHAP| (log-odds)")
    rng = np.random.default_rng(0)
    for i, f in enumerate(feats):
        g = s[s["feature"] == f].sample(min(1500, (s["feature"] == f).sum()), random_state=0)
        v = g["value"].to_numpy()
        r = (pd.Series(v).rank(pct=True).to_numpy())
        axes[1].scatter(g["shap"], i + rng.uniform(-0.3, 0.3, len(g)), c=r, cmap="coolwarm", s=3, alpha=0.6)
    axes[1].set_yticks(range(len(feats)), feats)
    axes[1].axvline(0, color=GREY, lw=1)
    axes[1].set_xlabel("SHAP value (effect on log-odds); colour = feature value rank (blue low, red high)")
    fig.suptitle(f"XGBoost nowcast, test period: SHAP summary ({rep['n_rows']:,} sampled rows)")
    return _save(fig, "shap_nowcast")


def main() -> dict:
    P = config.load_params()
    F = P["final"]
    proc = config.processed_dir()
    thr = json.loads((MODEL_DIR / "thresholds.json").read_text(encoding="utf-8"))
    tm = json.loads((REPORT / "test_metrics.json").read_text(encoding="utf-8"))
    sc = pd.read_parquet(proc / "final" / "test_scores.parquet")
    goes = pd.read_parquet(proc / "goes_matched.parquet")
    events = pd.read_parquet(proc / "events.parquet")
    pairs = pd.read_parquet(proc / "events_pairs.parquet")
    gx = pd.read_parquet(proc / "final" / "goes_xrs_minute_test.parquet")
    minute = pd.read_parquet(proc / "solexs_minute.parquet")["m"]
    fl = flare_starts(goes, events, pairs)
    out = {"calibration": calibration(sc, list(F["targets"]))}
    out["event_based"], pf = event_eval(sc, fl, events, thr, F)
    out["operational_lead"] = operational_lead(sc, fl, gx, thr, F)
    out["errors"] = error_analysis(sc, fl, pf, minute, thr, F)
    out["shap_figure"] = shap_figure(tm["shap_nowcast"]) if tm.get("shap_nowcast") else None
    _fresh(REPORT / "analysis.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8", newline="\n")
    print(json.dumps({k: out["event_based"][k] for k in out["event_based"] if not k.startswith("figure")}, indent=1, default=str))
    print(json.dumps(out["operational_lead"]["summary"], indent=1))
    return out


if __name__ == "__main__":
    main()
