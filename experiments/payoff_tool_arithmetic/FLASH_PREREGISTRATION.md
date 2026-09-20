# Permanent-Flash payoff/tool arithmetic diagnostic

**Protocol:** `flash-payoff-diagnostic-plan/v1`
**Claim boundary:** arithmetic and native tool-interface behavior only
**Production authority:** none

This is a versioned follow-on to the frozen Gemma payoff/tool study. It does
not reopen or modify that study. It reuses its six paired inputs, prompts,
`shared_return` tool, arm order, and objective graders so the warm permanent
Flash service can be diagnosed on the same interface.

The historical motivation is iteration `iter-2026-09-15-007` in campaign
`v2-utility-mechanism-followon-20260915`. That context is bound into the plan
as motivation only. It is not claim-binding evidence, and this diagnostic is a
preparatory interface check rather than a new scientific rung or focus stage.

The diagnostic has six input pairs and twelve conditions: one direct answer
and one native-tool condition per pair. A direct condition issues one call. A
tool condition issues a tool-selection call and issues a final call only after
the first call supplies one valid, exact `shared_return` invocation. The
maximum denominator is therefore eighteen call slots. A rejected first tool
call leaves its final slot explicitly `skipped_unissued`; cancellation,
deadline, readiness loss, identity drift, or a memory-floor breach leaves all
remaining slots explicitly `unissued_after_abort`.

An attempted call is not automatically a confirmed dispatch. A completed SSE
response is `confirmed_dispatched`; a failed transport with nonempty SSE bytes
is also confirmed dispatched; a recognized transport timeout/error with an
empty attached stream is `wire_unknown`; and an unclassified/local exception
without transport evidence is `prewire_failure`. A pre-wire failure aborts the
run. A run with zero returned model responses is aborted and cannot validate.

The exact generation policy is:

```json
{"enable_thinking":false,"temperature":0,"top_k":64,"top_p":1}
```

Every issued call has `max_tokens=256` and `timeout_s=90`. The entire evaluator
has a 900-second wall-clock budget. Calls are serial. Before each call the
controller checks cancellation, the remaining budget, the permanent Flash
readiness contract, the exact preregistered live identity, and a 20 GiB
`MemAvailable` floor.

Preparation and execution must run in the host PID/network namespace. A Codex
sandbox may see the host state and heartbeat while hiding the recorded host
supervisor PID; that observation is unknown readiness, not evidence that the
resident stopped. Validation is offline and does not require the live service.

Preparation freezes the evaluator sources; fixture payloads and order; model,
checkpoint and checkpoint-artifact identity; runtime image; serving profile;
deployment document; live supervisor/container identity; policy; and limits.
Execution acquires the existing cooperative `resource_lease` once (weekly
execution, coordinator, and GPU locks) and fails immediately if any lock is
busy. The permanent Flash supervisor releases those locks after readiness and
retains its separate lifetime lock, so the diagnostic does not deadlock the
server. It does not mutate a pause file, restart a service, or touch Docker.
Pi or another direct HTTP client can bypass these cooperative locks. The runner
therefore requires an observed-zero SGLang running/queue gauge before its first
call and records that probe, but makes no isolated-latency claim and cannot
exclude contention that begins later.

All calls use the registered local endpoint
`flash_next_sglang` (`127.0.0.1:30080`) and the registered NVIDIA checkpoint
artifact digest. Public output contains call receipts, hashes, grades, and the
complete declared denominator. Exact prompts, tool payloads, final text,
reasoning channels, and raw SSE stay in mode-0700 private artifacts. Validation
reconstructs each request, independently replays every returned SSE stream,
and recomputes the frozen objective grades.

The plan and run must live below the plan-bound mode-0700 artifact root outside
every Git checkout. No private transcript or raw stream is written into the
source repository. The CLI default is
`/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-20/flash-payoff-diagnostic`.

The validation receipt reports `correct/6` for direct answers, `exact/6` for
native tool invocations, and `correct/6` for tool-final answers. It also lists
every missing cell, ragged tool condition, failed cell, and failure-code count.
Those fields are derived from the independently replayed private evidence; the
validator does not trust or copy the stored run grades.

This run is part of the owner's explicitly authorized current local research
session. It does not debit the normal weekly two-hour maintenance budget. A
result can diagnose arithmetic or native tool behavior. It cannot establish
an L2 research finding, validate a trading strategy, authorize a production
change, or support a model-upgrade claim by itself.
