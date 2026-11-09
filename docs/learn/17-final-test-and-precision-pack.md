# Lesson 17 — Freezing the models, the one-time test, and the precision pack

## What we built
- **`docs/FINAL_CHOICE.md`:** the chosen model, features and thresholds per target, written and committed (`d31d6ab`)
  **before** any code that could read the test period existed.
- **DVC stage `final_models`:**
  - fits the frozen models on 2025-04-09 → 2026-04-30;
  - chooses thresholds A/B/C on May 2026;
  - fits isotonic calibration on May 2026;
  - registers each model in the MLflow registry with alias `champion`.
- **DVC stage `evaluate_test`:** the only code that reads `test.parquet`. It scores the frozen models once, with
  95% day-bootstrap intervals and paired tests.
- **DVC stage `test_analysis`:** reliability diagrams and Brier scores, a per-flare (event-based) evaluation, lead
  time against NOAA's M1 alert moment, error analysis, and a SHAP summary.
- **`docs/MODEL_CARD.md` and `docs/DATA_CARD.md`.**

## Why it matters (an everyday analogy)
A sealed exam:
- **FINAL_CHOICE.md** is writing your answers in ink and handing them in before the teacher reveals the marking
  scheme.
- **The test period** is the exam paper. It may be opened only once; looking again and changing answers would make
  the grade meaningless.
- **The registry** is the trophy shelf, holding the exact versions that sat the exam.
- **The model card** is the instruction leaflet: what the model is for, how well it did, and what it must not be
  used for.

## Concepts
- **Pre-registration:** decide the analysis before seeing the data. Here, git commit times prove the order: choice
  (`d31d6ab`) → frozen models (`5fb3338`) → test run.
- **Frozen model:** trained once, never refitted after test results are seen. Its thresholds are frozen too.
- **Model registry + alias:** a registered model has numbered versions; the alias `champion` points to the one in
  use. `models:/flare-nowcast@champion` always loads the champion, wherever it was trained.
- **Calibration:** "P = 0.3" should come true about 30% of the time.
  - Our models were trained with class balancing, so their raw probabilities are far too high (ECE 0.12–0.31 on May).
  - **Isotonic regression** learns a monotone mapping from raw score to observed frequency on held-out data.
    Because it is monotone, which rows exceed a threshold doesn't change; only the probability values do.
- **Brier score:** the mean of (probability − outcome)². Lower is better. Compare it with a climatology forecast.
- **Event-based evaluation:** forecasters care about *flares*, not 10-second rows.
  - Was each flare warned (any alert in the hour before it)?
  - How early? (lead time)
- **Operational lead time:** NOAA's official alert comes when GOES flux crosses M1 (10⁻⁵ W/m²). Our value is the
  time between our first alert and that moment.
- **Paired bootstrap test:** resample whole test days, compute TSS for both models on the *same* days, and see
  how often the chosen model is not better. That gives a one-sided p-value. Pairing removes day-to-day noise that
  affects both models equally.
- **SHAP:** splits each prediction into additive contributions per feature (for trees: exact, via XGBoost's
  `pred_contribs`). The summary shows which features push predictions up or down.

## Tools used
- **DVC:** `dvc repro test_analysis` ran the test-input stages, `evaluate_test` and the analysis, in that order.
  `dvc dag` shows that only `evaluate_test` and `test_analysis` depend on test-period outputs.
- **MLflow registry:** `MlflowClient().get_model_version_by_alias("flare-nowcast", "champion")`, version tags
  (`thr_A`, `fit_dates`, `git_commit`, `dvc_lock_md5`, `test_tss_A`).
- **scikit-learn:** `IsotonicRegression`, `VotingClassifier(voting="soft")` (the c_30m ensemble).
- **XGBoost:** `booster.predict(DMatrix(X), pred_contribs=True)` for SHAP values without extra packages.

## Code walkthrough
- `src/final/freeze.py`: `blocks()` defines fit / threshold rows; `thresholds()` computes A/B/C; the end of `main()`
  logs and registers each model and sets the alias.
- `src/final/evaluate_test.py`:
  - `load_all()` is the only reader of the test file;
  - `block_metrics()` gives metrics plus bootstrap draws;
  - the paired p-value is `(#draws where chosen ≤ other + 1) / (n + 1)`.
- `src/final/analysis.py`: `flare_starts()` (same rule as the labels; a test checks this), `event_eval()`,
  `operational_lead()`, `error_analysis()`, `shap_figure()`.
- `tests/test_final.py`:
  - only `src/dataset.py` and `src/final/evaluate_test.py` may name the test file;
  - only `evaluate_test`/`test_analysis` depend on test-period outputs;
  - the fit and threshold blocks end before the test.

## Hands-on
1. `git log --format="%h %ci %s" -6`. Check the order: choice → frozen models → test results.
2. `python -c "from src.models.load_production import load_production; m=load_production('flare-nowcast', alias='champion'); print(m.metadata.get_input_schema().input_names()[:5])"`.
3. Open `docs/final_figures/reliability.png`. Which target is worst calibrated before isotonic?
4. `pytest tests/test_final.py -v`. Read `test_the_test_file_pattern_matches_only_the_test_dataset`: why did we
   need it? (Hint: PROGRESS.md, 2026-11-09.)

## Break it on purpose
Add `pd.read_parquet("data/processed/dataset/test.parquet")` to `src/final/analysis.py` and run
`pytest tests/test_final.py`: two tests fail. Undo with `git checkout -- src/final/analysis.py`.

## Check yourself
1. Why must FINAL_CHOICE.md be committed before the test code runs?
2. Isotonic calibration changed the Brier score. Why didn't it change TSS?
3. Why is an event-based hit rate more meaningful to a space-weather forecaster than row-level POD?
4. What does a one-sided paired p-value of 0.30 mean?
5. Why can't the test result be used to pick between the chosen model and the runner-up now?

<details><summary>Answers</summary>

1. So the choice can't be influenced by the test result. Git timestamps prove the order.
2. It's a monotone mapping: the same rows stay above the (mapped) threshold, so alerts and TSS are unchanged.
3. Forecasters act per flare ("was I warned, and how early?"). Rows inside one long flare would otherwise count many
   times.
4. In 30% of resampled test periods the chosen model was not better: no convincing evidence that it is better.
5. That would be tuning on the test set. The test score would then no longer be unbiased.
</details>

## Questions to discuss with my tutor
- Is a 3.5-month test period with few M flares enough to judge M forecasts?
- Should the operating point for alerts be chosen by FAR (operational) or by TSS (scientific)?
- What would a monitoring plan for these champions look like (drift, calibration over time)?

## Key numbers to remember
- **Order in git:** choice `d31d6ab` → test code `edac79a` → frozen + registered `5fb3338` → test run.
- **Test TSS at A [95%]:**
  - now 0.758 [0.74, 0.78]
  - c_30m 0.358 [0.29, 0.42]
  - c_60m 0.304 [0.23, 0.37]
  - m_30m 0.518 [0.34, 0.63]
  - m_60m 0.494 [0.33, 0.60]
- **Paired tests:** every chosen model beats every baseline (p ≤ 0.001). c_30m beats the model it replaced
  (+0.091, p ≤ 0.001). For c_60m, m_30m and m_60m the chosen model and the runner-up are tied (p 0.15–0.61).
- **Per flare, m_60m:** 71/79 M flares warned, but 65 of those alerts were already on. Alert on 31% of the time;
  FAR 0.91.
- **NOAA M1 moment:** 82/82 M/X flares had an m_60m alert within 2 h before. The 12 new alerts came a median
  52 min before M1.
- **Calibration:** raw ECE on May 0.12–0.31. After isotonic, Brier beats climatology for all 5 targets (e.g. now
  0.031 vs 0.065).
- **SHAP (nowcast):** excess_1m, rate, ratio_1m_bg dominate.
