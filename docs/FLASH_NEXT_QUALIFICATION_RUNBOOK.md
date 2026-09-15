# Qwen3.8-Flash-Next C0 qualification runbook

This runbook covers bounded GPU qualification of the exact C0 runtime. The
owner has authorized local model A/B and optimization work; broader execution
uses the separately reviewed evaluation window and frozen benchmark plan.
Production adoption remains a separate decision. This controller uses the
existing canonical resource lease and
restores the current containers by their captured IDs; it never removes or
recreates a resident.

## Frozen inputs

- Controller commit: `75fead002b624cfa222aa24fb7b9f5954f559a6c`.
- Controller SHA-256:
  `611362f8a98f3e22cd2a731e23edeffe7e133f46153ee45f2e70028fc6bba328`.
- External contract:
  `/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/runtime/launch-contract.c0.json`.
- Contract SHA-256:
  `792be64624d1863bc6088755b5fdc839503bdd134baa6b3f03124009b9292a1f`.
- Image ID:
  `sha256:345bea72ff3bb548594d88f6a7661636c07cd3e7367f8e54b0e4a98494e5a48d`.
- Model revision:
  `nvidia/Qwen3.8-Flash-Next-NVFP4@fc694b54fb0174e0913e6adf86691ef85a4ead47`.
- Model-manifest SHA-256:
  `54e961084a2fca63b0dcd32d542eb340a7baa20224298b00030ffa7e59145063`.
- Docker argument-vector SHA-256:
  `090b2ef066487b7b513064050e5e1ba58240d3dc33d71a8f993ed188b515f655`.

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
a read-only model bind, 32,768 maximum context, one sequence, 2 GiB explicit KV,
KV dtype `auto` (record the resolved runtime dtype when observable), explicit
`--gpu-memory-utilization 0.75`, FP32 recurrent state,
exact QSA top-k environment settings (`VLLM_QSA_EXACT_TOPK=1`,
`VLLM_QSA_DET_TOPK=0`), MTP0, prefix cache off, and async
scheduling off. It must contain no remote URL, host network, privileged mode,
arbitrary extra argument, or API key.

## One qualification invocation

Finish unrelated CPU test/build jobs first. The v3 controller records all swap
activity during checkpoint verification, then requires a fixed 60-second quiet
interval with at least 20 GiB MemAvailable. A new baseline is recorded immediately
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
  --output-dir /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/qualification-runs/qfn-c0-20260915t0410z
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
2. require idle production queues and at least 20 GiB `MemAvailable`;
3. verify all checkpoint SHA-256 values and the exact ARM64 image, then prove
   60 seconds of zero swap-counter growth before establishing the mutation
   baseline;
4. recheck the idle queues and capture both resident IDs and the Nara user
   service state;
5. create the stopped `vllm-qwen-ab-flash-20260915` container, which makes the
   existing watchdog stand down, before stopping Nara or either resident;
6. stop Nara only if it was active, then stop the two exact resident IDs;
7. start the challenger and require `/health`, the exact `/v1/models` identity,
   a fresh 60-second interval without host swap growth, then two fixed exact
   answers and one fixed parsed tool call;
8. capture bounded candidate logs, stop and verify the candidate, start and
   health-check Gemma first, then start and health-check Qwen, using their exact
   original IDs. Restore Nara only after both residents
   are healthy, then remove the stopped watchdog sentinel.

The one-second monitor runs from before any service stop through restoration.
It stops the exact challenger on `MemAvailable < 20 GiB`, any candidate-cgroup
swap or local OOM event, unexpected restart/stop, identity mismatch, stale
sampling, or a paging-rate breach. Candidate attribution binds container ID,
PID, process start ticks, and cgroup v2 membership before and after each read.

Host paging limits are cumulative across **load and ready together**: 128 MiB
in 5 seconds, 256 MiB in 60 seconds, or 512 MiB total. During serving/probes the
limits are 32 MiB in 5 seconds, 64 MiB in 60 seconds, or 128 MiB total. Reaching a
limit aborts. Startup phase changes cannot reset these limits. Setup and the
final ready interval each require 60 seconds of zero host swap growth.
Restoration host paging is recorded diagnostically; it does not interrupt
recovery. The memory floor and exact resident identity/health checks still apply.

## Result gate

The shared validator reconstructs registered source bindings, raw contract and
plan hashes, contiguous phase/gate counters and rolling windows, candidate
cgroup identity, quiet intervals, and the final restoration sample. A broader
local A/B requires:

- `schema == "qwen-flash-next-qualification-result/v3"`;
- `status == "passed"`, `failure_stage == null`, and no errors;
- `restoration.status == "verified"`;
- the registered contract, plan, and model-manifest hashes;
- three successful fixed probes with exact provenance;
- `min_mem_available_gib >= 20`, raw-sample-confirmed setup and ready quiet
  intervals, continuous startup/serving limits, and zero candidate swap/OOM;
- `weekly_budget_debit == false`, `paid_api_calls == 0`, and
  `production_change_authorized == false`.

A claimed pass without its complete raw evidence cannot admit an evaluation.
Older v1/v2 receipts remain historical evidence under their original rules;
they cannot qualify the current v3 runtime. The research usage finish record
must be durable before a result is published.

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

The v3 state receipt records worker PID, Linux process start ticks, boot ID,
phase, update time and deadline. The UI verifies that process identity and a
fresh memory sample before describing an active research window. A stale state
file or a reachable candidate alone does not establish an authorized live window.
