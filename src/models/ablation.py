"""HEL1OS ablation: soft (SoLEXS) vs hard (HEL1OS) vs combined features, on rows where HEL1OS is available.

Fair comparison: the three feature sets use the SAME rows (hel1os_available == 1), the same models and settings,
the same threshold procedure (operating points A/B chosen on a later held-out block of tune), 3 seeds, the same
day-bootstrap, and the same all-rows / quiet-start split.

Because no HEL1OS session falls in Dec-Jan (the usual calibration block), the calibration block here is the
HEL1OS rows of `models.ablation.cal_start` .. `cal_end` (Nov 2025); fitting uses HEL1OS rows before it (minus the
purge gap). Validation is only the val period's HEL1OS rows. The test period is never read.

Small samples are reported as such: a target with fewer than `min_positive_episodes` positive episodes in validation
is flagged "too few positives" and must not be over-interpreted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.models import metrics, train

HARD_PREFIX = "hx_"


def feature_sets(feats: list[str]) -> dict[str, list[str]]:
    soft = [c for c in feats if not c.startswith(HARD_PREFIX) and c != "hel1os_available"]
    hard = [c for c in feats if c.startswith(HARD_PREFIX)]
    return {"soft": soft, "hard": hard, "combined": soft + hard}


def positive_episodes(d: pd.DataFrame, y_col: str, gap_s: int = 60) -> int:
    """Number of separate runs of positive rows (a run = consecutive positives with no time gap > gap_s).
    Rows 10 s apart are not independent; episodes are the honest count of positive 'events'."""
    pos = d.index[d[y_col].astype(bool)]
    if len(pos) == 0:
        return 0
    gaps = np.diff(pos.as_unit("s").asi8) > gap_s
    return int(gaps.sum() + 1)


def run_ablation(tune: pd.DataFrame, val: pd.DataFrame, feats: list[str], P: dict, xgb_params: dict[str, dict]) -> dict:
    mp, ab = P["models"], P["models"]["ablation"]
    ops = mp["operating_points"]
    sets = feature_sets(feats)
    if not sets["hard"]:
        return {"skipped": "no HEL1OS features in the dataset"}
    th = tune[tune["hel1os_available"] == 1]
    vh = val[val["hel1os_available"] == 1]
    c0, c1 = pd.Timestamp(ab["cal_start"], tz="UTC"), pd.Timestamp(ab["cal_end"], tz="UTC") + pd.Timedelta(days=1)
    fit_df = th[th.index < c0 - pd.Timedelta(minutes=mp["purge_min"])]
    cal_df = th[(th.index >= c0) & (th.index < c1)]
    days = pd.DatetimeIndex(sorted(vh.index.floor("D").unique()))
    bs = mp["bootstrap"]
    idx = metrics.bootstrap_indices(len(days), bs["n"], bs["seed"])
    out: dict = {"rows": {"fit": len(fit_df), "cal": len(cal_df), "val": len(vh)}, "val_days": len(days),
                 "cal_block": [ab["cal_start"], ab["cal_end"]], "min_positive_episodes": ab["min_positive_episodes"],
                 "feature_sets": {k: len(v) for k, v in sets.items()}, "targets": {}}
    for target in mp["targets"]:
        y_col, ok_col = train.TARGETS[target]
        fit = train._rows(fit_df, target, ab["train_stride"])
        cal, v = train._rows(cal_df, target), train._rows(vh, target)
        yf, yc, yv = train._y(fit, target), train._y(cal, target), train._y(v, target)
        quiet = v[train.FLAG].to_numpy() == 0
        dcodes = days.get_indexer(v.index.floor("D"))
        n_ep = positive_episodes(v, y_col)
        res = {"n_val_rows": len(v), "val_pos_rate": float(yv.mean()) if len(yv) else None,
               "val_positive_episodes": n_ep, "cal_positive_episodes": positive_episodes(cal, y_col),
               "fit_positive_rows": int(yf.sum()),
               "too_few_positives": bool(n_ep < ab["min_positive_episodes"]), "models": {}}
        if yf.sum() == 0 or yc.sum() == 0 or yv.sum() == 0:
            res["skipped"] = "no positives in fit, calibration or validation rows"
            out["targets"][target] = res
            continue
        for model in ("logreg", "xgb"):
            res["models"][model] = {}
            for name, cols in sets.items():
                runs = []
                for seed in mp["seeds"]:
                    if model == "logreg":
                        est = train.make_logreg(mp["logreg"], seed).fit(fit[cols], yf)
                    else:
                        est = train.make_xgb(mp["xgb"], xgb_params[target], seed, train._pos_weight(yf)).fit(fit[cols], yf)
                    sc, sv = est.predict_proba(cal[cols])[:, 1], est.predict_proba(v[cols])[:, 1]
                    runs.append(train._score_block(yc, sc, yv, sv, quiet, dcodes, len(days), ops))
                res["models"][model][name] = train.aggregate(runs, ops, idx, bs["level"])
        out["targets"][target] = res
    return out


def table(ab: dict) -> list[str]:
    """Markdown ablation table (operating point A; TSS mean ± std [95 % interval]), all rows and quiet-start."""
    if "skipped" in ab:
        return [f"Ablation skipped: {ab['skipped']}"]
    lines = ["| Target | Model | Val episodes | Soft (SoLEXS) | Hard (HEL1OS) | Combined | Quiet: soft | Quiet: hard | Quiet: combined |",
             "|---|---|---|---|---|---|---|---|---|"]
    fmt = lambda a: f"{a['tss_mean']:.2f} ± {a['tss_std']:.2f} [{a['tss_ci_low']:.2f}, {a['tss_ci_high']:.2f}]"  # noqa: E731
    for t, r in ab["targets"].items():
        flag = " ⚠ too few" if r["too_few_positives"] else ""
        if "skipped" in r:
            lines.append(f"| {t} | — | {r['val_positive_episodes']}{flag} | {r['skipped']} | | | | | |")
            continue
        for m, d in r["models"].items():
            cells = [fmt(d[s]["A"]["all"]) for s in ("soft", "hard", "combined")]
            cells += [fmt(d[s]["A"]["quiet"]) for s in ("soft", "hard", "combined")]
            lines.append(f"| {t} | {m} | {r['val_positive_episodes']}{flag} | " + " | ".join(cells) + " |")
    return lines
