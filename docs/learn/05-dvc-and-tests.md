# Lesson 05 — DVC pipelines and tests: dvc.yaml, hardlink cache, dvc repro, the 28 tests, leakage tests, the AST check

## What we built

We described the whole data pipeline as 8 named stages in `dvc.yaml`. DVC can then rebuild everything with one
command, and it only re-runs the parts whose inputs changed. We also wrote 28 automatic tests (pytest). They check
the readers, the detector, and above all that no future information leaks into features or labels. One of these
tests reads the *structure* of the code (its AST) to forbid centered windows.

## Why it matters

Think of a factory assembly line with stations: cut → weld → paint → pack. If you change the paint colour, you
don't re-cut and re-weld every car; you re-run painting and packing only. DVC is the line manager. It knows which
station needs which inputs, notices what changed, and re-runs only what's necessary. The tests are the quality
inspectors at the end of the line. They reject any car with a known defect before it ships, so a bug you fixed
once can't silently come back.

## Concepts

**Pipeline / stage.** A pipeline is a chain of steps. Each *stage* has three parts:
- a **command** to run
- **dependencies (deps):** the files and params it reads
- **outputs (outs):** the files it writes

The output of one stage is the dependency of the next, which creates a **DAG** (directed acyclic graph): a map of
arrows with no loops.

**Hash (md5).** A short fingerprint computed from a file's bytes, like `69bf6fb3...`. If one byte changes, the
fingerprint changes. DVC stores the fingerprint of every dep and out in `dvc.lock`. Next time, it recomputes the
fingerprints, and any mismatch means "this changed".

**`dvc.lock`.** DVC's memory of the last successful run: the exact hashes and param values used. It's committed
to git, so the git history also records which data version went with which code.

**Content-addressed cache.** DVC stores each output in `D:\dvc-cache\files\md5\<first 2 hex>\<rest of hash>`.
The file's name *is* its hash. Identical content is stored once, and old versions stay in the cache, so
`git checkout <old commit>` followed by `dvc checkout` brings back old data.

**Hardlink.** Two directory entries that point to the *same* bytes on disk. `data\processed\events.parquet` and
its copy in the cache are one file with two names, so 500 MB of outputs cost 500 MB, not 1 GB. The catch: editing
one name edits both, and corrupts the cache. So DVC makes outputs **read-only**, and our pipeline deletes an
output before writing a new one (the `_fresh()` helper).

**Line endings (CRLF vs LF).** Windows text files end lines with `\r\n` (CRLF); Linux uses `\n` (LF). Git on
Windows (`core.autocrlf=true`) can rewrite these on checkout. DVC hashes raw bytes, so a rewrite looks like a code
change and stages re-run for no reason. We hit this while writing this lesson. The fix is `.gitattributes` with
`* text=auto eol=lf`, which keeps LF everywhere.

**Unit test.** A small function that runs a piece of code on a known input and checks the output with `assert`.
`pytest` finds every `test_*.py` file and every `test_*` function and runs them.

**Synthetic data.** Fake data built so we *know* the right answer, for example a flare injected at exactly minute
600. Real data never tells you the true onset; synthetic data does.

**Leakage test.** A test that proves the model can't see the future, for example by changing the future and
checking that nothing in the past changes.

**AST (Abstract Syntax Tree).** Python can read source code and turn it into a tree of pieces: function calls,
arguments, numbers. Searching the *tree* instead of the *text* means a comment that mentions `center=True` isn't
mistaken for real code. (That exact false alarm happened in our first version of the test.)

## Tools used

| Tool | What it is | What it did here | Most useful commands |
|---|---|---|---|
| **DVC** | Data Version Control: pipelines plus versioned data, on top of git | Runs and caches our 8 stages | `dvc repro`, `dvc status`, `dvc dag`, `dvc params diff`, `dvc commit`, `dvc checkout` |
| **pytest** | Python test runner | Runs the 28 tests | `pytest -q`, `pytest -v`, `pytest -k leakage`, `pytest tests/test_detector.py -x`, `pytest --collect-only -q` |
| **ast** | Python's built-in code parser | Inspects `src/features.py` for forbidden patterns | `ast.parse(src)`, `ast.walk(tree)` |
| **inspect** | Python's built-in introspection | Gets a module's source text for the AST check | `inspect.getsource(module)` |
| **.gitattributes** | Per-file git settings | Forces LF line endings | `* text=auto eol=lf` |

## Code walkthrough

### `dvc.yaml` (one stage shown)

```yaml
  detect_events:
    cmd: python -m src.pipeline detect_events          # (1)
    deps:
      - src/detection/detector.py                      # (2)
      - src/pipeline.py
      - data/processed/solexs_minute.parquet           # (3)
    params:
      - flare_detection                                # (4)
      - periods
    outs:
      - data/processed/events_raw.parquet              # (5)
```
1. What to run. It uses plain `python`, so the venv must be active.
2. If the detector code changes, this stage re-runs.
3. The output of `solexs_clean` is an input here; that arrow is part of the DAG.
4. Only the `flare_detection` and `periods` sections of params.yaml matter here. Editing `evaluation:` does *not*
   re-run this stage.
5. Stored in the cache and hardlinked.

All 8 stages:
- `fetch_goes` → `solexs_clean` → `detect_events` / `legacy_events` → `match_goes` → `evaluate_detector` and `build_dataset`
- `hel1os_index` stands alone, because HEL1OS is optional
- `metrics:` entries with `cache: false` (`reports/*.json`) are kept in git instead of the cache, so you can diff them

### `src/pipeline.py` — the hardlink guard

```python
def _fresh(path: Path) -> Path:
    if path.exists():
        path.chmod(0o666)     # outputs are read-only hardlinks: make writable...
        path.unlink()         # ...then delete this name only (the cache copy is untouched)
    return path
...
    ev.to_parquet(_fresh(_p("events_raw.parquet")))
```
Deleting the name and writing a *new* file means the cached object is never modified.

### `tests/test_leakage.py`

```python
@pytest.mark.parametrize("cut_h", [1.5, 4.05, 4.2])                          # line 29
def test_features_unchanged_when_future_is_altered(cut_h):
    altered[fut] = altered[fut] * 7.0 + 1000.0  # wildly different future    # line 35
    a, b = _features(c), _features(altered)
    rows = a.index <= t_cut
    pd.testing.assert_frame_equal(a[rows], b[rows])                          # line 38
    assert not a[~rows].equals(b[~rows])                                     # line 39
```
- **Line 29:** run the same test three times: before, during and after an injected flare.
- **Line 35:** replace the future with nonsense.
- **Line 38:** every feature row up to the cut must be *bit-for-bit identical*. If any feature peeked ahead, this fails.
- **Line 39:** a sanity check that the change is visible after the cut. Without it the test could pass because
  nothing was computed at all.

```python
    tree = ast.parse(inspect.getsource(features))                            # line 53
    for node in ast.walk(tree):                                              # line 54
        if isinstance(node, ast.Call):                                       # line 55
            for kw in node.keywords:
                assert not (kw.arg == "center" and isinstance(kw.value, ast.Constant) and kw.value.value is True)   # line 57
            if isinstance(node.func, ast.Attribute) and node.func.attr == "shift" and node.args:   # line 58
                a = node.args[0]
                assert not (isinstance(a, ast.UnaryOp) and isinstance(a.op, ast.USub)), "negative shift = future data"   # line 60
```
- **Line 53:** turn `src/features.py` into a tree.
- **Line 54:** visit every node.
- **Line 55:** look only at function calls.
- **Line 57:** fail if any call passes the keyword `center=True`.
- **Line 58:** find calls to `.shift(...)`.
- **Line 60:** fail if the argument is negative (`shift(-5)` reads 5 rows in the future).

Docstrings are strings, not calls, so they're ignored.

### The 28 tests at a glance

| File | Tests | What they protect |
|---|---|---|
| `test_pipeline.py` | 6 | Unix time conversion, GOES text parser (only XRA lines, flares across midnight), unit-safe GTI mask, class only from the GOES match, HEL1OS newest-version rule, HEL1OS optional |
| `test_detector.py` | 7 | onset within 1 min over 20 noise seeds, halfway-decay end, frozen background, causal trigger, dip splitting, 3 h cap, no events in pure noise |
| `test_leakage.py` | 15 (13 functions, one run 3×) | future-perturbation test, right-closed bins, AST check, no label columns among features, labels strictly after t, unmatched never positive, class thresholds, nowcast window, no label across period end, ok flags, chronological periods, tuner reads tune only, built files chronological |

## Hands-on

Activate the venv and work from the project folder.

**1. See the pipeline map.**
```
dvc dag
dvc status
```
*Expected:* a box drawing with `solexs_clean` at the top, arrows down to `detect_events`, `legacy_events`,
`match_goes`, `evaluate_detector` and `build_dataset`, and `hel1os_index` on its own. `dvc status` prints
`Data and pipelines are up to date.`

**2. Read DVC's memory.** Open `dvc.lock` in an editor and find the `detect_events:` block.
*Expected:* `md5` hashes for each dep and out, plus a copy of the `flare_detection` param values that were used,
including `min_excess_abs: 12.0`. *Worked if* you can say which hash would change if you edited `detector.py`.

**3. Prove the hardlink.**
```
python -c "import os; print(os.stat('data/processed/events.parquet').st_nlink)"
```
*Expected:* `2`, one name in `data\processed` and one in `D:\dvc-cache`. Then try to save a change to that file
in an editor: it's read-only.

**4. Run and explore the tests.**
```
pytest --collect-only -q | Select-Object -Last 3
pytest -q
pytest -v -k leakage
```
*Expected:* `28 tests collected`, then `28 passed`, then the 15 leakage tests listed one by one, all `PASSED`.

**5. Run one test in isolation and read it.**
```
pytest tests/test_detector.py::test_background_is_frozen_during_event -v
```
*Expected:* `1 passed`. Now read the test and explain in one sentence why `pytest.approx(20.0, rel=0.15)` is the right check.

## Break it on purpose

Change one parameter and watch DVC re-run only what depends on it.

1. In `params.yaml`, change `size_cut_counts_s: 50` to `size_cut_counts_s: 60` (under `evaluation:`).
2. Run `dvc status`. *Expected:* only `evaluate_detector` is listed, with `params.yaml: modified: evaluation`.
   Detection and the dataset don't use this parameter.
3. Optional: run `dvc repro`. *Expected:* `Stage 'detect_events' didn't change, skipping` (and the same for the
   others), and only `Running stage 'evaluate_detector'`. Then `git diff reports/detection_metrics.json` shows
   `size_cut_counts_s` and `precision_above_cut` changed.
4. Undo: `git checkout -- params.yaml`. If you ran step 3, also run `git checkout -- reports docs/figures` and
   `dvc repro` again. Finish with `dvc status` → `Data and pipelines are up to date.`

## Check yourself

1. You edit only `src/detection/plots.py`. Which stages will `dvc repro` run, and why only those?
2. What is stored in `dvc.lock`, and why is it committed to git?
3. Why does DVC make outputs read-only, and what would go wrong if our code wrote into `events.parquet` in place?
4. Why was the CRLF/LF line-ending problem a *DVC* problem and not just a git annoyance?
5. Why does the AST check catch `rolling(5, center=True)` but not the words "center=True" in a docstring?

## Questions to discuss with my tutor

1. Our raw data on `D:\MLOPS_CP` is *not* tracked by DVC (stages read it through params). What are the pros and
   cons of `dvc add`-ing 9.5 GB of raw data, or using `dvc import-url`/external dependencies?
2. Detector tuning is deliberately *not* a DVC stage (it writes to params.yaml, which would create a loop). How do
   tools like `dvc exp run` or MLflow handle hyperparameter search inside a pipeline?
3. Leakage tests check our *code*. What leakage could still happen that no unit test here would catch (for example
   in model selection, or by reading the test-period results)?

## Key numbers

| What | Value |
|---|---|
| DVC stages | 8 (`hel1os_index` is independent) |
| Full `dvc repro` time | about 10 minutes (most of it the GOES download and cleaning 424 days) |
| Cache location and type | `D:/dvc-cache`, hardlink then symlink |
| Processed outputs | about 500 MB (stored once thanks to hardlinks) |
| Tests | 28: pipeline 6, detector 7, leakage 15 |
| Test run time | about 3 seconds |
| Line-ending fix | `.gitattributes` `* text=auto eol=lf`, then `dvc commit -f` (21 files normalised, no content change) |

---

<details>
<summary><b>Answers (spoiler — try first!)</b></summary>

1. Only `evaluate_detector`, because it's the only stage that lists `plots.py` as a dependency. Every other
   stage's deps and params are unchanged.
2. The hashes of every dependency and output and the param values used in the last successful run. Committing it
   ties each code version to the exact data version it produced, so the history is reproducible.
3. Outputs are hardlinks to the cached object: the same bytes. Writing in place would silently change the cached
   version too, breaking `dvc checkout` of that version. Read-only plus "delete then write" prevents this.
4. DVC decides what to re-run by hashing bytes. A CRLF rewrite changes the bytes (and the hash) without changing
   the meaning, so DVC re-runs or flags stages that didn't really change.
5. In the AST, `center=True` written inside a function call becomes a *keyword-argument node* belonging to that call,
   which is exactly what the test looks for. A docstring is a single string-constant node; the words inside it are
   never parsed as code, so the check doesn't see them.

</details>
