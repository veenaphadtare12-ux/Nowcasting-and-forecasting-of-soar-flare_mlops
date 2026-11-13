# Holdout2 lock

*Locked at **2026-11-13 05:03:46 UTC**, before any holdout2 feature or label existed and before any model saw these days.*

- Holdout2 = 2026-09-13 .. 2026-11-12 (UTC days). Usable SoLEXS days: **11** (2026-09-13, 2026-10-30, 2026-10-31, 2026-11-01, 2026-11-02, 2026-11-05, 2026-11-06, 2026-11-07, 2026-11-08, 2026-11-09, 2026-11-10).
- GOES flares on usable days: {'B': 33, 'C': 118, 'M': 7}; ≥M: **7** (< 15: every M result on holdout2 is **UNDERPOWERED**).
- Rules: holdout2 features and labels are built and opened only by the final DVC stage `evaluate_holdout2`, and only after `docs/FINAL_CHOICE_2.md` is committed. `tests/test_holdout2_lock.py` checks the code; the checksums below let anyone verify the files did not change.

| Group | Files | Bytes | SHA-256 of the concatenated file hashes |
|---|---|---|---|
| SoLEXS day folders (raw L1) | 44 | 66,728,944 | `5841c6f2e2c7e48eb1ff4f42b03de163dd3af4c3f4268149727cf1833f80d288` |
| HEL1OS sessions (extracted light curves + aux) | 264 | 1,181,315,832 | `2a62926e27916b30154c03b0731c941b46aadf42ddcc33d6de8401c3cb2692eb` |
| Original download bundles | 3 | 1,601,580,220 | `0ca0d4221c186c540c6ecd50e74dd42aaec65d0ad4b31b02acd240d07248cd01` |
| NOAA files (GOES events, GOES-19 XRS, SRS) | 183 | 18,156,234 | `c5bef1900e2b810338c12695a3f43b6e1e667c74ed84a3230f678ac909c1ad40` |

Full per-file list: `reports/holdout2/lock_sha256.txt` (`sha256sum -c` compatible). Verify with `python -m src.holdout2.ingest verify`.
