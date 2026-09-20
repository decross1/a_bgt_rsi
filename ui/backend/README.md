# UI backend

FastAPI serves the lab's research, benchmark and operations projections on
port 8700. Most routes read bounded files or incremental log indexes. Human
actions use explicit POST seams which validate capabilities and call the
canonical writer; the service is not wholly read-only.

Start from the repository root:

```bash
ui/scripts/ui-services.sh status
curl -fsS http://127.0.0.1:8700/api/health
```

For development, `ui/backend/run.sh` runs the backend directly. Production UI
processes are managed by `ui/scripts/ui-services.sh`; `ensure` starts missing
components, while `start` restarts all three. Follow the targeted recovery
instructions in [the operator guide](../../docs/v2/OPERATOR_GUIDE.md) when
only the backend needs to adopt changed code.

## Product boundaries

| Surface | Principal read endpoints | Meaning |
| --- | --- | --- |
| Now / Operations | `/api/health`, `/api/research_ops_status`, `/api/served_models` | Current process and recorded execution state |
| Research | `/api/ladder`, `/api/research_scope`, `/api/iteration/{id}/journey` | Scoped claims, exact-record evidence and pending actions |
| Application agenda | `/api/research_application_agenda` | Authored proposed direction, never completed study evidence |
| Research archive | `/api/research`, `/api/experiments/{id}`, `/api/loop_v0/iterations` | Historical records and observed outcomes |
| Benchmark program | `/api/benchmark_program` | Versioned core, freeze, run admission and comparable results |
| Benchmark evidence catalog | `/api/weekly_upgrade/progress` and registered study projections | Historical diagnostics, budgets, runtime qualification and evidence limits |
| Calls / traces | Model I/O routes, `/api/chain_by_request/{id}`, coordinator routes | Attributable requests and recorded causal links |

`app.py` is the route-registration inventory. `/openapi.json` contains the
running service's full HTTP schema. `/api/health.version` identifies the commit
loaded at process start, not merely the current checkout HEAD. `/api/live` is
an implemented WebSocket for live updates.

The application includes explicit human-action routes under `/api/attest`,
`/api/todo`, `/api/channel`, and LOOP_V0. Their presence does not grant a GET
projection authority to execute a model, accept a finding, schedule a study,
or deploy a model. See [the human writeback contract](../../docs/human_writeback_contract.md).

## Temporary bounded Oracle responder

The existing daily-operations route can be pointed temporarily at a separately
contained, summary-only Pi worker. This is a route identity, not a second
permanent Oracle. Canonical behavior remains the default when the optional
fields below are absent.

```json
{
  "instance_kind": "bounded_ui_responder",
  "responder_label": "Oracle bounded UI responder",
  "client_label": "Headless Pi client",
  "availability_ends_at": "2026-09-20T16:02:48Z",
  "worker_status_path": "/home/decross1/.local/state/oracle-pi-review-isolated-INSTANCE/controller/ui-worker-status.json",
  "max_owner_turns": 12,
  "legacy_recipient": {
    "mailbox_root": "/home/decross1/.local/state/oracle-pi-oversight/mailbox",
    "session_id": "CANONICAL-ORACLE-SESSION-UUID",
    "instance_kind": "canonical_oracle",
    "responder_label": "Oracle",
    "client_label": "Pi client"
  }
}
```

These fields augment the existing private root, mailbox root, session ID,
allowed origins, and planner pointer. The relay accepts a new owner request only
when both the mailbox heartbeat and the separate controller status are fresh,
the controller advertises `ready` with admission open, its configured deadline
has not passed, and the mailbox has no active or pending turn. The temporary
2026-09-20 availability window ends at **16:02:48 UTC**. The worker controller
owns the configured owner-request cap (12 for this window) and closes admission
at that limit; the relay checks the same advertised cap but does not extend it.

`legacy_recipient` is required during the temporary switch. It explicitly
binds request records created before recipient metadata existed to canonical
Oracle, preventing old history from being relabeled or searched in the
temporary mailbox. New request records carry their own immutable binding.

Each accepted request records the exact mailbox, session, instance kind, and
display labels that received it. Receipt projection continues to use that
immutable binding after the live route returns to canonical Oracle. Keep the
private temporary mailbox after shutdown while its receipts remain in the owner
thread.

For a bounded responder, the relay writes the exact envelope bytes first to
the private `admission/` archive and then to `inbox/`. This durable admission
copy lets the one-shot controller observe the accepted turn even if the Pi
extension claims the inbox entry before its next poll. An idempotent retry must
match the archived bytes exactly. Atomic-publication temporary files remain in
the private sibling `.relay-staging/` directory so strict queue readers never
mistake a partially published file for an owner request.

The bounded responder can read only `daily_ops_summary.json` and may write only
its request-specific private response draft. Its replies are advisory. Queueing
a question or plan-change request is never approval or execution, and this
configuration must not be promoted into a timer or permanent parallel service.

## Sources and provenance

Operational logs and mutable research state normally live in the canonical
checkout, even when server code is in a worktree. Route modules declare their
own roots and injectable test paths. Do not assume one universal `calls.jsonl`,
one common study schema, or that a file's presence proves success.

Model/study projections validate registered source identities, terminal
receipts and interpretation limits. Missing evidence is distinct from measured
failure. Benchmarks are not scientific thesis validation; data collection is
not a profitable strategy. Existing projections remain available to inspect
older evidence when the main page changes.

`benchmark_program.py` declares the active program artifact root.
`benchmark_history.py` reads at most 32 registered arm directories and bounded
regular JSON documents; redirected paths, conflicting hashes and future run
receipts withhold scores. `comparison.history` is the canonical dated series,
while `comparison.arms` contains compact references. Same-cohort paired deltas
remain descriptive family or mechanism results. Neither endpoint imports or
executes a model-generated repair during a GET.

Selected research detail is loaded on demand. Large list/archive views use
bounded windows, and the frontend must keep active-campaign and all-history
scope explicit. Never join unrelated records by topic text alone.

## Verification

From the repository root:

```bash
PYTHONPATH=ui:. .venv-chroma/bin/python -m pytest -q ui/backend/tests
```

Test roots and transport doubles should isolate reads/writes from live
research. A passing unit test does not replace a fresh browser check of changed
routes, an exact-record drill-down, and a live health check after deployment.
Historical fixture generators under `ui/backend/tests/fixtures/` are
development aids rather than the current production schema.

For frontend cleanup, run `node ui/scripts/component-inventory.mjs` from the
repository root. It reports import reachability and unresolved edges without
deleting anything. Confirm routing, dynamic entrypoints and external usage
before removing a candidate. The September 16 cleanup also removed the graph
libraries after their final production consumers were retired.
