# V2 engineering audit

**Audit date:** 2026-09-14
**Code baseline inspected:** `62fad9f100b04755c6415d266ab9ebc491e489ff`
**Scope:** tracked source, tests, schemas, launchers, installed user scheduling,
data contracts, retained benchmark evidence, and the v2 preparation changes in
the shared worktree.

This audit separates observed repository or runtime facts from recommendations.
It did not use prose under `human/` to infer what v0 or v1 accomplished. Human
material was preserved by the research archive and remains researcher-owned.

## Findings that affect v2

| Priority | Observed fact | Consequence | Required action |
| --- | --- | --- | --- |
| Resolved | `agent/README.md`, `agent/prompts/main.md`, and `agent/prompts/ui_session.md` now direct sessions to `LOOP_V2.md`, label v2 as preparation, and treat LOOP_V0/v1 as historical build records. Remaining LOOP_V0 references describe compatibility artifacts or the original loop rather than present authority. | The stale agent-facing authority path found during the audit is closed. | Keep the root front doors and these compatibility prompts aligned when v2 activates. |
| Resolved | A clean public checkout does not contain the ignored live inputs `memory/loop_memory.jsonl`, `memory/surfaced_findings.jsonl`, or `memory/idea_ledger.jsonl`. Thirteen tests in the initial integration run failed because those inputs and a checkout-local interpreter link were absent. Five tests that intentionally inspect the operator corpus now carry the explicit `canonical_corpus` marker, while the critic-calibration subprocess uses the running test interpreter. | A clean clone can run the portable suite without treating absent private state as a product failure. The five corpus checks remain scientific regression locks rather than disappearing from the suite. | Keep a required canonical-host job using `REQUIRE_CANONICAL_CORPUS=1`; its failure on any missing named input is intentional. The default clean-clone run may skip exactly those five marked checks. Do not copy private live data into Git. |
| P1 | Experiment summaries remain intentionally heterogeneous and have no common JSON Schema (`docs/DATA_SHAPES.md`, section 2). Core ledgers also have several independently implemented JSONL readers and appenders. | Cross-campaign joins, missing-versus-zero handling, and schema evolution require bespoke code. Silent semantic drift is likely as v2 adds campaign views. | Add a small registry describing producer, schema/version, identity key, observation time, availability semantics, and privacy class. Migrate a producer only with backward-read fixtures. |
| P1 | Research lineage is spread across topic attempts, dispatches, iterations, evidence, promotion reviews, findings, and human verdicts. The current v2 projection has to join these sources defensively. | A transport completion can be mistaken for scientific completion, and substring or timestamp joins can create false lineage. | Issue stable campaign/question/attempt IDs before dispatch and carry exact IDs forward. Keep the maintenance evaluation graph separate from the scientific verdict graph. |
| P1 | The current service and cron launchers use absolute paths into the canonical checkout. Linked worktrees need a local interpreter link for some tests, but deployed services must continue to target the canonical checkout. | Testing from a worktree and operating production are different environments. | Record checkout identity in deployment receipts. Test worktree portability without changing canonical service paths. |
| P2 | `run_state/week1.state.json` and `run_state/week1.run.jsonl` remain active canonical names even though the apparatus has moved beyond week 1. | The filenames encourage accidental historical interpretation and make future migrations tempting. | Treat the names as compatibility aliases. Introduce a versioned logical name in the data registry before any physical rename. |

## Repository and entrypoint inventory

At the inspected commit, `git ls-files` reported 1,326 tracked paths: 494
Python files, 184 top-level Python tests, 118 paths under `bench/`, 268 under
`experiments/`, 46 under `orchestrator/`, 27 under `workers/`, and 16 under
`agent_wrapper/`. There were 24 shell scripts and 20 schema files.

The deployed and scheduled entrypoints observed during the audit were:

- `nara-daemon.service` executes
  `.venv-chroma/bin/python -m orchestrator.nara_daemon` from the canonical
  checkout and is enabled as a user service.
- User cron runs `cron/run-coordinator.sh` hourly, `cron/watchdog.sh` every five
  minutes, `cron/weekly-frontier-agenda.sh` Sunday at 05:30 UTC, the UI service
  helper, literature ingestion, and the Chroma snapshot.
- `ui/scripts/ui-services.sh` starts the FastAPI backend, telemetry sampler,
  and Vite frontend from the canonical checkout.
- Benchmark and experiment modules are also legitimate manual entrypoints.
  Their absence from a Python import graph does not establish that they are
  dead.

A repository-wide AST import scan found 269 Python files with no static
incoming import. Most were tests, command-line programs, experiment runners,
embedded benchmark starters, or UI entrypoints. That result is why this audit
required corroboration from shell launchers, service definitions, tests,
registries, documentation, and live scheduling before removal.

## Confirmed retirement: autonomy-v1 sweepers

Six paths met the removal bar:

| Active path removed | Why it is no longer executable infrastructure |
| --- | --- |
| `tools/claims_check.py` | Reads the retired/absent `agent/ownership.yaml` and `run_state/claims.jsonl` contract. |
| `tools/gate_sla_check.py` | Implements the retired autonomy-tier soft/hard gate contract and refers to absent `agent/autonomy.md`. |
| `cron/claims-weekly.sh` | Wrapper for `claims_check.py`; its own header says it was not installed. |
| `cron/sla-sweep.sh` | Wrapper for both retired tools; its own header says it was not installed. |
| `tests/test_claims_check.py` | Dedicated tests for the retired claim registry. |
| `tests/test_gate_sla_check.py` | Dedicated tests for the retired autonomy SLA. |

The retirement is supported by all of the following observations:

1. `agent/README.md` records that the Track A/B/C/D ownership, claim/lock, and
   autonomy-tier machinery was retired on 2026-05-26 in `08fc327`.
2. A tracked-source reference scan found no active caller outside the two
   wrappers and their dedicated tests. Remaining references are explicitly
   historical prose or comments.
3. The user crontab contained neither wrapper, and no matching user or system
   timer was installed.
4. The two dedicated test files passed before removal (`41 passed`). This
   establishes preservation fidelity, not current operational relevance.
5. Each original byte stream was copied to
   `archive/retired-autonomy-v1/` with a `.txt` suffix, mode `0644`, source path,
   SHA-256, reason, and revival rule. A post-copy comparison against
   `git show HEAD:<source>` matched all six files exactly.

The archive index is `archive/retired-autonomy-v1/README.md`. Restoring a
single tool would not restore its missing schemas, inputs, scheduler, or
authority model; revival requires a new coherent design.

## Confirmed retirement: old dispatcher and proposal drafts

Eight additional paths met the removal bar:

- `agent_wrapper/dispatch_coding_agent.py`;
- `tests/test_dispatch_coding_agent.py`;
- all four Day-8/Day-9 drafts under `schema/proposed/`;
- `tests/test_calls_schema_proposed.py` and
  `tests/test_events_schema_proposed.py`.

The dispatcher depends on the absent
`agent/ownership.yaml` and `agent/prompts/dispatched_task.md`; its test is
module-level skipped with an explicit 2026-05-26 retirement reason; and the
active `orchestrator/packet_dispatcher.py` says it only salvaged patterns from
the stale dispatcher and does not import it. The proposed dispatched-task
schema still describes the retired Track A and autonomy-tier model.

A tracked-source scan found no producer, importer, loader, registry, launcher,
cron job, or service consuming any of these paths outside their dedicated
tests and historical references. The dedicated legacy slice reported `67
passed, 1 skipped, 35 subtests passed` before removal. The active
`schema/task_packet.schema.json`, packet dispatcher, self-improvement, and lab
channel slice separately reported `133 passed, 19 subtests passed` before and
after archival. Exact original bytes and SHA-256 values are preserved as
non-executable `.txt` files under `archive/retired-autonomy-v1/`.

Historical mentions in `DECISIONS.md`, `GLOSSARY.md`, `LOOP_V1.md`, journals,
and session records remain provenance. They do not make the retired files
active entrypoints.

No other source path met the same evidence bar. In particular, standalone
files under `bench/`, `experiments/`, `scripts/`, and `tools/` were retained
when they had a documented manual invocation, a test consumer, a registry
entry, a launcher reference, or immutable evidence value.

## Data-contract assessment

### What is working

- Core research records have versioned JSON Schemas where compatibility is
  load-bearing (`schema/iteration_record.schema.json`,
  `schema/active_run.schema.json`, `schema/task_packet.schema.json`, and the
  production call/event schemas).
- The follow-through evaluation runners bind manifests, task/input/grader
  hashes, execution-source hashes, call identities, budgets, denominators, and
  terminal states. They preserve failures as denominator rows rather than
  dropping them.
- The benchmark progress projection distinguishes terminal transport trials,
  recorded evaluations, complete executions, objective denominators, budget
  charges, and comparison eligibility. A broken cohort fingerprint withholds a
  longitudinal delta.
- The research-pipeline projection distinguishes an unavailable source from a
  verified zero and joins by exact identifiers within an explicit time window.
- Append-only source ledgers preserve negative results and later corrections.
  Derived UI views remain rebuildable and weaker than their source evidence.

### What remains fragmented

- `docs/DATA_SHAPES.md` explicitly documents heterogeneous experiment
  `summary.json` files without a schema. Feature detection is useful for old
  evidence, but it is not a stable v2 write contract.
- JSONL parsing, malformed-tail behavior, read bounds, and last-write folding
  are implemented in several modules. The code has good local defenses, but
  the semantics are easy to vary unintentionally.
- Older records often lack model/backend, observation time, campaign identity,
  or exact cross-ledger IDs. Backfilling an inferred value would overstate the
  evidence.
- Operator summaries are useful annotations. They cannot replace raw outcome
  rows, executable graders, or human verdict records.
- Private live ledgers are required for some integration views but are absent
  from a public checkout. The repository does not yet express that dependency
  consistently in test markers or fixture contracts.

### V2 contract sequence

1. Publish a read-only source registry before changing writers.
2. Define campaign and research-question identities as additive fields.
3. Add compatibility readers and fixtures for legacy records.
4. Change one producer at a time and bind the projection to source hashes.
5. Preserve missing fields as unknown; do not synthesize zeroes.
6. Keep human verdicts, scientific evidence levels, and apparatus-evaluation
   decisions in separate record types.
7. Retire a legacy path only after static references, dynamic entrypoints,
   schedulers, tests, and canonical-host use all clear it.

## Archive assessment

The most comprehensive non-destructive v0/v1 archive described by
`docs/v2/RESEARCH_ARCHIVE.md` contains 20,310 files and 959,334,485 bytes. Its
manifest identity is
`ef57b8e8027d04bc3c93c171d736438b852f5b23a5e51989d9883cbdbc33025f`.
Earlier narrower receipts remain in the append-only receipt history; their
smaller counts and hashes describe earlier captures rather than the current
authoritative archive.
The archive verifier now checks every listed byte stream, rejects unlisted or
redirected entries, enforces cumulative bounds during copy, and records named
credential-path exclusions accurately. It does not claim content-based secret
detection. The authoritative archive passed full verification after those
checks were added.

This is a preservation snapshot with per-file cutoffs. It is not a global
transaction across running append-only services. The originals remain in
place, and the archive does not rewrite historical scores.

## Validation record

- Retired-sweeper baseline: 41 tests passed before archival.
- Retired dispatcher/proposal baseline: 67 tests passed, one explicitly
  retired dispatcher module was skipped, and 35 subtests passed. The active
  packet-dispatch slice separately passed 133 tests and 19 subtests before and
  after archival.
- Archived retired files: all fourteen byte-for-byte comparisons and SHA-256 values
  matched; every preserved copy is non-executable.
- Historical repair runner review: 46 focused historical/controller tests
  passed, scoped Ruff passed, and the diff check passed after adversarial
  receipt fixes.
- Initial root integration run: 2,953 tests passed before 13 failures were
  isolated to three ignored operator ledgers and a checkout-local interpreter
  path. The portability repair leaves five corpus-dependent tests explicitly
  marked: an isolated clean clone reported 115 passes and five precise skips,
  while `REQUIRE_CANONICAL_CORPUS=1` failed on exactly those missing inputs.
  With the named inputs present, the required-corpus slice reported 120 passes.
  The required canonical-host mode must remain part of release validation.

## Activation implications

The codebase has enough structure to run bounded policy, diversity, effort,
historical-repair, and CPU calibration experiments. Agent-facing plan pointers
now agree, and the first game-theory/agent-behavior campaign is selected and
registered. V2 should remain labeled preparation until that campaign passes
its activation gates, a post-cutoff attempt reaches the measured pipeline, and
the cross-ledger identity additions have compatibility tests. CPU-only game
calibration validates game mechanics and identifiability; it does not measure
LLM behavior, model quality, or scientific novelty.
