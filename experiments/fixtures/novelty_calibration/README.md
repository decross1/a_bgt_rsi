# `novelty_calibration/`

10 synthetic hypothesis outcomes with ground-truth novelty labels for
the Day-41 (W2-05) auto-evaluator calibration. The Day-41 task scores
the auto-evaluator on these fixtures and computes Cohen's κ + Spearman
ρ against the ground-truth tier / score to set the deployment threshold.

## Per-fixture schema

| field                          | type    | notes                                                  |
|--------------------------------|---------|--------------------------------------------------------|
| `id`                           | string  | matches filename stem                                  |
| `hypothesis_text`              | string  | candidate hypothesis evaluated for novelty             |
| `prior_art_summary`            | string  | short description of the closest known prior result    |
| `ground_truth_tier`            | string  | `well_known` / `incremental` / `novel` / `surprising`  |
| `ground_truth_novelty_score`   | float   | 0.0-1.0, intended for Spearman against evaluator score |
| `domain`                       | string  | `game_theory` / `llm_behavior` / `mech_design` / `methodology` |
| `rationale`                    | string  | internal — why this score; not shown to the evaluator  |
| `schema_version`               | string  | "1.0"                                                  |

Spread (2 fixtures per tier + 2 borderline): designed so a calibrated
evaluator can be distinguished from one that scores everything in the
middle, and so κ has enough off-diagonal mass to be meaningful.

## Status

**Stretch deliverable from Day-8 Track C.** Day-41 may want to expand
this to 20-30 fixtures; this 10-entry set is enough to land the
W2-05 calibration with a documented threshold and identify whether
the evaluator is well-ordered (Spearman) AND tier-aligned (κ).
