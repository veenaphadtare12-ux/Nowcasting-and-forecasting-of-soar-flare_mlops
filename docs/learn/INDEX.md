# Learning index

Study these in order. Each lesson ends with exercises to do yourself, a safe "break it" experiment, and a quiz.

| # | Lesson | Covers | Status |
|---|---|---|---|
| 01 | [Setup](01-setup.md) | venv, Python 3.12, pip/wheels, git, requirements.txt, CLAUDE.md, params.yaml, data periods | ✅ written — to study |
| 02 | [Ingestion](02-ingestion.md) | FITS/HDUs, astropy, SoLEXS & HEL1OS parsers, Unix time & MJD, UTC, Parquet, data gaps | ✅ written — to study |
| 03 | [Detection](03-detection.md) | rolling background, noise (Poisson vs MAD), GOES-style onset/end, GOES matching, 300-trial tuning in MLflow, precision vs recall | ✅ written — to study |
| 04 | [Labels & features](04-labels-features.md) | nowcast vs forecast labels, ok flags, 27 causal features at 10 s cadence, class imbalance | ✅ written — to study |
| 05 | [DVC & tests](05-dvc-and-tests.md) | dvc.yaml stages, dvc.lock, hardlink cache, dvc repro, line endings, 28 tests, leakage tests, AST check | ✅ written — to study |
| 06 | [Model training](06-model-training.md) | time split + purge, rule / logistic regression / XGBoost, class imbalance, early stopping, thresholds, TSS/HSS/POD/FAR, MLflow, DVC train stage | ✅ written — numbers superseded by 08 |
| 07 | [Label noise & quiet-start](07-label-noise-and-quiet-start.md) | GOES-direct forecast labels, primary-match onset rule, label comparison, causal activity flag, quiet-start evaluation | ✅ written — to study |
| 08 | [Baselines, CV, operating points, bootstrap](08-baselines-cv-operating-points-bootstrap.md) | climatology/persistence baselines, rolling-origin CV, seeds, operating points A/B, day-bootstrap intervals, validation re-use | ✅ written — to study |
