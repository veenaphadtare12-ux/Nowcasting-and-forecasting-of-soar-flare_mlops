"""Presentation demo: load a model from MLflow (not from disk) and predict on 5 validation rows. Read-only.

    python -m src.demo_predict            # nowcast XGBoost
    python -m src.demo_predict c_60m logreg
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd

from src import config


def main(target: str = "now", model: str = "xgb") -> None:
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow

    mlflow.set_tracking_uri(config.mlflow_uri())
    name = f"{target}-{model}-seed42"
    r = mlflow.search_runs(experiment_names=["flare-models-v2"], filter_string=f"tags.mlflow.runName = '{name}'",
                           order_by=["start_time DESC"]).iloc[0]
    lm = mlflow.search_logged_models(experiment_ids=[r.experiment_id], filter_string=f"source_run_id = '{r.run_id}'",
                                     output_format="list")[0]
    m = mlflow.pyfunc.load_model(lm.model_uri)
    feats = json.loads((config.PROJECT_ROOT / "reports" / "model_metrics.json").read_text(encoding="utf-8"))["features"]
    x = pd.read_parquet(config.processed_dir() / "dataset" / "val.parquet", columns=feats).dropna().head(5)  # validation only
    print(f"run {name}  ({r.run_id[:8]})")
    print(f"  git commit {r['tags.git_commit'][:7]}   data (DVC md5) {r['tags.dataset_md5'][:8]}   seed {r['tags.seed']}")
    print(f"  signature: {len(m.metadata.get_input_schema().input_names())} input features -> 2 probabilities")
    for t, p in zip(x.index, m.predict(x)[:, 1]):
        print(f"  {t:%Y-%m-%d %H:%M:%S} UTC   P(flare) = {p:.3f}")


if __name__ == "__main__":
    main(*sys.argv[1:])
