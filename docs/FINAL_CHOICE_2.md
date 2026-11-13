# Final choice 2 — frozen before holdout2 is opened

*Written 2026-11-13 07:06 UTC. Committed before any code built a holdout2 feature or label (`src/holdout2/evaluate.py` refuses to run otherwise and checks the model hashes in section 6). Nothing here may change after the holdout2 results are seen; any later change must be a new, dated section. Machine-readable: `params.yaml` → `dev2.final`, `reports/dev2/choice.json`, `reports/dev2/final_freeze.json`.*

## 1. How the choice was made

Evidence: the 14-month rolling protocol (2025-08 … 2026-09; the old test months are ordinary development data and their old test scores were not used). Acceptance rule unchanged from `docs/IMPROVEMENTS.md`: mean monthly TSS up AND at least 9 of 14 months better (the same 60 % share as 6 of 10). Rule per target (`src/dev2/choose.py`, written before any development-2 result was read):

1. Learner = the reference learner (LogReg / XGBoost) with the higher mean monthly TSS.
2. Aditya-only candidates, each against the reference with the same learner: R2 primary (own detector events), R3 stacked pretrained score, and the FINAL_CHOICE.md feature sets (c_30m E2+E3+E5 ensemble, m_30m E5). The KEPT candidate with the highest mean monthly TSS wins; none kept → base 44 features.
3. GOES-derived inputs only if they pass the rule on their own (E6 vs reference, R2 secondary vs R2 primary, m_30m E5+E6 vs E5). Then the champion is the `with_goes` variant; otherwise `aditya`.
4. R1: per input variant, the learner with the higher pooled per-trigger ≥M TSS averaged over k.

## 2. Chosen model per target

| Target | Learner | Champion inputs | Idea adopted | Reference: mean monthly / pooled / worst month | Aditya-only candidates (mean, months better, decision) | GOES-derived tests on their own |
|---|---|---|---|---|---|---|
| now | xgb | base 44 (Aditya-only) | base | 0.719 / 0.722 / 0.641 (2025-08) | – | – |
| c_30m | ensemble | long + drift + spectral (Aditya-only) | champ_c30 | 0.168 / 0.194 / -0.003 (2025-09) | champ_c30: 0.218, 13/14, KEPT | – |
| c_60m | xgb | base 44 (Aditya-only) | base | 0.214 / 0.229 / 0.029 (2025-09) | r2a: 0.158, 3/14, DROPPED; r3_stack: 0.212, 7/14, DROPPED | e6: 0.214 → 0.184, 3/14, DROPPED; r2b_vs_r2a: 0.158 → 0.167, 8/14, DROPPED |
| c_120m | xgb | base 44 (Aditya-only) | base | 0.222 / 0.239 / 0.006 (2025-09) | r2a: 0.161, 3/14, DROPPED; r3_stack: 0.208, 6/14, DROPPED | e6: 0.222 → 0.216, 8/14, DROPPED; r2b_vs_r2a: 0.161 → 0.180, 8/14, DROPPED |
| m_30m | logreg | base 44 (Aditya-only) | base | 0.240 / 0.387 / -0.137 (2026-09) | champ_m30_E5: 0.284, 8/14, DROPPED | e6: 0.240 → 0.248, 8/14, DROPPED; m30_E6_vs_E5: 0.284 → 0.281, 5/14, DROPPED |
| m_60m | logreg | base 44 (Aditya-only) | base | 0.242 / 0.409 / -0.070 (2026-09) | r2a: 0.165, 6/14, DROPPED; r3_stack: 0.233, 6/14, DROPPED | e6: 0.242 → 0.230, 6/14, DROPPED; r2b_vs_r2a: 0.165 → 0.116, 6/14, DROPPED |
| m_120m | xgb | base 44 (Aditya-only) | base | 0.233 / 0.359 / -0.079 (2026-03) | r2a: 0.189, 7/14, DROPPED; r3_stack: 0.226, 5/14, DROPPED | e6: 0.233 → 0.211, 6/14, DROPPED; r2b_vs_r2a: 0.189 → 0.142, 6/14, DROPPED |

Near misses (mean up, too few months): m_30m champ_m30_E5: 0.240 → 0.284, 8/14 (needs 9). Under a literal "6 months" count they would have passed; the 60 % share was fixed in params.yaml before any development-2 result existed, and is kept.

Blocks: base 44 = SoLEXS + HEL1OS features; ax = own detector events 24/48/72 h (R2 primary); long / drift / spectral = E2 / E3 / E5; goes = GOES XRS flux (E6); gc = GOES flare counts (known from end + 24 h); srs = NOAA SRS.

Both input variants are frozen for every target, so each holdout2 result is shown with and without GOES:

| Target | `aditya` inputs | `with_goes` inputs | Champion |
|---|---|---|---|
| now | base 44 | base 44 + goes | aditya |
| c_30m | long + drift + spectral | base 44 + long + drift + spectral + goes | aditya |
| c_60m | base 44 | base 44 + goes + gc + srs | aditya |
| c_120m | base 44 | base 44 + goes + gc + srs | aditya |
| m_30m | base 44 | base 44 + goes | aditya |
| m_60m | base 44 | base 44 + goes + gc + srs | aditya |
| m_120m | base 44 | base 44 + goes + gc + srs | aditya |

## 3. Frozen training, calibration and thresholds

- Fit: development rows before 2026-08-01 minus 120 min (every 6th 10-s row, seed 42).
- Calibration (isotonic on the raw score): 2026-08-01 … 2026-09-01 minus 120 min.
- Thresholds on the raw score: 2026-09-01 … 2026-09-12 minus 120 min. A = max TSS. M targets also C = lowest threshold with FAR ≤ 0.8, and K = minimum cost with a missed positive row costing 10 false-alarm rows (sensitivity K5, K20). Baselines (rule, current flux) get thresholds from the same block; persistence alerts while a flare is in progress.

| Target | Variant | Features | Fit rows (pos) | Calibration rows (pos) | Threshold rows (pos) | Threshold-block TSS at A | A | C | K10 |
|---|---|---|---|---|---|---|---|---|---|
| now | aditya | 44 | 536,372 (42,835) | 214,367 (12,384) | 102,960 (5,220) | 0.816 | 0.2804 | – | – |
| now | with_goes | 50 | 536,372 (42,835) | 214,367 (12,384) | 102,960 (5,220) | 0.812 | 0.2917 | – | – |
| c_30m | aditya | 67 | 533,821 (72,915) | 213,896 (20,988) | 102,960 (7,446) | 0.294 | 0.2863 | – | – |
| c_30m | with_goes | 73 | 533,821 (72,915) | 213,896 (20,988) | 102,960 (7,446) | 0.309 | 0.2923 | – | – |
| c_60m | aditya | 44 | 531,239 (130,329) | 213,410 (37,572) | 102,960 (14,448) | 0.259 | 0.2912 | – | – |
| c_60m | with_goes | 66 | 531,239 (130,329) | 213,410 (37,572) | 102,960 (14,448) | 0.294 | 0.2814 | – | – |
| c_120m | aditya | 44 | 526,277 (210,047) | 212,438 (61,134) | 102,960 (26,478) | 0.274 | 0.3282 | – | – |
| c_120m | with_goes | 66 | 526,277 (210,047) | 212,438 (61,134) | 102,960 (26,478) | 0.277 | 0.3029 | – | – |
| m_30m | aditya | 44 | 533,821 (8,822) | 213,896 (1,980) | 102,960 (540) | 0.121 | 0.03927 | inf | inf |
| m_30m | with_goes | 50 | 533,821 (8,822) | 213,896 (1,980) | 102,960 (540) | 0.146 | 0.05714 | inf | inf |
| m_60m | aditya | 44 | 531,239 (16,579) | 213,410 (3,942) | 102,960 (1,080) | 0.156 | 0.05398 | inf | inf |
| m_60m | with_goes | 66 | 531,239 (16,579) | 213,410 (3,942) | 102,960 (1,080) | 0.157 | 0.3544 | inf | inf |
| m_120m | aditya | 44 | 526,277 (30,066) | 212,438 (7,542) | 102,960 (2,160) | 0.368 | 0.05834 | inf | inf |
| m_120m | with_goes | 66 | 526,277 (30,066) | 212,438 (7,542) | 102,960 (2,160) | 0.346 | 0.1383 | inf | inf |

**R1 (early class prediction).** Learner per input variant: aditya → logreg, with_goes → logreg. Fit on detections whose end was known before 2026-08-01 minus 120 min (2893 triggers, 306 ≥M); thresholds (max TSS, ≥M and ≥C) on the 182 triggers of 2026-08-01 … 2026-09-12 (15 ≥M).

## 4. What will be reported from holdout2 (decided now)

Holdout2: 11 usable days (2026-09-13, 2026-10-30, 2026-10-31, 2026-11-01, 2026-11-02, 2026-11-05, 2026-11-06, 2026-11-07, 2026-11-08, 2026-11-09, 2026-11-10); GOES flares on them: {'B': 33, 'C': 118, 'M': 7}. **7 ≥M flares < 15: every M result is UNDERPOWERED and no claim is made from it.**

Headline metrics, for every target (champion variant first, then the other one = with / without GOES):

1. TSS at operating point A pooled over all holdout2 rows, with a 95 % day-bootstrap interval (1,000 resamples, seed 0).
2. Per-month table: TSS at A for 2026-09 (1 day), 2026-10 (2 days), 2026-11 (8 days), with positives per month.
3. TSS at A on quiet-start rows, and on active vs quiet days (active = a GOES ≥M flare ended in the 72 h before the day).
4. Baselines at their own frozen thresholds: climatology (TSS 0), persistence, the 1-feature rule, current flux level.
5. M targets (UNDERPOWERED): POD, FAR and TSS at C (FAR ≤ 0.80) and K10 (cost), plus K5 / K20.
6. Calibration: Brier score raw vs isotonic vs climatology.
7. R1 per k ∈ {0, 1, 2, 3, 5} and input variant: per-trigger TSS, precision, recall for ≥M and ≥C; the 3-class confusion (<C, C, ≥M); lead time to NOAA's M1 crossing (median, share before it) for true ≥M alerts; the current-flux baseline.

No threshold, model or feature is changed after these numbers are seen.

## 5. Expected weaknesses, stated in advance

- **Holdout2 is tiny and patchy:** 11 days in two clusters (2026-09-13; 2026-10-30 … 11-10 without 11-03/04). Intervals will be wide; the per-month table has 1, 2 and 8 days.
- **M results are underpowered** (7 ≥M flares on 3 days). The 12-day threshold block holds only a few ≥M flares, so the M thresholds are noisy.
- **After the 46-day gap** before 2026-10-30, long-window features (24 h context, 72 h event counts, 7-day drift medians) start without history on the first day.
- **Operating points that never alert:** on the threshold block no threshold reaches FAR ≤ 0.80, and never alerting is the cheapest cost choice, for: m_120m C, m_120m K10, m_120m K20, m_120m K5, m_30m C, m_30m K10, m_30m K20, m_30m K5, m_60m C, m_60m K10, m_60m K20, m_60m K5 (both variants). They will show POD 0 on holdout2; this is known now and is not a result.
- NOAA may still revise the most recent GOES event lists; the versions downloaded at the lock are used.

## 6. Frozen files (SHA-256, checked by the holdout2 stage)

| File | SHA-256 |
|---|---|
| `models_final2/c_120m_aditya.joblib` | `c6ea6aa811b224611cb383e81a9e411e2fa0e6933528370d42ea4c77b89547a2` |
| `models_final2/c_120m_with_goes.joblib` | `8236adec0e611525a81e5afc133c92d2f55ee57f8c758d6ebd8a6dcb2ebada2e` |
| `models_final2/c_30m_aditya.joblib` | `b30f294284f44d2d5168235707be5c2e0f25821faed7cbd55be75b6e63411511` |
| `models_final2/c_30m_with_goes.joblib` | `c404429f81d858f3784e29066d779118368fa0dbf5819c4ac7bd54f8122e5986` |
| `models_final2/c_60m_aditya.joblib` | `31bf36d213fb5cba01635d09704cd1301827e379f0e3dff297a691fbe2426877` |
| `models_final2/c_60m_with_goes.joblib` | `5894cba32f3b93f94ec611e48aaba0d09201826fc5bc791d15e2f524bd19a00e` |
| `models_final2/m_120m_aditya.joblib` | `853f26390ef7b13a937099f29d762682d36b56e5f8803a96eee0af081ced4045` |
| `models_final2/m_120m_with_goes.joblib` | `beb7342d75ff16adb5fa8f84f81e08514b3e209604c922547c5f1274a3e43d05` |
| `models_final2/m_30m_aditya.joblib` | `bf84c428252f7e7f95032d2c083d9a65748d4a48754dde9ed609d245a8f77b9f` |
| `models_final2/m_30m_with_goes.joblib` | `f848cee00712b41069e8152505f00eec10fd472eb45ac09cb8de835abad0b53e` |
| `models_final2/m_60m_aditya.joblib` | `21c0fd81e9b2ef9761556eca3f90a4251c07f4e52ca80ec5a102897945ab5581` |
| `models_final2/m_60m_with_goes.joblib` | `52458fc630d5363c6090671c9b5c11447e4960a657366128c5ea7f3ba63f6077` |
| `models_final2/now_aditya.joblib` | `d3e3247fa6f5894bb3b49ac2d439daf5adbcc375b839636c0529ad60daecf89c` |
| `models_final2/now_with_goes.joblib` | `84ecbfc1726d6980fd05d1add4fd36009e0fdbeb20d161d15616a2dd7cb50ab4` |
| `models_final2/r1_k0_aditya.joblib` | `e0c2176f4987911e9a651d560e97a18f658685100d070f90b04599d03f2a04a2` |
| `models_final2/r1_k0_with_goes.joblib` | `67774a5741082f5ee706f789baaa5fee284252771be06d2bdad05380b7c4b2ca` |
| `models_final2/r1_k1_aditya.joblib` | `b44f183a05cec8b1cf18daf901446d922cf34a57d21fb170c33ed15efa823cac` |
| `models_final2/r1_k1_with_goes.joblib` | `61f562c6fe966b466c76bbbf4f0f577fd6b3c952fbac118a8b413d33d08e23bb` |
| `models_final2/r1_k2_aditya.joblib` | `8495a00cdd61b1f107a56cbd2f10dd35339d2aabe28749418d8a0275ed46d2f6` |
| `models_final2/r1_k2_with_goes.joblib` | `71ce133e04e6db6023df74e3199363db9ab75c26aa4bddd993b025e2bb15e896` |
| `models_final2/r1_k3_aditya.joblib` | `9ada78fc96a18abbc6ca294c778a64d448a91a3d45aa24762136a1b673ec8481` |
| `models_final2/r1_k3_with_goes.joblib` | `54f5a3326bfdfe70336fd8f720377e910a40190aaa1d4b40a0c7644788e1596d` |
| `models_final2/r1_k5_aditya.joblib` | `32c86fd5be16fb35438395de9229d11bbe0b12a673554719d23387c270b29f88` |
| `models_final2/r1_k5_with_goes.joblib` | `ae9049fd1f57da2cb92a1894beb1e0922c8396e21d416c8a2b94ea1597a25c09` |
