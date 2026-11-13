# Lesson 19 — CI, data contracts, orchestration and drift (GitHub Actions, ruff, pandera, Prefect, Evidently)

## What we built
- **GitHub Actions CI** (`.github/workflows/ci.yml`): on every push and pull request it installs `requirements-ci.txt`
  on Linux with Python 3.12, then runs `ruff check` and `pytest -m "not data"`. Tests use a small committed fixture
  dataset (`tests/fixtures/`, 128 KB); tests that need the full DVC data carry the `data` marker and are skipped in CI.
- **pandera data contracts** (`src/validation/`): SoLEXS minute series, HEL1OS sessions, GOES events, the 10-s feature
  dataset and model predictions. Four DVC stages run the matching contract right after writing their output.
- **Prefect flows** (`flows/`, logic in `src/ops/`): `daily_ingest`, `score_replay`, `check_drift`, `retrain_candidate`.
- **Evidently drift report**: the training feature block vs the last 30 development days → `reports/drift/`.
- **Developer tooling:** `pyproject.toml` (ruff + pytest settings), `.pre-commit-config.yaml`, `Makefile`,
  `requirements-serve.txt`.

## Why it matters (everyday analogy)
- **CI** is a smoke alarm. It doesn't stop you cooking, but it beeps the moment you burn something, before your
  guests (the main branch) notice.
- **Data contracts** are the delivery checklist at a restaurant's back door. If the fish arrives warm, it's refused
  at the door, not discovered by a customer.
- **Prefect** is the kitchen's daily schedule, with "try again in 5 minutes" written next to the jobs that sometimes
  fail.
- **Drift monitoring** is checking whether this week's customers order very differently from the menu you planned.

## Concepts
- **Continuous integration:** every change is tested automatically on a clean machine. "Works on my laptop" isn't
  enough: the CI machine has no `D:\` drive and no DVC cache, which is why fixtures exist.
- **Test markers:** `@pytest.mark.data` labels tests that need local data; `-m "not data"` deselects them.
- **Linting vs formatting:** ruff *lint* finds likely bugs (unused imports, undefined names). Ruff *format* rewrites
  layout.
  - We format only new code. Re-formatting files that frozen DVC stages depend on would change their hashes and make
    DVC want to retrain.
- **Data contract:** a machine-checked promise about a table: column types, ranges, unique sorted UTC timestamps on
  the right grid, and cross-column rules.
  - For example, "an M flare within 30 min implies a ≥C flare within 30 min", or "the alert agrees with
    p ≥ threshold".
  - `lazy=True` collects all failures at once.
- **Fail-closed pipeline:** the stage command is `produce && check`. If the check fails, the stage fails and
  `dvc repro` stops.
- **`dvc commit` vs `dvc repro`:** adding a read-only check changed four stage commands, but not their outputs. We
  ran the checks on the existing outputs, then `dvc commit` recorded the new commands without recomputing anything.
  Only the 8 new dependency hashes were added (verified).
- **Orchestration:** flows are made of tasks with retries (e.g. `retries=3, retry_delay_seconds=[60, 300, 900]` for
  the NOAA download), logging and run history.
- **Frozen stages + window locks:** model and evaluation stages are `frozen: true`. `src/ops/locks.py` refuses any
  window after the development end, and `score_replay` also refuses the old test period.
  - Found while doing this: the dev2 and `evaluate_holdout2` stages were *not* frozen, so a plain `dvc repro` could
    have re-scored holdout2. Fixed, and tested.
- **Challenger vs champion:** retraining registers a *challenger*; only a human promotes it. The code asserts that the
  champion alias did not move.
- **Data drift:** a feature's distribution changes between a reference window and a current one.
  - Evidently picks a test per column: distance measures (Wasserstein) drift when the distance is ≥ the threshold;
    p-value tests (K-S) drift when p < the threshold.
  - Our first parser treated both the same way and undercounted (7 instead of 21); a test now checks agreement with
    Evidently's own count.

## Tools used
| Tool | What it did here | Most useful commands |
|---|---|---|
| GitHub Actions | runs lint + tests on every push | the Actions tab; `gh run list`, `gh run view --log` |
| ruff 0.17.5 | lint everywhere, format new code | `ruff check .`, `ruff format <paths>` |
| pre-commit 4.7 | runs ruff and basic checks before each commit | `pre-commit install`, `pre-commit run --all-files` |
| pandera 0.34 | data contracts | `python -m src.validation.check dataset` |
| Prefect 3.8.7 | flows, retries, run history | `prefect server start`, `python -m flows.check_drift` |
| Evidently 0.7.23 | drift report (HTML + JSON) | `python -m flows.check_drift` |

## Code walkthrough
- `src/validation/schemas.py`:
  - `_index_checks(step)` = UTC, unique, sorted, on the grid;
  - `dataset_schema(features, period)` builds the 57-column contract with nested-label checks;
  - `validate()` turns pandera's error table into a short report.
- `src/validation/check.py`: the command the DVC stages call; exit code 1 on a broken table.
- `src/ops/locks.py`: `check_window(start, end, kind)` is the single guard used by every flow.
- `src/ops/ingest.py`: `discover_days` (names only), `stages_to_run` (only unfrozen data stages).
- `src/ops/replay.py`: loads `models:/<name>@champion`, uses the version tag `thr_A`, validates, writes Parquet + SQLite
  (`INSERT OR REPLACE`, so replays are idempotent).
- `src/ops/retrain.py`: `register_challenger` snapshots the champion version before and after.
- `src/ops/drift.py`: `drift_report` reads Evidently's per-column results by method.

## Hands-on
1. `pytest -q -m "not data"`. *Expected:* all pass, 4 deselected. Compare with `pytest -q`.
2. `python -m src.validation.check solexs_minute`. *Expected:* `data contract OK: solexs_minute`.
3. `$env:PREFECT_HOME="$PWD\.prefect"; python -m flows.daily_ingest`. *Expected:* "new development days: none" and a
   warning listing the locked holdout2 days by name.
4. `python -m flows.check_drift`, then open `reports/drift/drift_20260814_20260913.html`. Which feature group drifts
   most, and why? (Hint: when is HEL1OS observing?)
5. `prefect server start`, set `$env:PREFECT_API_URL="http://127.0.0.1:4200/api"` in a second terminal, rerun
   exercise 3, and find the run in the UI.

## Break it on purpose
Copy `tests/fixtures/solexs_minute.parquet` to `D:\tmp`. Set one value of `m` to −5 with pandas, and run
`S.validate(df, S.SOLEXS_MINUTE)`: read the message. The original fixture is untouched, so there is nothing to undo.

## Check yourself
1. Why do CI tests use fixtures instead of the real dataset?
2. Why did we use `dvc commit` instead of `dvc repro` after adding the checks?
3. Why can `daily_ingest` list holdout2 day folders but never open them?
4. A K-S test returns p = 0.03 with threshold 0.05. Drift or not? And a Wasserstein distance of 0.03 with threshold 0.1?
5. Why does `retrain_candidate` register a challenger instead of replacing the champion?

<details><summary>Answers</summary>

1. The CI machine has no DVC cache or raw data, and tests must be fast and reproducible.
2. The outputs didn't change, only a read-only check was added. Re-running would mean hours of recompute, and
   downstream frozen stages would see changed inputs.
3. Folder names reveal nothing about labels or features. Reading the data would break the holdout lock.
4. K-S: drift (p < 0.05). Wasserstein: no drift (0.03 < 0.1).
5. A new model must first win a fresh one-time evaluation. Automatic promotion would let an unchecked model reach
   users.
</details>

## Questions to discuss with my tutor
- Should drift on HEL1OS features (which depend on when sessions happen) trigger anything, or be excluded?
- How strict should data contracts be on scientific data with known gaps (fail vs warn)?

## Key numbers to remember
- CI: 97 tests run, 6 skipped, 4 deselected (`data`) in a clean copy.
- Contracts: 5 tables, 4 DVC stages wired, 8 broken-sample tests.
- Drift (training block vs 2026-08-14 … 09-13): 21 of 44 features drifted (share 0.48, flag threshold 0.5).
