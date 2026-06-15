# Human write-back contract (the "A5 blessing") — D-046, 2026-06-10

This document blesses the CLI contract the UI backend may build write-back
("B4") endpoints against. It exists so the UI session can ship in-UI
attestation (verdict buttons, ack buttons, defer-to-dev-session) without
ever writing apparatus files itself.

## Principles (non-negotiable)

1. **CLIs are the writers of record.** The UI backend NEVER opens
   `run_state/` or `memory/` files for writing. A POST endpoint execs the
   blessed CLI below as an **argv array — no shell strings, no string
   interpolation into a shell**, `cwd` = the primary repo root,
   interpreter = `.venv-chroma/bin/python`. (Precedent:
   `POST /api/loop_v0/start` in `ui/backend/loop_v0.py`.)
2. **The CLI's validation is the gate.** Out-of-enum values exit nonzero
   and write NOTHING — never coerced (inviolate rule 4). The UI should
   ALSO validate client/server-side for UX, but the CLI is authoritative.
3. **Failure semantics:** nonzero exit → the endpoint returns an error
   payload carrying the CLI's **stderr verbatim** and the exit code. The
   UI renders it un-summarized.
4. **Success semantics:** each CLI prints JSON on stdout; the endpoint
   returns it so the UI can render the confirmed write. **Shapes differ by
   CLI:** `gate_cli` and `todo_cli` print the appended ledger row itself
   (`gated_by` / `ack_by` / `attested_by` = `human:ui`);
   `finding_session --set-status` prints an envelope
   `{finding_id, session_id, outcome, loop_feedback_row, status_audit_row}`
   — the audit stamp is `status_audit_row.changed_by`, and
   `loop_feedback_row` is null for `in_review`.
5. **Confirmation = the queue.** After a successful POST the UI re-polls
   `GET /api/human_todo`; the item leaving the queue (because the ledger
   row now exists) is the durable confirmation, not the POST response.
6. **Identity:** writes initiated from the UI stamp `human:ui`. Writes
   typed at a terminal default to `human`.

## Blessed commands by TODO kind

(`PY` = `.venv-chroma/bin/python`, run from the repo root.)

| TODO kind | Blessed argv | Writer of record |
| --- | --- | --- |
| `gate_verdict` | `PY -m orchestrator.gate_cli --iteration-id <iter-ID> --verdict <valid\|invalid\|needs_revision> --note <why> --gated-by human:ui` | `memory/loop_feedback.jsonl` (schema-frozen enum) |
| `finding_review` (quick disposition) | `PY -m orchestrator.finding_session --set-status <finding_id> <validated\|rejected\|in_review> --note <why> --by human:ui` | `memory/surfaced_findings.status.jsonl` (+ `memory/loop_feedback.jsonl` for validated/rejected, against the finding's source iteration) |
| `bubble_ack` | `PY -m orchestrator.todo_cli ack --bubble-run-id <run_id> --note <why> --by human:ui` | `memory/coordinator_acks.jsonl` (`bubble_run_id` is the join key `ui/backend/human_todo.py` reads) |
| `defer to dev session` (ANY kind) | `PY -m orchestrator.todo_cli defer --kind <gate_verdict\|finding_review\|bubble_ack\|stale_active_run\|state_gate> --ref-id <id> --note <why> --by human:ui` | `memory/dev_session_queue.jsonl` |
| `stale_active_run`, `state_gate` (direct resolution) | **not blessed** — these stay primary-session human actions (process autopsy / state-file edit). The UI offers only the defer action for them. | — |
| **directive sign-off** (sign-off WITH a "proceed to <next step>" directive) | `PY -m orchestrator.finding_session --set-status <finding_id> validated --note <why> --directive <next-step> --by human:ui` | `memory/surfaced_findings.status.jsonl` (`status_audit_row.directive`) + `memory/loop_feedback.jsonl` valid against the finding's source iteration |
| **authorize fix** (outcome 4 — authorize an autonomous fix) | `PY -m orchestrator.authorize_fix authorize-fix --ref-id <id> --task <statement> --note <why> --by human:ui` | `memory/authorize_fix_queue.jsonl` (a NEW append-only enqueue; NOT `run_state/spawn.jsonl` — that ledger is written at actual dispatch) |

Notes:
- `--note` is **required non-empty** for `defer` and `--set-status` (the
  why is what gets triaged); for `gate_verdict` the CLI permits an empty
  note but the UI SHOULD require one — the note is the audit value.
- Deep finding interrogation (spawn/refine outcomes) remains the
  `finding_session` REPL / a future session UI — NOT one-shot blessed.
- The deferral queue is append-only: `defer` appends `status:"open"`,
  `close` appends `status:"closed"`; readers fold by `ref_id`, last
  status wins. `python -m orchestrator.todo_cli list-deferred` prints
  open items; the primary session triages them at startup (CLAUDE.md
  "How to start a primary session").
- A deferral **assigns** the work; it does not resolve the item. The UI
  keeps deferred items visible (tagged), and the TODO counts still
  include them.
- **directive sign-off** is a clean SUPERSET of the bare
  `finding_session --set-status <id> validated` row above: omit
  `--directive` and the behavior is identical to today's bare sign-off
  (so the UI degrades cleanly against an older backend). When present,
  the directive is recorded ONLY on the status-audit row
  (`status_audit_row.directive`) — the `loop_feedback` row keeps its
  frozen/closed schema (inviolate rule, schema is not extended). Nara's
  next planning session reads the status audit, so the directive
  surfaces there. The same `--directive` superset also exists on the
  in-session `end_session` validated path (the REPL/two-voice exit), but
  the one-shot `--set-status` argv above is what the UI execs.
- **authorize fix** (outcome 4) is a NET-NEW writer. The
  `authorize-fix` **subcommand token** is load-bearing (it matches the
  sibling `todo_cli` writer-of-record shape; the UI execs this exact
  argv). It does NOT dispatch — it ENQUEUES a full spawn-contract block
  `{task_statement, done_condition, skill_subset, authority_cap,
  self_gating_rules, reporting_format, escalation_path, budget,
  state_basis}` (Dynamic Workflow rule 3) into
  `memory/authorize_fix_queue.jsonl`, which a later dev session
  consumes. The success stdout is that whole enqueued row (the
  `contract` block nested under it) so the UI can render the authorized
  work verbatim. `--task` and `--note` are **required non-empty**; the
  `--ref-id` must resolve to a known finding / open deferral /
  coordinator bubble or the CLI **fails closed** (`rejected: …` on
  stderr, exit 1, nothing written — inviolate rule 4). The
  merge-gate invariant and the D-014 runtime firewall are preserved: an
  enqueue authorizes the *work*, never an unreviewed merge, and writing
  a queue row is not a dispatch.

## The full 6-outcome resolution mapping (`/todo` cockpit)

The `/todo` cockpit (`docs/todo_cockpit_seam_plan.md`) resolves a surfaced
uncertainty into one of six outcomes. Four reuse writers already blessed
above (do NOT re-bless — they are mapped here for completeness); two are
the NET-NEW commands just added. The cockpit's `ui/backend` endpoints exec
these via the same argv discipline as the table above.

| # | Outcome | Blessed writer (argv) | New? |
| --- | --- | --- | --- |
| 1 | **Sign off** | `finding_session --set-status <id> validated --note <why> --by human:ui` (bare) — or the **directive sign-off** row above to add `--directive <next-step>` | reuse (directive variant NEW) |
| 2 | **Reject** | `finding_session --set-status <id> rejected --note <why> --by human:ui` | reuse |
| 3 | **Refine — defer to a session** | `todo_cli defer --kind <kind> --ref-id <id> --note <why> --by human:ui` | reuse |
| 4 | **Refine — authorize autonomous fix** | `authorize_fix authorize-fix --ref-id <id> --task <statement> --note <why> --by human:ui` | **NEW** |
| 5 | **Spawn topic** | `finding_session` `spawn_topic` outcome → `memory/finding_followups.jsonl` (the in-session `end_session`/`/spawn` exit; NOT a one-shot `--set-status`, it needs the conversation) | reuse |
| 6 | **Abstain** | `finding_session` `abandoned` outcome (session-local feedback event; no verdict — an honest exit) | reuse |

Notes on the 6-outcome map:
- Outcomes 1–4 are one-shot CLI argv the UI can exec directly. Outcomes
  5 and 6 are **session-only** terminal outcomes (`spawn_topic`,
  `abandoned`): they are reached through `finding_session`'s interrogation
  REPL / two-voice session (`end_session`), not a one-shot `--set-status`
  — they need the conversation, exactly as the seam plan specifies. The
  UI renders them as session exits, not one-shot buttons.
- The `gate_verdict` writer (`gate_cli`, top table) backs the cockpit's
  gate-disposition path; it is unchanged.

## What the UI session builds against this (its side, in `ui/`)

- A capability handshake (e.g. `GET /api/attest/available`) so a frontend
  newer than the backend degrades to copy-paste rendering instead of 404
  noise.
- POST endpoints with an injectable runner for tests; tests NEVER exec
  against the live ledgers — backend tests use tmp paths + a stubbed
  runner. One manual live gate resolution (human present) is the final
  acceptance.
- The copy-paste `resolve_command` rendering stays as the fallback path.
