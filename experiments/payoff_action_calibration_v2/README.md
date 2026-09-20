# Payoff-action native-tool v2 — offline core and excluded runner

This package separates a model's tool-call shape, one local execution, the
continuation scaffold, and the quality of the final answer. The contract core
is pure and offline. A bounded runner now applies that core to a fresh,
permanently excluded engineering shakedown against the already-resident Flash
endpoint.

The runner does not start, stop, or reconfigure serving. The package has no
scheduler, registration, scientific-admission, production-cutover, or
promotion path. It does not change or regrade any v1 file or result.

**Operational status on 2026-09-20:** implementation and injected-fixture
testing only. No live v2 experiment request was made. Oracle separately used
Flash for bounded peer review; that review was not a v2 study request or
result. The commands below document the operator interface and were not
executed as part of this work.

## Frozen core decisions

- Contract ID: `payoff-action-native-tool-core/v2`.
- Visible pre-tool content is classified by strict UTF-8 byte length. `None`,
  empty, whitespace, and ordinary nonempty strings are eligible through 512
  bytes. Byte 513 is not eligible. No lexical rule labels prose benign.
- Raw pre-tool content remains evidence. The primary continuation always uses
  assistant `content=""`; policy ID is `empty-pretool-content/v2`.
- Valid intended `reasoning_content` is recorded separately and is not treated
  as visible reasoning leakage. Invalid type or encoding is an integrity
  failure.
- An unavailable transport or receipt leaves downstream call, argument, and
  content-validity facets `unassessed`. Raw partial counts and text remain
  diagnostic evidence; they are not credited as protocol observations.
- Tool-call strings require strict UTF-8. Argument text is capped at 8,192
  bytes and 16 JSON container levels before parsing, so corrupt Unicode and
  adversarial nesting become classified failures instead of escaping.
- `strict_v1_comparable` is true only for an otherwise eligible turn whose
  visible content is `None` or `""`.
- Tool classification is pure. It parses and validates but never calls the
  calculator or another executor.
- Each call to `execute_once()` consumes the classifier's parsed arguments and
  invokes the supplied local executor at most once, then canonicalizes the
  returned finite JSON once and retains those exact bytes. The execution
  receipt is bound to the exact
  classified call and arguments so it cannot be paired with another eligible
  call. Eligibility is not an execution receipt.
- The continuation inserts the retained result bytes. It never recomputes a
  result from a frozen cell.
- Final protocol, final content contract, and substantive correctness are
  graded independently. A wrong final answer cannot rewrite successful tool
  progression; a grader failure remains unassessed rather than becoming a model
  failure.

All sequential facets use `pass`, `fail`, or `unassessed`. Stable failure codes
remain orthogonal: transport, receipt, finish reason, no-call bypass, call
shape/name, JSON, argument contract/value, visible content, reasoning content,
executor, result contract, final protocol, terminal contract, and substantive
quality are not collapsed into one status.

## API

1. Build a `ToolExpectation` with the exact tool name, `calculator` or `table`
   argument contract, and expected frozen arguments.
2. Call `classify_tool_turn(...)`. The result contains retained raw content,
   parsed arguments when structurally valid, and an exact accepted call only
   when execution is eligible.
3. Call `execute_once(...)` with a local executor and a pure result validator.
   `calculator.calculate` plus `calculator_result_contract_valid` is the
   calculator path used by fixtures.
4. Call `build_empty_content_continuation(...)`. Its `messages()` method returns
   fresh assistant/tool messages whose tool content is byte-identical to the
   retained result.
5. After the runner obtains a terminal model response, call
   `grade_final_turn(...)` with a pure task-specific grader returning
   `FinalContentAssessment`.

The result validator in this core validates schema and internal consistency. It
does not perform another live tool execution. The replay validator may apply
pure result checks and independently recompute expected calculator payoffs, but
labels that work as replay verification rather than a second execution.

The core has no process-global idempotency store. The runner calls
`execute_once()` at most once for each classified turn and persists a durable
attempt marker before entering the executor. Repeated direct calls to the core
function remain separate requested executions.

## Implemented excluded design

`design.py` freezes four new units with endowments `22`, `26`, `30`, and `34`.
Their cell IDs, task hashes, controls, and seeds are new v2 identities; no v1
outcome is imported as evidence. Each unit is paired across three arms:
`direct`, `table`, and `calculator`.

The denominator is fixed before any request:

- 4 units;
- 12 unit/arm conditions;
- 4 direct slots;
- 8 first-turn native-tool slots across the two tool arms; and
- 8 possible post-tool final slots, for 20 designed slots and at most 20 model
  calls.

Every designed slot receives exactly one disposition: returned, failed,
skipped unissued because tool progression was ineligible, or unissued after an
abort. A malformed call, unavailable transport, cancellation, or early abort
cannot remove a unit or condition from the denominator. The cohort is
permanently excluded from confirmation, scientific admission, L2 evidence,
model-quality claims, strategy-generalization claims, and market claims.

The frozen limits are 512 output tokens per call, a 30-second call timeout, a
900-second evaluator budget, a 20 GiB available-memory floor, and one
cooperatively exclusive run. Readiness, memory, and runtime identity are
checked around every issued call. The idle observation explicitly does not
claim exclusion of uncoordinated direct HTTP clients or isolated latency.

## Components and schemas

| Component | Versioned contract | Responsibility |
| --- | --- | --- |
| `contract.py` | `payoff-action-native-tool-core/v2` | Pure classification, one-shot execution, retained-result continuation, and final grading |
| `design.py` | `flash-payoff-action-calibration-plan/v2` | Fresh panel, exact controls, source hashes, runtime binding, limits, authority boundary, and plan freeze/load |
| `wire.py` | `flash-payoff-action-calibration-private-call/v2` | One bounded request, strict request and response digests, raw SSE retention, partial-failure evidence, and offline call replay |
| `runner.py` | `flash-payoff-action-calibration-run/v2` | Fixed-denominator orchestration, resource and cancellation gates, public receipts, and exhaustive slot accounting |
| `runner.py` plan claim | `flash-payoff-action-calibration-plan-claim/v2` | Permanent, nofollow, create-exclusive consumption of one study/plan identity before any effectful request |
| `runner.py` private protocol | `flash-payoff-action-calibration-private-protocol/v2` | Durable per-condition wire/execution markers, exact private channels, retained execution bytes, continuation, and final grade |
| `replay.py` | `flash-payoff-action-calibration-validation/v2` | Offline authentication and deterministic regrading of the complete plan/run/private bundle |

Plan loading recomputes the source-bound design and rejects source, panel,
runtime, denominator, policy, tool-spec, limit, or authority drift. Wire
evidence binds the exact rendered request body, messages, tools, policy,
content, reasoning content, tool calls, response receipt, and raw SSE bytes.
Only a complete raw SSE stream that agrees with its response receipt can have
status `returned`. Missing or contradictory transport evidence is an explicit
integrity error and cannot be credited as a tool observation.

## Evidence, accounting, and replay

The plan binds an absolute private artifact root outside every Git checkout.
Plan, run, call, stream, and condition-protocol files are created beneath that
root with private directory and file permissions. `run.json` contains slot
dispositions, public grades, accounting, and digests; exact model content,
reasoning, native calls, local result bytes, and continuation messages remain
in the private evidence files.

After admission and before any effectful request, the runner creates a
permanent, create-exclusive plan claim under the artifact root. The claim binds
the study ID and plan digest to the one output path. That study/plan identity is
single-use even if the requested output directory is changed later. The runner
then writes a durable `wire_attempting` marker before each model request and an
`execution_attempting` marker before each eligible local execution. It never
resumes or appends to an existing output directory. These refusals are
intentional: after a crash, a claim or in-flight marker may represent a
dispatched request or completed executor whose terminal receipt was not
persisted. Automatic retry could duplicate either action.

Transport failures keep any validated partial content, reasoning, calls, and
raw bytes as diagnostic evidence. Sequential facets downstream of unavailable
evidence remain `unassessed`; they are not silently converted to either pass or
model failure. Replay reports `pass`, `fail`, and `unassessed` counts for
terminal-contract validity and substantive correctness with a primary
denominator of four units per arm. It verifies all 20 slot dispositions,
request and response identities, protocol transitions, retained result bytes,
continuation identity, resource observations, and public summaries without a
model call or tool execution.

## Command lifecycle

Importing the package performs no preflight, filesystem mutation, model call,
or tool execution. `__main__.py` exposes three deliberately separate commands.
Run them from an environment where this repository is importable, using an
absolute artifact root outside Git.

`freeze` is the only plan-creation step. It checks the current resident runtime,
readiness, and memory floor, then exclusively creates the source-bound plan. It
makes zero model calls.

```bash
python3 -m experiments.payoff_action_calibration_v2 freeze \
  --plan /ABSOLUTE/PRIVATE_ROOT/native-tool-v2/plan.json \
  --study-id excluded-native-tool-v2-YYYYMMDD \
  --artifact-root /ABSOLUTE/PRIVATE_ROOT
```

`run` is a separate, explicit mutation and execution step. It reloads and
authenticates the frozen plan, acquires the cooperative resource lease, creates
a permanent single-use plan claim, creates a new output directory, and may
issue resident model requests and eligible local executions. It refuses an
existing output directory, a previously claimed study/plan identity, and any
attempt to resume a crashed run.

```bash
python3 -m experiments.payoff_action_calibration_v2 run \
  --plan /ABSOLUTE/PRIVATE_ROOT/native-tool-v2/plan.json \
  --output /ABSOLUTE/PRIVATE_ROOT/native-tool-v2/run-001
```

`validate` is read-only, offline replay. It reads the frozen plan and retained
bundle, recomputes the strict contracts and grades, prints a validation receipt,
and executes zero model and tool calls.

```bash
python3 -m experiments.payoff_action_calibration_v2 validate \
  --plan /ABSOLUTE/PRIVATE_ROOT/native-tool-v2/plan.json \
  --output /ABSOLUTE/PRIVATE_ROOT/native-tool-v2/run-001
```

Each command prints one JSON result. A completed `run` exits 0; a durably
recorded aborted run exits 1. `validate` exits 0 for any internally consistent
bundle, including a consistently recorded aborted bundle; that exit status is
replay validity, not scientific success. A contract, evidence, path, or I/O
error prints a JSON `status="invalid"` result and exits 2. The CLI does not
combine freeze and run, so creating a plan never implicitly authorizes a model
request.

## Fixture coverage

`test_contract.py` parameterizes the material boundaries from the accepted
development decision:

- timeout, cancellation, transport error, missing receipt, and a true no-call
  bypass, including unassessed downstream facets with raw diagnostic evidence;
- wrong containers/counts/shapes/names;
- malformed JSON, invalid UTF-8 call text, bounded size/depth, duplicate keys,
  non-finite values, wrong shape/range, valid but wrong arguments, and exact
  arguments;
- null, empty, whitespace, ordinary prose, exact 512/513-byte ASCII and
  multibyte boundaries, invalid type, and unencodable strings;
- separate intended reasoning, executor exception, invalid and boolean-aliased
  results, exact one-call behavior, detached arguments, and retained-result
  identity;
- forced-empty continuation despite retained raw prose; and
- final transport/tool-call errors, malformed/fenced/leaked content labels,
  correct finals, and contract-valid but substantively wrong finals.

The tests explicitly prove that classification does not execute the calculator,
ineligible turns do not invoke an executor, an eligible live path invokes it
exactly once, continuation construction does not invoke it again, and wrong
terminal content does not alter the earlier receipts.

The integration fixtures additionally cover the fresh design and source freeze,
strict v2 wire schema, request/channel/raw-stream tampering, partial and empty
transport failures, fixed slot accounting, ineligible native calls, execution
exceptions, cancellation between execution and final issuance, crash-output
refusal, public/private separation, complete and aborted replay, and proof that
replay performs zero model or tool calls.

The implementation is ready for review as code. Any future live freeze and run
remain separate operator actions. Even a valid live bundle would establish
honest replayable accounting for this excluded instrument, not perfect model
compliance, a correct strategy, a positive treatment effect, scientific
admission, or authorization for another study.
