# Progress log

Newest entries at the bottom. Each entry: what was done, key numbers, decisions (with reasons), problems.

## Before this log (summary of commits 7c9339f … 07c7845)

- **Setup.** Scaffolding, git, venv. Rebuilt on Python 3.12 (3.14 had no `dvc` wheels). `params.yaml` and `CLAUDE.md`
  added. `antlr4-python3-runtime==4.9.3` was built locally from its pure-Python sdist (no PyPI wheel exists).
- **Ingestion.** SoLEXS SDD2 light curves plus GTI → 1 s Parquet per day and a 1-min grid. 452 day folders in the
  periods, 424 usable (≥ 50% valid). HEL1OS parser: 27 → 23 sessions after the newest-version rule; no date overlap
  with SoLEXS, so HEL1OS is optional everywhere.
- **Detection.** GOES-style detector (trailing quantile background, Poisson threshold, onset = sustained rise,
  end = halfway decay, frozen background, dip splitting, 3 h cap). Tuned on the tune period only (300-trial grid,
  MLflow). Tune: match rate 0.76, C+ recall 0.865, onset error median 1 / p90 10 min, 5 events > 2 h.
  Val: 0.76, 0.887, 1/9 min, 2 events > 2 h.
- **Labels/features.** Nowcast + ≥C/≥M forecasts at 30/60/120 min, with `ok` flags. 27 causal features at 10 s
  cadence. Rows: tune 1.94 M / val 0.82 M / test 0.79 M (118.5 / 49.3 / 47.1 MB).
- **DVC + tests.** 8 stages, hardlink cache on `D:/dvc-cache`, 28 tests including leakage tests.

## 2026-10-21 — Task 1: catch-up lessons 01–05

**Done**
- Wrote `docs/learn/01-setup.md`, `02-ingestion.md`, `03-detection.md`, `04-labels-features.md`,
  `05-dvc-and-tests.md`, and `docs/learn/INDEX.md`.
- Every quoted line and "expected output" was checked against the current code and data. The "break it"
  experiments of lessons 02, 04 and 05 were run and reverted to confirm their outcomes.
- `CLAUDE.md`: teaching-mode rules replaced by autonomous-build-mode rules (the two conflicted).

**Problem found and fixed: CRLF line endings broke DVC's change detection**
- *Symptom:* after `git checkout -- src/features.py` (while verifying lesson 04's experiment), `dvc status` reported
  `build_dataset` as changed, although the code was identical.
- *Cause:* `core.autocrlf=true` makes git write Windows CRLF endings on checkout. DVC hashes raw bytes, so the
  file's md5 no longer matched `dvc.lock`. 21 tracked text files had CRLF in the working copy.
- *Fix:* added `.gitattributes` (`* text=auto eol=lf`, binaries marked binary), normalised the 21 files to LF,
  `git add --renormalize .`, then `dvc commit -f` to record the new hashes. No content changed (verified with
  `git diff --cached --ignore-cr-at-eol`), so re-running stages was unnecessary. After the fix the lesson-05
  experiment (edit a param, `git checkout`) leaves `dvc status` clean.

**Decisions**
- *Lesson 03 is honest about MAD.* The task asked for "MAD noise", but the detector does not use MAD; it uses
  Poisson counting noise √(bg/60) plus relative and absolute floors. The lesson explains MAD as a concept and says
  clearly that the code doesn't use it.
- *No pipeline code changed*, so no stage re-run was needed; `dvc status` is clean after `dvc commit`.

**Key numbers:** 28 tests pass (3 s). `dvc status`: up to date. Free disk: C: 18 GB, D: 27 GB (D: dropped from
41 GB since 7 Oct; not caused by this project, which uses about 2 GB on D:).

**Oddity noted, not touched:** `D:\dvc-cache\1NPDPRO5.DOC` (55 KB, dated Sep 2025) is not a DVC file. It looks like
a user document that ended up in that folder. DVC ignores it.
