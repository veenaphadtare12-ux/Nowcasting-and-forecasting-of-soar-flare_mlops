import os

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

from src.models import load_production as lp  # noqa: E402


@pytest.mark.parametrize("alias", ["champion", "production"])
def test_registered_models_load(alias):
    """Real registry (mlflow.db): every model with the alias loads and predicts probabilities."""
    names = lp.production_models(alias=alias)
    if not names:
        pytest.skip(f"model registry has no model with alias '{alias}' yet")
    for name in names:
        model = lp.load_production(name, alias=alias)
        cols = [c.name for c in model.metadata.get_input_schema().inputs]
        p = np.asarray(model.predict(pd.DataFrame(np.zeros((3, len(cols)), np.float32), columns=cols)))
        assert p.shape == (3, 2) and np.all((p >= 0) & (p <= 1))


def test_load_production_round_trip(tmp_path):
    """Helper works end to end on a throwaway registry (never touches the project's mlflow.db)."""
    import mlflow
    from mlflow import MlflowClient
    from mlflow.models import infer_signature
    from sklearn.linear_model import LogisticRegression

    uri = f"sqlite:///{(tmp_path / 'reg.db').as_posix()}"
    old = mlflow.get_tracking_uri()
    try:
        mlflow.set_tracking_uri(uri)
        # explicit artifact folder: the default is ./mlruns/<id>, which would write into the project's mlruns
        mlflow.set_experiment(experiment_id=mlflow.create_experiment("t", artifact_location=(tmp_path / "art").as_uri()))
        X = pd.DataFrame({"a": np.r_[np.zeros(20), np.ones(20)].astype(np.float32), "b": np.ones(40, np.float32)})
        y = np.r_[np.zeros(20), np.ones(20)].astype(int)
        clf = LogisticRegression().fit(X, y)
        with mlflow.start_run():
            info = mlflow.sklearn.log_model(clf, name="model", signature=infer_signature(X, clf.predict_proba(X)),
                                            input_example=X.head(5), serialization_format="cloudpickle",
                                            pyfunc_predict_fn="predict_proba", registered_model_name="toy")
        MlflowClient(tracking_uri=uri).set_registered_model_alias("toy", "production", info.registered_model_version)
        assert lp.production_models(tracking_uri=uri) == ["toy"]
        p = np.asarray(lp.load_production("toy", tracking_uri=uri).predict(X.head(3)))
        assert p.shape == (3, 2)
        np.testing.assert_allclose(p, clf.predict_proba(X.head(3)), rtol=1e-6)
    finally:
        mlflow.set_tracking_uri(old)
