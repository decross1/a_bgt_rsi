# Payoff-action native-tool contract v2 — offline core

This package is the smallest versioned seam needed to stop conflating a model's
tool-call shape, a local execution, the continuation scaffold, and the quality
of the final answer. It is development-only and offline.

It does **not** contain a model client, runner, CLI, scheduler, resource lease,
calibration plan, replay bundle, registration, or scientific-admission path.
It does not change or regrade any v1 file or result.

## Frozen decisions

- Contract ID: `payoff-action-native-tool-core/v2`.
- Visible pre-tool content is classified by strict UTF-8 byte length. `None`,
  empty, whitespace, and ordinary nonempty strings are eligible through 512
  bytes. Byte 513 is not eligible. No lexical rule labels prose benign.
- Raw pre-tool content remains evidence. The primary continuation always uses
  assistant `content=""`; policy ID is `empty-pretool-content/v2`.
- Valid intended `reasoning_content` is recorded separately and is not treated
  as visible reasoning leakage. Invalid type or encoding is an integrity
  failure.
- `strict_v1_comparable` is true only for an otherwise eligible turn whose
  visible content is `None` or `""`.
- Tool classification is pure. It parses and validates but never calls the
  calculator or another executor.
- `execute_once()` consumes the classifier's parsed arguments, invokes one
  supplied local executor once, canonicalizes the returned finite JSON once,
  and retains those exact bytes. The execution receipt is bound to the exact
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
5. After a future runner obtains a terminal model response, call
   `grade_final_turn(...)` with a pure task-specific grader returning
   `FinalContentAssessment`.

The result validator in this core validates schema and internal consistency. It
does not perform another live tool execution. A future replay validator may
independently recompute expected payoffs, but must label that as replay
verification rather than a second execution.

## Fixture coverage

`test_contract.py` parameterizes the material boundaries from the accepted
development decision:

- timeout, cancellation, transport error, missing receipt, and a true no-call
  bypass while retaining independent call facets;
- wrong containers/counts/shapes/names;
- malformed JSON, duplicate keys, non-finite values, wrong shape/range, valid
  but wrong arguments, and exact arguments;
- null, empty, whitespace, ordinary prose, exact 512/513-byte ASCII and
  multibyte boundaries, invalid type, and unencodable strings;
- separate intended reasoning, executor exception, invalid result, exact
  one-call behavior, detached arguments, and retained-result identity;
- forced-empty continuation despite retained raw prose; and
- final transport/tool-call errors, malformed/fenced/leaked content labels,
  correct finals, and contract-valid but substantively wrong finals.

The tests explicitly prove that classification does not execute the calculator,
ineligible turns do not invoke an executor, an eligible live path invokes it
exactly once, continuation construction does not invoke it again, and wrong
terminal content does not alter the earlier receipts.

## Work still required before any v2 shakedown

This core is not a complete runner. A separate patch must add new v2 plan, run,
private-evidence, and validation schemas; resource/cancellation gates; exact
final-slot issuance receipts; wire evidence; content/result/request digests;
fixed-denominator accounting; and replay that proves every designed slot has
one disposition. That integration must preserve the empty-content policy and
must never import v1 results as v2 evidence.

Only after those deterministic fixtures and replay checks pass may the project
freeze a fresh, permanently excluded v2 shakedown. Instrument validity will
still mean honest replayable accounting, not perfect model compliance, a
correct strategy, or a positive treatment effect.
