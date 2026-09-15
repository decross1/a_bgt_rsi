# Qwen3.8-Flash-Next qualification runbook

This runbook covers bounded GPU qualification of the NVIDIA C0-S1 and Mia
C0-MIA-S1 runtimes. The
owner has authorized local model A/B and optimization work; broader execution
uses the separately reviewed evaluation window and frozen benchmark plan.
Production adoption remains a separate decision. This controller uses the
existing canonical resource lease and
restores the current containers by their captured IDs; it never removes or
recreates a resident.

## NVIDIA frozen inputs

- Controller commit: `6349b27` (includes the probe recorder repair).
- Controller SHA-256:
  `5ddf210f8f55e2b6948c1de49cd84d0f6d08c725e717103b9dff6f57a7f59dce`.
- External contract:
  `/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/runtime/launch-contract.c0.json`.
- Contract SHA-256:
  `e63c046aed5f765361803cf080d85ed98b378002c72aaa9994c0572dd2505d2b`.
- Image ID:
  `sha256:345bea72ff3bb548594d88f6a7661636c07cd3e7367f8e54b0e4a98494e5a48d`.
- Model revision:
  `nvidia/Qwen3.8-Flash-Next-NVFP4@fc694b54fb0174e0913e6adf86691ef85a4ead47`.
- Model-manifest SHA-256:
  `54e961084a2fca63b0dcd32d542eb340a7baa20224298b00030ffa7e59145063`.
- Docker argument-vector SHA-256:
  `6706701d2559144ccde83adfbbfa917365b4392067dc8f0d859cc2439ed93605`.

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

The preceding 32K C0 run, `qfn-c0-20260915-0407`, failed after four of eleven
checkpoint shards: candidate swap reached 715,464,704 bytes and startup host
paging exceeded its limits. Its minimum available memory was 31.1813 GiB;
the 20 GiB floor was not breached. Both original services and Nara were
restored and verified. The original contract is archived read-only as
`launch-contract.c0.v7-792be64624d1863b.json`. C0-S0 subsequently loaded four shards with zero candidate swap/OOM but
aborted at a host paging burst of 140,914,688 bytes in five seconds. Its minimum
host reserve was 31.1554 GiB; restoration was verified at 04:59:23 UTC. That
result remains failed and does not demonstrate a hardware-fit failure.

C0-S1 is a new exploratory startup guard: 512 MiB/5s, 2 GiB/60s and 4 GiB total.
These limits were registered before a new attempt, after review of the S0
failure. Candidate swap/OOM, host reserve, ready quiet and serving gates stay
unchanged. Continuous page-in and host PSI counters plus separate dashboard
responsiveness observations support interpretation of a future paging burst.

The first S1 attempt, `qfn-c0-s1-20260915-0511`, completed checkpoint loading,
health/model identity checks, and its 60-second ready quiet interval. All three
probe validators returned, but serializing their nested raw response bytes
raised `TypeError: Object of type bytes is not JSON serializable`. Consequently
no durable `probes.json` exists and the attempt remains **failed and ineligible
for benchmark admission**. Do not reconstruct or retroactively approve its
missing responses. Repair the recorder and repeat the fixed probes in a new
qualification run.

That attempt measured a minimum 31.4798 GiB MemAvailable, zero candidate swap
or OOM, no paging-limit breach, and 638,627,840 bytes of startup host pageout.
The original residents and Nara were restored at 05:33:37 UTC on September 15.
Independent API-health/frontend HTTP observations all returned 200 (280 probes;
maximum 45.5 ms). Those probes measure these two endpoints, not every Spark
operation or the correctness of dashboard contents. The immutable analysis is
`runtime/c0-s1-recorder-failure-analysis.json` in the research artifact directory.

The owner's current authority permits a separately registered 12 GiB absolute
reserve if needed; 20 GiB remains preferred and is still this S1 profile's
mandatory floor. Local R&D has no weekly GPU-hour cap and is accounted separately
from the 120-minute weekly maintenance allowance.

## Mia single-Spark candidate

The independently pinned Mia lane uses the same three fixed correctness/tool
probes, 32,768 context, 2 GiB KV allocation, FP32 recurrent state, MTP0,
20 GiB host floor, and zero candidate swap/OOM policy. Its v4 evidence binds
the actual image, checkpoint, packed PLE table, and immutable CandidateSpec;
the shared endpoint port alone never identifies a variant.

- Recipe: `MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark`
  at `d03809008834124e80223c3482f2ddb59577a48f`.
- Checkpoint: `Mia-AiLab/Qwen3.8-Flash-Next-NVFP4`
  at `925d7be6c14c6c9442ef83e8f05b5a3c39304f69`.
- Served name: `qwen3.8-flash-next-mia`; evaluation route: `flash_next_mia`.
- Image: `sha256:da68dd27a8ef1dadd0f380178a51f0a0671dc4235933ea1ae89fdaf66295ec72`.
- Fixed contract: the research root's `runtime/launch-contract.mia-c0.json`,
  SHA-256 `ba5153b2047213aa93fb24b048da38cc2c90cc6576d9450a2088bd11afa01964`.
- Spec SHA-256: `dde4fe1f72cf91de92089a95748cee1f6a8204e351d517aa0ae46d8d27122857`.
- Docker argv SHA-256: `648baa0e0adfe7c2e98afa2013ab379bc797a3df495e3735ba991e88168bd051`.

Use the same `--plan`/`--run` CLI below with that fixed Mia contract and a fresh
`qfn-mia-c0-*` output directory. The shared controller selects the registered
Mia path without changing NVIDIA globals. Prepare the user-owned
`compile-cache-mia-c0` parent under the existing runtime-candidates directory
before launching; the controller creates its specific child cache.

Mia is an evaluation candidate, not a production change. A complete A/B plan
must explicitly select `flash_endpoint_name="flash_next_mia"` and bind Mia's
own successful qualification and runtime hashes. All seven Flash roles use
that one checkpoint/runtime. NVIDIA plans retain their original route.

The first actual Mia load, `qfn-mia-c0-20260915-0602`, **passed** on September 15.
Its result SHA-256 is
`01e5d094b27f0aea9c0464762ef36c0a99b46f18af0e2050369dfe1aab978fbc`;
the qualified runtime SHA-256 is
`439459a83ac0a961a969b1fc1108057c0e0f3a90c5facc8012238e6a5d13d12c`.
All three exact probes and the fresh 60-second quiet interval passed, with
durable response evidence. Minimum host MemAvailable was 36.3107 GiB;
candidate swap/OOM and paging-limit violations were zero. Host startup pageout
was 777,052,160 bytes, within the declared startup limits. The packed 26.82 GiB
PLE mmap was confirmed in the runtime log. Exact original residents and Nara
were restored at 06:24:14 UTC, and the supervisor exited zero without recovery.
The strict shared admission validator passed after supervisor closure.

This admits a bounded benchmark window, not production promotion or a claim
of scientific/coding superiority. The preceding `qfn-mia-c0-20260915-0600`
attempt failed before mutation because the coordinator held its resource lock;
it is not a model-fit failure. Both immutable attempts remain recorded.

## Probe evidence and startup timing

Each attempted probe now has a durable `probe-attempts.json` record. Bounded
raw SSE responses are saved separately under `private-probes/` with restrictive
permissions; JSON records contain their hashes and relative paths. A wrong
response or transport failure remains a failed qualification and retains its
diagnostic output. This fixes the S1 recorder failure without weakening any
correctness check or changing its historical failed result.

Keep container-start-to-readiness, checkpoint-loading time, the full experiment
window, TTFT, and decode/task performance separate. The first NVIDIA S1 run
measured 639.26 seconds from container start to readiness, including 533 seconds
reported by the shard loader; its full verification/restoration invocation was
1,390.97 seconds. Those are startup observations, not steady-state throughput.

The passed Mia run measured 610.46 seconds to server readiness: its runtime
reported 486.02 seconds loading the model and 72.19 seconds initializing the
engine (including 22.53 seconds compiling). The ready quiet interval added
60.79 seconds, the three-probe phase took 5.25 seconds, and original-service
restoration took 402.46 seconds. The whole invocation took 1,322.98 seconds.
These are distinct, sometimes nested spans, not an exhaustive additive timing
decomposition or an isolated NVMe benchmark. One cold run does not establish a
repeatable startup advantage over NVIDIA. Independent API-health/frontend
HTTP checks returned 200 in all 266 probes (maximum 26.6 ms); their scope does
not include every Spark operation. Source hashes and probe timings are in
the private research artifact `runtime/mia-c0-startup-breakdown.json`.

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
The vector must use port 8012, `--restart=no`, `--memory 103079215104`,
`--memory-swap 103079215104`, the image ID rather than a tag,
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
  --output-dir /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/qualification-runs/qfn-c0-s1-20260915t0515z
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
   existing watchdog stand down; verify its exact Docker memory and combined
   memory/swap limits before stopping Nara or either resident;
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
The live cgroup must report `memory.max=103079215104` and `memory.swap.max=0`
at binding and throughout the armed interval. This container-only setting
does not change host VM settings. The 20 GiB host reserve remains independent
of the container limit, because cgroup accounting is not a complete Spark
physical-memory ledger.

Host paging limits are cumulative across **load and ready together**: 512 MiB
in 5 seconds, 2 GiB in 60 seconds, or 4 GiB total. During serving/probes the
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

- the registered NVIDIA v3 or Mia v4 result/plan/contract bundle;
- `status == "passed"`, `failure_stage == null`, `failure_class == null`, and no errors;
- `restoration.status == "verified"`;
- the registered contract, plan, and model-manifest hashes;
- three successful fixed probes with exact provenance;
- `min_mem_available_gib >= 20`, raw-sample-confirmed setup and ready quiet
  intervals, continuous startup/serving limits, and zero candidate swap/OOM;
- `weekly_budget_debit == false`, `paid_api_calls == 0`, and
  `production_change_authorized == false`.

C0-S1 additionally binds the raw memory-log hash and `cgroup-diagnostics.json`.
Admission reconstructs its attributed phase snapshots, peak charged memory,
all five host phases, and raw page-in/PSI totals and deltas. PSI magnitude is
diagnostic; missing, malformed or decreasing counters cannot support a pass.
Each sample records cgroup current/anon/file/reclaim/pressure and host memory
diagnostics, so another failure can distinguish more possible causes.

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
