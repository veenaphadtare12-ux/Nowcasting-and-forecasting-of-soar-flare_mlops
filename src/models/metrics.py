"""Forecast-verification metrics. Primary: TSS and HSS (CLAUDE.md rule 4); never accuracy alone.

Contingency table for a yes/no forecast:
                 observed yes   observed no
    forecast yes      TP             FP
    forecast no       FN             TN
TSS = TP/(TP+FN) - FP/(FP+TN)   (hit rate minus false-alarm rate; 0 = no skill, 1 = perfect; not affected by
                                  how rare flares are)
HSS = 2(TP*TN - FN*FP) / ((TP+FN)(FN+TN) + (TP+FP)(FP+TN))   (skill relative to random chance)
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


def contingency(y: np.ndarray, yhat: np.ndarray) -> dict:
    y, yhat = np.asarray(y).astype(bool), np.asarray(yhat).astype(bool)
    return {"tp": int((y & yhat).sum()), "fp": int((~y & yhat).sum()),
            "fn": int((y & ~yhat).sum()), "tn": int((~y & ~yhat).sum())}


def tss(c: dict) -> float:
    pos, neg = c["tp"] + c["fn"], c["fp"] + c["tn"]
    return (c["tp"] / pos if pos else 0.0) - (c["fp"] / neg if neg else 0.0)


def hss(c: dict) -> float:
    tp, fp, fn, tn = c["tp"], c["fp"], c["fn"], c["tn"]
    den = (tp + fn) * (fn + tn) + (tp + fp) * (fp + tn)
    return 2.0 * (tp * tn - fn * fp) / den if den else 0.0


def best_threshold(y: np.ndarray, score: np.ndarray, metric: str = "tss") -> tuple[float, float]:
    """Threshold on `score` that maximises TSS (or HSS), checking every distinct score value at once.

    Sorting the scores once gives TP/FP counts for every possible cut, so this is exact and fast.
    Returns (threshold, metric value). Predict "yes" when score >= threshold.
    """
    y = np.asarray(y).astype(bool)
    s = np.asarray(score, dtype=float)
    order = np.argsort(-s, kind="mergesort")
    s_sorted, y_sorted = s[order], y[order]
    tp = np.cumsum(y_sorted)
    fp = np.cumsum(~y_sorted)
    last = np.r_[np.nonzero(np.diff(s_sorted))[0], len(s_sorted) - 1]  # last index of each distinct score
    tp, fp, thr = tp[last], fp[last], s_sorted[last]
    P, N = y.sum(), (~y).sum()
    fn, tn = P - tp, N - fp
    if metric == "tss":
        val = tp / max(P, 1) - fp / max(N, 1)
    else:
        den = (tp + fn) * (fn + tn) + (tp + fp) * (fp + tn)
        val = np.where(den > 0, 2.0 * (tp * tn - fn * fp) / np.where(den > 0, den, 1), 0.0)
    i = int(np.argmax(val))
    return float(thr[i]), float(val[i])


def evaluate(y: np.ndarray, score: np.ndarray, threshold: float, proba: bool = True) -> dict:
    """All verification numbers at a fixed threshold, plus threshold-free ones."""
    y = np.asarray(y).astype(bool)
    c = contingency(y, score >= threshold)
    out = {**c, "n": int(len(y)), "pos_rate": float(y.mean()), "threshold": float(threshold),
           "tss": tss(c), "hss": hss(c),
           "pod": c["tp"] / max(c["tp"] + c["fn"], 1),          # probability of detection (recall)
           "far": c["fp"] / max(c["tp"] + c["fp"], 1),          # false alarm ratio
           "accuracy": (c["tp"] + c["tn"]) / max(len(y), 1)}    # reported only for contrast, never alone
    if y.any() and (~y).any():
        out["roc_auc"] = float(roc_auc_score(y, score))
        out["avg_precision"] = float(average_precision_score(y, score))
    if proba:
        out["brier"] = float(brier_score_loss(y, np.clip(score, 0, 1)))
    return out


# ---------------------------------------------------------------- bootstrap by day
def daily_counts(y: np.ndarray, yhat: np.ndarray, day_codes: np.ndarray, n_days: int) -> np.ndarray:
    """(n_days, 4) array of TP, FP, FN, TN per day. day_codes are integers 0..n_days-1."""
    y, yhat = np.asarray(y).astype(bool), np.asarray(yhat).astype(bool)
    cols = [y & yhat, ~y & yhat, y & ~yhat, ~y & ~yhat]
    return np.stack([np.bincount(day_codes, weights=c, minlength=n_days) for c in cols], axis=1)


def tss_from_counts(c: np.ndarray) -> np.ndarray:
    """TSS for counts with last axis (TP, FP, FN, TN)."""
    tp, fp, fn, tn = (c[..., i] for i in range(4))
    pos, neg = tp + fn, fp + tn
    return np.where(pos > 0, tp / np.where(pos > 0, pos, 1), 0.0) - np.where(neg > 0, fp / np.where(neg > 0, neg, 1), 0.0)


def bootstrap_indices(n_days: int, n_boot: int, seed: int) -> np.ndarray:
    """(n_boot, n_days) day indices drawn with replacement. Reuse the same draws for every model so the
    intervals are comparable."""
    return np.random.default_rng(seed).integers(0, n_days, size=(n_boot, n_days))


def bootstrap_mean_tss(day_counts_per_seed: list[np.ndarray], idx: np.ndarray, level: float = 0.95) -> tuple[float, float]:
    """Confidence interval of the seed-averaged TSS: resample whole days (flares cluster within days, so rows are
    not independent), recompute each seed's TSS from the summed counts, average over seeds, take percentiles."""
    boot = np.mean([tss_from_counts(dc[idx].sum(axis=1)) for dc in day_counts_per_seed], axis=0)
    a = (1 - level) / 2
    return float(np.quantile(boot, a)), float(np.quantile(boot, 1 - a))
