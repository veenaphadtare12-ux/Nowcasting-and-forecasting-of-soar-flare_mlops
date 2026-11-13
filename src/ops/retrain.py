"""retrain_candidate logic: refit the frozen recipe on a newer window and register it as alias "challenger" ONLY.

The champion alias is never moved here (promotion is a human decision, after a fresh one-time evaluation). The recipe
(learner, features, threshold rule) comes from params `final.targets`. Windows outside development data are refused.
Layout: fit on [start, block_start - purge), thresholds (A = max TSS) on [block_start, end - purge).
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from src import config
from src import mlflow_utils as mu
from src.ops.locks import check_window

CHALLENGER, CHAMPION = "challenger", "champion"


def fit_candidate(
    df: pd.DataFrame,
    feats: list[str],
    target: str,
    model_kind: str,
    block_start,
    end,
    seed: int = 42,
    purge_min: int = 120,
    stride: int = 6,
) -> dict:
    from src.final import freeze
    from src.models import train

    y_col, ok_col = train.TARGETS[target]
    purge = pd.Timedelta(minutes=purge_min)
    b0, e = pd.Timestamp(block_start), pd.Timestamp(end)
    ok = df[ok_col].to_numpy().astype(bool)
    fit = df[(df.index < b0 - purge) & ok].iloc[::stride]
    blk = df[(df.index >= b0) & (df.index < e - purge) & ok]
    yf = fit[y_col].to_numpy().astype(int)
    est = freeze.make_model(model_kind, target, yf, seed).fit(fit[feats], yf)
    sb = est.predict_proba(blk[feats])[:, 1]
    thr = freeze.thresholds(blk[y_col].to_numpy().astype(bool), sb, config.load_params()["final"]["far_cap"])
    return {
        "estimator": est,
        "features": feats,
        "thresholds": thr,
        "fit_rows": len(fit),
        "block_rows": len(blk),
        "fit_dates": [str(fit.index.min()), str(fit.index.max())],
        "block_dates": [str(blk.index.min()), str(blk.index.max())],
        "example": fit[feats].dropna().head(5) if fit[feats].dropna().shape[0] >= 5 else fit[feats].head(5),
    }


def register_challenger(cand: dict, registry_name: str, target: str, tracking_uri: str | None = None) -> int:
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow
    from mlflow import MlflowClient
    from mlflow.models import infer_signature

    uri = tracking_uri or config.mlflow_uri()
    client = MlflowClient(tracking_uri=uri)
    before = _alias_version(client, registry_name, CHAMPION)
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment("flare-challengers")
    est, ex, thr = cand["estimator"], cand["example"], cand["thresholds"]
    tags = {
        "target": target,
        "role": CHALLENGER,
        "thr_A": f"{thr['A']:.6g}",
        "thr_B": f"{thr['B']:.6g}",
        "thr_C": f"{thr['C']:.6g}",
        "fit_dates": " .. ".join(cand["fit_dates"]),
        "threshold_block": " .. ".join(cand["block_dates"]),
    }
    try:
        tags |= mu.run_tags()
    except Exception:  # outside a git/DVC checkout (e.g. tests): provenance tags are best-effort
        pass
    with mlflow.start_run(run_name=f"challenger-{target}"):
        mlflow.set_tags(tags)
        info = mlflow.sklearn.log_model(
            est,
            name="model",
            signature=infer_signature(ex, est.predict_proba(ex)),
            input_example=ex,
            serialization_format="cloudpickle",
            pyfunc_predict_fn="predict_proba",
            registered_model_name=registry_name,
        )
    v = int(info.registered_model_version)
    client.set_registered_model_alias(registry_name, CHALLENGER, v)
    for k, val in tags.items():
        client.set_model_version_tag(registry_name, str(v), k, str(val))
    after = _alias_version(client, registry_name, CHAMPION)
    assert after == before, "the champion alias must never move during retraining"
    return v


def _alias_version(client, name: str, alias: str):
    try:
        return client.get_model_version_by_alias(name, alias).version
    except Exception:
        return None


def retrain(target: str, start, end, block_start, tracking_uri: str | None = None, frame: pd.DataFrame | None = None) -> dict:
    """Fit the params `final` recipe for `target` on development data and register it as challenger."""
    from src.dev2 import protocol
    from src.final import features as ff

    s, e = check_window(start, end, kind="dev")
    spec = config.load_params()["final"]["targets"][target]
    if frame is None:
        base = protocol.load(ff.base_features() + ff.label_columns() + ["flare_in_progress_at_t"])
        frame, feats = ff.build(base[(base.index >= s - pd.Timedelta(days=8)) & (base.index < e)], list(spec["ideas"]))
    else:
        feats = [c for c in frame.columns if not c.startswith(("y_", "ok_")) and c not in ("period", "flare_in_progress_at_t")]
    frame = frame[(frame.index >= s) & (frame.index < e)]
    cand = fit_candidate(frame, feats, target, spec["model"], block_start, e)
    v = register_challenger(cand, spec["registry"], target, tracking_uri)
    return {
        "target": target,
        "registry": spec["registry"],
        "challenger_version": v,
        "thresholds": cand["thresholds"],
        "fit_rows": cand["fit_rows"],
        "block_rows": cand["block_rows"],
        "block_has_positives": bool(np.isfinite(cand["thresholds"]["A"])),
    }
