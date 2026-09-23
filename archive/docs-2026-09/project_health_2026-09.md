# Project health review — 2026-09

State basis: `f0c7ea1ddd1859b0a671c72c6d71814941b9c25b` (the committed
Teams 1/3/4 checkpoint). This is the decision-grade output of Team 2's
read-only audit. It separates bounded cleanup from changes that need an owner
decision, a dedicated UI session, or protected-spine work.

## Dashboard

| Area | Status | Evidence and implication |
| --- | --- | --- |
| Tests | Red | The correctly scoped suite collected 2,496 tests. A fresh base run produced **7 failed, 2,487 passed, 1 skipped, 2 xpassed, 68 subtests passed** in 37.67 seconds. The seven failing node IDs are recorded below. This is not green, even though the current session plan permits an exact baseline comparison. |
| Structure | Yellow | Core behavior is concentrated in large protected modules: `orchestrator/nara.py` is 1,228 lines, `orchestrator/coordinator.py` 1,381, and `orchestrator/finding_session.py` 1,530. Decomposition needs characterization tests and a separate serial-integrator change. |
| Dependencies | Red | The repository has unpinned root/UI requirements and a frontend lockfile, but no Python lock or declared canonical environment. Production imports and the two existing virtual environments do not map cleanly to one install recipe. Dependency changes are not safe without a fresh-environment check. |
| Dead code | Yellow | Two non-strict `xfail` wrappers are obsolete because their expected behavior has landed. No production file was proven safe to delete: legacy dispatch and UI candidates still have tests, contracts, or historical obligations. |
| Reproducibility | Red | Ten experiment `results/summary.json` files exist, but only `exp001` has an `experiment.lock`. Results do not share a uniform code/seed/data/environment provenance envelope. |
| Docs/onboarding | Red at audit | Current onboarding points to retired `LOOP_V0.md` plan state, v4 diagrams, and superseded daemon/model topology. Sixteen broken links were found in current root documentation; historical and UI-owned broken links are outside this cleanup. |

## Trustworthy test baseline

The base command was:

```bash
MOCK_LLM=1 PYTHONDONTWRITEBYTECODE=1 \
  .venv-chroma/bin/python -m pytest tests/ -q -p no:cacheprovider
```

Its failing-node fingerprint is:

1. `tests/test_critic_cal.py::test_unusable_rows_are_excluded_by_name_not_by_silence`
2. `tests/test_critic_cal.py::test_pinned_reference_rates_match_the_live_record`
3. `tests/test_critic_cal.py::test_undecidable_census_splits_native_by_pack_state`
4. `tests/test_critic_cal.py::test_cluster_reconstruction_has_no_ordering_ambiguity`
5. `tests/test_readjudication.py::test_manifest_has_no_hash_seed_dependence[0]`
6. `tests/test_readjudication.py::test_manifest_has_no_hash_seed_dependence[1]`
7. `tests/test_readjudication.py::test_manifest_has_no_hash_seed_dependence[12345]`

Unscoped repository collection is invalid because it enters gitignored clone
trees. Sandbox runs that cannot create ephemeral localhost sockets are also not
a valid regression baseline. Candidate comparison must use the same interpreter,
environment, command, and node-ID fingerprint; totals alone are insufficient.

The owner-approved [September 2 plan](../human/sessions/2026-09-02.md)
explicitly authorizes a suite-at-baseline comparison, retained in the
[September 3 continuation](../human/sessions/2026-09-03.md). That specific
authorization governs this bounded cleanup despite the generic full-green
rule in [`CLAUDE.md`](../CLAUDE.md). The failures remain failures; this is
not a general waiver for future changes.

## Bounded apply-now work

One isolated-worktree builder may make only these changes, with no file deletion
and a 180-line diff cap:

- Correct active-plan, diagram, daemon, and model-role guidance in
  `README.md`, `START_HERE.md`, `ARCHITECTURE.md`, `PROJECT_CONTEXT.md`,
  `docs/sources/research_program_v2.md`, `docs/sources/README.md`, and
  `docs/AUTORESEARCH.md`.
- Repair the current broken links identified in `GLOSSARY.md` and
  `ARCHITECTURE.md` by pointing explicitly historical material into `archive/`.
- Remove only the obsolete non-strict `xfail` wrappers from
  `tests/test_tool_plane.py` and `tests/test_runlog_agent.py`; retain and run
  both test bodies normally.

The audit proposed removing the unused direct `pydantic` declaration, but the
primary excluded that change because no clean-install proof exists. It remains
an owner/dependency-session item.

## Retain and defer

| Item | Disposition | Reason |
| --- | --- | --- |
| Runtime `LOOP_V0` names in modules, schemas, bridges, and API paths | Retain | These are active protocol identifiers, not active-plan pointers. |
| Historical Week-1 Qwen decision in `PROJECT_CONTEXT.md` | Retain | Preserve it as temporally qualified history while correcting current guidance. |
| Legacy dispatched-agent bundle | Owner decision | It lacks a production import, but coordinated archive/removal would affect a module, schema, test, and historical contract. |
| Python lock/bootstrap strategy | Owner decision | Requires selecting the canonical interpreter and dependency policy before inventing pins. |
| Generic experiment provenance envelope | Owner decision | Cross-cutting schema and artifact change; do not retrofit results casually. |
| Protected-spine decomposition | Owner decision | High-risk serial-integrator work, not cleanup. |
| `OweStrip` and remaining UI drift | Future UI session | Already assigned by the UI work order; Team 2 must not write `ui/`. |
| Broken links under `archive/`, historical `human/`/`notes/`, and `ui_plan.md` | Retain or UI session | Do not rewrite append-only history merely to force a global zero. |

## Acceptance gates

The bounded candidate must independently satisfy:

- only the ten allowlisted files changed; no deletion or rename;
- `git diff --check` and `tools/premerge_check.sh` pass;
- changed-document local links resolve;
- the two named tests and `tests/test_autoresearch.py` pass;
- active guidance agrees with [`LOOP_V1.md`](../LOOP_V1.md) and current model
  roles while historical/runtime `LOOP_V0` references remain intact;
- a same-environment full-suite run introduces no new failing node, error, or
  timeout relative to the fingerprint above;
- framework code review reports no blocking finding.

Passing the baseline comparison means only “no regression from the ratified
checkpoint.” It does not mean that the full suite is green. Integration of
this cleanup uses the specific session authorization above.

## Completion — 2026-09-04

The ten-file cleanup landed as `2ad38c5` after independent review and fixes,
108 resolving local links, 43 targeted passes, and a passing mechanical
premerge gate at exactly 180 changed lines. The fresh same-environment suite
went from 7 failed / 2,487 passed / 1 skipped / 2 xpassed to
7 failed / 2,489 passed / 1 skipped, with identical failing node IDs and no
errors. Both formerly xpassed tests now pass normally. The seven existing
failures and the deferred health findings above remain open.

See [Team 2 validation](../notes/research/2026-09-02-teams/team2_validation.md)
for commands, review findings and resolution, comparison data, and smoke scope.
