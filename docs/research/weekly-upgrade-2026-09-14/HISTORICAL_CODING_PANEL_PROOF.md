# Historical coding panel proof

**Date:** 2026-09-14
**Verdict:** **SIX TASKS PROVED FOR CURATION; RUNNER REGISTRATION STILL PENDING**
**Manifest:** `experiments/weekly_historical_coding_panel_v1_2026-09-14.json`

## Result

Six public historical repair tasks passed the required focused proof:

- the exact public base failed for the intended defect;
- the exact public fix passed;
- a mutation made from the fixed tree, with only the declared repair file
  replaced by its exact base blob, failed again; and
- no run timed out or produced a dependency/collection failure.

The fixed trees passed **9/9 focused grader cases**. Across the untouched bases,
seven defect assertions failed and two independent control assertions passed.
All six mutated tasks reproduced their intended failure. This establishes that
the graders exercise the repair contract rather than merely accepting the
surrounding fixed revision.

This is a **public historical regression proof**. It is neither a private nor a
contamination-resistant benchmark, and no agent repair performance has been
measured.

## Receipts

| Task | Repair seam | Untouched base | Exact fix | Reverted-file mutation | Intended failure |
|---|---|---:|---:|---:|---|
| HCP-001 | Create a missing call-log directory | rc=1; 1 failed | rc=0; 1 passed | rc=1; 1 failed | missing_parent_directory |
| HCP-002 | Resolve frontier CLI binaries under a minimal PATH | rc=1; 1 failed | rc=0; 1 passed | rc=1; 1 failed | resolver_absent |
| HCP-005 | Preserve a JSONL ledger with an unterminated tail | rc=1; 2 failed | rc=0; 2 passed | rc=1; 2 failed | unterminated_tail_appended |
| HCP-006 | Recompute health on a budget-refused cycle | rc=1; 1 failed | rc=0; 1 passed | rc=1; 1 failed | health_recompute_omitted |
| HCP-007 | Bind an evaluation driver to the worker result schema | rc=1; 1 failed, 2 passed | rc=0; 3 passed | rc=1; 1 failed, 2 passed | worker_driver_contract_helper_absent |
| HCP-008 | Serialize replayed tool arguments with one deliberate trap | rc=1; 1 failed | rc=0; 1 passed | rc=1; 1 failed | tool_argument_polarity_reversed |

The sanitized failure classifications are:

- **HCP-001:** the base raised `FileNotFoundError` for the missing nested log
  directory.
- **HCP-002:** the base had no `_resolve_binary` implementation.
- **HCP-005:** both unterminated-tail cases were appended and reported as
  persisted instead of being refused without a write.
- **HCP-006:** the budget-refusal branch returned without invoking health
  recomputation.
- **HCP-007:** the driver lacked the loud worker-contract helper; its two
  independent result-shape controls still passed on the base.
- **HCP-008:** the old polarity produced four dictionary-typed replays in the
  trap history instead of exactly one.

Every row's base/fix commit and tree, task/grader/source-test hashes, repair-file
blob hashes, return code, test counts, elapsed time, raw-log hash, and
task-bound outcome hash are frozen in the manifest.

## Isolation

Each variant ran from a task-specific `git archive` allowlist at the exact
public commit. Documentation, notes, canonical `run_state`, memory, logs,
and historical result artifacts were absent. HCP-008 used a focused grader
derived from its public regression test and stubbed unrelated live-driver
imports, so it exercised only `tool_probe.build_messages`.

The command contract was:

```text
MOCK_LLM=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  .venv-chroma/bin/python -m pytest -q <test-node> \
  -p no:cacheprovider --basetemp <workspace>/.pytest_tmp
```

Each process received a new temporary `HOME`, an otherwise minimal
environment, empty CUDA visibility, and a Python audit hook that rejected
socket, subprocess, or process-spawn events. The accepted proof recorded
**zero guard events**. It made no model/GPU/network calls, installed no
dependencies, and wrote no canonical state. Raw pytest logs remain outside Git
in the disposable proof root; only their SHA-256 hashes are retained in the
manifest.

Environment: `Python 3.12.3`, pytest
`9.0.3`, `aarch64`,
`Linux-6.17.0-1018-nvidia-aarch64-with-glibc2.39`. The per-variant timeout was
60 seconds.

## What this closes

This converts six entries in `HISTORICAL_CODING_PANEL_PLAN.md` from
“ready to prove” into reproducibly hashed base-fail/fix-pass/mutation evidence.
It also excludes missing dependencies, test collection breakage, timeouts, and
accidental external activity as explanations for the results.

## Remaining boundary

The machine-readable artifact is a **proof manifest**, not yet a registered
agent benchmark. Before these tasks can affect a weekly upgrade decision, the
runner must:

1. materialize the scrubbed candidate workspace without the fix, manifest,
   commit subject, or grader;
2. keep the grader and base/fix control receipts outside candidate visibility;
3. enforce the declared one-file repair allowlist and timeout;
4. register and hash the exact grader material, including the focused HCP-008
   grader; and
5. report this panel separately from the synthetic eight and from any future
   owner-sanitized private/hidden tasks.

Only the focused contract tests were run here. A broader unchanged regression
suite was outside this bounded proof task and should be added only if declared
as part of the scored runner contract.
