# Daily lab workspace

The **Now** page brings together daily goals, recent accomplishments, system
improvements, the selected research thesis and its next gate. Oracle is the
steward running in the Pi client; Nara is the observed research runner. The
owner conversation reaches that live Pi session through its existing mailbox.

## Using it

Read the brief on Now. Expand recorded details for longer blockers and next
actions. **Ask Oracle about Nara** prepares a question without sending it.

To unlock the private conversation, copy the local credential on the Spark:

```sh
cat ~/.local/state/oracle-lab-ui/owner.key
```

Paste it into the password field. It stays in the browser tab's session storage
and is sent as an Authorization header, never in the URL or message body. A
question asks for a reply. A change request is bound to the currently displayed
agenda revision; if that revision changes or expires, refresh and review it
before resubmitting. Neither mode approves or executes an agenda.

Queued means durably accepted by the relay. Delivered means Pi accepted the
message. An Oracle reply means a visible assistant turn completed. These states
do not certify the answer's correctness or completion of the requested work.
The existing lab event channel is a separate history.

Owner questions and proposed changes use the mailbox's enforced review scope:
Pi may read the named bounded lab snapshot and write one named proposal draft.
Other tools, shell commands, repository changes and ledger appends are blocked
for that request. If more context is needed, Oracle should identify the missing
evidence. The bridge refuses new owner requests until the live mailbox reports
that this enforcement is loaded.

## Sources and operation

- `run_state/daily_ops_brief.json` is the curated, source-dated brief. The
  supervisor updates it after verified changes; it is not model-generated
  scientific evidence. An updated projection timestamp does not refresh the
  underlying claims' observation dates.
- `run_state/active_research_focus.json` selects a hash-verified focus receipt.
  Selection does not inherit a historical evidence rung or authorize execution.
- The mailbox heartbeat observes Oracle/Pi connectivity and processing state.
  A fixed read-only service query observes `nara-daemon.service` every 30 seconds.
- The current unexpired proposal revision comes from the installed daily
  proposal service. The service continues to own its schedule and approval gate.
- `run_state/daily_ops_summary.json` and `daily_ops_messages.jsonl` are disposable
  bounded projections. Refresh performs no model call or research execution.

The backend reads `ORACLE_DAILY_OPS_CONFIG`, a local JSON configuration:

```json
{
  "private_root": "/absolute/private/relay-state",
  "mailbox_root": "/absolute/private/oracle-mailbox",
  "session_id": "the-existing-authorized-pi-session-uuid",
  "allowed_origins": ["http://your-spark-host:5173"],
  "planner_latest": "/absolute/private/daily-planning/latest.json"
}
```

Both state roots must be owned by the service user and mode 0700. The relay's
`owner.key` is a random credential of at least 32 characters, mode 0600. Never
commit the configuration, credential, conversation, or runtime brief. The UI
launcher discovers `~/.config/oracle-lab/daily-ops.json` when present. Without
configured authentication and routing, the write path remains unavailable.

Requests are immutable records under `private_root/requests/`. Identical UUID
replays are idempotent; changed content under the same UUID is rejected. Private
message responses are not cacheable. Only the latest 50 request records and up
to 100 projected rows are read for the dashboard. At 2,048 retained requests the
relay pauses new submissions until an operator archives older terminal records;
it never silently deletes history.

The session binding is deliberate. When Oracle moves to a new Pi session, verify
the mailbox's binding and update this configuration together. A stale heartbeat,
changed session, or processing block is displayed as unavailable/degraded rather
than being replaced with a new model pretending to be Oracle.

## Validation

Focused backend tests cover authentication and exact browser origins, bounded
projection reads, message lifecycle validation, real mailbox receipt states,
idempotency and crash replay, stale agenda revisions, missing/invalid sources,
and focus digest verification. Frontend checks cover the locked and unlocked
states, request submission, honest delivery labels, responsive layout and the
single thesis placement. A release should additionally verify one real message
and visible reply through the bound Pi session.
