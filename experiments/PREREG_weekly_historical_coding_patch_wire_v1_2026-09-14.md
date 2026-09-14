# Preregistration — public-historical raw-patch wire follow-up v1

**Frozen:** 2026-09-14, before this follow-up's model calls
**Manifest:** `experiments/weekly_historical_coding_patch_wire_v1_2026-09-14.json`
**Evidence class:** `public_historical`; `contamination_resistant=false`

## Trigger and question

The registered JSON-wire baseline returned all six completions but produced no
valid patch. Five completions failed the strict JSON boundary, including four
markdown-fenced responses; the sixth reached patch parsing with a malformed
diff header. That result is an output-contract failure and is not evidence that
the model could not reason about the repairs.

This follow-up asks whether removing the JSON envelope and requiring the
completion itself to be one raw unified diff lets the same resident model and
policy reach patch application and the unchanged graders.

## Frozen treatment and controls

The only intended treatment is the model-visible response contract:

- baseline: strict JSON object with exactly `path` and `patch`;
- follow-up: raw unified diff bytes, with no JSON, markdown fence, commentary,
  prefix, suffix, stripping, extraction, repair, or other salvage.

The follow-up arm is `gemma_patch_native`. It retains the resident
`gemma-4-26b-a4b` model, `vllm-gemma` backend, `coding_precise` profile,
temperature 0.2, top-p 0.9, null reasoning effort, seed 20260914, fixed task
order, and one serial call per task.

The six task objects, base commits and files, defect contracts, source proof,
workspace allowlists, hidden-from-request graders, sandbox identity, output
caps, time caps, and failure-inclusive denominator are byte-for-byte identical
to the v2 JSON-wire manifest. Only the arm declaration, model-visible messages,
suite metadata, and their derived hashes differ.

## Acceptance and outcomes

Every one of HCP-001, HCP-002, HCP-005, HCP-006, HCP-007, and HCP-008 remains
in the denominator. A completion passes the response boundary only if its first
line is exactly the registered one-file `diff --git a/PATH b/PATH` header. The
entire completion must obey the one-file unified-diff grammar, with exact hunk
counts, one header per line, LF line endings and a final LF; no prefix/suffix
is ignored. Those bytes are then handed unchanged to the patch validator.
The validator still requires one allowed file, exact `--- a/PATH` and
`+++ b/PATH` headers, an applicable bounded text patch, and no extra operation.

Report separately:

1. transport returns / 6;
2. response-contract-valid raw diffs / 6;
3. patch-validator-valid patches / 6;
4. grader-passing repairs / 6;
5. each transport, response, patch, sandbox, and grader failure code;
6. failure-inclusive elapsed time and Correct Task Throughput.

No failed or unrun task may leave the denominator. The trusted receipt must
reconstruct the exact prompt, completion hash, raw patch parse, application,
grader receipt, runtime identity, and summary.

## Interpretation rules

- More than zero valid patches is evidence that the raw-patch scaffold reaches
  farther through this interface than the observed JSON-wire run. With one
  six-task run, it is diagnostic evidence rather than a stable causal estimate.
- Valid patches that fail graders separate serialization/application from
  substantive repair correctness.
- A grader-passing repair demonstrates success on that public historical task
  under this exact scaffold. It does not establish general coding capability.
- Zero valid patches provides no support for this raw-patch treatment and must
  retain the exact failure categories.
- This run cannot establish a model, runtime, quantization, inference-policy,
  contamination-resistant, or production advantage.

## Resources and authority

- six serial resident Gemma calls;
- 4,096 maximum output tokens and 145 seconds per model request;
- 15 seconds per grader and 90 seconds cumulative grading;
- 1,020 seconds runner ceiling inside a 1,050-second controller reservation;
- no tools exposed to the model, dependency install, service action, runtime
  cutover, production write, or promotion authority.

The weekly controller owns live execution. This preregistration and any
completed receipt record measurement only.
