# Track D — observations for Track A

Things Track D (UI improvements) noticed while working that belong to
Track A's lanes. Track D does not edit `plan.yaml`, schemas, or the
apparatus; it files observations here instead.

## 2026-05-19 — experiment-result schema does not exist

The v2 UI results browser (sketched in `ui/ui_plan_v2.md`) needs
experiment *semantic* fields — experiment id, round index, agent
action, opponent identity, opponent action, payoff. Today only the
structural call-log fields are pinned (`request_id`,
`parent_request_id`, `task_id`, `caller_tag`, timestamps). No schema
pins experiment outcomes.

Not a v1 blocker — v1 deliberately never interprets results. But when
the apparatus reaches the day-7 experiment work, a decision is owed:
do experiment outcomes live as extra fields on the call-log lines, as
a separate per-experiment results file, or both? A committed
`schema/experiment.schema.json` (or an explicit extension of the
day-7 `exp###` contract) would unblock the v2 results browser without
any prompt-text parsing.

## 2026-05-19 — embedded tool-call key name unconfirmed

Track D resolved `ui_plan.md` §9's tool-call-shape question (r4) by
supporting both shapes. The embedded shape assumes the wrapper record
carries its tools under a `tool_calls` key. If the day-4 tool-call
work uses a different key, the UI side is a one-line change
(`EMBEDDED_TOOL_KEY` in `ui/backend/chain.py`) — no rework — but it
would be good to confirm the key name when day 4 lands.

## 2026-05-23 — 4 malformed lines in `run_state/week1.run.jsonl`

Surfaced by the new `/api/unlock_status` endpoint (`ui/backend/unlock.py`)
when it first ran against the real Day-7 state. Lines **99, 105, 106,
109** fail JSON parsing — all Day-6 entries with unescaped inner
double-quotes inside `observable_actual` strings. Examples:

- L99 (`day6_block1_reading`): `"observable_actual":"human attested complete ("these human blocks are done")"` — the inner `"these..."` needs `\"these...\"`.
- L106 (`day6_block3_reading`): same pattern with `"LLMs as Simulated Economic Agents"`.
- L105 (`day6_block2_inspect_run_cli`): inner `--task-id seq-1` quote nesting.
- L109 (`day6_end_of_day_artifacts`): the longest entry; multiple unescaped pairs.

These are Day-6 entries, so Day-7's experiment review is unaffected.
But per [`agent/autonomy.md`](../agent/autonomy.md) §4.3, the Week-2
unlock attestation requires zero malformed entries across the
run-log / attestations / escalations files. **The publication-review
gate's alignment-evidence check cannot legitimately clear with these
four lines as-is.** Track A is the rectifier per
[`agent/collision_protocol.md`](../agent/collision_protocol.md) §2.3
and §7 — Track D does not write to `run_state/*`.

**Related docs drift (Track A's call):** `autonomy.md` §4.3 references
`verify_log_integrity` against `run_state/*` files. The function in
`agent_wrapper/wrapper.py:315` validates against the *call-record*
schema (`schema/calls.jsonl.schema.json`) — it's the right validator
for `logs/day*.jsonl` and the wrong one for `run_state/week1.run.jsonl`.
Pointed at the run-log it reports 130 malformed, because none of the
entries are call records. Either `autonomy.md` should point at a
dedicated `verify_run_log_integrity` (apparatus-side), or the existing
function needs disambiguation. The UI-side
`ui/backend/unlock.py:verify_run_log_integrity` validates against the
run-log required-field set from CLAUDE.md inviolate rule 8 — it is the
function `/api/unlock_status` calls, and it correctly found the four
genuinely-broken lines above. The two-validator situation is fine if
documented; Week-2 polish item.
