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
