# Flash-Next model selection — 15 September 2026

Status: evaluation in progress. The first complete pair supports keeping the resident setup while testing explicit Flash thinking controls and MTP. It does not yet support replacing every local role.

The owner authorized this overnight model R&D separately from the weekly maintenance allowance, with 20 GiB preferred available memory and a separately declared 12 GiB floor if needed. The initial completed comparison maintained the 20 GiB floor. Production promotion is separate from a benchmark result.

## Complete initial comparison

Both arms completed all 126 declared task cells under their supervised windows and passed completed-evidence/restoration admission. Counts below include malformed responses, timeouts and unsuccessful repairs. These are development fixtures, not hidden benchmark confirmation; the contrast mixes the resident role bundle with the Flash bundle.

| Family | Gemma + Qwen passed | Flash C0 passed | Resident task wall | Flash task wall |
|---|---:|---:|---:|---:|
| context | 4/4 | 4/4 | 13.9 s | 155.7 s |
| diversity | 2/10 | 2/10 | 20.9 s | 682.1 s |
| historical | 0/6 | 0/6 | 44.0 s | 870.1 s |
| objective | 2/24 | 12/24 | 174.0 s | 458.8 s |
| portfolio | 5/16 | 12/16 | 38.5 s | 1059.9 s |
| role_effort | 17/18 | 11/18 | 228.8 s | 451.3 s |
| topic | 47/48 | 13/48 | 110.2 s | 1280.1 s |

Whole-harness elapsed time was **630.23 seconds resident** and **4,958.02 seconds Flash**. Startup and service restoration are additional. Per-family task walls include failed calls and grading; raw tokens/second cannot replace these completion measures.

Flash passed all 12 science/evidence portfolio cases; its four portfolio coding attempts timed out. All six historical repair attempts also timed out. Default Flash topic generation often timed out. Those failures count against the tested configuration, but do not isolate model-weight capability from reasoning policy.

The exact Mia tokenizer template defaults omitted thinking controls to thinking enabled and omitted reasoning effort to `xhigh`. The first panel preserved this native behavior where the shared profile omitted those fields. The next diagnostic fixes the model/runtime and explicitly tests off, low, medium, xhigh and an escalation policy. It will be a new experiment, not a retrospective score repair.

The initial resident historical patches all lacked a final line feed. An isolated copy-only diagnostic appended one LF and reused the unchanged parser and real sandbox: one of six then passed. Two still failed parsing, two failed sandbox checks, and one did not apply. Flash had no completed patch to transform in six cases. The original historical score remains 0/6 for each arm.

## Next measured configuration choices

1. Explicit thinking and fresh game-theory/application-validity tasks, with fixed budgets, private response evidence and request timing.
2. Full-vocabulary native MTP3 against a fresh MTP0 parity/timing panel.
3. A separate reduced-draft-vocabulary, V2-runner/FULL-decode bundle built on the exact Mia image; any gain belongs to that runtime bundle until isolated further.
4. Input-plus-output-safe long-context checks; 64K is a capability lane rather than the normal working default.
5. Actual repair/topic tasks under the selected explicit policy before claiming all-local-primary suitability.

The pinned [Mia one-Spark recipe](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark/tree/d03809008834124e80223c3482f2ddb59577a48f) is the upstream implementation reference. Its measurements are hypotheses for local replication, not local results. DFlash remains a separate compatibility question because its exact checkpoint and serving integration must match this single-Spark, disk-backed setup.

## Evidence

Full private requests remain in the local artifact store. The dashboard reads content-free aggregates only after recorded completed-pair admission; it recounts raw outcome denominators and recomputes paired source-task statistics. It distinguishes historical admission from current-source replay availability.

- [Initial pair aggregate](/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/evaluation/aggregate-summaries/qfn-ab-mia-c0-20260915-a.json)
- [Recorded admission](/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/evaluation/pair-proofs/qfn-ab-mia-c0-20260915-a.json)
- [Separate LF diagnostic](/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/evaluation/diagnostics/historical-terminal-lf-20260915-a/receipt.json)
- [Overnight execution status](/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/overnight-research/STATUS.md)
