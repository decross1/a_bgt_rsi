# UI session plan — SUPERSEDED

> **Current handoff: [`docs/ui_session_handoff_2026-06-10.md`](ui_session_handoff_2026-06-10.md).**
>
> This file's 2026-06-09-evening content (review fixes + live re-validation +
> verdict-semantics renders) was never executed by a UI session; every still-open
> item is carried over into the 2026-06-10 handoff as **Task 0 (blocking)** with
> re-verified file:line references, alongside the new RENDER work that pairs with
> the 2026-06-10 EMIT (provenance fields, multi-run registry, steps[] board,
> D-046 write-back contract, D-048 purge). Read the dated handoff; do not work
> from this file.

---

## 2026-06-10 closure

The carry-over items this stub pointed into
[`ui_session_handoff_2026-06-10.md`](ui_session_handoff_2026-06-10.md) (its
Task 0; items 9–10 absorbed this file's old Task 3) were re-numbered
T1.1–T1.6 / T3.1–T3.3 in the 2026-06-10 UI-overhaul workflow. **All nine
landed this session** — Phase-2 build agents R1a (ui-tests) and R1b
(ui-components); the integrator's merge plus the Phase-4 suite gates are the
verification of record. One-line resolutions:

- **T1.1** (R1a) — repo-root walk-up (probe ancestors of the test file for
  `memory/loop_memory.jsonl`; loud failure listing probed paths) inlined in
  the 3 live test files; shared-helper extraction deferred to the integrator.
- **T1.2** (R1a) — `topicality` added to `KNOWN_RELEVANCE_KEYS` and to the
  additive relevance-diagnostics comment/type in `types/schemas.ts`.
- **T1.3** (R1a) — `cleanup()` between the two renders in the axes census;
  the `Found multiple elements` throw is gone on live axes rows.
- **T1.4** (R1a) — trust tiles asserted as cohort invariants recomputed from
  the loaded rows, not the literal `"0%"`.
- **T1.5** (R1a) — `/api/human_todo` `{items, counts}` probe added to
  `test_live_8700.py`; `_GIT_SHA` snapshotted at import in `app.py` and
  served from both the FastAPI `version` and `/api/health`.
- **T1.6** (R1b) — Dashboard "drill into activity →" decoupled from the
  `<summary>` toggle (click navigates without toggling the disclosure).
- **T3.1** (R1b) — `override_reason` added to the override tooltip in
  `ResolvedIterationsList` under the same `badgeText` guard.
- **T3.2** (R1b) — quiet `transfer` label on `phenomenon=known` +
  `direction ∈ {matches, silent}` (substrate-independent per
  `novelty_two_axis_rubric.md`); the cyan chip emphasis unchanged.
- **T3.3** (R1b) — `ActiveRunCard` per-field coercion: malformed/partial
  `active_run` rows degrade legibly instead of crashing the hero.

Nothing in this file remains open; it stays superseded. The follow-on live
session runs from [`live_session_runbook.md`](live_session_runbook.md).
