# Lesson 14 — Slide figures 03–10: making charts that don't lie

**Code:** `src/presentation_figures.py` (run `python -m src.presentation_figures`). **Output:** `docs/presentation_figures/`
and the numbers behind the figures in `reports/presentation_figures.json`. Tune + validation data only; nothing from the
test period is read (`eda.check_no_test` asserts it).

## The rules we used, and why
- **1920 × 1080, no titles, big fonts.** The slide supplies the title. A projector washes out 9-pt text.
- **Colour means instrument.** Orange = SoLEXS (soft X-rays), blue = HEL1OS (hard X-rays), grey/black = everything
  else (baselines, the old detector, GOES spans). The audience learns the code once and can read every figure.
- **Every bar gets an uncertainty.** Validation has 114 days. A TSS of 0.47 with interval [0.33, 0.57] is a very
  different claim from 0.47 ± 0.01.

## Figure by figure

| Figure | Idea worth remembering |
|---|---|
| 03 monthly flares | A stacked bar shows the total *and* the mix. Class B→X goes light→dark orange: an ordered (sequential) quantity gets an ordered colour ramp. |
| 04 flare profiles | **Superposed epoch analysis:** line up many flares on the same moment (the SoLEXS onset), normalise each to its own peak, and take the median. Bigger flares rise later and decay longer. The 25–75 % band shows how much single flares vary. |
| 05 Neupert histogram | **The bin width is the data resolution (10 s).** Narrower bins would invent precision that the data don't have. The axis label says so. |
| 06 stacked example | The soft X-ray panel is on a **log scale**. On a linear scale, the gradual rise after the detector onset (08:01) is invisible, and the onset marker looks wrong. |
| 07 detector before/after | The three examples come from **fixed rules** in `detection/plots.pick_examples` (earliest-onset case, longest event, first merged M-flare), not from browsing for flattering cases. |
| 08 model skill | The model is compared with the **best baseline**, chosen separately for all rows and for quiet-start rows. Persistence is strong for the nowcast (0.66) but useless on quiet starts, where the 1-feature rule becomes the best baseline. |
| 09 ablation | **Underpowered bars are faded** and labelled "too few" (< 30 positive episodes). The bars are still shown, so nothing is hidden, but they are visually demoted. |
| 10 feature importance | **Permutation importance:** shuffle one feature, measure how much average precision drops. It works for any model, unlike LogReg coefficients, which are unstable when features are correlated. |

## Where permutation importance is blind
We measured it on the Dec–Jan calibration block (part of tune), so validation isn't used once more. But no HEL1OS
session falls in Dec–Jan. HEL1OS features are missing on every row there, so shuffling them changes nothing and their
importance is exactly 0. **The figure cannot tell us whether HEL1OS matters;** figure 09 answers that question.
General lesson: an importance score only describes the data it was computed on.

## Exercises
1. In `neupert_histogram`, change the bin edges to 5 s. What artefact appears, and why?
2. In `model_skill`, force the baseline to always be persistence. How does the quiet-start panel change, and why is
   that comparison unfair?
3. Run permutation importance for `c_60m` on the Nov 2025 rows that have HEL1OS data (`hel1os_available == 1`). Do
   any `hx_*` features enter the top 15? (Read-only: write to a scratch file, not to `docs/`.)

## Break it (safely)
Set `ax.set_yscale("linear")` back in `stacked_example`, re-run, and look at 06: the onset line now seems to sit
8 minutes before the "flare". Undo with `git checkout -- src/presentation_figures.py`.

## Quiz
1. Why is the median, not the mean, used for the superposed-epoch curve?
2. Why are the ablation's M-class bars faded rather than removed?
3. What does a permutation importance of exactly 0 mean, and what does it *not* mean?

<details><summary>Answers</summary>

1. A few huge or overlapping flares would dominate a mean. The median shows the typical shape.
2. Removing them would hide results. Fading them shows the numbers but signals that 12–17 episodes are too few to
   compare.
3. Shuffling that feature didn't change the score on *those rows*. It does not mean the feature is useless: it may be
   constant or missing there, as HEL1OS is in Dec–Jan.
</details>
