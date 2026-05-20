# Adversarial Architecture Review — deliverable index

Date: 2026-05-19. Reviewer: Claude (Opus 4.7), single session.
Source paper: Google AI co-scientist (research.google blog + arXiv 2502.18864 abstract).
Subject: a_bgt_rsi project — meta-scientific research apparatus on DGX Spark.

## Read in this order

1. **`1_adversarial_review_memo.md`** — Stages 1+2: per-claim verdicts on the
   seven prior insights (C1–C4, O1–O3) plus four lower-priority items, plus
   five missed gaps (M1–M5). This is the central deliverable. Each claim has
   re-derivation, falsification attempt, severity check, mitigation check,
   and verdict with paper citation.
2. **`2_architecture_audit.md`** — Stage 3: where each validated insight maps
   into the current architecture as (a) already handled, (b) silently assumed,
   or (c) absent; three-bucket split (architecture docs / Week 2+ / frozen
   Week 1).
3. **`3a_architecture_md_patches.md`** — Stage 4 part A: six patches to
   `ARCHITECTURE.md` (replace §6, insert new §6.5, update §4.4 / §5.1 / §8 /
   diagram references). Phase 2 additions clearly labeled.
4. **`docs/diagrams/intelligence_loop_v5.svg`** — Stage 4 part B: updated
   autonomous-decision-loop diagram. Adds critic (step 2.5), meta-review
   synthesis (step 1.5), Phase 2 experiment→generator feedback edge gated by
   step 8, degradation-metrics callout, retrieval_context and structured-claim
   annotations. Indigo dashed borders = Phase 2.
5. **`docs/diagrams/architecture_v5.svg`** — Stage 4 part C: minimal-delta
   update to the infrastructure-containment diagram (only the orchestrator
   block and one experiment-log annotation change).
6. **`docs/diagrams/README.md`** — diagram versioning notes; v4 retained.
7. **`week2_plan_seed.md`** — Week 2+ planning note. 12 items (W2-01 through
   W2-12), each with one-sentence success criterion. NOT a full Week 2 plan.
8. **`5_frozen_plan_change_proposals.md`** — three proposals (P1, P2, P3)
   that would touch the frozen Week 1 schema. NOT APPLIED. Decision form
   for Huchi at the end.
9. **`6_changelog.md`** — dated list of every file change with verdict→change
   traceability map. Includes draft D-023 and D-024 entries for DECISIONS.md
   if proposals are accepted. Includes honest-accounting note on the high
   HOLDS rate.

Also: **`0_stage0_inventory.md`** — what files were and were not visible.

## Headline result

All seven prior claims (C1–C4, O1–O3) and all four lower-priority items
**HOLD**. Five additional missed gaps identified (M1–M5). Most important new
gap is **M1 — retrieved-literature provenance** (reproducibility hole the
project's stated reproducibility commitment doesn't actually meet).

## What to do next

- Apply patches in `3a_architecture_md_patches.md` to `ARCHITECTURE.md`
  on a branch.
- Swap `architecture_v4.svg` / `intelligence_loop_v4.svg` references to the
  v5 versions in PROJECT_CONTEXT.md and START_HERE.md.
- Read `5_frozen_plan_change_proposals.md` and decide on P1/P2/P3.
  Recommendation: **approve all three** (combined budget ~2.5 hours,
  additive only, reversible).
- If P1/P2 accepted, also commit D-023 and D-024 entries to DECISIONS.md
  (drafts in `6_changelog.md`).
- File `week2_plan_seed.md` for Week 2 planning; it is not the Week 2 plan.

## Honest accounting

Seven-for-seven HOLDS is suspiciously clean. Caveats stated in the changelog:
the prior analysis was good (the rate is correct), I only fetched the Blog +
arXiv abstract (Paper body could contain text that changes C2 or O2), and
mitigations were shaped to fit the existing decisions (D-010/D-011/D-012).
The missed gaps (M1–M5) come from reading the project against the Blog and
noticing implicit inheritance — not from defending the prior.
