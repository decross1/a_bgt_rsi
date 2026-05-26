# Track D — progress

Scratch progress log for the Track D (UI improvements) worktree. The
detailed build log is `ui/notes/ui-build.md`; this is the short index.

## Session 2026-05-19

Improvement pass over the built steps 6.1–6.7. Completed P0 + P1.

- **P0 — §9 open questions.**
  - Tool-call rendering shape: resolved. Both shapes (separate
    call-log lines, embedded `tool_calls` array) supported and unified
    into one inspector tree. Backend synthesizes embedded tools into
    `kind="tool"` nodes. Tests added both sides.
  - Inspector diffing: formally deferred to v2 (rationale in
    `ui_plan.md` §0 r4) — the CLI already gives a textual chain diff.
  - Experiment-level results browser: not built; one-page v2 sketch
    drafted at `ui/ui_plan_v2.md`. v2 is blocked on an
    experiment-result schema — filed in `track-d-observations.md`.
- **P1 — data-driven baseline card.** New `GET /api/baseline` sources
  decode tok/s from `bench/day1.csv` + `run_state` `metric_log`, falls
  back to documented §5.3 constants per-row, annotates each row
  measured vs documented. Both sources already exist on disk; decode
  row is measured (~32 tok/s, below the documented band — drift now
  visible).

Tests: 31 Python + 6 frontend, all green. `ui_plan.md` bumped r3 → r4.

Stopped here — clean P0+P1 chunk. Not started: P2 (stale-telemetry /
error-state UX audit), P3 (vLLM metric-name resilience), P4 (inspector
polish), P5 (a11y), P6 (README/DX).
