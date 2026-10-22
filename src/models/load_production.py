"""Load a registered model by name and alias (default "production") as an MLflow pyfunc model.

    from src.models.load_production import load_production
    model = load_production("flare-nowcast")
    p = model.predict(features_df)          # (n, 2) class probabilities; column 1 = flare
"""
from __future__ import annotations

import os

from src import config


def load_production(name: str, alias: str = "production", tracking_uri: str | None = None):
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow

    mlflow.set_tracking_uri(tracking_uri or config.mlflow_uri())
    return mlflow.pyfunc.load_model(f"models:/{name}@{alias}")


def production_models(alias: str = "production", tracking_uri: str | None = None) -> list[str]:
    """Names of registered models that have the given alias (empty if the registry is empty)."""
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    from mlflow import MlflowClient

    client = MlflowClient(tracking_uri=tracking_uri or config.mlflow_uri())
    return [m.name for m in client.search_registered_models() if alias in (m.aliases or {})]
