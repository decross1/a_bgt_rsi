# Cockpit seam wiring — the authoritative per-outcome writer spec (U4)

**Status: VERIFIED against landed code on 2026-06-17.** This doc is the
authoritative wiring contract the UI session (U4) wires the `/todo` cockpit
to. It supersedes the earlier optimistic framing ("flip the flags / argv
already match"): the P5 reconciliation found that `ui/backend/todo_cockpit.py`'s
`_SEAM_MODULES` **mis-targets several seams**, so a few of the stub's
`would_run` argv arrays point at the wrong module (and one at the wrong
identity key). Those are `ui/backend` corrections — listed explicitly in the
"ui/backend U4 fixes" section — NOT orchestrator gaps.

With P1–P4 landed, **every one of the six resolution outcomes, plus
calibration and the tutor / two-voice chat seams, has a LANDED writer of
record.** There is **no orchestrator gap that blocks U4.** This is a doc-only
reconciliation (orchestrator code built: none).

Governing rules: **D-046** — the CLI is the writer of record; `ui/backend`
only execs blessed argv arrays and NEVER writes ledgers directly. **Inviolate
rule 4** — out-of-enum / out-of-range / empty-required inputs exit nonzero and
write NOTHING (the CLI re-validates authoritatively; the UI's checks are
UX-only). **Inviolate rule 8** — bounded codegen: no one-shot spawn/abstain
writers are built (the reconciliation concludes they are neither required nor
contract-permitted).

## Per-outcome wiring table

Legend for **wiring class**:
- **one-shot** — a single blessed CLI exec (the `attest._exec_blessed` pattern).
- **chat-seam** — a `finding_session chat start|turn` exec whose stdout is a
  single-line JSON envelope the cockpit parses; NOT a `would_run` one-shot.
- **session-exit** — a terminal `end_session` outcome reached through the
  interrogation REPL / chat session; NOT a one-shot button (see disposition).

`PY` = `.venv-chroma/bin/python` (absolutized under the primary repo root by
`attest._exec_blessed`). `IDENTITY` = `human:ui`.

| # | Outcome | Writer module | Exact argv | Identity key | Wiring class | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | **sign_off** (bare) | `orchestrator.finding_session` (`set_status`) | `PY -m orchestrator.finding_session --set-status <FINDING_ID> validated --note <why> --by human:ui` | `finding_id` | one-shot (attest reuse: `POST /api/attest/finding_review`) | **landed** — writer + attest endpoint both landed (attest.py:219-222) |
| 1d | **directive_signoff** (outcome 1 variant) | `orchestrator.finding_session` (`set_status`, `--directive`) | `PY -m orchestrator.finding_session --set-status <FINDING_ID> validated --note <why> --directive <next-step> --by human:ui` | `finding_id` | one-shot (clean superset of bare sign_off) | **landed** — `--directive` flag on the `--set-status` branch (finding_session.py:1303, 1121-1122); recorded on the `status_audit_row` only (loop_feedback schema stays frozen). **Cockpit stub MIS-TARGETS** `gate_cli` keyed on `iteration_id` — U4 fix below |
| 2 | **reject** | `orchestrator.finding_session` (`set_status`) | `PY -m orchestrator.finding_session --set-status <FINDING_ID> rejected --note <why> --by human:ui` | `finding_id` | one-shot (attest reuse: `POST /api/attest/finding_review`) | **landed** |
| 3 | **refine_defer** | `orchestrator.todo_cli` (`defer`) | `PY -m orchestrator.todo_cli defer --kind <gate_verdict\|finding_review\|bubble_ack\|stale_active_run\|state_gate> --ref-id <id> --note <why> --by human:ui` | `ref_id` (the TODO item id; `--kind` names the queue) | one-shot (attest reuse: `POST /api/attest/defer`) | **landed** — attest.py:250-256; `DEFER_KINDS` todo_cli.py:32-38 |
| 4 | **authorize_fix** | `orchestrator.authorize_fix` | `PY -m orchestrator.authorize_fix authorize-fix --ref-id <id> --task <statement> --note <why> --by human:ui` | `ref_id` (must resolve to a finding / open deferral / coordinator bubble or exit 1) | one-shot CLI | **landed** (2f4ceaf). **Cockpit stub MIS-TARGETS** `orchestrator.todo_cli` (no `authorize-fix` subcommand there) — U4 fix below |
| 5 | **spawn_topic** | `orchestrator.finding_session` (`end_session`, outcome=`spawn_topic`) | session REPL exit: `/spawn <topic>` → `end_session(..., outcome="spawn_topic", new_topic=...)` → writes `memory/finding_followups.jsonl`. **No one-shot CLI verb exists.** | `finding_id` (via the open session) | **session-exit** | **landed-as-session-exit** — the only writer is `end_session` (finding_session.py:987-1009). The cockpit stub's `spawn-topic` one-shot argv targets a verb `finding_session` does NOT expose — U4 renders as a session exit, NOT a one-shot button |
| 6 | **abstain** | `orchestrator.finding_session` (`end_session`, outcome=`abandoned`) | session REPL exit: `/quit` → `end_session(..., outcome="abandoned", note=...)` → session-local `feedback` event only (NO verdict ledger). **No one-shot CLI verb exists.** | `finding_id` (via the open session) | **session-exit** | **landed-as-session-exit** — finding_session.py:1028; the stub's `abstain` one-shot argv targets a non-existent verb — U4 renders as a session exit |
| — | **gate_verdict** (the cockpit's gate-disposition path — the verdict edge, not one of the 6 finding outcomes) | `orchestrator.gate_cli` | `PY -m orchestrator.gate_cli --iteration-id <ITER_ID> --verdict <valid\|invalid\|needs_revision> --note <why> --gated-by human:ui` | `iteration_id` | one-shot (attest reuse: `POST /api/attest/gate`) | **landed** — attest.py:200-204; `gate_cli` has NO subcommand, flags only (gate_cli.py:72-78) |
| — | **calibration** (pre-verdict) | `orchestrator.calibration_cli` | `PY -m orchestrator.calibration_cli calibration --ref-id <id> --prediction <text> --confidence <0..1> --by human:ui` | `ref_id` (the surfaced finding) | one-shot CLI | **landed** (P4) — appends to `run_state/events.jsonl` validated against `schema/calibration_pre_verdict.schema.json` (calibration_cli.py:113-139). **Cockpit stub MIS-TARGETS** `gate_cli` — U4 fix below |
| — | **tutor chat** | `orchestrator.finding_session` (`_chat_cli`) | `PY -m orchestrator.finding_session chat start --mode tutor --finding-id <id>` THEN `chat turn --mode tutor --finding-id <id> --session-id <sid> --message <text>` | `finding_id` (+ `session_id` after start) | **chat-seam** (single-line JSON envelope; verdict-fenced) | **landed** (P1) — `--addressee` is INVALID in tutor mode (single-voice; finding_session.py:1159-1162) |
| — | **two_voice chat** | `orchestrator.finding_session` (`_chat_cli`) | `PY -m orchestrator.finding_session chat start --mode two_voice --finding-id <id>` THEN `chat turn --mode two_voice --finding-id <id> --session-id <sid> --message <text> [--addressee defender\|attacker\|both]` | `finding_id` (+ `session_id` after start) | **chat-seam** (single-line JSON envelope; defender = vllm-gemma, attacker = vllm-qwen) | **landed** (P2) — cockpit gates this on `actions["two_voice_chat"]` (todo_cockpit.py:178), which can flip True now |

### Chat-seam envelope shape (tutor + two_voice)

`_chat_cli` exposes **only** `start` and `turn` — there is **no verdict verb**
on the chat branch (the verdict fence; finding_session.py:1139-1210,
1149). On success it emits exactly **one JSON line on stdout, exit 0**; on
error a JSON error envelope on stderr, **empty stdout**, exit 1. The cockpit
parses stdout-on-success / stderr-on-failure. Keys:

- `start`: `{ok, mode, action:"start", finding_id, session_id, stances}`
  (`stances` is null in tutor mode, the two-stance object in two_voice).
- `turn` (tutor): `{ok, mode, action:"turn", finding_id, session_id,
  turn_index, capped, warning:null, replies:[{stance:null, reply, request_id}]}`.
- `turn` (two_voice): `{ok, mode, action:"turn", finding_id, session_id,
  turn_index, capped, addressee, warning, replies:[...]}`.

A tutor session is **verdict-fenced** in `end_session` too (finding_session.py:937-938):
a tutor transcript can never be closed with a disposition — it rejects before
any ledger write.

## ui/backend U4 fixes (the corrections the UI session makes in `ui/`)

These are **`ui/backend/todo_cockpit.py` defects** — the stub's `_SEAM_MODULES`
mappings and a `would_run` argv. The orchestrator side is correct and landed;
only the cockpit's module targets / one identity key are wrong. **This doc does
NOT edit `ui/` (a UI session is live).** It documents the corrections for the
U4 work order.

### Mis-targeted `_SEAM_MODULES` (todo_cockpit.py:56-63)

1. **`authorize_fix`** is mapped to `("orchestrator.todo_cli", …)` — **WRONG.**
   `todo_cli` exposes only `ack` / `defer` / `close` / `list-deferred`
   (todo_cli.py:165-197); there is NO `authorize-fix` subcommand there.
   **Correct target:** `("orchestrator.authorize_fix", orchestrator/authorize_fix.py)`.
   The argv token `authorize-fix` and the flags (`--ref-id` / `--task` /
   `--note` / `--by`) in the stub's `would_run` are already correct — only the
   **module** is mis-targeted.

2. **`calibration`** is mapped to `("orchestrator.gate_cli", …)` — **WRONG.**
   `gate_cli` is flag-only (`--iteration-id` / `--verdict` / `--note` /
   `--gated-by`); it has no `calibration` subcommand.
   **Correct target:** `("orchestrator.calibration_cli", orchestrator/calibration_cli.py)`.
   The `would_run` subcommand token `calibration` + flags are correct; only the
   **module** is mis-targeted. (Nuance: the stub emits `--confidence` via
   `repr(float(confidence))`; `calibration_cli` parses `--confidence` with
   `type=float`, so the float `repr` round-trips — e.g. `repr(0.1) == "0.1"` —
   fine, but confirm during the swap.)

3. **`directive_signoff`** is mapped to `("orchestrator.gate_cli", …)` —
   **WRONG ON TWO COUNTS.**
   - **(module)** Directive sign-off is `finding_session --set-status` with the
     `--directive` flag — NOT `gate_cli` (which has no `--directive` flag and
     writes `loop_feedback` keyed on `iteration_id`).
   - **(identity key)** The stub's `would_run` keys on `iteration_id` with
     verdict-style argv (`--iteration-id` / `--verdict valid` / `--directive` /
     `--gated-by`; todo_cockpit.py:205-223) — but the writer needs a
     **`finding_id`**.
   **Correct argv:** `PY -m orchestrator.finding_session --set-status
   <FINDING_ID> validated --note <why> --directive <next-step> --by human:ui`.
   The directive lands on the `status_audit_row` only; the `loop_feedback`
   schema stays frozen. **The cockpit endpoint must collect `finding_id`, not
   `iteration_id`.**

### Fictional one-shot argv (spawn_topic + abstain; todo_cockpit.py:225-258)

The `spawn_topic` and `abstain` endpoints emit `would_run` for one-shot
`spawn-topic` / `abstain` subcommands that **DO NOT EXIST** on `finding_session`
(main dispatch has only `chat` / `--set-status` / REPL — finding_session.py:1284-1314).
Per the disposition below, these should **NOT be one-shot POSTs at all** —
render them as **session-exits off the chat seam**. The stub correctly keeps
them `stub:false` in `/available`, but the `would_run` argv is fictional and
should be removed / re-shaped to a session-exit, not flipped to "available".

### Capability flags (`GET /api/todo/available`, todo_cockpit.py:162-184)

When the integrator swaps the stubs for real execs, the per-action existence
checks must point at the **corrected** modules above:
`authorize_fix.py` for `authorize_fix`; `calibration_cli.py` for `calibration`;
`finding_session.py` for `directive_signoff`. The **`two_voice_chat` flag
(todo_cockpit.py:178) can flip `True` now** (the chat seam landed P1/P2). The
chat seam itself (tutor + two_voice) is **NOT in `_SEAM_MODULES`** (it is a
chat-seam, not a `would_run` one-shot) — the cockpit must add a **chat exec
path** that runs `finding_session chat start|turn` and parses the single-line
JSON stdout envelope (`ok` / `mode` / `action` / `session_id` / `replies`).

## spawn_topic / abstain disposition

**RECOMMENDATION: render spawn_topic (5) and abstain (6) as SESSION-EXITS, not
one-shot buttons. Do NOT build one-shot spawn/abstain writers.**

Contract rationale. `docs/human_writeback_contract.md` (lines 107-116) and
`docs/todo_cockpit_seam_plan.md` (seam 3) both bless these as the in-session
`end_session` terminal outcomes (`spawn_topic` / `abandoned`) reached through
the `finding_session` interrogation REPL / two-voice session — "they need the
conversation" (D-046). The contract states plainly: "The UI renders them as
session exits, not one-shot buttons."

Landed-code confirmation. There is **NO one-shot CLI verb** for either:
`end_session` is the only writer for `spawn_topic` / `abandoned`
(finding_session.py:987-1009 / 1028), reachable via the REPL (`/spawn`,
`/quit`; finding_session.py:1261-1268) or programmatically from a session.
`QUICK_STATUSES` — the one-shot `--set-status` enum — **deliberately excludes**
`spawn_topic` / `refine` (finding_session.py:1051: comment "spawn/refine stay
session-only — they need the conversation").

Why not build them. One-shot writers would (a) duplicate `end_session`,
violating inviolate rule 8 (bounded codegen / resist abstraction), and (b)
contradict the blessed contract. The cockpit chat-seam (tutor / two_voice,
landed) IS the conversation surface; the natural UI shape is: the human runs a
chat session, then exits it into spawn_topic or abstain.

**Caveat for the U4 work order.** `end_session` is currently **NOT exposed by
the chat CLI** — `_chat_cli` exposes ONLY `start` / `turn` (the verdict fence).
So a contract-consistent in-UI session-exit would need an exit verb. Two
options for the integrator / UI to decide:

- **(i) — default, no new code.** The human runs `end_session` from a terminal
  REPL (`/spawn`, `/quit`). Fully blessed today; nothing to build.
- **(ii) — narrow orchestrator addition (only if U4 shows an in-UI exit is
  genuinely needed).** Add an `end` action to the chat CLI that maps to
  `end_session` for the two non-verdict outcomes only (`spawn_topic`,
  `abandoned`), preserving the tutor verdict fence. This is an explicitly-scoped
  small follow-up, NOT a standalone one-shot writer.

Default to **(i)** (session-exit framing). Treat **(ii)** as a small, scoped
orchestrator follow-up only if U4 surfaces a genuine in-UI exit requirement.
Either way: **NO standalone one-shot spawn/abstain CLI.**

## allowed_actions → cockpit endpoint name map (for U4)

`schema/escalation.schema.json` `allowed_actions` enum uses
`sign_off` / `reject` / `refine_defer` / `refine_authorize_fix` /
`spawn_topic` / `abstain`, while the cockpit POST routes are named
`authorize_fix` (not `refine_authorize_fix`) and `directive_signoff` (a variant
of `sign_off` not in the enum). The UI maps escalation `allowed_actions` →
cockpit endpoints:

| escalation `allowed_actions` | cockpit endpoint(s) |
| --- | --- |
| `sign_off` | `/directive_signoff` (with directive) and the bare sign_off via attest `/finding_review` (validated) |
| `reject` | attest `/finding_review` (rejected) |
| `refine_defer` | `/defer` (attest) |
| `refine_authorize_fix` | `/authorize_fix` |
| `spawn_topic` | session-exit (chat seam → `end_session` spawn_topic) |
| `abstain` | session-exit (chat seam → `end_session` abandoned) |

Document this map so an escalation that allows `refine_authorize_fix` lights up
the `authorize_fix` form, and `sign_off` covers both bare and directive
sign-off.

## Open questions (for the U4 work order)

1. **In-UI session exit for spawn_topic / abstain.** Does U4 require an IN-UI
   session exit (forcing the narrow chat-CLI `end` addition, option (ii)), or is
   a terminal-run `end_session` acceptable for v1? Integrator / human decision;
   the contract permits either; default is the no-new-code session-exit.
2. **`calibration_cli` spine reconciliation — RESOLVED (D-055).**
   `schema/events.jsonl.schema.json` already owned `event_type
   "calibration_entry"` for the post-experiment shape. The integrator reconciled
   it in **D-055**: an additive `phase: "pre_verdict"` `oneOf` branch, so a
   pre-verdict row validates against both `schema/calibration_pre_verdict.schema.json`
   (the writer's focused schema) and the `events.jsonl` spine schema. No action
   for U4. (Open: the human may still *redirect* D-055 to a distinct `event_type`
   — small, reversible — but nothing is pending for the cockpit wiring.)
3. **`allowed_actions` naming map** (above) — confirm it is documented so the UI
   maps escalation actions to the correctly-named cockpit endpoints.

## Verification note

Verified against landed code on **2026-06-17**:
- `ui/backend/todo_cockpit.py` — `_SEAM_MODULES` mis-targets (authorize_fix→todo_cli,
  calibration→gate_cli, directive_signoff→gate_cli) at lines 56-63; directive
  `would_run` keys on `iteration_id` at 205-223; spawn_topic/abstain fictional
  one-shot argv at 225-258; `two_voice_chat` flag at 178.
- `orchestrator/authorize_fix.py:221-245` — subcommand `authorize-fix`,
  `--ref-id` / `--task` / `--note` / `--by`; module is `orchestrator.authorize_fix`.
- `orchestrator/calibration_cli.py:113-139` — subcommand `calibration`,
  `--confidence type=float`, writes `run_state/events.jsonl`; the spine schema
  was reconciled in D-055 (additive `pre_verdict` branch in `events.jsonl.schema.json`).
- `orchestrator/gate_cli.py:72-78` — flags only, no subcommand, no `--directive`.
- `orchestrator/finding_session.py` — main dispatch 1284-1314 (`chat` /
  `--set-status` / REPL only); `set_status` 1054-1125 (finding_id key,
  `QUICK_STATUSES` = validated/rejected/in_review, optional `--directive` on
  `status_audit_row`); `_chat_cli` 1139-1210 (start|turn only, verdict-fenced,
  single-line JSON envelope, `--addressee` invalid in tutor); `end_session`
  889-1029 (the only writer for spawn_topic/abandoned; session-only).
- `orchestrator/todo_cli.py:165-197` — `ack` / `defer` / `close` /
  `list-deferred` only (no `authorize-fix`); `DEFER_KINDS` 32-38.
- `ui/backend/attest.py` — gate argv 200-204, finding `--set-status` argv
  219-222, defer argv 250-256 (the blessed reuse writers for outcomes 1-3 +
  the gate edge).
- `docs/human_writeback_contract.md:101-116` — the 6-outcome map (5/6 are
  session-only `end_session` outcomes, NOT one-shot; "renders them as session
  exits, not one-shot buttons").
- `schema/escalation.schema.json` — `allowed_actions` enum.

**Conclusion: doc-only phase. No orchestrator code built — every writer of
record is already landed and tested under `MOCK_LLM`. The remaining defects are
entirely on the `ui/backend` cockpit stub (the U4 fixes above).**
