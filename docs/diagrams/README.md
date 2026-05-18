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

### `architecture_v4.svg` — Static apparatus architecture

Shows the apparatus's structure at rest: the human researcher at the top
(novelty evaluation, research journal, approval gate), the DGX Spark
containing the NemoClaw/OpenShell sandboxed runtime, the Gemma 4 26B MoE
orchestrator inside that, the three-tier sandbox spectrum (synthetic /
semi-synthetic / applied), the tool layer (literature pipeline,
autoresearch, robustness battery), the three-layer knowledge base
(foundational corpus / live literature / loop memory) on ChromaDB, and the
external data feeds (arXiv nightly, Polymarket APIs, Semantic Scholar).

Reference: `ARCHITECTURE.md` §2 through §5 walk through every element of
this diagram in detail.

### `intelligence_loop_v4.svg` — Eight-step intelligence loop

Shows the apparatus's behavior over time: the eight loop steps, the
autonomy boundary between the autonomous zone (steps 1–7) and human
evaluation (step 8), the autoresearch side-branch off step 3, the monthly
red-flag callout, the cross-tier-replication strongest-signal note, the
continuous-loop return arrow, and the assessments-to-loop-memory feedback
edge that closes the learning loop.

Reference: `ARCHITECTURE.md` §6 walks through every step in detail.

## Known limitations of the v4 diagrams

- Colors are hardcoded hex values rather than CSS-variable theme tokens, so
  the SVGs do not automatically flip in dark mode. Not blocking; cosmetic
  only. A v5 redraw could fix this.
- The architecture diagram does not yet show the Pi harness explicitly
  (currently labeled as "NemoClaw / OpenShell sandboxed runtime"). Pi is
  the layer underneath OpenClaw. A v5 redraw could surface this if needed.
- The intelligence loop diagram's "Claude API (Phase 1)" callout reflects
  the pre-June-15-2026 Anthropic policy; from June 15, third-party Agent
  SDK usage draws from a separate metered credit pool. See
  `PROJECT_CONTEXT.md` §5 "Anthropic policy snapshot" for the current
  state. A v5 redraw could relabel this.
