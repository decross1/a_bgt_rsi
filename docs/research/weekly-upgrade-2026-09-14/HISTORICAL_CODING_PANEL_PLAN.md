# Historical coding panel curation plan

**Prepared:** 2026-09-14
**Repository:** `decross1/a_bgt_rsi`
**Public-history boundary:** candidates below are ancestors of public
`origin/main` at `d920cba71077480035690cd0389a74b42077b231`.

## Decision and evidence boundary

Public history contains enough authentic regressions to curate a first
repository-repair panel. Eight candidates have small implementation surfaces
and direct offline tests. Two more are useful reserves but need a stronger
grader before they should affect an upgrade decision.

This is a **curation plan**, not a completed benchmark. This audit inspected
public commits, diffs, and tests without checking out old revisions or running
historical code. Every candidate still needs an isolated fail-before/pass-after
proof. The tasks are authentic, but they are not private or contamination-free:
their commits and tests are public. They therefore measure project-shaped
repair under a reproducible harness, not memorization-resistant generalization.

Status terms:

- **READY TO PROVE:** bounded public base/fix pair and an existing objective,
  offline regression test were found. It becomes runnable only after the proof
  protocol below succeeds.
- **CONDITIONAL:** authentic and bounded, but the existing test or historical
  evidence is not strong enough for scoring without an added hidden check.

## Candidate panel

All SHAs are public. “Base” is the fix commit's first parent. Documentation,
session notes, and recorded run outputs are provenance only; they must not be
placed in the repair workspace or supplied as solution hints.

### HCP-001 — create a missing call-log directory

- **Status:** READY TO PROVE
- **Base -> fix:** `d7faff3019b1` -> `1eba8f6027ca`
- **Repair surface:** `agent_wrapper/wrapper.py`
- **Objective tests:** `tests/test_wrapper_calls_log_mkdir.py`, especially
  `test_emit_creates_missing_log_dir` and
  `test_emit_appends_to_existing_dir`
- **Defect contract:** emitting to a configured nested JSONL path must create
  its parent directory and must append without replacing prior records.
- **Constraints:** temporary filesystem only; no model, network, dataset,
  credential, daemon, or GPU is needed.

### HCP-002 — resolve frontier CLI binaries under a minimal PATH

- **Status:** READY TO PROVE
- **Base -> fix:** `350ef5afc340` -> `2f9738c4a1fa`
- **Repair surface:** `agent_wrapper/frontier_cli.py`
- **Objective tests:** `tests/test_frontier_cli.py`, including
  `test_resolve_binary_order` and the existing Claude/Codex command-shape tests
- **Defect contract:** resolve each CLI in the order explicit environment pin,
  executable user install, then bare command name; use the result for command
  construction and version lookup.
- **Constraints:** the grader must replace HOME and environment paths with
  temporary fixtures and stub subprocess execution. It must never invoke a
  frontier CLI or expose subscription credentials.

### HCP-003 — enforce planner escalation admission at both boundaries

- **Status:** READY TO PROVE
- **Base -> fix:** `eff0042a0544` -> `6239ce43a791`
- **Repair surface:** `orchestrator/coordinator.py` and
  `orchestrator/coordinator_actions.py`
- **Objective tests:** `tests/test_coordinator_actions.py` and
  `tests/test_coordinator_escalation.py`, including the invalid kind/action,
  literal-enum agreement, whitespace-only payload, and no-dispatch-on-invalid
  tests introduced by the fix
- **Defect contract:** planner schema admission and the defensive handler must
  share the escalation enums, reject inadmissible payloads before charging or
  dispatching, and retain all established valid forms.
- **Constraints:** Python plus `pytest` and `jsonschema`; patch model calls and
  handlers. Use only temporary run-state paths.

### HCP-004 — reject an explicitly empty escalation question

- **Status:** READY TO PROVE; use as a reserve if HCP-003 makes the panel too
  concentrated on one subsystem.
- **Base -> fix:** `6239ce43a791` -> `0ff11b871321`
- **Repair surface:** `orchestrator/coordinator_actions.py`
- **Objective tests:** `tests/test_coordinator_actions.py` and
  `tests/test_coordinator_escalation.py`, including
  `test_bubble_up_admission_rejects_supplied_empty_question_with_legacy_ids`
  and the valid coexistence check
- **Defect contract:** omitted `question` remains compatible, but a supplied
  empty string violates the persisted wire contract even when legacy finding
  IDs are present.
- **Constraints:** offline schema/handler tests only. This follows HCP-003 in
  history, so its base must be exactly the stated commit rather than an older
  common base.

### HCP-005 — preserve a JSONL ledger with an unterminated tail

- **Status:** READY TO PROVE
- **Base -> fix:** `0c3e22d4d771` -> `9c540351a108`
- **Repair surface:** `orchestrator/coordinator.py`
- **Objective tests:** `tests/test_coordinator_escalation.py`, including
  `test_t05_unterminated_tail_refuses_append_and_preserves_history` and
  `test_t05_newline_history_and_unicode_append_remain_reader_compatible`
- **Defect contract:** refuse an append before writing if the existing file
  lacks a terminating newline; preserve old bytes, distinguish definitely
  unpersisted from uncertain durability, and keep valid Unicode rows readable.
- **Constraints:** temporary files and injected write/flush/fsync failures
  only. No canonical ledger or concurrent writer may be used.

### HCP-006 — recompute health on a budget-refused cycle

- **Status:** READY TO PROVE
- **Base -> fix:** `7405ae953e3a` -> `f7c3c27e56f7`
- **Repair surface:** `orchestrator/coordinator.py`
- **Objective tests:** `tests/test_coordinator.py`, principally
  `test_budget_refusal_still_recomputes_health_alert`; the same fix also pins
  budget state in three time-dependent coordinator tests
- **Defect contract:** a daily-budget refusal must still emit current health
  signals while making no dispatch/model call.
- **Constraints:** stub wall-clock budget functions and health emission; use
  temporary state. Exclude `run_state/spawn.jsonl` from both prompt and allowed
  patch because it is an operational record, not implementation.

### HCP-007 — bind an evaluation driver to the worker's actual result schema

- **Status:** READY TO PROVE
- **Base -> fix:** `4bb4d3d25cb8` -> `771c7b15d44b`
- **Repair surface:** `bench/critic_eval/stage3a_driver.py`
- **Objective tests:** `tests/test_stage3a_driver_contract.py`, covering the
  worker key set, AST reads of the result object, and loud failure on a missing
  verdict key
- **Defect contract:** consume `attack_verdict` and `rationale`, never silently
  interpret nonexistent `verdict`/`status` fields as model failure, and fail
  loudly on future contract drift.
- **Constraints:** AST and pure result-shape checks only. Set `MOCK_LLM=1`, deny
  network, and do not execute the 22-case model battery.

### HCP-008 — serialize replayed tool arguments with one deliberate trap

- **Status:** READY TO PROVE after the repair workspace excludes historical
  run-result JSON
- **Base -> fix:** `a217880c4374` -> `53fc78367f4d`
- **Repair surface:** `bench/fp8_ab/tool_probe.py`
- **Objective tests:** `tests/test_fp8_ab_driver.py`, particularly the modified
  `test_probe_script_is_deterministic_and_trap_is_isolated`
- **Defect contract:** normal OpenAI-compatible replay arguments are JSON
  strings; exactly one designated trap is a dictionary; repeated message
  construction stays deterministic.
- **Constraints:** score only the pure message builder. The fix commit also
  contains three large live-run JSON artifacts; exclude them from the prompt,
  workspace overlay, patch allowance, and grader. Do not make HTTP/model calls.

### HCP-009 — make a turn wall capable of spending its token budget

- **Status:** CONDITIONAL
- **Base -> fix:** `db9fee9e6b28` -> `5c0f2739fab0`
- **Repair surface:** `workers/debate.py` and
  `orchestrator/finding_promotion.py`
- **Existing tests:** `tests/test_debate.py`, including
  `test_turn_wall_can_fund_a_full_token_budget` and
  `test_decode_rate_is_the_slower_measured_export_not_an_optimistic_one`
- **Defect contract:** configured wall time must cover the advertised token
  cap at the declared conservative decode rate, including a bounded margin.
- **Why conditional:** the unit tests prove arithmetic/config coherence but do
  not independently authenticate the historical 16.5 tok/s measurement or
  exercise timeout propagation. Add a frozen measurement receipt check and a
  harmless fake slow-worker boundary test before this affects model promotion.
- **Constraints:** never use a live backend for grading.

### HCP-010 — reattach a non-gating advisory after re-retrieval

- **Status:** CONDITIONAL
- **Base -> fix:** `e3add86a0ec8` -> `bcf1563657d7`
- **Repair surface:** `orchestrator/nara.py`
- **Existing tests:** `tests/test_ml_intern_advisory_reattach.py`, covering the
  armed, dark-by-default, and primary-condemned paths
- **Defect contract:** after the `ml_intern` re-retrieval path recomputes
  relevance, attach the optional topicality advisory only when armed and keep
  it non-gating.
- **Why conditional:** most behavioral assertions run against an in-test
  mirror; only a source-string assertion connects them to `nara.py`. Replace
  that weak connection with an extracted pure helper or an integration test
  that executes the real branch before scoring it.
- **Constraints:** use fixed public game-theory fixtures and `MOCK_LLM=1`; patch
  the skeptic; no corpus, Chroma, network, model, or canonical cache access.

One other authentic public fix, `b9ec733a6cbf` (watchdog cron working-directory
resolution), was screened but is not proposed as a scored task because its fix
commit added no objective regression test. It can enter a later reserve set
after a hermetic shell test proves module resolution from a foreign CWD.

## Required curation and proof protocol

For each READY TO PROVE candidate:

1. Create an isolated, disposable worktree at the exact public base commit.
2. Copy only a scrubbed task statement and a hidden grader derived from the
   fix-side tests. Do not expose the fix SHA, commit subject, patch, explanatory
   comments, or test body to the candidate.
3. Limit writable paths to the declared repair surface. Set a temporary HOME,
   clear credential variables, disable network, set `MOCK_LLM=1`, and deny
   access to canonical `run_state`, model endpoints, datasets, and services.
4. Prove the hidden grader fails for the intended reason on the untouched base
   and passes on the exact public fix. Reject tasks that fail because the old
   environment no longer installs or whose fix passes for an unrelated reason.
5. Add at least one mutation check that reintroduces the defect while retaining
   incidental refactors. This guards against tests that merely recognize the
   historical patch text.
6. Freeze base/fix trees, task input, grader, allowed paths, dependency lock or
   container digest, timeout, architecture, and all hashes in a signed manifest.
7. Grade functional tests first, then the unchanged relevant regression suite.
   Record exit status, test counts, timeout, patch scope, and artifact hashes.

These public tests can seed hidden graders, but should not be copied verbatim
into the model-visible workspace. A task is admitted to the weekly panel only
after the fail-before/pass-after and mutation evidence is stored.

## Relationship to the current eight-task portfolio

The current eight-task slice in `BENCHMARK_PORTFOLIO_PLAN.md` is correctly
labelled **public synthetic development data**. It contains six
science/evidence exercises and two authored coding exercises (delegation and
external regret). It is useful for proving manifest, sandbox, execution,
grading, receipt, and paired-arm mechanics. It does not measure repair of this
repository and must not be relabelled historical, private, hidden, or
contamination-resistant.

The historical candidates above add a different signal: bounded repairs at
real project seams. They still do not complete the originally contemplated
20–40-task private repository suite. A defensible progression is:

1. use the synthetic eight only as the public development/canary panel;
2. curate and prove six of HCP-001 through HCP-008 as a public historical
   regression panel, holding two as rotation reserves;
3. strengthen HCP-009/HCP-010 before admitting either;
4. later create owner-sanitized private tasks and graders outside public Git,
   with a hidden fresh set drawn from future real failures; and
5. report public-historical and private-hidden results separately.

Until step 4 exists, reports must say “public historical regression panel,”
not “private repo benchmark.”

## Long-context completion gap

The resident serving contracts cap **Qwen at 16,384 total tokens** and
**Gemma at 32,768 total tokens**. A claimed paired 32K or any 64K evaluation
would therefore be false under the current launcher. Context limits cover the
whole request plus generated output; a “16K input” with no output reserve is
also not a valid Qwen arm.

The feasible first public-evidence lane is:

- freeze two approximately 8K-token and two approximately 14K-token evidence
  packs from hashed public `origin/main` blobs;
- reserve system/tool/output tokens explicitly and compute exact lengths with
  each installed model tokenizer rather than estimating from characters;
- run identical 8K and <=14K packs on both resident models, with fixed facts,
  contradictions, source IDs, and answer schema;
- compare full-context against a preregistered retrieved/compacted version;
  score fact recall, contradiction detection, attribution, unsupported claims,
  completion, TTFT, wall time, and memory; and
- use only public evidence. Do not copy private notes, runtime logs, secrets,
  or canonical state into a reusable benchmark fixture.

A later **32K lane is Gemma-only** under the current contract and must leave a
generation reserve below 32,768. It can qualify Gemma long-context behavior,
but it cannot be presented as a same-model or paired-model Qwen comparison.

The **64K lane is blocked** for both resident servers. It requires a separate
challenger runtime/context allocation, memory and repeated-call qualification,
and an immutable launch/runtime receipt before any task is dispatched. The
weekly loop must reject, rather than truncate or silently reroute, a 32K Qwen
or 64K resident task. This limitation is a recorded future experiment, not an
unfinished weekly canary that can be claimed today.

## Concrete completion criteria

This portion of the handoff is complete when:

- at least six READY TO PROVE tasks have clean base-fail/fix-pass and mutation
  receipts in an immutable, CPU-only sandbox;
- their manifests and graders are registered while solutions remain hidden
  from the evaluated agent;
- reports retain the `public_historical` provenance label and keep their score
  separate from the synthetic eight;
- the four public-evidence 8K/~14K fixtures have tokenizer-specific size and
  answer-key hashes and pass a no-model structural validation; and
- 32K is labelled Gemma-only and 64K remains ineligible until runtime
  qualification changes the serving contract.
