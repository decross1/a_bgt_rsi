> Design source: ~/.claude/plans/modular-petting-feigenbaum.md (2026-06-13/14 design dialogue), committed per the plans policy.

# `/todo` cockpit — PRIMARY-session orchestrator-seam work order

**Status: BUILT (2026-06-15) — all four seams' primary-session limbs are built
and verified** (tests green under `MOCK_LLM=1`; `tests/` suite 1225 passed / 0
failed; the three new seam test files = 45 passed). Per-seam status markers are
inline below; the spec is retained as the build record. The seam-2 planner-gate
discrepancy the build pinned (the `bubble_up` arg-schema rejected generic
escalations) was CLOSED by the integrator the same day — see seam 2's note. This
was the work order for the *primary-session*
(non-`ui/`) seams that the `/todo` uncertainty-resolution cockpit needs. The `/todo` cockpit itself (chat pane, the six resolution forms,
the `ui/backend` endpoints that exec these CLIs) is the **UI session's** job and
is specified in the day's session note "## UI session work order"; it builds
*against* the seam contracts the primary ships first.

The product target (from the design dialogue): `/todo` becomes the dynamic place
where Nara escalates ANYTHING it is unsure about and the human resolves it
interactively — a two-voice, human-driven interrogation, a generalized
escalation, and a 6-outcome resolution taxonomy. This document covers only the
four seams the **primary** builds.

## Execution discipline (applies to every seam below)

- **Order:** seams build in the order given (1 → 2 → 3 → 4); each is independently
  shippable. Seam 4 depends on seam 3's CLIs existing.
- **Merge gate (the invariant):** every seam lands only via the single
  merge/commit authority — the **framework `code-review` skill** over the local
  commit range + full suite green under `MOCK_LLM=1` + one real `env -u MOCK_LLM`
  smoke. Workflows return reports; they do not commit (CLAUDE.md Dynamic
  Workflow rule 4). This invariant is load-bearing for seam 4 and is NOT relaxed.
- **No new spine churn beyond what each seam names.** The shared spine
  (`orchestrator/nara.py`, `tool_registry.py`, `iteration_record.schema.json`) is
  touched only where a seam explicitly says so, and only by the serial integrator.
- **Writers of record (D-046):** all human dispositions go through CLIs; the UI
  backend never writes `memory/`/`run_state/` directly. New CLIs honor the
  `docs/human_writeback_contract.md` argv discipline (argv array, no shell
  strings, `cwd` = repo root, interpreter `.venv-chroma/bin/python`; out-of-enum
  exits nonzero and writes nothing — inviolate rule 4).

## Seam 1 — two-voice human-driven interrogation (extend `orchestrator/finding_session.py`)

Today `finding_session.py` is a single-defender REPL: one `system_seed` (defender),
`vllm-qwen` default backend, `session_turn` replays the transcript and calls one
model, 5 outcomes via `end_session`, append-only JSONL transcript, `MAX_TURNS=24`.
Extend it to **two stances**, human-directed:

- **Gemma DEFENDS, Qwen ATTACKS.** This honors D-044 independence: the interrogator
  must NOT be the authoring model. Gemma authored the findings, so Gemma is the
  defender and the standing `vllm-qwen` skeptic is the attacker (reuse the existing
  `vllm-qwen` backend; the Gemma-adversary persona from D-044 is NOT what we want
  here — Gemma's role is defense). Each stance gets its own seeded system prompt:
  defender = the existing honest-defender seed; attacker = a skeptic seed that
  mounts the strongest honest attack (fail-open: any failure path stays
  non-committal, never a fabricated concession — mirror `novelty_skeptic.attack()`'s
  `inconclusive`-on-failure discipline).
- **Human-directed turns, NOT a spectator debate.** The human directs topic/flow
  and addresses either stance or both. A turn carries which stance(s) to invoke;
  the transcript records the addressee. Keep the append-only JSONL model (one
  transcript per session); add a `stance` field on `assistant` rows. Do NOT
  rebuild the storage model — extend the row schema.
- **Turn + token caps stay explicit.** Keep the bounded `MAX_TURNS` cap with the
  explicit cap reply (no silent continue past the limit — inviolate rule 7). Token
  caps per call stay as today (`max_tokens` bounded). Both-stances-per-turn counts
  against the same turn budget.
- **Concurrency guard.** The loop and the cockpit reuse the SAME models (Gemma
  gen+defend; Qwen skeptic+attack). Add a warn/queue guard when an iteration is
  mid-flight (`run_state/active_run.json` present) so a cockpit turn does not race a
  live loop iteration. Today a real conflict is rare (single-shot loop + human-paced
  chat); the guard is a warn-and-proceed-or-queue, not a hard block. Surface the
  contention state (the model-health panels already show it).

**Done-when:** a two-stance session can be opened, the human can direct a turn at
defender / attacker / both, the transcript records stance + addressee, caps hold,
the concurrency guard fires under a mid-flight active run; test green under
`MOCK_LLM`.

**BUILT (2026-06-15):** additive in `orchestrator/finding_session.py`
(`start_two_voice_session`, `two_voice_turn`, `_stance_turn`,
`_replay_stance_messages`, `_is_run_live`; `STANCE_BACKEND` =
defender→`vllm-gemma`, attacker→`vllm-qwen`). The single-defender path
(`start_session`/`session_turn`) is unchanged. Stance + addressee are recorded on
the rows; `MAX_TURNS` cap holds with the explicit cap reply (both-stances-in-one
counts as one turn); the concurrency guard is warn-and-proceed (never a fabricated
concession on a call failure — mirrors `novelty_skeptic.attack()`). Tests:
`tests/test_finding_session_twovoice.py` (green under `MOCK_LLM=1`).

## Seam 2 — generalized escalation schema + coordinator `bubble_up` emit + `human_todo` surfacing

Today the coordinator bubble is finding-id-centric and ack-only:
`handle_bubble_up(finding_ids, note)` returns a report entry; `_persist_bubble_up`
writes `{timestamp, run_id, finding_ids, note}` rows to
`memory/coordinator_bubbles.jsonl`; `ui/backend/human_todo.py` surfaces them as
the `bubble_ack` kind (read-receipt only — taxonomy C, not a decision).

Generalize the bubble into a generic escalation so Nara can escalate ANY uncertain
step, not just finding ids:

- **Schema:** an escalation row carries `{question, context, kind, allowed-actions}`
  (plus the existing `run_id`/`timestamp`). `kind` is the escalation taxonomy
  (judgment / blocking-halt / read-receipt — the A/B/C split the design verified);
  `allowed-actions` enumerates which of the 6 resolution outcomes (seam 3) are
  valid for THIS escalation. The legacy `{finding_ids, note}` shape stays valid
  (back-compat — the 16 pending are all finding-id bubbles); new escalations add
  the generic fields. Keep it additive; do not break existing readers.
- **Emit:** the planner's `bubble_up` action is the existing escalation vehicle —
  extend `handle_bubble_up` to accept the generic `{question, context, kind,
  allowed-actions}` payload alongside `finding_ids`, and `_persist_bubble_up` to
  persist it. Execute-only semantics stay (a planned-but-not-executed bubble is
  never recorded as real — rule 4).
- **Surfacing:** `ui/backend/human_todo.py` is `ui/`-owned (UI session writes it).
  The PRIMARY's job is the *contract*: the new escalation-row shape that
  `human_todo` will read, and (if needed) a non-`ui/` reader helper the backend
  can call. Couple the dashboard idle-hero count to real escalations only
  (taxonomy A+B, never C) — that coupling is computed from these rows; the count
  contract is named here, the UI renders it.

**Done-when:** the planner can emit a generic escalation; it persists with the
4-field shape; legacy finding-id bubbles still surface; the A+B-only count
contract is documented; test green under `MOCK_LLM`.

**BUILT (2026-06-15):** `orchestrator/coordinator.py` — `handle_bubble_up`
accepts the generic `{question, context, kind, allowed_actions}` alongside the
legacy `{finding_ids, note}` (back-compat: a legacy call leaves the generic keys
`None`/absent and still surfaces); `_collect_bubble_up`/`_persist_bubble_up` carry
+ persist the generic fields additively (no empty generic keys written on a legacy
bubble); `kind`/`allowed_actions` validate fail-closed (off-enum raises — rule 4).
New `schema/escalation.schema.json` (Draft7) accepts BOTH on-disk forms and
rejects off-enum `kind`/`allowed_actions`. The **A+B-only count contract** is
`count_actionable_escalations()` (kind C / legacy read-receipts excluded). Tests:
`tests/test_coordinator_escalation.py` (green under `MOCK_LLM=1`).

**Planner-gate discrepancy — RESOLVED by the integrator (2026-06-15):** the build
correctly surfaced that `orchestrator/coordinator_actions.py` (the action-validator
spec, originally outside this seam's limb contract) defined `bubble_up` with a
CLOSED arg_schema (`additionalProperties: False`, `required: ["finding_ids"]`), so
`validate_plan` rejected a generic `{question, kind, …}` bubble_up. The integrator
opened it the same day: `bubble_up`'s arg_schema now accepts the legacy finding-id
form OR a generic `{question, context, kind, allowed_actions}` escalation
(`anyOf finding_ids|question`; `additionalProperties` stays closed). The
`kind`/`allowed_actions` ENUMs are deliberately NOT duplicated into the validator —
they stay enforced fail-closed in `handle_bubble_up` (single source of truth), so
the planner gate checks shape only. Done-condition #1 ("the planner can emit a
generic escalation") is now met end-to-end, pinned by
`test_coordinator_escalation.py::test_validator_accepts_generic_bubble_args`
(validates the generic form + the legacy form + rejects an empty bubble).

## Seam 3 — the six resolution-outcome CLIs (writers of record, D-046)

The 6-outcome resolution taxonomy and its writer for each. Four reuse existing
CLIs; two are NET-NEW. All follow `docs/human_writeback_contract.md` argv rules.

| # | Outcome | Writer of record | New? |
| --- | --- | --- | --- |
| 1 | **Sign off** | `finding_session --set-status <id> validated` (one-shot) or `end_session` validated → `loop_feedback` valid + status-audit | reuse |
| 2 | **Reject** | `finding_session --set-status <id> rejected` → invalid verdict (generator steers away / promotion blocks) | reuse |
| 3 | **Refine — defer to a session** | `todo_cli defer --kind <kind> --ref-id <id> --note <why>` → `memory/dev_session_queue.jsonl` (D-046; triaged at startup) | reuse |
| 4 | **Refine — authorize autonomous fix** | NEW `authorize-fix` CLI → enqueues a spawn-contract (seam 4) | **NEW** |
| 5 | **Spawn topic** | `finding_session` spawn_topic outcome → `memory/finding_followups.jsonl` | reuse |
| 6 | **Abstain** | `finding_session` abandoned outcome (session-local feedback event; no verdict — honest exit) | reuse |

Plus one variant on outcome 1: **directive sign-off**. A sign-off MAY carry an
optional directive ("proceed to <next step>") vs a bare "this is fine". The bare
form is the existing validated path. The directive form is **NEW** — a sign-off
CLI (or a `--directive` flag on the sign-off path) that records the directive so
Nara's next planning session can consume it. Specify the argv contract:

- **`authorize-fix`** (outcome 4): `PY -m orchestrator.<module> authorize-fix
  --ref-id <id> --task <statement> --note <why> --by human:ui`. Validates the
  ref-id resolves; writes the spawn-contract enqueue (seam 4); out-of-enum /
  empty-required exits nonzero, writes nothing. Prints the enqueued contract JSON.
- **directive sign-off**: extend the sign-off path with `--directive <next-step>`
  (optional). Empty/absent = bare sign-off (today's behavior). Present = records
  the directive on the verdict/audit row. Argv stays a superset of the existing
  `--set-status validated` contract so the UI degrades cleanly.

Reuse `gate_cli` (the `gate_verdict` kind), `todo_cli defer`,
`finding_session --set-status`, and the followups queue exactly as
`docs/human_writeback_contract.md` blesses them — do NOT re-implement those
writers. Only directive-sign-off and `authorize-fix` are new code.

**Done-when:** each of the 6 outcomes has a named writer with a tested argv
contract; the two NEW CLIs validate-and-reject out-of-enum input; directive
sign-off is a clean superset of the bare path; `docs/human_writeback_contract.md`
gains rows for the two new commands; tests green under `MOCK_LLM`.

**BUILT (2026-06-15):** the four reused writers (`gate_cli`, `todo_cli defer`,
`finding_session --set-status`, the followups queue) are unchanged. The two NEW:
- **`authorize-fix`** (outcome 4) — new module `orchestrator/authorize_fix.py`.
  Argv as specified: `PY -m orchestrator.authorize_fix authorize-fix --ref-id <id>
  --task <statement> --note <why> --by human:ui`. The `authorize-fix` **subcommand
  token** is load-bearing (matches the sibling `todo_cli` writer-of-record shape;
  the bare flat form is rejected — pinned by a test). `--task`/`--note` required
  non-empty; the ref-id must resolve (finding / open deferral / coordinator bubble)
  or it **fails closed** (`rejected: …`, exit 1, nothing written — rule 4). Prints
  the enqueued row (full `contract` block nested) on stdout. Writer of record =
  `memory/authorize_fix_queue.jsonl` (NOT `run_state/spawn.jsonl`).
- **directive sign-off** — `--directive <next-step>` optional flag added to the
  existing `finding_session --set-status` path (and the in-session `end_session`
  validated path). Omit it → identical to today's bare sign-off (clean superset, UI
  degrades cleanly). Present → recorded on the status-audit row
  (`status_audit_row.directive`) only; the frozen `loop_feedback` schema is NOT
  extended.

`docs/human_writeback_contract.md` gained both argv rows + the full 6-outcome
mapping table (this session). Tests: `tests/test_authorize_fix.py` and the
directive cases in `tests/test_finding_session_twovoice.py` (green under
`MOCK_LLM=1`).

## Seam 4 — outcome-4 spawn-contract-on-approve (the gated autonomy boundary)

This is the one seam with a real autonomy boundary. The design locks the SHIP
scope and stages the rest with **no schema change**.

- **SHIP option (i):** approve (outcome 4) **enqueues a spawn-contract** that the
  **next dev session dispatches**. The human approval authorizes the WORK, not an
  unreviewed merge. The flow: `authorize-fix` → a spawn-contract enqueue row →
  (next dev session) the primary picks it up, dispatches a coding agent under the
  `spawn-contract` skill (ledger `run_state/spawn.jsonl`) → the agent returns a
  branch + tests + report → the primary merges under the merge gate. Nothing
  dispatches automatically at approve time.
- **Shape the enqueue for option (ii) with NO schema change.** Option (ii) is the
  documented TARGET (Nara/an autonomous dispatcher consumes the enqueue later;
  eventually clears the gate under D-040 bounds) but is NOT committed now. The
  enqueue row therefore carries everything an autonomous dispatcher would need —
  the full spawn-contract block `{task_statement, done_condition, skill_subset,
  authority_cap, self_gating_rules, reporting_format, escalation_path, budget,
  state_basis}` (per the spawn-contract skill / CLAUDE.md Dynamic Workflow rule 3)
  — so a future dispatcher reads the SAME rows with no migration. Ship (i)
  consumes it manually; (ii) consumes it programmatically. Same schema.
- **Preserve the merge-gate invariant.** Even at option (ii), a coding agent
  returns a branch + tests + report; the primary session stays the SINGLE
  merge/commit authority; the framework `code-review` + full-suite + smoke gate is
  not bypassed. Auto-dispatch ≠ auto-merge. Do not weaken this.
- **Preserve the runtime firewall (D-014).** The Gemma/Nara RUNTIME does not
  dispatch coding agents today — dispatch is dev-time (primary session + the
  Workflow primitive). A UI approval that triggered *immediate runtime dispatch*
  would be a new boundary crossing the firewall; option (i) deliberately does NOT
  cross it (the enqueue is consumed by a human-driven dev session). Crossing it
  for (ii) is an explicit future decision, annotated on D-014 when wired (D-044
  precedent for narrow annotated exceptions). Until then, the firewall stands.

**Done-when:** `authorize-fix` enqueues a full-spawn-contract-shaped row; option
(i) is the only consuming path (dev session dispatches; primary merges); the row
schema is sufficient for an autonomous (ii) consumer with no change; the
merge-gate invariant and the D-014 firewall are intact and explicitly documented;
test green under `MOCK_LLM`.

**BUILT (2026-06-15):** realized by `orchestrator/authorize_fix.py` (seam 3's NEW
CLI). The enqueue row carries the FULL spawn-contract block — `{task_statement,
done_condition, skill_subset, authority_cap, self_gating_rules, reporting_format,
escalation_path, budget, state_basis}` — so a future stage-(ii) dispatcher reads
the SAME rows with NO schema migration (a test asserts every field is present and
non-empty). Option (i) is the only consuming path: the enqueue is written to
`memory/authorize_fix_queue.jsonl`, NOT the live `run_state/spawn.jsonl` ledger
(that is written at actual dispatch). The merge-gate invariant + the D-014 runtime
firewall are encoded IN the row (`authority_cap` says "do NOT merge"; `state_basis`
= `HEAD@dispatch`; `self_gating_rules` says dispatch is dev-time only) and are
verified by `tests/test_authorize_fix.py`. Nothing dispatches at approve time; no
firewall crossing — stage-(ii) auto-dispatch stays the documented, un-built target.

## DECISIONS implication (future, append-only)

When these seams land, the escalation/outcome model + the graduated outcome-4
boundary (ship (i), target (ii)/(iii) under D-040) is a new append-only
`DECISIONS.md` entry — NOT a draft file, NOT written now. D-052 is already
ratified and is a separate concern. Do not pre-write a decision draft.

## Out of scope (this work order)

- Anything under `ui/` or the root `ui_plan.md` — UI-session-owned.
- The dashboard layout reorder/coupling beyond naming the A+B escalation-count
  contract (seam 2) — that render work is the UI session's.
- Option (ii)/(iii) autonomous dispatch implementation — documented target, not
  built; the firewall (D-014) stands until an explicit annotated decision.
- Fixing upstream promotion starvation (why little survives the promotion bar) —
  the real blocker to RICH cockpit cargo, tracked separately.
