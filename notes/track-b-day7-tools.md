# Track-B Day-7 — backfill tests for three tools

Agent: `claude-track-b-day7-tools-tests`
Worktree: `day7-tools-tests` (branch `worktree-day7-tools-tests`)
Claim: `run_state/claims.jsonl` 2026-05-23T09:18:10Z → 11:18:10Z, zone `tests-shared`.

## What was added

| Test file | Target | # tests |
|---|---|---|
| `tests/test_claims_check.py` | `tools/claims_check.py` | 25 |
| `tests/test_gate_sla_check.py` | `tools/gate_sla_check.py` | 16 |
| `tests/test_mock_payoffs.py` | `tools/mock_payoffs.py` + `mock_payoffs.schema.json` | 13 |

Total: 54 new tests, all passing (`python3 -m unittest discover -s tests
-p 'test_{claims_check,gate_sla_check,mock_payoffs}*.py' -v`).

## Coverage notes

### `tools/claims_check.py`
Every documented subcommand has at least one test:

- `--dry-run` (default): empty log, released, expired, single overlap,
  same-agent re-claim, disjoint paths, malformed-line tolerance,
  `_schema_comment` line skipping.
- `--check <path>`: free (exit 0), held (exit 1), held-but-expired
  (exit 2), released-then-checked, and "latest-claim-wins" when an
  expired claim and an active claim coexist on the same path.
- `--validate-ownership`: clean ownership exits 0; two zones with
  overlapping globs flagged as multi-assigned (exit 1); an unassigned
  file (e.g. `README.md`) is a warning, not a hard error. The test
  monkey-patches `subprocess.check_output` so the surrounding git tree
  doesn't affect outcomes.
- `--gc`: just-expired (under 24h) is NOT stale; >24h expired is stale;
  release entries are never gc'd; the strict `>` boundary at exactly 24h
  is verified (still not stale).
- `--weekly-summary`: empty case, overlaps + expired-unreleased counts,
  released-old-claim is NOT counted as expired-unreleased.

Plus two CLI smoke tests via real `subprocess.run` (`--dry-run` and
`--help` exercise the actual entry point on the live repo).

### `tools/gate_sla_check.py`
Mocks the clock to T0 = 2026-05-23T12:00:00Z and monkey-patches
STATE_FILE / ATTESTATIONS / ESCALATIONS into a per-test temp dir.

- 4h soft-gate boundary: 3h59m is NOT expired; 4h01m IS expired.
- Custom `sla_hours` on a request honored (1h SLA + 2h-old request =
  expired).
- Closing outcomes — `approved`, `rejected`, `no_objection` — all
  prevent re-expiry.
- `--dry-run` prints `[dry-run]` and does NOT write to
  `attestations.jsonl`/`escalations.jsonl`.
- 48h hard-gate boundary: 47h59m is NOT expired; 49h IS.
- Undated string-format gates (older `human_gates_pending` shape) are
  surfaced as `{undated: True}` and never written to escalations.
- Missing state file is tolerated (0 hard-gates, no crash).
- Corrupt state JSON emits a warning to stderr but does not crash.
- One CLI smoke test against the live tool in `--dry-run`.

### `tools/mock_payoffs.py` + `mock_payoffs.schema.json`
- Schema document shape: `type=function`, `function.name`,
  required `game_name`, non-empty enum, `additionalProperties:false`.
- Schema/code consistency: the schema's enum equals
  `set(mock_payoffs._GAMES)` — drift would fail loudly.
- For every enum-listed game, `get_payoff_matrix` returns a dict whose
  matrix is 2×2 of `[int, int]` pairs and survives a JSON round-trip
  (the wrapper feeds the dict back to the model as a `role:"tool"`
  message, so JSON-serialisability is load-bearing).
- Pinned exact payoff values for `prisoners_dilemma`; verified
  `matching_pennies` is zero-sum.
- `get_payoff_matrix("not_a_game")` raises `ValueError` whose message
  lists the known games.
- `jsonschema.validate` exercised: every enum game validates; unknown
  name, missing `game_name`, and extra property all fail validation.

## Surprises / minor notes

- The mock_payoffs schema is an OpenAI tool-call descriptor (validates
  the *input* `game_name`), not the matrix returned. The task brief
  said "validate the output against the schema" — that's not literally
  possible against this schema. I interpreted the intent as "exercise
  the schema/implementation contract" and covered both sides
  (`jsonschema.validate` on inputs + structural assertions on outputs).
- `claims_check.py`'s `--gc` boundary is a strict `> 24*3600` in
  seconds: exactly-24h-old expiry is NOT stale. The test pins this so
  any future loosening to `>=` is caught.
- `gate_sla_check.py` correctly treats old string-form
  `human_gates_pending` entries as undated (never escalated). Verified
  the regression-prone path that the print message is emitted but the
  escalations file remains empty.
- No `LOCAL_LLM_BASE_URL` calls anywhere; Track B's
  no-real-model rule honored. All tests run in `MOCK_LLM=1` shells.

## Out of scope (would belong to Track C if pursued)

- Coverage on `tools/inspect_run.py` is already present in
  `tests/test_inspect_run.py` — not re-touched.
- No edits to `tools/*.py` itself; tools are the system under test.
- No new schemas authored — `mock_payoffs.schema.json` was used as-is.
