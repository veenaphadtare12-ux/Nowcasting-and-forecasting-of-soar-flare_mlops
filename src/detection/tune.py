"""Grid search of detector thresholds on the TUNING PERIOD ONLY.

    python -m src.detection.tune            # run the grid from params.yaml, log every trial to MLflow

Data from the validation and test periods is never loaded here: the minute series is sliced to the tune period
before anything else happens (and `_tune_slice` asserts it). Results go to reports/tuning_results.csv and
reports/tuning_best.json; the chosen values are then copied into params.yaml `flare_detection` by hand, so the
change is visible in git and DVC.

Objective (higher is better):
    F1(match_rate_all, GOES recall >=C) - penalty_long * frac(events > long_event_s) - penalty_onset * median|onset err|
"""
from __future__ import annotations

import itertools
import json
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from src import config, goes
from src.detection import detector, matching

REPORTS = config.PROJECT_ROOT / "reports"


def _tune_slice() -> tuple[pd.Series, pd.Timestamp, pd.Timestamp]:
    lo, hi = config.period_bounds("tune")
    m = pd.read_parquet(config.processed_dir() / "solexs_minute.parquet")["m"]
    m = m[(m.index > lo) & (m.index <= hi)]  # minute labels are minute ENDS
    assert m.index.min() > lo and m.index.max() <= hi, "tuning must only see the tune period"
    return m, lo, hi


def _goes_tune(lo, hi) -> pd.DataFrame:
    g = goes.load_flare_list()
    return g[(g["begin"] >= lo - pd.Timedelta(hours=6)) & (g["begin"] < hi)].reset_index(drop=True)


def score(r: dict, frac_long: float, cfg: dict) -> float:
    p, rec = r["match_rate_all"] or 0.0, r["goes_recall_C_and_above"] or 0.0
    f1 = 2 * p * rec / (p + rec) if p + rec else 0.0
    onset = r["onset_error_min"]["median_abs"] or 0.0
    return f1 - cfg["penalty_long_event"] * frac_long - cfg["penalty_onset_per_min"] * onset


def _trial(args):
    combo, base, m, g, lo, hi, P = args
    s = detector.DetectorSettings.from_params(base, **combo)
    ev = detector.detect(detector.prepare(m, s), s)
    ev, gm, pairs = matching.match_goes(ev, g, P["goes_match"]["tolerance_s"])
    cfg = P["evaluation"]
    gaps = goes.missing_days(lo, hi)
    r = matching.evaluate_period(ev, gm, pairs, m.notna(), lo, hi, cfg["size_cut_counts_s"], cfg["long_event_s"],
                                 cfg["duration_bins_min"], exclude_days=gaps)
    frac_long = r["n_events_gt_long"] / max(r["n_events"], 1)
    return combo, r, frac_long, score(r, frac_long, P["tuning"])


def run(workers: int = 6) -> pd.DataFrame:
    import mlflow

    P = config.load_params()
    m, lo, hi = _tune_slice()
    g = _goes_tune(lo, hi)
    grid = P["tuning"]["grid"]
    keys = list(grid)
    combos = [dict(zip(keys, v)) for v in itertools.product(*(grid[k] for k in keys))]
    print(f"{len(combos)} trials on tune period {lo.date()} .. {(hi - pd.Timedelta(days=1)).date()}")
    with ProcessPoolExecutor(workers) as ex:
        results = list(ex.map(_trial, [(c, P["flare_detection"], m, g, lo, hi, P) for c in combos]))

    rows = []
    for combo, r, frac_long, sc in results:
        rows.append({**combo, "score": sc, "n_events": r["n_events"], "match_rate_all": r["match_rate_all"],
                     "precision_above_cut": r["precision_above_cut"], "recall_C_plus": r["goes_recall_C_and_above"],
                     "recall_all": r["goes_recall"], "n_gt_2h": r["n_events_gt_long"], "frac_gt_2h": frac_long,
                     "onset_med_abs_min": r["onset_error_min"]["median_abs"],
                     "onset_p90_abs_min": r["onset_error_min"]["p90_abs"]})
    df = pd.DataFrame(rows).sort_values("score", ascending=False)
    best = df.iloc[0].to_dict()
    # save results first, so a logging problem can never lose a finished grid
    REPORTS.mkdir(exist_ok=True)
    df.to_csv(REPORTS / "tuning_results.csv", index=False, lineterminator="\n")
    (REPORTS / "tuning_best.json").write_text(json.dumps({k: (v.item() if hasattr(v, "item") else v) for k, v in best.items()}, indent=2), newline="\n")

    mlflow.set_tracking_uri(config.mlflow_uri())
    mlflow.set_experiment("detector-tuning")
    with mlflow.start_run(run_name="grid-tune-period"):
        mlflow.log_params({"period": "tune", "start": str(lo.date()), "end": str((hi - pd.Timedelta(days=1)).date()),
                           "n_trials": len(combos)})
        for row in rows:
            with mlflow.start_run(nested=True, run_name="trial"):
                mlflow.log_params({k: row[k] for k in keys})
                mlflow.log_metrics({k: float(v) for k, v in row.items() if k not in keys and v is not None})
        mlflow.log_metrics({f"best_{k}": float(v) for k, v in best.items() if k not in keys})
        mlflow.log_params({f"best_{k}": best[k] for k in keys})
        mlflow.log_artifact(str(REPORTS / "tuning_results.csv"))
    return df


if __name__ == "__main__":
    out = run()
    print(out.head(10).to_string(index=False))
