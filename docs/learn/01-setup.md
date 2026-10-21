# Lesson 01 — Project setup: venv, Python 3.12, git, requirements.txt, CLAUDE.md, params.yaml

## What we built

We made a clean, repeatable "workbench" for the project. That means a private copy of Python 3.12 with exactly
the libraries we need, a git history that records every change, and two plain-text files. `params.yaml` holds
every setting; `CLAUDE.md` holds the rules everyone (including the AI assistant) must follow.

## Why it matters

Imagine baking a cake from a recipe that just says "some flour, some sugar, bake until done". Every cake comes
out different and nobody can repeat your best one. MLOps starts by turning the recipe into an exact one: the same
oven (Python version), the same ingredient brands (pinned library versions), the same quantities (params.yaml),
written house rules (CLAUDE.md), and a notebook of every change you made (git). Then anyone, including you in
three months, can bake the same cake.

What actually went wrong for us, and why the setup fixed it:

- **First attempt failed.** The first venv was made with the MSYS2/Git-Bash Python. PyPI had no ready-made
  packages ("wheels") for it, so pip tried to compile numpy and astropy from source and died on SSL errors.
- **Python 3.14 was too new.** The second venv used Windows Python 3.14, but `dvc` could not be installed on it.
- **Python 3.12 worked.** We rebuilt the venv on Python 3.12 (a mature version) and everything installed from wheels.

## Concepts

**Interpreter.** The program that runs your `.py` files (`python.exe`). Different versions (3.12, 3.14) can
behave differently and support different libraries.

**Virtual environment (venv).** A folder (`.venv/`) containing its own Python and its own installed libraries.
Installing a library inside it does not touch any other project. "Activating" the venv just puts its
`Scripts\` folder first on your PATH, so typing `python` runs the venv's Python.

**Package / wheel / source distribution.**
- A *package* is a library you install with `pip` (for example pandas).
- A *wheel* (`.whl`) is a pre-built, ready-to-copy package: fast, nothing to compile.
- A *source distribution* (`.tar.gz`) must be built on your machine. That may need a C compiler, which is why it failed for us.

**Pinning.** Writing exact versions (`pandas==3.0.6`) instead of just `pandas`, so a future install gets the same
code. `pip freeze` prints every installed package with its exact version.

**Version control (git).** A tool that stores snapshots ("commits") of your files with a message, so you can see
what changed, when, and why, and go back if needed. `.gitignore` lists files git should not track (the venv, big
data, caches).

**Configuration file.** A file of settings separate from code. Our code never contains a path or a date; it asks
`params.yaml`. Changing a setting then means editing one line, and the change is visible in git.

**Data periods.** Our data is a time series, so we split it by time, never randomly:
- **tune:** 2025-04-09 to 2026-01-31. We tune and train here.
- **val:** 2026-02-01 to 2026-05-31. An honest check; we never tune on it.
- **test:** 2026-06-01 to 2026-09-12. Locked away until the very end.

## Tools used

| Tool | What it is | What it did here | Most useful commands |
|---|---|---|---|
| **Python 3.12** | The language interpreter | Runs all our code | `py -0p` (list installed Pythons), `py -3.12 --version` |
| **venv** | Built-in Python module for isolated environments | Created `.venv/` | `py -3.12 -m venv .venv`, `.venv\Scripts\Activate.ps1`, `deactivate` |
| **pip** | Python's package installer | Installed ~280 pinned packages | `pip install -r requirements.txt`, `pip freeze > requirements.txt`, `pip check`, `pip show <pkg>` |
| **git** | Version control | Records every change (9 commits once these lessons are committed) | `git status`, `git log --oneline`, `git diff`, `git add <file>`, `git commit -m "msg"` |
| **PyYAML** | Reads `.yaml` files into Python dicts | Loads `params.yaml` | `yaml.safe_load(f)` |

## Walkthrough of the code

### `params.yaml` (the single place for settings)

```yaml
paths:
  data_root_solexs: "D:/MLOPS_CP/Data/SoLEXS"      # (1)
  processed_dir: "data/processed"                   # (2)
  mlflow_tracking_uri: "sqlite:///mlflow.db"        # (3)
periods:
  tune: {start: "2025-04-09", end: "2026-01-31"}    # (4)
  val:  {start: "2026-02-01", end: "2026-05-31"}
  test: {start: "2026-06-01", end: "2026-09-12"}
```

1. Where the raw data lives. It stays on D: and is never copied into the project.
2. A *relative* path: relative to the project folder.
3. Where MLflow stores experiment results (lesson 03).
4. The three time periods. Every stage reads them from here.

### `src/config.py` (the only code that reads params.yaml)

```python
PROJECT_ROOT = Path(__file__).resolve().parents[1]          # line 9
PARAMS_FILE = PROJECT_ROOT / "params.yaml"                  # line 10

@lru_cache(maxsize=1)                                        # line 13
def load_params(path: str | None = None) -> dict:
    with open(path or PARAMS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)                             # line 16

def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else PROJECT_ROOT / path   # line 22
```

- **Line 9:** `__file__` is this file (`src/config.py`), and `.parents[1]` goes up two levels to the project
  folder. So the code finds params.yaml wherever the project is copied to.
- **Line 13:** `@lru_cache` remembers the result, so params.yaml is read once, not every time it is needed.
- **Line 16:** `yaml.safe_load` turns the YAML text into a normal Python dictionary. *Safe* means it will not run
  code hidden in the file.
- **Line 22:** absolute paths (like `D:/...`) are used as they are; relative ones are joined to the project folder.

```python
def period_bounds(name: str) -> tuple[pd.Timestamp, pd.Timestamp]:          # line 47
    p = load_params()["periods"][name]
    return pd.Timestamp(p["start"], tz="UTC"), pd.Timestamp(p["end"], tz="UTC") + pd.Timedelta(days=1)

def validate_periods() -> None:                                              # line 68
    ...
        assert hi <= lo, "periods overlap or are out of chronological order"  # line 74
```

- **Line 47 onward:** returns `[start, end)`. The end is *the day after* the last day, so "less than end" includes
  the whole last day. `tz="UTC"` matters: all our times are in UTC, never local time.
- **Line 74:** a safety check. If someone edits params.yaml so val starts before tune ends, the code stops.

### `requirements.txt` and `.gitignore`

```
astropy==8.0.1
dvc==3.67.1
mlflow==3.16.1
pandas==3.0.6
```

These are 4 of the 284 pinned lines produced by `pip freeze`.

```
.venv/
data/processed/
mlflow.db
```

Git ignores these. The venv can be rebuilt from requirements.txt, processed data is managed by DVC (lesson 05),
and mlflow.db is a local database.

### `CLAUDE.md`

This is a plain-English rulebook at the project root. It holds the seven permanent rules (chronological splits,
causal features, labels after the window, TSS/HSS metrics, raw data read-only, MLflow logging, folder layout),
verified facts about the data, and the "autonomous build mode" rules that say how the remaining work is done
(one task at a time, test + commit + progress note + lesson after each).

## Hands-on

Do these yourself in PowerShell, from `D:\projects\solar-flare-project`.

**1. Find your Pythons and activate the venv.**
```
py -0p
.venv\Scripts\Activate.ps1
python --version
```
*Expected:* a list including `-V:3.12`, then your prompt starts with `(.venv)`, then `Python 3.12.10`.
*If activation is refused* ("running scripts is disabled"), run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use `cmd` with `.venv\Scripts\activate.bat`.

**2. Prove the venv is isolated.**
```
where.exe python
python -c "import sys; print(sys.prefix)"
```
*Expected:* the first `python` listed is inside `...\solar-flare-project\.venv\Scripts\`, and `sys.prefix` ends in `.venv`.
*Worked if* the path points into `.venv`, not `AppData\Local\Programs\Python`.

**3. Check the pinned packages are consistent.**
```
pip check
pip show pandas
```
*Expected:* `No broken requirements found.` and `Version: 3.0.6`.

**4. Read the git history.**
```
git log --oneline
git show --stat HEAD~1
```
*Expected:* at least 9 commits, newest first. Near the top you will see the commit that adds these lessons and `b61ab00 Switch CLAUDE.md to autonomous build mode rules`; the bottom one is `7c9339f Initial project scaffolding`. `--stat` lists which files a commit touched.

**5. Use the config from Python.**
```
python -c "from src import config; print(config.period_bounds('val')); print(config.solexs_root())"
```
*Expected:* `(Timestamp('2026-02-01 00:00:00+0000', tz='UTC'), Timestamp('2026-06-01 00:00:00+0000', tz='UTC'))`
and `D:\MLOPS_CP\Data\SoLEXS`. Notice the val end shown is 06-01, the day after 05-31, because the interval is `[start, end)`.

## Break it on purpose

Make the periods overlap and watch the safety check fire.

1. In `params.yaml`, change `val: {start: "2026-02-01", ...}` to `val: {start: "2026-01-15", ...}`.
2. Run: `python -c "from src import config; config.validate_periods()"`
3. *Expected:* `AssertionError: periods overlap or are out of chronological order`.
4. Undo it: `git checkout -- params.yaml`, then run step 2 again. It now prints nothing (success is silent).
5. Confirm with `git status` that params.yaml is no longer modified.

## Check yourself

1. Why did installing numpy fail in the very first venv, even though the internet worked?
2. What is the difference between a wheel and a source distribution?
3. Why is `.venv/` in `.gitignore`, and how does a teammate get the same libraries?
4. In `period_bounds`, why is one day added to the end date?
5. Why does no file in `src/` contain the string `D:/MLOPS_CP` directly?

## Questions to discuss with my tutor

1. Pinning every version with `pip freeze` makes installs repeatable but can trap you on old, insecure versions.
   How do real teams balance reproducibility against updates (for example lock files, Dependabot, or `pip-tools`)?
2. Our `requirements.txt` contains Windows-only packages (`pywin32`). How should a cross-platform project handle
   operating-system-specific dependencies?
3. Is a YAML config file enough for a real system, or when would you need environment variables, secrets
   managers, or a config library like Hydra?

## Key numbers

| What | Value |
|---|---|
| Python version | 3.12.10 |
| Pinned packages in requirements.txt | 284 |
| Package that needed a local build | `antlr4-python3-runtime==4.9.3` (pure Python, no compiler) |
| tune period | 2025-04-09 to 2026-01-31 |
| val period | 2026-02-01 to 2026-05-31 |
| test period | 2026-06-01 to 2026-09-12 |
| Project location | `D:\projects\solar-flare-project` (moved out of OneDrive) |

---

<details>
<summary><b>Answers (spoiler — try first!)</b></summary>

1. It was the MSYS2/Git-Bash Python build. PyPI has no ready-made wheels for it, so pip had to compile numpy
   from source. The build then needed to download extra build tools and failed on SSL certificate errors.
2. A wheel is pre-built and only needs copying. A source distribution has to be built on your machine, which may
   need a compiler.
3. The venv is large (about 1.2 GB) and tied to one machine's paths. A teammate creates their own with
   `py -3.12 -m venv .venv` and `pip install -r requirements.txt`.
4. The function returns a half-open interval `[start, end)`. Using "less than the next day" includes every second
   of the last day without having to write 23:59:59.
5. All paths come from `params.yaml` through `src/config.py`. Moving the data then means editing one line, not
   hunting through code.

</details>
