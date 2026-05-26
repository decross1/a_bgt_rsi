# Track B — Day 9 test scaffolds + dispatched-task schema (DRAFT for Day-39/42 Track-A review)

Worktree `day9-tests` (branch `worktree-day9-tests`). Drafts the test
scaffolds Track A consumes on Day 39 (W2-01 critic + dispatcher) and
the second of the two competing event-schema designs Track A will
choose between at the Day-42 W2-06 lock.

Track A is the reviewer. Until Track A merges, none of these files are
load-bearing; Day-39 work runs against `schema/proposed/events.jsonl.schema.json`
(option 1) by default.

## Deliverables

| File | Kind | What it does | Live today? |
|---|---|---|---|
| `tests/test_critic_contract.py` | new | 9 cases. Pins the `workers.critic.critique(hypothesis_text, context=None) -> dict` signature, the required output keys (`critique_text` / `flag_decision` / `reasoning_chain`), the enum on `flag_decision`, and the no-network invariant under `MOCK_LLM=1`. | yes — runs against `_MockCritic` until Day 39, then against the real `workers/critic.py`. |
| `tests/test_critic_eval_scoring.py` | new | 17 cases. Pins the scoring rule + the ≥80% pass bar for the W2-01 critic eval. Includes oracle / label-only / all-sound stub critics so the scoring scaffold itself is regression-tested. | yes — `MOCK_LLM=1 python3 tests/test_critic_eval_scoring.py` is green today. |
| `tests/test_dispatch_coding_agent.py` | new | 23 cases. Schema shape + ownership/zone resolution + prompt-template ordering + subprocess-isolation guard. Two tests skip when `agent_wrapper/dispatch_coding_agent.py` is absent (pre-Day-39). | yes — 21/23 active, 2 skipped pending Day 39. |
| `schema/proposed/dispatched_task.schema.json` | new | Draft-2020-12 schema for the `dispatch_coding_agent(task_spec, ...)` input. Required: `task_id`, `target_zone`, `allowed_paths`, `task_description`, `success_criteria`, `autonomy_tier`, `worktree_prefix`. Optional: `timeout_minutes`, `extra_required_reads`, `parent_request_id`, `decision_id`. `additionalProperties: false`. | yes — self-validates and accepts/rejects the test fixtures. |
| `schema/proposed/events_v2_separate_gate_clear.jsonl.schema.json` | new | OPTION 2 alternative to `schema/proposed/events.jsonl.schema.json`. `gate_clear` is its own top-level `oneOf` member rather than a `human_intervention` subtype. Side-by-side with option 1 so Track A can diff before the Day-42 W2-06 lock. | yes — self-validates; the 6-case smoke battery in this file's commit message confirms backwards-compat for the Day-3.5 shapes. |
| `notes/track-b-day9-tests.md` | new | This file. The Day-9 followup. | n/a |

All four test files run cleanly under `python3 -m unittest` and
`pytest`. No `LOCAL_LLM_BASE_URL` calls (a TCP-connect patch in
`tests/test_critic_contract.py` proves the no-network invariant
end-to-end, not just at the wrapper boundary). No writes outside
Track-B zones.

## §1 — Option 1 vs. Option 2 for `gate_clear` (the Day-42 decision)

`notes/track-b-day8-schemas.md` §"Design tension" flagged the choice
without picking one. Day-9 ships option 2 as a parallel draft so Track
A can diff the two designs and decide at the Day-42 W2-06 lock. The
calibration_entry side of the design is **the same** in both files —
this section is only about `gate_clear`.

### Option 1 (`schema/proposed/events.jsonl.schema.json`)

`gate_clear` is a `human_intervention.subtype`. The Day-3.5 schema's
`subtype` enum gains a sixth value; five new top-level fields
(`decision_id` / `human_identity` / `disposition` / `decisions_ref` /
`gate_name`) are added as OPTIONAL, then made REQUIRED by an
`if/then` block when `subtype == "gate_clear"`.

```jsonc
// option 1 — gate_clear inside human_intervention
{ "event_type": "human_intervention",
  "subtype": "gate_clear",         // new enum value
  "task_id": "day7_block2_publication_review",
  "decision_id": "D-028",          // required-when-subtype-is-gate_clear
  "human_identity": "decross1",
  "disposition": "no-publish-standalone",
  "decisions_ref": "DECISIONS.md#D-028",
  "gate_name": "day7_publication_review",
  "reason": "...", "context_hash": "...", "timestamp": "..." }
```

Pros:
- Backwards-compat with the Day-3.5 schema is extend-only. Any
  Day-3.5 `human_intervention` record (the 12 existing entries in
  `run_state/events.jsonl` plus the `tests/test_events_schema.py`
  fixtures) validates unchanged.
- Single event-type filter: `inspect_run --event-type human_intervention`
  shows every human action, scheduled or in-task.
- Day-8 prompt already pitched this design ("D-028 inside
  human_intervention"); Track B's option-1 file ships it.

Cons:
- The `if/then` block carries the new shape. A reader who only looks
  at the top-level `required` array misses that five more fields are
  required for `subtype=='gate_clear'`.
- The 2026-05-19 adversarial-review memo
  (`notes/research/2026-05-19-adversarial-review/5_frozen_plan_change_proposals.md`)
  explicitly distinguishes `human_intervention` (action *inside*
  agent task) from `gate_clear` (gate clearance). Option 1 merges
  the two; consumers that want to distinguish them have to filter on
  `subtype`.

### Option 2 (`schema/proposed/events_v2_separate_gate_clear.jsonl.schema.json`)

`gate_clear` is its own top-level `oneOf` member with its own
`event_type` discriminator. `human_intervention` reverts to its
Day-3.5 shape unchanged. Three `oneOf` members total.

```jsonc
// option 2 — gate_clear as its own event_type
{ "event_type": "gate_clear",
  "gate_name": "day7_publication_review",
  "decision_id": "D-028",
  "human_identity": "decross1",
  "disposition": "no-publish-standalone",
  "decisions_ref": "DECISIONS.md#D-028",
  "reason": "...", "context_hash": "...", "timestamp": "..." }
```

Pros:
- The new shape stands alone with `additionalProperties: false` and an
  unconditional `required` list. No `if/then` gymnastics.
- Faithful to the P1 prose distinction in the 2026-05-19
  adversarial-review memo (scheduled vs. in-task).
- `inspect_run --event-type gate_clear` is one filter, not two. The
  gate-clearance timeline is a first-class query.
- The `human_intervention` member is IDENTICAL to the Day-3.5 schema —
  zero migration risk for the existing 12 records.

Cons:
- Two event types overlap in intent ("human did a thing"). Downstream
  consumers building a "human-action timeline" UI tab merge both event
  types — slightly more code in the UI layer.
- The total schema gets longer by ~one `oneOf` member; the existing
  test file (`tests/test_events_schema_proposed.py`, 43 cases) needs
  re-targeting if Track A adopts option 2.

### Recommendation (non-binding)

**Author's lean: option 2.** Three reasons:

1. The P1 memo's distinction (in-task vs. scheduled) was a deliberate
   design choice, not an artefact of how the schema was carved up. If
   future research-design events (e.g. a `pre_experiment_attestation`
   event, a `journal_entry` event) borrow the schema, they'll be
   `gate_clear`-shaped (scheduled, decision-attached) not
   `human_intervention`-shaped (in-task, free-form). The shape lineage
   should follow that.
2. `if/then` conditional requirements are a fragile JSON-Schema
   pattern — a future writer who adds a sixth `subtype` enum value
   has to remember to extend the conditional. Option 2's flat
   `required` list is mechanically harder to break.
3. The migration cost is one extra `oneOf` member + a re-targeted
   test file. Cheap, one-shot, and Track B handles both files in this
   PR. The "extend-only backwards-compat" pro of option 1 is real but
   small: there are 12 Day-3.5 `human_intervention` records, all of
   which validate under both schemas as-is.

If Track A disagrees and prefers option 1, the migration back is also
cheap: delete the option-2 file. Both files are drafts; nothing
downstream depends on either until Day 42.

### Decision request

Track A picks one at the Day-42 lock. Either way, the chosen file
gets promoted to `schema/events.jsonl.schema.json` (overwriting the
Day-3.5 contract) and the `$id` URL is updated. The discarded file is
deleted. `tests/test_events_schema_proposed.py` gets re-targeted if
option 2 wins.

## §2 — Why a `dispatched_task` schema at all

Day 9's prompt asked the test to use `schema/dispatched_task.schema.json`
if it exists, or propose one if not. It doesn't, so this file proposes
`schema/proposed/dispatched_task.schema.json`.

The rationale for having a schema (vs. an ad-hoc Python TypedDict):

1. **The dispatcher is the Week-2 unlock that enables ~80% of dev to
   run through orchestrator-dispatched coding agents** (per
   `PHASE_1_ROADMAP.md` §2.3 + `agent/collision_protocol.md` §5).
   The `task_spec` is the wire format between the orchestrator (the
   producer) and the dispatched-agent runtime (the consumer). Both
   sides should agree on the shape; a JSON Schema gives that
   guarantee with no runtime hand-waving.

2. **The schema lets the dispatcher reject malformed specs without
   launching a subprocess.** Per `agent/collision_protocol.md` §7
   ("Failure modes"), a dispatched agent that touches a
   non-dispatchable zone is a protocol violation. The schema catches
   the misconfiguration earlier — at spec-validation time — than the
   `tools/claims_check.py --validate-ownership` post-hoc sweep.

3. **`additionalProperties: false` blocks scratchwork-pollution.** If
   the orchestrator (or a future contributor) starts adding ad-hoc
   fields to the spec ("oh let me just throw a `notes` field in"),
   the schema bumps. That forces the discussion to happen at schema-
   amend time, not at "why does this dispatched agent suddenly behave
   differently in production."

The fields chosen for `required` are the minimum the dispatcher needs
to launch ONE valid agent. Optional fields (`timeout_minutes`,
`extra_required_reads`, `parent_request_id`, `decision_id`) carry
information that's nice-to-have but not invariant — defaulting them is
safe.

### Open questions for Track A on the dispatched_task schema

1. **`task_id` pattern strictness.** Draft is `^[a-z0-9][a-z0-9_-]{2,63}$`.
   This matches the existing claim convention `claude-dispatched-<task_id>`.
   If you want UUIDs or shorter ids, ping me.
2. **`timeout_minutes` upper bound.** Draft is 480 (8h) so a claim
   TTL doesn't have to renew mid-task. If Phase-2 dispatches run
   overnight, you'll want renewal support and a higher cap.
3. **Should `decision_id` be REQUIRED when `autonomy_tier == "hard_gate"`?**
   The intuition: a hard-gate dispatch should always be backed by an
   architectural decision. An `if/then` block expressing this is a
   one-line add; let me know if you want it.

## §3 — Why a TCP-connect patch in the critic-contract test

The Day-9 prompt says: "Assert no LOCAL_LLM_BASE_URL calls behind
MOCK_LLM=1." The natural test is to patch `agent_wrapper.wrapper.call_sync`
to raise. But:

- The critic might bypass the wrapper and ship its own HTTP client
  (today: unlikely; tomorrow: possible — a Phase-2 critic that calls
  Claude API via the Anthropic SDK to compare critiques is a plausible
  feature). The wrapper-level patch would be a false negative.
- `MOCK_LLM=1` is an environment-flag convention, not a runtime
  guarantee. Future code that forgets the flag would silently leak a
  real call.

The test files use a TWO-LAYER guard: (1) patch the wrapper boundary
(the expected path), and (2) patch `socket.socket.connect` (the
catch-all). Any TCP connect under `MOCK_LLM=1` fails the test
immediately. If a future critic adds an HTTP path the wrapper-boundary
patch misses, the socket-level patch still catches it.

This is the only test in the Day-9 batch with a socket-level guard;
the dispatcher test doesn't need one because subprocess isolation is
the relevant invariant there.

## §4 — Files NOT touched

- No edit to `schema/calls.jsonl.schema.json` or
  `schema/events.jsonl.schema.json` (the Day-3.5 contracts) — both
  competing proposals live in `schema/proposed/`.
- No edit to `schema/proposed/events.jsonl.schema.json` (the option-1
  Day-8 draft). Option 2 ships SIDE-BY-SIDE so Track A diffs the two.
- No edit to `schema/proposed/calls.jsonl.schema.json` — the
  retrieval_context extension is unchanged from Day 8.
- No edit to `tests/test_events_schema_proposed.py` or
  `tests/test_calls_schema_proposed.py` — they validate against the
  Day-8 option-1 schema and stay green there. If Track A picks option
  2 at the Day-42 lock, Day-42 Track-B re-targets them; that's a
  Day-42 deliverable, not Day 9.
- No edit to `agent_wrapper/`, `workers/`, `run_state/`, `logs/`,
  `bench/`, `chroma_db/`, `CLAUDE.md`, `plan.yaml`, or any Track A/C/D
  file. The critic-eval pass bar (`PASS_RATE_BAR = 0.80`) is locked in
  `tests/test_critic_eval_scoring.py`, not in a Track-A file, so a
  drift in the bar requires a Track-B edit.

## §5 — Forward hooks (NOT in this PR)

1. **Wire the real critic into `score_critic_run`.** Day 39, Track A,
   workers/critic.py. The scoring scaffold is ready; the import is
   one line.
2. **Append per-fixture scoring records to `logs/day39.jsonl`** per
   the `schema/calls.jsonl.schema.json` contract, populating
   `retrieval_context` for any chunk the critic retrieves (D-025/P2).
3. **Decide what to do on a sub-bar pass_rate.** This scaffold REPORTS
   the rate. The live eval also has to choose between [[slip-ladder]],
   re-prompt, or accept-and-document — that decision is Track A's at
   eval time.
4. **Promote the chosen events-schema option at the Day-42 W2-06 lock.**
   Track A decides; Day-42 Track-B reconciles the test files.
5. **Validate task specs at dispatcher entry.** The schema is here;
   the dispatcher needs to call `Draft202012Validator(SCHEMA).validate(spec)`
   at the top of `dispatch_coding_agent`. One-line change.
