# Autonomy-observability RENDER half — validation report

> Serial-integrator pass, 2026-06-09. Validates the merged RENDER half (commit
> 07b6729) against **live apparatus data** and hardens it. Boundary: only `ui/`
> was touched; `run_state/` `memory/` `orchestrator/` `schema/` were read-only.
> Spec: `docs/ui_autonomy_observability_plan.md`, `docs/ui_session_handoff_2026-06-09.md`,
> `ui_plan.md` §AUTONOMY OBSERVABILITY.

## Verdict — ALL THREE SUITES GREEN

| Suite | Result |
| --- | --- |
| `tsc --noEmit` (frontend) | **PASS** — exit 0, 0 errors |
| `vitest run` (frontend) | **PASS** — 82 files, **639 tests** |
| `pytest backend/tests` | **PASS** — **196 tests**, 0 skipped in the live-data module |

No tests are `.skip`/`.only`/`.todo`/`xit` on the frontend; the backend's
`skipif`s in `test_validate_live_real_data.py` are file-presence guards and all
**ran** (the gitignored cycle file is present), none silently skipped.

## Per-surface PASS/FAIL

| Surface | Status | Live evidence |
| --- | --- | --- |
| **Coordinator cycles** (`/api/coordinator/cycles`) | PASS | 200; **19** real rows (grew from 13); all `topic_source=arxiv_pick`, all `agent=coordinator`; `dispatched_iteration_id` present on 0 — exact shape the brief described. |
| **Errored cycles → explicit RED rows** | PASS | **3** errored cycles (grew from 2: `coordinator_2805571f`, `_27629ba6`, `_696791e2`); every errored outcome carries a non-empty `error` string (asserted live). `ActionChip` renders the error inline (red), never a silent gap. |
| **Resolved iterations** (live `loop_memory.jsonl`) | PASS | **52** rows; renders every row across every page with **no** `console.error`/`console.warn` (jsdom gate); pre-novelty rows degrade quiet; the 4 `retrieval.relevance` rows render without crashing the nested block. |
| **Low-evidence badge** | PASS | 0 live rows have `retrieval.relevance.low_confidence===true`, so the flag correctly **does not fire** (doesn't cry wolf). `novelty/critique.low_confidence` keys (4 rows) are not read by this surface — no interaction, handled gracefully. Drift-proof invariant test stays green regardless. |
| **Panels empty-state** (findings / bubbles / health_signals) | PASS | All three files absent → 200 with `{key: []}` (empty list), n=0; panels render the clean empty state, never a blank gap or crash. |
| **Active run** (`/api/coordinator/active`) | PASS | File absent → **204**, empty body → Activity panel shows clean idle state, not a 500. |
| **Routes render w/o console errors** | PASS | Dashboard / Coordinator / Activity / Experiments render under jsdom with `console.error`/`console.warn` spied and asserted not-called. |
| **Backend** (in-process merged app over real data) | PASS | `TestClient(create_app())` reads the real primary checkout via `_PRIMARY_REPO`; 9/9 live-data tests pass; cohort-invariant assertions survived the 13→19 / 2→3 growth. |

## nemoclaw_agent badge — NOW LIVE (was forward-compat)

The brief said `seed.source=nemoclaw_agent` was **not in the data yet**. It has
since landed: **2 live `nemoclaw_agent` rows** are now in `loop_memory.jsonl`.

- **Component:** `SourceBadge` maps `nemoclaw_agent` → **violet** (`bg-violet-950
  text-violet-300`) + label `nemoclaw`, distinct from coordinator (sky) and
  arxiv_pick (indigo). Verified by reading the component and by existing tests
  (`test_source_badge.tsx` asserts it end-to-end as a bare badge AND inside
  `CoordinatorCycleCard` via `topic_source`; `test_harden_SourceBadge_r3` covers
  the whitespace-trimmed edge).
- **Live spot-check (transient, removed after):** rendered the **real** 2
  `nemoclaw_agent` rows through `ResolvedIterationsList` — a violet `source-badge`
  with `nemoclaw` text appears, **no console errors**. Permanent regression
  coverage already exists in `test_source_badge.tsx`, so no new test file was
  added (avoided busywork per the brief).
- **Status: PASS, now exercised by live data.** No code change was needed — the
  forward-compat build was correct.

## Bugs found / fixed in this integrator pass

Two **real, suite-blocking** bugs the parallel phases left, plus a type-resolution gap:

1. **`Dashboard.tsx` failed to typecheck** (`TS2304: Cannot find name
   'TelemetrySample'`). A prior phase added a `cleanSamples` filter using a
   `(s): s is TelemetrySample` type predicate but never imported the type — a
   hard build break. **Fix:** added `TelemetrySample` to the existing
   `import type { … } from "../types/schemas"`. No behavior change.

2. **`CoordinatorCycleCard.ActionChip` crashed the whole Coordinator page on an
   object/array-valued `action` or `status`** (the "row-27" shape from a
   malformed/forward-compat JSONL row). The prior `?? "?"` / `?? "unknown"`
   coalesce only caught null/undefined; an object sailed past `??` and, rendered
   as a React child, threw "Objects are not valid as a React child" and unwound
   React (the route maps **every** cycle, so one bad row blanks the page — the
   exact dark-loop failure this view exists to prevent). A fuzz test
   (`test_fuzz_CoordinatorCycleCard.tsx`) had this anchored as a `KNOWN BUG` with
   a `.toThrow()` assertion and an "INTEGRATOR: fix + flip" note. **Fix:** routed
   `action`/`status` through the file's existing `asText()` helper
   (`asText(outcome.action) ?? "?"`), so a non-string degrades to the legible
   `?`/`unknown` placeholder chip instead of crashing. No exported signature
   changed. **Regression:** flipped the two `KNOWN BUG` assertions from
   `.toThrow()` to `.not.toThrow()` + a visible placeholder chip + no
   `console.error` — they now lock in the guarded behavior.

3. **Live-data validation tests didn't typecheck** (`node:fs`/`node:path`/
   `node:url` unresolved → `TS2591`, cascading to 6 implicit-`any` errors on the
   downstream `.split/.filter/.sort` callbacks). `test_validate_iterations.tsx`
   and `test_validate_lowevidence.tsx` read the **real** gitignored JSONL (a
   deliberate "the data IS the contract" design), but the project intentionally
   carries no `@types/node` (the app is a browser bundle). **Fix:** added one
   minimal ambient shim, `ui/frontend/tests/node-builtins.d.ts`, declaring only
   the symbols those tests import (with `readFileSync → string`, which also
   clears the implicit-`any` cascade). Scoped to `tests/`; not a substitute for
   `@types/node`. Preferred over installing `@types/node` (a tree-wide
   dependency + lockfile change) to keep the integration surgical.

**Minor type/lint fixes** (test-only, no behavior change): typed the two
`.map/.filter` callbacks in `test_audit_states.tsx` (implicit-`any`); non-null
assertion on `REAL_ACTIVE_RUN.run_id!` in `test_validate_active.tsx` (the
fixture provably sets it; `getByText` needs a `Matcher`). These two also
resolved the only `noUnusedLocals` flag (the flipped fuzz block now *reads* its
spies in assertions).

**Collisions resolved:** the only cross-agent collision was the fuzz
`KNOWN BUG` anchor contradicting another agent's hardening direction — resolved
by fixing the component and flipping the anchor (above). No duplicate test-name
or duplicate-`data-testid` collisions were found across the 82 test files.

## Live real-data smoke — captured numbers (2026-06-09)

Recipe: `TestClient(create_app())` over the real primary checkout (`_PRIMARY_REPO`).

```
/api/coordinator/cycles         200   19 rows   (3 errored, all error-string present)
                                      topic_source: {arxiv_pick: 19}
                                      agent:        {coordinator: 19}
                                      dispatched_iteration_id present: 0
/api/coordinator/findings       200   {findings: []}        (file absent → empty)
/api/coordinator/bubbles        200   {bubbles: []}         (file absent → empty)
/api/coordinator/health_signals 200   {health_signals: []}  (file absent → empty)
/api/coordinator/active         204   (empty body)          (file absent → idle)

memory/loop_memory.jsonl        52 rows
  seed.source: {human_cli: 34, loop_memory_probe: 15, coordinator: 1, nemoclaw_agent: 2}
  retrieval.relevance present: 4 rows
  retrieval.relevance.low_confidence==true: 0 rows   ← low-evidence flag has no live trigger
  novelty.low_confidence / critique.low_confidence keys: 4 rows each (not read by lowevidence surface)
```

## Hardening rounds

The merged tree already carried extensive per-component hardening from the
parallel phases (rounds r1–r6 per component: missing structure / wrong type /
unknown enum / prototype-collision / whitespace edges, plus property-fuzz files
that generate ~50 malformed rows per component and assert no-throw + no-console
on each). This integrator pass added **one** more real fix (the row-27
object-status crash, #2 above) on top of those. Every panel/list now degrades a
malformed producer row to a legible fallback rather than crashing — the
make-absence-legible principle applied to the rows' own shapes.

## Deferred followups (for the primary / EMIT session)

1. **EMIT-side gap — no live low-evidence trigger.** `retrieval.relevance` is on
   4 rows but **0** carry `low_confidence===true`, so the low-evidence badge's
   populated/firing path is unexercised by live data (only by fixtures). The
   render side is correct and proven; this is an **EMIT** observation: once the
   relevance signal flags a genuine thin/off-domain verdict (the 2026-06-09 false
   `novel/survives` class), re-run the lowevidence validation to confirm the badge
   fires on a real row. The drift-proof invariant test is dated to today and will
   (correctly) tighten if such a row lands.
2. **Surfaced-findings / bubbles / health_signals panels are fixture-only.** Their
   files are still absent live, so the *populated* render path is unvalidated
   against real rows. When the EMIT half writes a first real row to any of the
   three, a follow-up should confirm the populated render (the empty-state and
   shape are already validated).
3. **`active_run.json` mid-flight render unvalidated live.** `/active` returns 204
   today (no cycle in flight). When a cycle is mid-flight, the file exists and the
   Activity coordinator-phases narration path activates; re-validate
   `CoordinatorPhases` against a live `active_run.json` then (the backend test
   already asserts the on-disk JSON round-trips when present).
4. **`coordinator_cycles.jsonl` has no `dispatched_iteration_id` yet** (0/19), so
   the Coordinator card's `dispatched-iteration` footer link is unexercised by
   live data. The EMIT side populates this only on a *successful* dispatch; all 19
   live cycles either errored or didn't dispatch. Re-spot-check once a successful
   dispatch lands.
5. **Optional, non-blocking, NOT done (out of minimal scope):** the docstring in
   `backend/tests/test_validate_live_real_data.py` still narrates "13 rows / 2
   errored" (now 19 / 3). The **assertions** are deliberately count-agnostic
   (cohort invariants), so this is a stale *comment* only, not a failure. A
   one-word refresh could be folded in by whoever next touches that file.

## Addenda the ui_plan.md owner may want to fold in (I did NOT edit ui_plan.md)

- **`nemoclaw_agent` is now LIVE** (2 rows in `loop_memory.jsonl` as of
  2026-06-09) and renders violet end-to-end — the §AUTONOMY OBSERVABILITY note
  calling it "forward-compat / unexercised" can be updated to "live-validated".
- **Cycle/iteration counts grew** (cycles 13→19, errored 2→3, loop_memory 49→52)
  — purely data accretion; all live-data tests use cohort invariants / generous
  lower bounds and stayed green, so no acceptance criterion regressed.
- The RENDER half meets every acceptance bullet that has live data to exercise it
  (errored dispatch as an explicit row; clean empty panels; agent + source badges
  on every row; low-evidence flag quiet on confidently-grounded verdicts;
  degraded-vs-broken health distinct). The bullets gated on absent EMIT data
  (populated findings/bubbles, mid-flight narration, a firing low-evidence flag)
  are listed under deferred followups above.
