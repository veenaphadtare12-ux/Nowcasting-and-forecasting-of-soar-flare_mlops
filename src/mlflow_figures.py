"""Attach existing figures to MLflow runs as artifacts. Only artifacts and tags are added; metrics are never touched.

    python -m src.mlflow_figures

- experiment "eda", run "eda-figures": docs/figures/eda/*, slide figures 01-06, reports/eda_numbers.json
- latest detector-tuning parent run: detector evaluation figures in docs/figures/ and slide figure 07
- latest flare-models-v2 parent run of each target: docs/model_figures/*, slide figure 08 (and 10 for c_60m)
- latest hel1os-ablation run: slide figure 09
Re-running reuses the same "eda-figures" run (artifacts are overwritten, not duplicated).
"""
from __future__ import annotations

import os

from src import config
from src import mlflow_utils as mu

R = config.PROJECT_ROOT
PF = R / "docs" / "presentation_figures"


def _latest_parent(mlflow, experiment: str, run_name: str) -> str:
    df = mlflow.search_runs(experiment_names=[experiment], order_by=["start_time DESC"], max_results=1,
                            filter_string=f"tags.mlflow.runName = '{run_name}' and attributes.status = 'FINISHED'")
    df = df[df.get("tags.mlflow.parentRunId").isna()] if "tags.mlflow.parentRunId" in df else df
    if df.empty:
        raise LookupError(f"no finished run '{run_name}' in experiment '{experiment}'")
    return df.iloc[0]["run_id"]


def _attach(mlflow, run_id: str, files: list, folder: str) -> int:
    with mlflow.start_run(run_id=run_id):
        for f in files:
            mlflow.log_artifact(str(f), artifact_path=folder)
    return len(files)


def main() -> dict:
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow

    mlflow.set_tracking_uri(config.mlflow_uri())
    done = {}

    # EDA
    exp = mlflow.set_experiment("eda")
    old = mlflow.search_runs([exp.experiment_id], filter_string="tags.mlflow.runName = 'eda-figures'", max_results=1)
    ctx = mlflow.start_run(run_id=old.iloc[0]["run_id"]) if len(old) else mlflow.start_run(run_name="eda-figures")
    with ctx as run:
        mlflow.set_tags(mu.run_tags() | {"kind": "eda", "periods": "tune+val (test never evaluated)", "target": "none",
                                         "model": "none", "horizon_min": "none", "seed": "none"})
        eda_figs = sorted((R / "docs" / "figures" / "eda").glob("*.png"))
        for f in eda_figs:
            mlflow.log_artifact(str(f), artifact_path="eda_figures")
        slides = [PF / n for n in ("01_coverage_heatmap.png", "02_longterm_lightcurve.png", "03_monthly_flares_by_class.png",
                                   "04_flare_profiles_by_class.png", "05_neupert_lag_histogram.png", "06_stacked_flare_example.png")]
        for f in slides:
            mlflow.log_artifact(str(f), artifact_path="presentation_figures")
        mlflow.log_artifact(str(R / "reports" / "eda_numbers.json"))
        mlflow.log_artifact(str(PF / "FIGURE_NOTES.md"), artifact_path="presentation_figures")
        done["eda-figures"] = (run.info.run_id, len(eda_figs) + len(slides) + 2)

    # detector
    det = _latest_parent(mlflow, "detector-tuning", "grid-tune-period")
    det_files = sorted((R / "docs" / "figures").glob("*.png")) + [R / "docs" / "figures" / "examples.json"]
    n = _attach(mlflow, det, det_files, "detector_figures") + _attach(mlflow, det, [PF / "07_detector_before_after.png"],
                                                                      "presentation_figures")
    done["detector-tuning/grid-tune-period"] = (det, n)

    # models
    model_figs = sorted((R / "docs" / "model_figures").glob("*.png"))
    for target in config.load_params()["models"]["targets"]:
        rid = _latest_parent(mlflow, "flare-models-v2", target)
        n = _attach(mlflow, rid, model_figs, "model_figures")
        slides = [PF / "08_model_skill_validation.png"] + ([PF / "10_feature_importance.png"] if target == "c_60m" else [])
        n += _attach(mlflow, rid, slides, "presentation_figures")
        done[f"flare-models-v2/{target}"] = (rid, n)
    rid = _latest_parent(mlflow, "flare-models-v2", "hel1os-ablation")
    done["flare-models-v2/hel1os-ablation"] = (rid, _attach(mlflow, rid, [PF / "09_ablation.png"], "presentation_figures"))

    for k, (rid, n) in done.items():
        print(f"{k:38s} {rid}  {n} files")
    return done


if __name__ == "__main__":
    main()
