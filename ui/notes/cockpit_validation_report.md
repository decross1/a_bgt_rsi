# /todo cockpit + dashboard reframe — build & validation report (2026-06-14)

Work order: `human/sessions/2026-06-14.md` "## UI session work order". Built by
the UI session via three Dynamic Workflows + serial integration; scope `ui/` +
`ui_plan.md` only. Full narrative in `ui_plan.md` §2026-06-14.

## Final test state

| Suite | Baseline (pre-sweep) | After harden/validate sweep |
| --- | --- | --- |
| frontend vitest | 903 pass / 75 files | **1255 pass / 91 files** |
| backend pytest | 358 pass | **517 pass** |
| `tsc --noEmit` | clean | clean |

+352 frontend / +159 backend tests, all green. No test was coerced; two existing
tests were updated to the new contract (dashboard no longer mounts the inbox;
`/todo` renders the cockpit).

## What shipped

- **Topicality advisory badge (D-052):** `TopicalityAdvisoryBadge.tsx` — quiet
  zinc, non-gating, fires only on explicit `"off"`. Wired into the resolved list
  + detail modal. `relevance.topicality_advisory` added to `types/schemas.ts`.
- **PART 1 dashboard reframe:** center order HealthVerdict → SystemActivityHero →
  HealthStrip (+ new `HostMemoryTile`, 6th tile) → Vllm+Qwen. `HumanTodoPanel`
  removed from the dashboard; the `SystemActivityHero` `needsYou` slot shows
  `N need you →` (= `counts.gate_verdict + counts.state_gate`, taxonomy A+B only)
  linking `/todo`, in every state.
- **PART 2 `/todo` cockpit (stubbed):** `routes/Todo.tsx` assembles
  ConcurrencyWarning → HumanTodoPanel inbox → pre-verdict CalibrationCapture
  (ordering-gated) → 6 resolution forms (4 blessed reuse + 4 NEW stub forms) →
  TwoVoiceChatPane + fenced TutorPanel. Backend `todo_cockpit.py` serves the NEW
  seams as honest read-only `would_run` stubs (writes nothing). Route + router
  wired in `App.tsx` / `app.py`.

## Adversarial verification — 6 real bugs found & fixed

The harden sweep's adversarial-verify stage broke 6 surfaces that the happy-path
build left fragile, and fixed each (regression-pinned):

1. **SystemActivityHero `needsYou` slot (dashboard-blanking):** a valid React
   element wrapping a producer-derived bad-object child threw at render and
   blanked the whole dashboard → fixed with a scoped `SlotBoundary` error
   boundary (drops to absent-slot, identical to the static `asNode` fallback).
2. **`GET /api/todo/concurrency`:** deeply-malformed/huge/non-dict
   `active_run.json` → hardened to `{active:false}`, never 500.
3. **`api/todo.ts`:** malformed/non-JSON bodies + the error envelope hardened.
4. **AbstainForm**, 5. **DirectiveSignOffField**, 6. **CalibrationCapture:**
   edge-input handling (bounds, ordering contract) hardened.

## Live-data validation (in-process TestClient over the real `_PRIMARY_REPO`)

- `/api/todo/available` → `available:false, stub:true`, all 5 NEW seams + the
  `two_voice_chat` gate report `false`; interpreter present.
- `/api/todo/concurrency` → `{active:false}` (real `active_run.json` absent), 200.
- `/api/human_todo` → real `{items, counts}`; `counts` carries both
  `gate_verdict` (16 live pending) and `state_gate`, the exact keys the dashboard
  coupling sums.
- **Every `/api/todo` POST stub writes nothing:** firing all 5 with valid
  payloads, a before/after snapshot of `memory/` + `run_state/` shows **zero
  delta** (D-046 / inviolate rule 4 verified empirically).

## Known boundary handed to the primary session

The cockpit's NEW resolution outcomes are inert stubs until the four
`docs/todo_cockpit_seam_plan.md` seams ship (two-voice `finding_session.py`, the
generalized escalation schema + coordinator emit, the resolution-outcome CLIs,
the outcome-4 spawn-contract enqueue). The calibration→verdict ordering is a UI
contract (ARCH §6.5.4) today; backend enforcement arrives with those seams. On
landing: flip the per-action flags in `todo_cockpit.py` `/available` and swap
each stub body for an `attest._exec_blessed` call — the argv shapes already match
the seam plan verbatim, so zero churn.
