# Qwen3.8-Flash-Next C0 qualification runbook

This runbook covers bounded GPU qualification of the exact C0 runtime. The
owner has authorized local model A/B and optimization work; broader execution
uses the separately reviewed evaluation window and frozen benchmark plan.
Production adoption remains a separate decision. This controller uses the
existing canonical resource lease and
restores the current containers by their captured IDs; it never removes or
recreates a resident.

## Frozen inputs

- Controller commits: `29dbb0c41b61c675d7caca3cce2468a6ad7720b9`,
  followed by race hardening commit
  `e1595bfbb48cdac6c71ee21a00b09017483ce011`, and owned-cache remediation
  commit `8c2949c`, explicit-memory/sequential-restoration fix `83435cc`,
  localized recovery-catch cleanup `de59223`, and the phase-separated
  v2 monitor/validator in `71cc9af`.
- Controller SHA-256:
  `2e77867c0d3e4c63ed21f763482dd6c6a39c8ed3d162007bd9a8a26c9d51ae53`.
- External contract:
  `/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/runtime/launch-contract.c0.json`.
- Contract SHA-256:
  `b409dda5f58d720f2057ca97260bd01db36f4b9eece7a48feaba46ec3bf3f3e3`.
- Image ID:
  `sha256:345bea72ff3bb548594d88f6a7661636c07cd3e7367f8e54b0e4a98494e5a48d`.
- Model revision:
  `nvidia/Qwen3.8-Flash-Next-NVFP4@fc694b54fb0174e0913e6adf86691ef85a4ead47`.
- Model-manifest SHA-256:
  `54e961084a2fca63b0dcd32d542eb340a7baa20224298b00030ffa7e59145063`.
- Docker argument-vector SHA-256:
  `6a3afd70f65527b10e6ebd4d44fa1c9f81b2d3a2f0930ac81713ecfec6072630`.

The first invocation used contract SHA-256
`3757f596d03bd3d386ac30d21b7b2397fbe0c4910b8fab95a5d1b72cd58486f1`
and failed before mutation because `/mnt/vllm-cache` was not writable. Its
byte-identical contract is preserved read-only as
`launch-contract.c0.v1-3757f596d03bd3d3.json`. The current contract mounts a
dedicated cache below the pre-created, user-owned
`/home/decross1/projects/a_bgt_rsi_runtime_candidates/flash-next-20260914/compile-cache-c0`
parent. The controller refuses an absent, redirected, or differently owned
parent.

The model manifest covers all 25 top-level repository files. The controller
streams and verifies each file before its first runtime mutation. The 11
safetensor files total 132,680,249,378 bytes; the whole pinned repository totals
132,734,506,847 bytes. The model directory is mounted read-only.

## Side-effect-free review

Run the plan first from the Flash worktree. Choose a new output name even for a
plan; plan mode validates the location but does not create it.

```bash
cd /home/decross1/projects/a_bgt_rsi_worktrees/flash-next-ab-20260914
env -u MOCK_LLM .venv-chroma/bin/python \
  -m bench.flash_next_ab.qualification \
  --plan \
  --contract /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/runtime/launch-contract.c0.json \
  --output-dir /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/qualification-runs/qfn-c0-review
```

Verify the three hashes above and inspect the complete `docker_create_argv`.
The vector must use port 8012, `--restart=no`, the image ID rather than a tag,
a read-only model bind, 16,384 maximum context, one sequence, 1 GiB explicit KV,
BF16 KV, explicit `--gpu-memory-utilization 0.75`, FP32 recurrent state,
exact top-k, MTP0, prefix cache off, and async
scheduling off. It must contain no remote URL, host network, privileged mode,
arbitrary extra argument, or API key.

## One qualification invocation

Finish unrelated CPU test/build jobs first. The v2 controller records all swap
activity during checkpoint verification, then requires a fixed 60-second quiet
interval with at least 30 GiB MemAvailable. A new baseline is recorded immediately
before the first Docker mutation; even counter growth between quiet completion
and that baseline aborts. Setup churn remains visible and is not attributed to
Flash inference. No historical failed receipt is changed.

Use a fresh direct child of the fixed qualification-run root:

```bash
cd /home/decross1/projects/a_bgt_rsi_worktrees/flash-next-ab-20260914
env -u MOCK_LLM .venv-chroma/bin/python \
  -m bench.flash_next_ab.qualification \
  --run \
  --contract /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/runtime/launch-contract.c0.json \
  --output-dir /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/qualification-runs/qfn-c0-20260915t0100z
```

`--run` launches its worker in a separate process group. The preregistered
ceiling is 3,600 seconds including boot, probes, and restoration. At 3,000
seconds the supervisor sends `SIGTERM` so the worker enters `finally` and
restores. If the worker does not exit, the supervisor kills it at 3,300 seconds
and uses the remaining interval for an independent recovery from the durable
exact-ID state. Each Docker and systemd operation also has its own timeout.

The guarded sequence is:

1. acquire `.weekly-upgrade-execution.lock`, `.coordinator-cron.lock`, and
   `.weekly-upgrade-gpu.lock` in the canonical checkout;
2. require idle production queues and at least 30 GiB `MemAvailable`;
3. verify all checkpoint SHA-256 values and the exact ARM64 image, then prove
   60 seconds of zero swap-counter growth before establishing the mutation
   baseline;
4. recheck the idle queues and capture both resident IDs and the Nara user
   service state;
5. create the stopped `vllm-qwen-ab-flash-20260915` container, which makes the
   existing watchdog stand down, before stopping Nara or either resident;
6. stop Nara only if it was active, then stop the two exact resident IDs;
7. start the challenger and require `/health`, the exact `/v1/models` identity,
   two fixed exact answers, and one fixed parsed tool call;
8. capture bounded candidate logs, stop and verify the candidate, start and
   health-check Gemma first, then start and health-check Qwen, using their exact
   original IDs. Restore Nara only after both residents
   are healthy, then remove the stopped watchdog sentinel.

The one-second monitor runs from before any service stop through restoration.
It cancels the request and stops the exact challenger ID on any
`MemAvailable < 30 GiB`, increase in mutation-window `pswpout`, candidate OOM, candidate
restart, disappearance, or unexpected stop. A stale lifecycle sample is ignored
after restoration disarms that same candidate ID.

## Result gate

The shared validator checks exact source bindings, a contiguous setup-to-mutation
sample sequence, zero counter growth across the entire mutation window, and a
final sample after restoration. The run is eligible for a broader local A/B only
when `result.json` has all of:

- `schema == "qwen-flash-next-qualification-result/v2"`;
- `status == "passed"`;
- `restoration.status == "verified"`;
- the frozen contract, plan, and model-manifest hashes;
- `probe_count == 3`;
- `min_mem_available_gib >= 30`, raw-sample-confirmed 60-second setup
  quiescence, and `mutation_pswpout_delta_pages == 0`;
- `weekly_budget_debit == false`, `paid_api_calls == 0`, and
  `production_change_authorized == false`.

`challenger_gpu_seconds` and `all_gpu_research_seconds` are the same conservative
upper bound, measured from the candidate start attempt to its stop confirmation.
They exclude subsequent resident boot verification. `resident_downtime_seconds`
now measures from resident stop through full restoration completion. Older run
`qfn-c0-20260915-0107` undercounts this value and must not be used for downtime
comparison; its original receipt is retained. The raw one-second samples,
model verification, readiness response, probe provenance, bounded candidate
log, durable state, result, and supervisor receipt stay inside that run's
isolated directory. Exact original contract bytes are saved as
`launch-contract.raw.json`, alongside the normalized snapshot; raw and semantic
JSON hashes are intentionally distinct.

Local model R&D is uncapped by the 120-minute weekly maintenance ledger under
the owner's 2026-09-15 instruction. The controller does not import or construct
`BudgetLedger` and never touches `run_state/weekly_upgrade_budget.jsonl`. It
appends start, finish, and any supervisor-recovery rows to
`runtime/research-usage.jsonl`; every invocation remains subject to its finite
3,600-second ceiling. No paid API call is permitted.

## Unknown restoration

Treat a missing result, `status == "unknown"`, or
`restoration.status != "verified"` as an active recovery incident. Do not start
a resident while the candidate may still be running. The controller retains
the `vllm-qwen-ab...` sentinel on uncertainty so the watchdog cannot add another
GPU load. Inspect `state.json`, `supervisor-recovery.json`, `candidate.log`, and
the exact IDs. Confirm the challenger is absent or stopped before starting the
captured resident IDs. Start Nara only after both resident health endpoints
return successfully. Remove the sentinel last. An unverified recovery never
qualifies the model, even when a later manual restore succeeds.

The v2 state receipt records worker PID, Linux process start ticks, boot ID,
phase, update time and deadline. The UI verifies that process identity and a
fresh memory sample before describing an active research window. A stale state
file or a reachable candidate alone does not establish an authorized live window.
