# Canonical diagrams

This directory holds the canonical SVG diagrams of the apparatus. They are
referenced from `ARCHITECTURE.md` and `PROJECT_CONTEXT.md`.

## Versioning convention

Each diagram is suffixed with a version (`_v4`, `_v5`, …). When a diagram
is revised:

1. The new file is committed as `<name>_v<N+1>.svg` — do NOT overwrite the
   old version in place.
2. The previous version stays in this directory unless explicitly retired
   (in which case it moves to `docs/diagrams/retired/`).
3. The change is noted in `DECISIONS.md` under a new `D-NNN` entry with
   what changed and why.
4. References to the diagram in `ARCHITECTURE.md` and `PROJECT_CONTEXT.md`
   are updated to point at the new version.

The "current" version of each diagram is the highest-numbered one present.

## Current diagrams

### `architecture_v5.svg` — Static apparatus architecture (current)

Shows the apparatus's structure at rest: the human researcher at the top
(novelty evaluation, research journal, approval gate), the DGX Spark
containing the NemoClaw/OpenShell sandboxed runtime, the Gemma 4 26B MoE
orchestrator inside that, the three-tier sandbox spectrum (synthetic /
semi-synthetic / applied), the tool layer (literature pipeline,
autoresearch, robustness battery), the three-layer knowledge base
(foundational corpus / live literature / loop memory) on ChromaDB, and
the external data feeds (arXiv nightly, Polymarket APIs, Semantic
Scholar).

**v5 changes from v4:**
- Orchestrator block carries a third line annotating its Phase 2 role:
  per-hypothesis compute budget, cost-aware bandit reward, and the
  critic + meta-review worker dispatches.
- Annotation under the knowledge-base block noting that Phase 2 adds an
  experiment-outcome → loop-memory feedback edge (in addition to the
  Phase 1 human-assessment feedback edge already drawn), gated by human
  review; the edge itself is on the loop diagram, not here, to keep
  the static diagram readable.
- Annotation on the experiment-logs block noting the
  `retrieval_context` field (doc IDs + content hashes) that each
  generator call should log, with a pointer to the Day-3.5 schema work.
- Diagram height extended by 20 px to accommodate the orchestrator
  annotation line cleanly.

Reference: `ARCHITECTURE.md` §2 through §5 walk through every element of
this diagram in detail.

### `intelligence_loop_v5.svg` — Eight-step intelligence loop (current)

Shows the apparatus's behavior over time: the eight loop steps, the
autonomy boundary between the autonomous zone (steps 1–7) and human
evaluation (step 8), the autoresearch side-branch off step 3, the
monthly red-flag callout, the cross-tier-replication strongest-signal
note, the continuous-loop return arrow, and the assessments-to-loop-
memory feedback edge that closes the learning loop.

**v5 changes from v4:**
- New step 1.5 — *Meta-review synthesis* — between step 1 (literature
  scan) and step 2 (generate hypothesis). Indigo dashed border; Phase 2.
- New step 2.5 — *Critic / red-team* — between step 2 (generate) and
  step 3 (experiment), with a retry edge back to step 2 (bounded ≤ 2).
  Indigo dashed border; Phase 2.
- Annotation on step 3 noting Phase 2 per-hypothesis compute budget
  with early-stop semantics.
- Annotation on step 4 clarifying robustness battery is *falsification*,
  not *exploration*.
- Expanded step 6 (novelty evaluation) text noting Phase 1 human-
  sampling on automated novelty calls and Phase 2 separation of novelty
  scorer from generator (Qwen 3.6) + structured-claim search alongside
  semantic retrieval.
- Annotation on step 7 noting the `retrieval_context` reproducibility
  field.
- New Phase 2 feedback edge (indigo dashed) from step 3 (experiment
  outcome) through step 8 (gated by human) into loop memory.
- New degradation-metrics callout on the right side (hypothesis:
  experiment ratio, model canary task, retrieval-context audit,
  researcher calibration log) — Phase 1 logs them, Phase 2 sets
  thresholds.
- Annotation on step 8 noting it clears the Phase 2 experiment-outcome
  edge.
- Title bar added.
- Diagram height extended from 850 to 1020 px to accommodate the new
  nodes and edges without crowding.

Reference: `ARCHITECTURE.md` §6 walks through every step in detail;
§6.5 covers the degradation metrics.

## Previous diagrams

### `architecture_v4.svg` — kept as historical record

The pre-adversarial-review version. Still useful as a baseline showing
the apparatus pre-adversarial-review. Per versioning convention, NOT
overwritten.

### `intelligence_loop_v4.svg` — kept as historical record

The pre-adversarial-review version. Still useful as a baseline. Per
versioning convention, NOT overwritten.

## Known limitations of the v5 diagrams

- Colors are still hardcoded hex values rather than CSS-variable theme
  tokens, so the SVGs do not automatically flip in dark mode. Carried
  forward from v4. Not blocking; cosmetic only.
- The architecture diagram still does not show the Pi harness explicitly
  (still labeled "NemoClaw / OpenShell sandboxed runtime"). Carried
  forward from v4. A future v6 could surface this if it becomes
  important.
- The intelligence loop diagram's "Claude API (Phase 1)" callout is no
  longer drawn here because the static API callout lives on the
  architecture diagram. The loop diagram's autoresearch branch is
  unchanged.
- New Phase 2 elements use a single indigo color (`#3C3489` /
  `#534AB7`) consistently to distinguish them from Phase 1 elements
  without inventing a fourth palette family.
