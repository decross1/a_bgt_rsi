# `agent/` — agent-facing documentation

This directory is read by Claude Code sessions. The operating contract
(`CLAUDE.md`) lives at the repo root — Claude Code auto-loads it. Files
here are the deeper references that contract points to.

## What's here

- [`autonomy.md`](autonomy.md) — The three-tier autonomy framework
  (`autonomous` / `soft_gate` / `hard_gate`), SLA discipline,
  phase-aware tier boundaries, alignment evidence. Read by every
  session; canonical for tier semantics.
- [`orchestration.md`](orchestration.md) — How worktrees are launched
  (Tracks A/B/C/D), the per-day parallel schedule, merge procedures,
  failure modes specific to parallel execution.
- [`ownership.yaml`](ownership.yaml) — Machine-readable registry: which
  paths belong to which zone, which zones are dispatchable. Consumed
  by `tools/claims_check.py` and by every agent before any file write.
- [`collision_protocol.md`](collision_protocol.md) — The claim/lock
  protocol every agent obeys before writing. The mechanism that lets
  N concurrent agents build the system without stepping on each other.
- [`prompts/`](prompts/) — Per-track launch prompts, one file per
  track:
  - [`prompts/track_a.md`](prompts/track_a.md) — Main session
  - [`prompts/track_b.md`](prompts/track_b.md) — Tests & schemas
  - [`prompts/track_c.md`](prompts/track_c.md) — Pipeline & ops
  - [`prompts/track_d.md`](prompts/track_d.md) — UI
  - [`prompts/dispatched_task.md`](prompts/dispatched_task.md) —
    Template for orchestrator-dispatched coding agents (Week-2
    deliverable).

## Reading order for a new session

1. `../CLAUDE.md` — auto-loaded; the inviolate rules.
2. `autonomy.md` — your tier semantics.
3. `ownership.yaml` + `collision_protocol.md` — your file-write rules.
4. `../plan.yaml` (or the relevant day section) — your task content.
5. `../run_state/week1.state.json` — current state; resume here.
6. The prompt for your track in `prompts/`.

## Authority

Where this directory disagrees with prose elsewhere:
- `autonomy.md` wins on tier assignment.
- `ownership.yaml` wins on file-zone mapping.
- `collision_protocol.md` wins on claim discipline.
- `plan.yaml` wins on task content (always).
- `CLAUDE.md` wins on inviolate rules (always).

## Where to look next

- For the 90-day arc: [`../PHASE_1_ROADMAP.md`](../PHASE_1_ROADMAP.md).
- For terminology: [`../GLOSSARY.md`](../GLOSSARY.md).
- For decision rationale: [`../DECISIONS.md`](../DECISIONS.md).
- For technical architecture: [`../ARCHITECTURE.md`](../ARCHITECTURE.md).
