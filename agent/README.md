# `agent/` — agent-facing documentation

This directory is read by Claude Code sessions. The operating contract
([`../CLAUDE.md`](../CLAUDE.md)) lives at the repo root and is auto-loaded.

## What's here

- [`prompts/`](prompts/) — Launch prompts, one file per session kind:
  - [`prompts/main.md`](prompts/main.md) — Main session prompt (the
    primary build / research session).
  - [`prompts/ui_session.md`](prompts/ui_session.md) — Concurrent UI
    session prompt (worktree-isolated; writes only to `ui/`).

## Where the old track/tier scaffolding went

The Track A/B/C/D parallel-execution framework, the autonomy-tier
machinery (`autonomous` / `soft_gate` / `hard_gate`), the
ownership registry, the claim/lock collision protocol, and the
multi-track per-day startup matrix were retired on 2026-05-26 in
favor of a single primary session + one concurrent UI session.

Those files now live under [`../archive/agent/`](../archive/agent/)
and [`../archive/agent_prompts/`](../archive/agent_prompts/). They are
read-only references, not active rules.

## Authority

- [`../CLAUDE.md`](../CLAUDE.md) — inviolate rules.
- [`../LOOP_V0.md`](../LOOP_V0.md) — the active build plan.
- [`../human/sessions/`](../human/sessions/) — per-session working
  notes (the daily working artifact).
- [`../DECISIONS.md`](../DECISIONS.md) — why a choice was made.
