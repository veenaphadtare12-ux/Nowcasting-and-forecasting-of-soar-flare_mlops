# Hands-on lesson: DVC and MLflow on our real project

You run every command yourself. After each one, compare your screen with the **Expected** text. Nothing here changes
code or data, except the optional time-travel exercise, which tells you exactly how to come back.

**Before you start** (PowerShell, in `D:\projects\solar-flare-project`):
```
.venv\Scripts\Activate.ps1
```
Your prompt should start with `(.venv)`.

**Two words you'll need:**
- **DVC** is a "smart kitchen" for data. `dvc.yaml` is the recipe, `dvc.lock` is the kitchen's memory of what it
  cooked, and the cache is the store room of every dish ever cooked.
- **MLflow** is a "lab notebook". Every experiment run writes down its settings, its scores and its files.

---

## Part A — DVC

### A1. Is everything up to date?
```
dvc status
```
*Expected:* `Data and pipelines are up to date.` That means every output matches the code, data and settings that
`dvc.lock` remembers. If a stage name appears instead, something it depends on has changed since the last run.

### A2. See the pipeline map
```
dvc dag
```
*Expected:* a drawing with 9 boxes: `fetch_goes`, `solexs_clean`, `detect_events`, `legacy_events`, `match_goes`,
`evaluate_detector`, `build_dataset`, `train`, and `hel1os_index` (connected to `build_dataset`). Follow the lines from
`solexs_clean` down to `train`: that is the path the data takes.

### A3. List the data versions
```
git log --oneline -- dvc.lock
```
*Expected:* 10 lines, newest first, starting with `998609a Retrain with HEL1OS features + soft/hard ablation ...` and
ending with `3e0781a Add stage-2 data pipeline ...`. Each line is one saved version of all our data outputs.

### A4. What settings changed between two versions?
```
dvc params diff 3722f6e
```
*Expected:* a table that includes the rows below. They show settings added since version `3722f6e` (the `-` means
"did not exist then").
```
params.yaml  models.ablation.cal_start          -          2025-11-01
params.yaml  models.ablation.min_positive_episodes  -      30
params.yaml  paths.archive_root                 -          D:/MLOPS_CP/Data/original_zips
```

### A5. Did a result change between two versions?
```
dvc metrics diff 3722f6e --targets reports/model_metrics.json
```
*Expected:* a long table. Find the row `targets.now.models.xgb.summary.A.all.tss_mean`. It shows `0.72569` (old),
`0.72673` (now), change `0.00104`. Adding HEL1OS features moved the nowcast score by only 0.001.

### A6. See a hardlink with your own eyes
```
python -c "import os; print(os.stat('data/processed/events.parquet').st_nlink)"
```
*Expected:* `2`. The same file has two names: one in `data/processed`, one in `D:\dvc-cache`. That's why the outputs
cost no extra disk space.

### A7 (optional). Travel back in time and return
Only do this if `git status` shows nothing you want to keep, or stash it first.
```
git stash
git switch --detach 3722f6e
dvc checkout
dvc status
```
*Expected:* `Data and pipelines are up to date.` You are now looking at version 8 (before HEL1OS features). Check
`reports/dataset_summary.json`: it lists 27 features instead of 44. Come back with:
```
git switch master
dvc checkout
git stash pop
```

---

## Part B — MLflow

### B1. Count the runs without opening the UI
```
python -c "import sqlite3; c=sqlite3.connect('mlflow.db'); [print(n, k) for n, k in c.execute('select e.name, count(r.run_uuid) from experiments e left join runs r on r.experiment_id=e.experiment_id group by e.name')]"
```
*Expected:* `Default 0`, `detector-tuning 410`, `flare-models 105`, `flare-models-v2 85`, for 600 runs in total.

### B2. Open the UI
```
mlflow ui --backend-store-uri sqlite:///mlflow.db
```
Open http://127.0.0.1:5000. If the port is busy, an old UI may still be running: just open the address, or add
`--port 5001`. Stop it with Ctrl+C when you're done.

### B3. Find the best detector setting
1. Click **detector-tuning** on the left.
2. Expand the newest `grid-tune-period` parent run (▸).
3. Add the **score** column (Columns menu) and sort it from high to low.

*Expected:* the top trial has score ≈ **0.7986**, with params `min_excess_frac 1.0`, `min_excess_abs 12.0`,
`rise_steps 3`, `dip_frac 0.3`, `impulsive_factor 0`.

### B4. Compare logistic regression and XGBoost for one target
In **flare-models-v2**, expand the newest `m_60m` parent, tick `m_60m-logreg` and `m_60m-xgb`, then click **Compare**.

*Expected:* `A_all_tss_mean` is about 0.468 (logreg) vs about 0.418 (xgb), and `A_all_far_mean` is about 0.92 vs about
0.94. Logistic regression wins on TSS, and both raise many false alarms.

### B5. Open a file saved inside a run
In **flare-models-v2**, open the run `hel1os-ablation` → **Artifacts** → `ablation.json`.

*Expected:* JSON with `val_positive_episodes` for each target, for example `"m_30m"` → 15, which is why the M-class
ablation is marked "too few positives".

---

## Quiz (answers at the bottom)

1. You edit only `params.yaml → evaluation.size_cut_counts_s`. Which DVC stage(s) will `dvc repro` re-run, and how can you check *before* running?
2. Our raw SoLEXS data is not `dvc add`-ed. Where does it live, how do stages find it, and why didn't we put it in the cache?
3. What is stored in `dvc.lock`, and why does every commit that changes it count as a "data version"?
4. In MLflow, what is the difference between the `detector-tuning` parent run and its child runs?
5. Our MLflow model registry is empty. What is a registry for, and what would we need to do to use it?

---

<details>
<summary><b>Answers (spoiler — try first!)</b></summary>

1. Only `evaluate_detector`, because it's the only stage that lists `evaluation` under `params` in `dvc.yaml`. Check
   first with `dvc status`, which lists exactly the stages that would re-run.
2. In `D:\MLOPS_CP\Data`. Stages read it through `params.yaml` (`paths.data_root_solexs`, `paths.data_root_hel1os`).
   It's large and never changes, so copying it into the cache would double the disk use for no benefit.
3. The fingerprints (md5 hashes) of every stage's inputs and outputs, plus the param values used. Since it pins the
   exact data produced, each commit of `dvc.lock` is a restorable snapshot of all outputs (`git switch` + `dvc checkout`).
4. The parent run is one whole grid search (it records the period and the best result). Each child run is one trial:
   one combination of settings with its score.
5. A registry keeps named, versioned "official" models (for example `flare-nowcast v1 → Production`) so a service can
   load the approved one. We'd register the chosen model from its run (`mlflow.register_model(...)`) and give it an
   alias. That's **not done** yet.

</details>
