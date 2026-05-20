# Changelog — adversarial architecture review, 2026-05-19

> Per the handoff prompt's guardrail "Anything driven by an insight that
> was judged `wrong` or `overstated` must not appear as a change":
> nothing in this review was judged `wrong` or `overstated`, so every
> change below is motivated by a `holds` verdict from
> `1_adversarial_review_memo.md`.

## Files created by this review

| File | Description | Driven by |
|---|---|---|
| `0_stage0_inventory.md` | What I could and couldn't see, per the guardrail "list exactly what is missing before proceeding" | Stage 0 |
| `1_adversarial_review_memo.md` | Stages 1+2 — per-claim verdicts + missed gaps | All Stage 2 verdicts |
| `2_architecture_audit.md` | Stage 3 — where each insight lands in current docs, three-bucket split | All Stage 2 verdicts that held |
| `3a_architecture_md_patches.md` | Stage 4 — replacement text and inserts for `ARCHITECTURE.md` | C1, C2, C3, O1, O2, O3, M1, M3, M4, M5 |
| `docs/diagrams/intelligence_loop_v5.svg` | New behavioral diagram with critic, meta-review, feedback edge, degradation metrics | C1, C2, O1, O2, M1, M3, M4 |
| `docs/diagrams/architecture_v5.svg` | Static diagram with orchestrator + Phase-2 annotations and retrieval_context note | O3, M1, C2 (annotation) |
| `docs/diagrams/README.md` | Updated to describe v5 diagrams; v4 kept as historical record per versioning convention | (versioning convention) |
| `week2_plan_seed.md` | Week 2+ planning seed — 12 items with success criteria, no full plan | O1, O2, O3, M2, M3, M4, M5 + lower-priority insights |
| `5_frozen_plan_change_proposals.md` | Three schema-change proposals (Week 1 touch) — proposals only | C4, M1, M2 |
| `6_changelog.md` | This file | (handoff deliverable #6) |

## Files NOT changed by this review, and why

| File | Reason |
|---|---|
| `plan.yaml` | Frozen per Week 1 guardrail. Three schema changes that *would* touch it are in `5_frozen_plan_change_proposals.md` as proposals only. |
| `CLAUDE.md` | Frozen per Week 1 guardrail. Two of the three proposals would add prose to it; they're proposals only. |
| `START_HERE.md` | Orientation document; no architecture content changes. References to v4 diagrams could be updated to v5 after the change is approved; not done in this review. |
| `PROJECT_CONTEXT.md` | References v4 diagrams; same as above. The "Open scoping items" section in §6 mentions "General architecture re-scope" — this review resolves that item, but updating `PROJECT_CONTEXT.md` to *say* it's resolved is appropriate as a follow-up, not as an in-review edit. |
| `DECISIONS.md` | Adding new D-NNN entries to document the v5 diagrams is appropriate per the versioning convention; I drafted them below but did not commit them — they belong to Huchi as the decision-maker. |
| `docs/diagrams/architecture_v4.svg` | Kept verbatim per versioning convention. |
| `docs/diagrams/intelligence_loop_v4.svg` | Kept verbatim per versioning convention. |

## Draft DECISIONS.md entries (for Huchi to commit if v5 diagrams are accepted)

Per `docs/diagrams/README.md` versioning convention #3, each diagram
revision gets a D-NNN entry. Drafts below.

### D-023 (draft) — Architecture v5 diagrams from adversarial review

**Date locked.** _(to be filled by Huchi if accepted)_
**Decision.** Adopt `architecture_v5.svg` and `intelligence_loop_v5.svg`
as the canonical diagrams. The v4 diagrams are kept in
`docs/diagrams/` per versioning convention #2.

**v5 changes (loop diagram).**
- Critic / red-team node inserted between Step 2 (generate) and Step 3
  (experiment); retry edge bounded at ≤ 2 cycles. Phase 2.
- Meta-review synthesis node inserted between Step 1 (literature scan)
  and Step 2 (generate). Phase 2.
- Experiment-outcome → loop-memory feedback edge added, gated by Step 8
  (human review). Phase 2.
- Step 6 (novelty evaluation) annotated with Phase 1 human-sampling
  requirement and Phase 2 generator-scorer separation + structured-
  claim search.
- Step 7 (log) annotated with `retrieval_context` reproducibility
  field.
- Step 3 (experiment) annotated with per-hypothesis compute budget
  (Phase 2).
- Step 4 (robustness battery) annotated to clarify falsification ≠
  exploration.
- Degradation-metrics callout added on the right side
  (hypothesis:experiment ratio, model canary, retrieval-context audit,
  researcher calibration log).

**v5 changes (architecture diagram).**
- Orchestrator block expanded with Phase-2 annotation: compute budget,
  cost-aware bandit reward, critic + meta-review worker dispatch.
- `retrieval_context` reproducibility annotation under experiment logs.
- Phase-2 experiment-outcome feedback edge annotated (drawn fully in
  the loop diagram).

**Alternatives.**
- Leave v4 unchanged; capture additions in prose only.
- Redesign from scratch (v5 as full redraw).

**Rationale.** Adversarial review from 2026-05-19 (see
`1_adversarial_review_memo.md`) identified seven structural critiques
of the Google AI co-scientist that hold against this project's
intended architecture. The v5 diagrams make the Phase 2 additions
visible without redesigning Phase 1 elements that have already shipped
or are mid-implementation. v4 is preserved as a baseline showing the
pre-review architecture.

**Reversibility.** Trivial. Revert `ARCHITECTURE.md` reference and
`docs/diagrams/README.md` "current" pointer to v4. v5 files can be
moved to `docs/diagrams/retired/`.

### D-024 (draft) — Architecture-document patches from adversarial review

**Date locked.** _(to be filled by Huchi if accepted)_
**Decision.** Apply the patches in `3a_architecture_md_patches.md` to
`ARCHITECTURE.md`: replace §6 with the labeled-Phase-1/Phase-2
version, insert §6.5 "Degradation metrics," add the active-vs-passive
paragraph to §4.4, add the compute-budgeting / critic / meta-review
paragraphs to §5.1, and add the two negative-scope bullets to §8.

**Alternatives.**
- Apply only the §6 changes and defer the rest.
- Don't apply; carry insights in supplementary memos only.

**Rationale.** Same as D-023. The architecture document is the
canonical written walkthrough; if Phase 2 additions are not in it,
they don't exist for any future reader.

**Reversibility.** Easy. `git revert` the change.

---

## Verdict-to-change map (full)

For honest accounting, here's every Stage 2 verdict mapped to the
files it produced changes in. The handoff prompt asked for this so
that "the Stage-2 verdict that motivated each change" is visible.

| Verdict | Where it shows up |
|---|---|
| C1 (HOLDS) — self-evaluation circularity | `1_adversarial_review_memo.md`, `2_architecture_audit.md`, `3a_architecture_md_patches.md` Patch 1 step 6, `intelligence_loop_v5.svg` step 6 annotation, `5_frozen_plan_change_proposals.md` (mitigation does not require Week 1 schema change in itself) |
| C2 (HOLDS, with refinement) — no truth-feedback into generator | `3a_architecture_md_patches.md` Patch 1 step 8, `intelligence_loop_v5.svg` Phase-2 feedback edge, `architecture_v5.svg` annotation under knowledge base |
| C3 (HOLDS) — generate-and-filter with no cost to being wrong | `3a_architecture_md_patches.md` Patch 2 §6.5.1, `intelligence_loop_v5.svg` degradation-metrics callout |
| C4 (HOLDS — most important) — expert-in-the-loop hides autonomy gap | `5_frozen_plan_change_proposals.md` P1 |
| O1 (HOLDS) — adversarial critic before experiment | `3a_architecture_md_patches.md` Patches 1 and 3, `intelligence_loop_v5.svg` step 2.5, `architecture_v5.svg` orchestrator annotation, `week2_plan_seed.md` W2-01 |
| O2 (HOLDS) — active meta-review synthesis | `3a_architecture_md_patches.md` Patches 1 and 5, `intelligence_loop_v5.svg` step 1.5, `architecture_v5.svg` orchestrator annotation, `week2_plan_seed.md` W2-02 |
| O3 (HOLDS) — compute-budgeting Supervisor | `3a_architecture_md_patches.md` Patches 1 and 3, `intelligence_loop_v5.svg` step 3 annotation, `architecture_v5.svg` orchestrator annotation, `week2_plan_seed.md` W2-03, W2-04 |
| Lower — six-role taxonomy as worker menu | `week2_plan_seed.md` W2-07 |
| Lower — calibrate auto-eval on synthetic ground truth | `week2_plan_seed.md` W2-05 |
| Lower — rediscovery-with-holdout | `week2_plan_seed.md` W2-08 |
| Lower — test-time-compute knob at 26B | `week2_plan_seed.md` W2-06 |
| Lower — N-collapse symmetry | Acknowledged in `1_adversarial_review_memo.md` as methodological commitment; no diagram/doc change (intentional) |
| M1 (missed) — retrieved-literature provenance | `3a_architecture_md_patches.md` Patches 1 (step 7) and 2 (§6.5.3), `intelligence_loop_v5.svg` step 7 annotation, `architecture_v5.svg` log-block annotation, `5_frozen_plan_change_proposals.md` P2 |
| M2 (missed) — researcher's calibration log | `3a_architecture_md_patches.md` Patch 2 §6.5.4, `intelligence_loop_v5.svg` degradation-metrics callout, `5_frozen_plan_change_proposals.md` P3, `week2_plan_seed.md` (implicit, follows from P3) |
| M3 (missed) — novelty checker's pre-arXiv blind spot | `3a_architecture_md_patches.md` Patch 1 step 6, `intelligence_loop_v5.svg` step 6 annotation, `week2_plan_seed.md` W2-10 |
| M4 (missed) — model-degradation detector | `3a_architecture_md_patches.md` Patch 2 §6.5.2, `intelligence_loop_v5.svg` degradation-metrics callout, `week2_plan_seed.md` W2-11 |
| M5 (missed) — robustness battery ≠ tournament | `3a_architecture_md_patches.md` Patch 1 step 4 methodological note, `intelligence_loop_v5.svg` step 4 annotation, `week2_plan_seed.md` W2-12 |

Every change is traceable to a held verdict. Nothing is here on the
account of a `wrong` or `overstated` claim because no claim was judged
that way.

## Honest accounting note

The Stage 2 work produced an unusually high `holds` rate — 7 of 7
prior claims, plus the lower-priority items, plus 5 added missed
gaps. Per the handoff prompt's "honest assessment over agreement"
guardrail, this deserves a comment: I considered for each claim
whether I was confirming because the analysis was strong, or because I
was insufficiently adversarial. My audit-trail on this:

- Each verdict cites the source text. The Blog's language is direct on
  C1 ("not based on independent ground truth"), C4 ("expert-in-the-
  loop guidance"), and the Supervisor/test-time-compute mechanism
  (O3). These are not interpretive readings.
- C2's verdict was the most contested in my own reasoning — I added
  the "with refinement" qualifier specifically because the Meta-review
  agent *could* be doing more than the Blog reveals. Without the
  Paper body I cannot fully test this. The verdict is contingent on
  what the Blog and abstract describe.
- The mitigation for each claim was tested against this project's
  existing decisions (D-010, D-011, D-012). Several mitigations had to
  be re-shaped to be consistent (e.g., O1's critic is a prompt
  pattern, not a second model, because D-012 excludes a dual-model
  routing layer in Phase 1).
- The five missed gaps came from reading the project documents
  *against* the co-scientist Blog and noticing what the project
  inherits implicitly. M1 (retrieval provenance) in particular is a
  concrete reproducibility hole that the project's stated
  reproducibility commitment doesn't actually meet — that's not a
  defense-of-the-prior, it's a strengthening.

If anything in this review is wrong, the most likely candidates are:
the Paper body addresses something the Blog doesn't (would change C2
and possibly O2 verdicts); my characterization of Phase 1's
single-model constraint is too strict and O1's critic could be a
second model after all; the structured-claim search (M3 / W2-10) is
significantly harder than I'm estimating because real claim extraction
from arbitrary LLM output is itself a research problem.

End of review.
