# Preregistration — weekly public-historical coding repair baseline v2

**Frozen:** 2026-09-14  
**Manifest:** `experiments/weekly_historical_coding_panel_v2_2026-09-14.json`  
**Evidence class:** `public_historical`; `contamination_resistant=false`

## Question

Can the resident Gemma generator, under the explicit experimental
`coding_precise` profile, produce a valid one-file repair for each of six
previously proved repository defects from only a scrubbed behavior contract and
the exact base file?

This first run establishes a descriptive baseline. It has one arm, supplies no
matched comparison, and cannot support a claim that one model, runtime, or
policy is better than another.

## Frozen panel and denominator

The task order is HCP-001, HCP-002, HCP-005, HCP-006, HCP-007, HCP-008. All six
are retained in the failure-inclusive denominator, including transport errors,
timeouts, malformed output, patch rejection, sandbox denial, and test failure.
The score is successful repairs / 6. A task succeeds only when:

1. the wrapper records the exact resident model and resolved policy;
2. the completion is strict JSON with only `path` and `patch`;
3. the path equals the one registered repair path;
4. the unified diff changes that file and no other file; and
5. every focused grader case passes in the pinned sandbox.

Correct Task Throughput is successful repairs divided by total run wall time.
It is reported alongside the six-case score and must not replace it.

## Candidate isolation

The prompt excludes test bodies, grader paths, proof observations, fix commits,
known-fix content, commit subjects, historical notes, and Git history. The model
has no terminal or tool surface. Workspace export and grading happen after the
completion is durable. Only preregistered public base sources and fixtures enter
the disposable workspace.

The grader runs under bubblewrap with an allowlisted filesystem, private PID and
network namespaces, cleared environment, disabled GPU visibility, bounded CPU,
address space, files and output, and an audit hook denying network and process
spawn. Source and grader files are read-only. A disposable `run_state` overlay
supports legacy offline tests without exposing or modifying canonical state.

The grader is hidden from the model request, not cryptographically hidden from
Python executing later in the same read-only sandbox. A separate trusted
supervisor scores pytest hook receipts sent over a private pipe and ignores
candidate-controlled terminal summaries. Missing terminal hooks, early process
exit, audit denial, malformed hook reports, and output overflow cannot pass.
This is a hardened functional benchmark boundary, not a proof against an
arbitrary program designed with prior knowledge of the harness implementation.

## Resources

- one resident Gemma call per task; six serial calls;
- 4,096 maximum output tokens per call;
- 145 seconds maximum per model request;
- 15 seconds maximum per grader;
- 90 seconds cumulative grading ceiling;
- 1,020 seconds runner ceiling inside a 1,050-second controller reservation;
- no dependency install, service action, runtime cutover, or production write.

## Interpretation

The public fail-before/pass-after/mutation proof is bound through the v1 proof
manifest. Public provenance means a model could have encountered related code
or fixes before evaluation. Report this panel separately from synthetic
development fixtures and any future owner-held private tasks.

Completion records measurement only. It does not authorize promotion, runtime
changes, role reassignment, or scheduler/service changes.
