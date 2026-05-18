# Backend

FastAPI service that reads the apparatus's JSONL logs and serves the
dashboard and chain inspector. Read-only — it never writes anything.
See `ui_plan.md` §5.2.

## Run

```sh
pip install -r ui/requirements-ui.txt
ui/backend/run.sh                              # serves on :8700
curl -s localhost:8700/api/health
```

## Endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/health` | `{ok, telemetry_last_seen, version}` |
| `GET /api/chain/{task_id}` | full causal tree for a task (404 if unknown) |
| `GET /api/recent_tasks?limit=50` | recent orchestrator dispatches, latest first |
| `GET /api/state` | `run_state/week1.state.json` passthrough |

`WS /api/live` is build step 6.4 and is not implemented yet.

## Data sources

- **Call log** — `logs/day*.jsonl` + `logs/exp*.jsonl` (there is no single
  `calls.jsonl`; see `ui_plan.md` §4.2). Indexed by `request_id`.
- **Orchestrator** — `logs/orchestrator.jsonl`, indexed by `task_id`.
- **Telemetry** — `ui/logs/telemetry.jsonl` (for `/api/health`).
- **State** — `run_state/week1.state.json`.

All are tailed incrementally by byte offset (`tailer.py`) — files are
never re-slurped, so `/api/chain` stays fast during active runs.

Paths are overridable by env var: `UI_LOGS_DIR`, `UI_TELEMETRY_FILE`,
`UI_STATE_FILE`.

## Fixtures

The apparatus's day-2 call schema and day-6 orchestrator schema do not
exist yet. Generate synthetic logs with known chains to develop against:

```sh
cd ui && python3 -m backend.tests.fixtures.gen /tmp/fixture_logs
UI_LOGS_DIR=/tmp/fixture_logs ui/backend/run.sh
```

The generator (`tests/fixtures/gen.py`) only commits to the structural
fields `ui_plan.md` §4.2 marks stable; payload fields are plausible
placeholders. Swap to real logs when days 2 and 6 land.

## Tests

```sh
pytest ui/backend/tests
```
