# Lesson 15 — MLflow provenance: tags, datasets, signatures, registry

**Code:** `src/mlflow_utils.py`, `src/models/train.py` (`_log_seed_run`), `src/mlflow_figures.py`,
`src/models/load_production.py`.

## Why
A metric without provenance is a rumour. Three months from now, "TSS 0.47" is only useful if you can answer three
questions: which code, which data, and which model file produced it?

| Question | What answers it | Where |
|---|---|---|
| Which code? | `git_commit` tag (+ `git_dirty`) | every new run |
| Which data? | `dvc_lock_md5` tag; dataset input digest = DVC md5 of `data/processed/dataset` | every new run, **Datasets used** |
| Which model, and how do I call it? | logged model with a **signature** (44 float32 columns in, 2 probabilities out) and a 5-row input example | the `*-seed42` runs |
| Which variant? | `target`, `model`, `horizon_min`, `seed` tags | every new run |

## Ideas
- **Dataset digest from DVC, not from MLflow.** MLflow would hash a sample of the DataFrame. Using DVC's md5 instead
  ties the run to the same data version that `dvc checkout` can restore.
- **Never log the test set.** `make_inputs` refuses any period except tune and val. A logged dataset is an invitation to
  use it.
- **A signature is a contract.** `pyfunc` checks the input columns and types before predicting, so a renamed feature
  fails loudly instead of silently producing garbage.
- **Attach, don't reopen.** `MlflowClient.log_artifact(run_id, …)` adds a figure to a finished run without
  changing its status or metrics. Reopening a run with `start_run(run_id=…)` would change its status and end time.
- **Registry = decision.** Registering a model and aliasing it `production` is a human choice. The loader is ready and
  tested on a throwaway registry; the real registry stays empty until you choose.

## Exercises
1. In the MLflow UI, open `now-xgb-seed42`. Find the git commit, the dataset digest and the model signature.
2. Run `git show <git_commit tag>:params.yaml`. Is that the same `params.yaml` as today?
3. Register the c_60m LogReg (seed 42) as `flare-c60`, set the alias `production`, then run
   `python -c "from src.models.load_production import load_production; print(load_production('flare-c60'))"`.
   Run `pytest tests/test_load_production.py` again: the skipped test now runs.

## Quiz
1. Why is the seed tag `42,43,44` on the aggregate run but `42` on a grandchild run?
2. What would happen if training ran with uncommitted code changes?
3. Why does the pyfunc model return two columns?

<details><summary>Answers</summary>

1. The aggregate run's metrics are means over three seeds; the grandchild holds one seed's own metrics and model.
2. `git_dirty` = True. The commit tag alone would then not reproduce the run, so commit before training.
3. It was logged with `pyfunc_predict_fn="predict_proba"`: column 0 = P(no flare), column 1 = P(flare).
</details>
