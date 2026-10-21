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
