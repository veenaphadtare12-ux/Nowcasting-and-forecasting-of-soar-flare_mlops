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
| 09 | [Data inventory](09-data-inventory.md) | archives vs extracted data, zip listings, truncated zips and local headers, duplicates/versions, disk budget; part 2: safe selective extraction | ✅ written — to study |
| 10 | [HEL1OS hard X-ray features](10-hel1os-hard-xray-features.md) | sub-second offset bug, hard X-ray channels, hardness ratio, lags, Neupert effect, missing-by-design, imputer + indicator | ✅ written — to study |
| 11 | [EDA](11-eda.md) | why EDA comes first, reading each plot type, test-period guard, takeaways, correlation vs causation | ✅ written — to study |
| 12 | [Ablation](12-ablation.md) | retraining with HEL1OS features, fair ablation (same rows/model/thresholds), positive episodes, statistical power, saying "too few to conclude" | ✅ written — to study |
| 13 | [Presentation pack](13-presentation-pack.md) | facts sheet with sources, provenance, honest framing, slide-ready figures | ✅ written — to study |
| — | [Hands-on DVC & MLflow](lesson-dvc-mlflow.md) | run `dvc status/dag/params diff/metrics diff`, hardlinks, time travel with `dvc checkout`; count, browse and compare MLflow runs; quiz | ✅ written — to do yourself |
| 14 | [Slide figures 03–10](14-slide-figures.md) | superposed epoch, honest bin widths, best-vs-baseline with intervals, faded underpowered bars, permutation importance and where it is blind | ✅ written — to study |
| 15 | [MLflow provenance](15-mlflow-provenance.md) | git/dvc.lock tags, dataset inputs with DVC digest, per-seed runs, model signatures, attaching figures, registry + production loader | ✅ written — to study |
| 16 | [Honest improvement experiments](16-honest-improvement-experiments.md) | rolling monthly evaluation, purge gaps, pre-registered acceptance rule, adaptive thresholds and FAR cap, long-context/drift/spectral/GOES features, ablation, ensemble | ✅ written — to study |
