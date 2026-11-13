"""Register the model bundle's champions in an MLflow tracking server (Docker Compose / Kubernetes service "mlflow").

    MLFLOW_TRACKING_URI=http://mlflow:5000 BUNDLE_DIR=/bundle python seed_registry.py

The project's own registry (mlflow.db) lives on the developer machine and is exported to the model bundle; this script
makes the same champions visible in the containerised MLflow (same names, alias "champion", the original version and
run id as tags, SHA-256 of the exported file). Idempotent: models whose champion already carries the same SHA-256 are
skipped. Runs inside the official MLflow image (no XGBoost needed: models are logged as a thin pyfunc wrapper around the
bundle's joblib file and are only unpickled when someone loads them).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import mlflow
from mlflow import MlflowClient
from mlflow.models import ModelSignature
from mlflow.types import ColSpec, Schema

BUNDLE = Path(os.environ.get("BUNDLE_DIR", "/bundle"))


class BundleModel(mlflow.pyfunc.PythonModel):
    """pyfunc wrapper: predict() returns [P(no flare), P(flare)] like the champion's predict_proba."""

    def load_context(self, context):
        import joblib

        self.model = joblib.load(context.artifacts["estimator"])

    def predict(self, context, model_input, params=None):
        return self.model.predict_proba(model_input)


def main() -> None:
    man = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    mlflow.set_experiment("model-bundle")
    client = MlflowClient()
    for target, m in man["models"].items():
        name = m["registry_name"]
        try:
            cur = client.get_model_version_by_alias(name, "champion")
            if cur.tags.get("bundle_sha256") == m["sha256"]:
                print(f"{name}: champion v{cur.version} already matches bundle {man['bundle_version']}")
                continue
        except Exception:
            pass
        sig = ModelSignature(
            inputs=Schema([ColSpec("double", f) for f in m["features"]]),
            outputs=Schema([ColSpec("double", "p_no_flare"), ColSpec("double", "p_flare")]),
        )
        tags = {
            "target": target,
            "learner": m.get("learner") or "",
            "ideas": ",".join(m["ideas"]) or "none",
            "thr_A": str(m["thresholds"].get("A")),
            "thr_B": str(m["thresholds"].get("B")),
            "thr_C": str(m["thresholds"].get("C")),
            "fit_dates": m.get("fit_dates") or "",
            "source_registry_version": m["version"],
            "source_run_id": m["run_id"],
            "bundle_version": man["bundle_version"],
            "bundle_git_sha": man["git_sha"],
            "bundle_sha256": m["sha256"],
        }
        with mlflow.start_run(run_name=f"bundle-{target}"):
            mlflow.set_tags(tags)
            info = mlflow.pyfunc.log_model(
                name="model",
                python_model=BundleModel(),
                artifacts={"estimator": str(BUNDLE / m["file"])},
                signature=sig,
                registered_model_name=name,
                pip_requirements=["scikit-learn==1.9.1", "xgboost==3.4.1", "joblib==1.6.0", "pandas==3.0.6", "numpy==2.5.3"],
            )
        v = info.registered_model_version
        client.set_registered_model_alias(name, "champion", v)
        for k, val in tags.items():
            client.set_model_version_tag(name, str(v), k, val)
        print(f"{name}: registered v{v} as champion (source registry v{m['version']}, run {m['run_id'][:8]})")


if __name__ == "__main__":
    main()
