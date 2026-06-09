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

## WF-A — forward-compat + live-:8700 + staleness (evening block)

Serial-integrator close-out for the evening workflow. Scope: prove the merged
renders survive the PRIMARY session's **announced additive-only** contract
(critique `verdict:"undecidable"` + three override siblings, the
`novelty.novelty_axes` OBJECT, five new `retrieval.relevance` siblings), add a
live validation of the served :8700 process, and land the one real bug fix
(CoordinatorPhases phantom-presence). New renders for the announced fields are
deliberately NOT built — that is the later, gated task.

### Suite results (all green, growth-only)

| Suite | Result | Baseline |
| --- | --- | --- |
| `npx tsc --noEmit` | clean | clean |
| `npx vitest run` | **54 files / 678 tests passed** | 49 / 639 (+5 files, +39 tests) |
| `pytest backend/tests -q` | **202 passed, 0 skipped** | 196 (+6, `test_live_8700.py`) |

`test_live_8700.py` did **NOT** skip — :8700 was up and all 6 live tests ran
against the served process. Zero failures anywhere; no test was weakened or
deleted. New test files are exactly the budgeted six — no sprawl, nothing to
consolidate: `tests/test_forwardcompat_{routes,iterations_list,lowevidence_strip,findings_panel}.tsx`,
`tests/test_stale_active_run.tsx`, `backend/tests/test_live_8700.py`.

### Per-surface forward-compat verdicts

| Surface | Verdict | Evidence |
| --- | --- | --- |
| ResolvedIterationsList | **ROBUST** | 5 probes: `undecidable` + override siblings → quiet fallback badge; `novelty_axes` object never leaks into a React child; all five relevance siblings inert; combined row; garbled variants degrade silently. Cosmetic gap only (see deferred). |
| SurfacedFindingsPanel | **ROBUST** | 3 probes: `undecidable` renders as quiet badge; observability siblings not rendered raw; axes/relevance extras inert. |
| LowEvidenceBadge / `isLowEvidence` | **ROBUST** | Verdict driven solely by `low_confidence` + structural triggers: `category:"off_domain"` with `low_confidence:false` does NOT fire; `"ok"` with `true` DOES; every announced category value stays silent when unflagged; garbled new fields never throw, flip the verdict, or leak into the tooltip. |
| RedFlagsTrendStrip | **ROBUST** | NaN-free rates with announced + garbled rows mixed; `undecidable` never enters the suspect numerator (fail-closed). |
| Routes (Dashboard / Coordinator / Activity / Experiments) | **ROBUST** | Announced-shape rows mixed with legacy rows: no crash, no console.error/warn, unknown enums fall to the existing quiet fallbacks. |
| CoordinatorPhases | **FIXED** | Phantom-presence / staleness bug, below. |
| Served :8700 process | **VALIDATED** | Live route/shape assertions, below. |

No surface crashed on `undecidable` or `novelty_axes` — the only crash-class
finding of the block was the CoordinatorPhases phantom-presence bug (a
staleness/honesty bug, not a contract-shape one).

### Bugs fixed (1)

1. CoordinatorPhases now annotates a possibly-stale active run (>30min since
   `step_started_at ?? started_at`) with an amber in-panel hint instead of
   presenting it as confidently live; malformed/non-string/unparseable
   timestamps are guarded to "freshness unknown" (no hint) so the fix cannot
   produce a false-stale. Regression-tested in `tests/test_stale_active_run.tsx`
   (7 cases).

**Staleness-hint behavior:** fresh run → stepper, no hint; >30min-old freshest
timestamp → amber `coordinator-stale-hint` AND the stepper still renders
(annotate state, don't hide it); NaN-parsing / non-string / absent timestamps →
no hint, no crash; idle (`activeRun` null) unchanged. Live today the hint has
nothing to annotate: no `active_run.json` on disk, `/active` → 204, so the
panel renders its quiet idle state — the hint path is pinned by the 7 unit
cases. No exported-signature change; uses the existing `useNow`/`elapsed`
idiom, hook called unconditionally before the idle early-return.

### Live (:8700) vs in-process — comparison numbers (2026-06-09 evening)

Both targets read the same on-disk files; they agree on every count.

| Probe | Live :8700 | In-process / on-disk |
| --- | --- | --- |
| `/api/health` | `ok:true`, version `5ddff08` | = current HEAD (not a stale binary) |
| `/api/coordinator/cycles` | **73 rows**, all carrying the 7 non-optional `CoordinatorCycle` keys | `coordinator_cycles.jsonl` = **73 lines** (grew from 19 at the earlier validation; the test's ≥19 floor is a documented lower bound and stays green) |
| `/api/coordinator/active` | **204** | no `active_run.json` on disk — agree |
| `/findings` / `/bubbles` / `/health_signals` | wrapper shape correct, **0 rows each** | files still absent live — matches the earlier EMIT-side observation |

### Followups deferred to WF-B / the gated render task

- **After the primary's close-out confirms shapes** (serial-integrator change,
  forbidden during this probe per the additive-contract freeze):
  `types/schemas.ts` gains the optional fields — critique
  `verdict_overridden_from` / `override_reason` / `skeptic_verdict` (+
  `"undecidable"` in the verdict union), `novelty.novelty_axes`, the five
  relevance siblings — and the inline `as unknown as IterationRecord` literals
  in the four `test_forwardcompat_*` files can be narrowed / promoted into
  `src/fixtures/`.
- **Gated render task** (deliberately NOT built here; the forward-compat tests
  pin the fields as inert and will need updating when it lands): surface
  `novelty_axes`, override provenance, and `relevance.category`/`rule_fired`
  (badge tooltip); optionally a dedicated `undecidable` tone in
  `VERDICT_TONE` (one line in SurfacedFindingsPanel + the matching palette in
  ResolvedIterationsList — keep the two in sync).
- **Cosmetic, not a crash:** ResolvedIterationsList filter dropdowns use the
  fixed legacy enum lists — `undecidable` rows render fine but cannot be
  filter-selected; same for new `novelty_axes` values. Fold into the gated
  render task.
- `test_live_8700.py`'s cycles floor (≥19) is deliberately a lower bound; live
  is at 73. If `coordinator_cycles.jsonl` is ever rotated/reset, the floor
  needs a matching revision — documented in the test docstring.

## WF-C — reconciliation operable slice (2026-06-09, serial integrator)

The operable slice of `observability_reconciliation_plan.md` (B1 + B2 + B3 +
B5-light), four build agents fanned out + this serial-integrator wiring pass.

### What shipped

- **B1 — SystemActivityHero** (`components/SystemActivityHero.tsx`, pure +
  `computeActivity` unit-tested): three-state RUNNING (emerald, registered
  run named) / BUSY-unregistered (amber — calls flowing OR vllm running
  requests OR GPU > 20% with no registered run; "activity without
  provenance") / IDLE (zinc). Wired into `routes/Dashboard.tsx` directly
  under the HealthVerdict hero, fed by a 7 s poll of
  `getActivityMonitor(1).live_calls` + the latest clean telemetry sample +
  `getActiveIteration()` + `getCoordinatorActive()` (204 → null → that
  absence is the amber signal). GPU-at-96% can no longer coexist with
  "idle/nominal".
- **B2 — failed-dispatch grouping** on /activity: identical
  (topic, action, error) failures collapse to one row with ×count +
  first/last timestamps (the 12 `noop · FASE · RuntimeError: boom` rows
  render as one line).
- **B3 — HUMAN TODO, read-only**: backend `GET /api/human_todo`
  (`backend/human_todo.py`, registered in `app.py`) composing the five
  sources; `HumanTodoPanel` mounted PROMINENTLY on the Dashboard (below the
  hero block, above the model panels) and on a new page-width **/todo**
  route with a "todo" nav tab. Each item carries the exact copy-pastable
  resolve command (verified against `orchestrator/gate_cli.py` argparse:
  `--iteration-id <id> --verdict <valid|invalid|needs_revision>`).
- **B5-light — drill-into links**: activity hero → /activity, Autonomy
  block → /coordinator, recent-iterations → /activity (react-router
  `<Link>`s; Dashboard tests now render under MemoryRouter).
- Integrator fix: panel kind-label aliases `bubble_ack` / `state_gate`
  added to match the producer's exact KINDS (additive; the original
  spellings kept so prior fixtures stay humanized).

### Live smoke (in-process TestClient(create_app()), REAL repo data)

`GET /api/human_todo` → 200, counts:
`{"gate_verdict": 11, "finding_review": 0, "bubble_ack": 0,
"stale_active_run": 0, "state_gate": 0}` — the 11 pending-gate iterations
from the screenshot complaint are now a first-class surface, oldest first
(`iter-2026-06-05-002` since 2026-06-05T00:26Z), each with its verbatim
`gate_cli` resolve command.

### Suites

- `npx tsc --noEmit` — clean.
- frontend `npx vitest run` — **698 passed** (floor 678; growth only).
- backend `pytest backend/tests -q` — **215 passed** (floor 202).

### Stays gated on the main session

- **B4 write-back** (valid/invalid/needs_revision buttons, bubble ack):
  gated on the A5 CLI-contract blessing; `orchestrator/ack_cli.py` does not
  exist yet — the bubble_ack resolve_command carries the A5 placeholder.
- **A1–A4 producer fixes** (active_run mirror registration, `set_run_id`
  lifecycle, `task_type` stamping, test/dev hygiene for live artifacts):
  until they land, the amber busy-but-unregistered hero state and the
  stale-run_id attribution will show often — rendered honestly by design.

## WF-B — confirmed contract + gated re-validation (2026-06-09 late evening)

The gated render task: build the renders for the close-out-CONFIRMED additive
contract (`docs/ui_validation_handoff.md` §"2026-06-09 evening additions"),
plus the live re-validation against the real artifacts. Three build limbs +
this serial-integrator pass.

### Suites (all green, growth-only)

| Suite | Result | Prior floor |
| --- | --- | --- |
| `npx tsc --noEmit` | clean | clean |
| `npx vitest run` | **62 files / 730 tests passed** | 698 (WF-C) |
| `pytest backend/tests -q` | **215 passed** | 215 (WF-C; no backend change in WF-B) |

No test weakened or deleted; the one WF-A pin that the brief *scheduled* for
relax was updated by the integrator (coordinated relax, below).

### Confirmed-vs-announced divergences

1. **Undecidable tone shade.** The close-out's example shade
   (`bg-zinc-700/40 text-zinc-300`) collides with the WF-A forward-compat pins
   (`test_forwardcompat_iterations_list` / `_findings_panel` hard-assert the
   `bg-zinc-800` + `text-zinc-400` quiet family). **`bg-zinc-800/40
   text-zinc-400` was chosen instead** — satisfies the pins AND keeps the
   close-out's deliberate `/40`-translucency "intentional quiet-grey, not the
   unknown-enum fallback" intent. Integrator decision: KEEP the chosen shade;
   no pin relax needed. If the exact suggested shade is ever wanted, both WF-A
   pin files need a coordinated edit.
2. **`types/schemas.ts` already declared the five additive relevance keys**
   (`anchor_cosine`/`curated_overlap`/`neighbor_spread`/`category`/
   `rule_fired`, with `category` typed as the announced enum `| string`) —
   no type change was needed for that block; the WF-B type additions were the
   novelty/critique side (`novelty_axes`, `low_confidence`, the override trio,
   `"undecidable"` in the verdict union).
3. Everything else matched the announcement exactly: `critique.verdict
   "undecidable"`, the `verdict_overridden_from`/`override_reason`/
   `skeptic_verdict` trio on both blocks, `novelty_axes`
   `{phenomenon, substrate, predicted_direction}` (nullable).

### The three new renders

1. **Undecidable verdict chip** — quiet-grey `/40` in BOTH
   `ResolvedIterationsList.VERDICT_TONE` and
   `SurfacedFindingsPanel.VERDICT_TONE` (kept in sync per the WF-A followup),
   plus **override-provenance tooltips** on the novelty AND critique badges
   (`overrideTooltip`: "overridden from X; skeptic said Y" — garbled fields
   dropped via the scalar coercion, never `[object Object]` in a title).
   `override_reason` is deliberately NOT surfaced (tooltip spec carries only
   `verdict_overridden_from` + `skeptic_verdict`); see followups.
   Pinned in `test_undecidable_verdict.tsx`.
2. **`NoveltyAxesChip`** (new component) — the decomposed novelty judgment as
   one scannable token `axes: phenomenon/substrate/direction`; the
   transfer/replication bucket (`known`/`unstudied_llm`) reads **cyan**
   (`bg-cyan-950 text-cyan-300` — previously unused across components, now
   reserved for that meaning), every other combination quiet zinc; non-object
   axes / all-garbage values render nothing. Pinned in
   `test_novelty_axes_chip.tsx`. **Wired into the `ResolvedIterationsList`
   row by this integrator pass** (one element after the novelty badge).
3. **Relevance diagnostics in the low-evidence tooltip** —
   `LowEvidenceBadge.reason()` now folds `category: X` / `rule: Y` into the
   tooltip when usable. Detail only: the five new keys NEVER decide the
   verdict (`isLowEvidence`'s pinned contract — driven by the
   `low_confidence` boolean + structural triggers).

### Integrator actions (this pass)

- Wired `NoveltyAxesChip` into the `ResolvedIterationsList` row + a
  one-assertion presence test (3 chips on `ITERATIONS_OBSERVABILITY_FIXTURE`)
  in `test_resolved_iterations_list.tsx`.
- **Coordinated relax of WF-A pin (b)** in
  `test_forwardcompat_iterations_list.tsx`: the pin's own comment marked the
  axes render as "a later, gated task" — this run is that task. The pin now
  asserts the axes render THROUGH the chip as plain strings
  (`axes: novel/unstudied_llm/deviates`) and the raw OBJECT still never
  reaches a React child; case (e) additionally pins that a garbled
  (string-valued) `novelty_axes` produces NO chip.
- **`undecidable` is now filter-selectable** (added to `VERDICT_CLASSES` in
  the verdict dropdown — it is a real producible verdict; an auditor can pull
  the undecided rows). The one screen-level `getByText("undecidable")` in
  `test_revalidate_live_rows.tsx` was scoped to its row (it would otherwise
  be ambiguous with the new `<option>` label).
- Suite run + this report + `emit_test_plan.md` dispositions.

### Live numbers (2026-06-09 ~21:08 UTC; :8700 version `5ddff08`, healthy)

```
memory/loop_memory.jsonl            52 rows
  seed.source: {human_cli: 34, loop_memory_probe: 15, nemoclaw_agent: 2, coordinator: 1}
  critique.verdict census: {survives: 35, falsified: 6}   ← ZERO undecidable live
  retrieval.relevance present: 4    low_confidence==true: 0   ← flag still has no live trigger
  relevance keys live: {relevance, low_confidence, reason} only ← five additive keys not yet emitted
  novelty.novelty_axes present: 0   override fields present: 0
run_state/coordinator_cycles.jsonl  133 rows (was 73 at WF-A; 22 errored)
  dispatched_iteration_id present: 0 / 133
run_state/health_signals.jsonl      ABSENT
memory/surfaced_findings.jsonl      ABSENT
memory/coordinator_bubbles.jsonl    ABSENT
run_state/active_run.json           ABSENT   (/api/coordinator/active → 204)
```

Every NEW-shape render is therefore fixture/synthetic-pinned TODAY; the
live-census loops in `test_revalidate_live_rows.tsx` (undecidable /
novelty_axes / relevance.category / findings / bubbles) branch on the REAL
artifacts and **auto-validate each future live row on every suite run** — no
re-dispatch needed when the data lands. The two real `nemoclaw_agent` rows
(`iter-2026-06-09-003`/`-004`) are pasted verbatim as permanent render pins.

### Per-gap disposition (gaps 1–5, `emit_test_plan.md`)

| Gap | Disposition | Evidence |
| --- | --- | --- |
| 1. Low-evidence flag live trigger | **DEFERRED-no-live-data-yet** | 0/4 relevance rows carry `low_confidence==true`; render + tooltip (now with category/rule detail) proven on fixtures + WF-A/WF-B pins. The genuine off-domain re-run appears to have landed ON-domain (see followups) — needs the primary to confirm/emit the real row; the live-census test then bites automatically. |
| 2. Findings / bubbles / health panels populated | **DEFERRED-no-live-data-yet** | All three files still ABSENT. `test_revalidate_live_rows.tsx` branches on real file state (honest empty today; real rows when present). Health-signals populated path remains fixture-pinned only. |
| 3. `active_run.json` mid-flight | **DEFERRED-no-live-data-yet** | File absent; `/active` → 204. Stepper + staleness hint pinned by unit cases (WF-A). |
| 4. `dispatched_iteration_id` on a cycle | **DEFERRED-no-live-data-yet** | 0/133 cycles carry it (all errored or no dispatch). Footer-link render fixture-pinned. |
| 5. `nemoclaw_agent` end-to-end | **CLOSED (UI side)** | 2 live rows render violet end-to-end; both pinned VERBATIM in `test_revalidate_live_rows.tsx` (full row contract: violet badge, novel/survives, red redteam chip, NO low-evidence flag). EMIT-side schema-enum test remains the primary's last mile. |

### Followups (out of UI scope — for the primary / EMIT session)

1. **Low-evidence live row**: either (a) append the genuine
   `low_confidence=true` row to `memory/loop_memory.jsonl` (the re-run appears
   to have landed on-domain) or (b) confirm which iteration_id was meant. Once
   it lands, the live-census loop validates it automatically; a verbatim-pin
   test (à la the nemoclaw rows) plus the on-domain negative control against
   `iter-2026-06-09-002` can then be added.
2. **Emit the three artifacts**: `run_state/health_signals.jsonl`
   (`ml_intern_zero_papers` row), a cycle row carrying
   `dispatched_iteration_id`, and a mid-flight `run_state/active_run.json`
   snapshot — gaps 2–4 close themselves against the existing tests.
3. **`iter-2026-06-09-001` absent-relevance stance**: `isLowEvidence` treats
   an ABSENT relevance block as not-low-evidence (conservative). If the EMIT
   side decides that row SHOULD flag, that is a contract change needing an
   explicit decision before any UI edit.
4. **`override_reason`** (free-text) is intentionally not surfaced; fold into
   the tooltip or a detail view later if auditors want it.
5. **Local `asText` copies** now exist in SourceBadge / SurfacedFindingsPanel /
   NoveltyAxesChip / LowEvidenceBadge (parallel-limb shared-file rule barred
   hoisting). Deliberately NOT consolidated this pass (inviolate rule 8:
   resist abstraction; no exported-signature changes during integration) —
   a future shared `lib/coerce.ts` is the natural home if one more consumer
   appears.
6. **Tone registry note**: cyan (`bg-cyan-950 text-cyan-300`) is now the
   transfer/replication emphasis tone — keep it reserved for that meaning.
