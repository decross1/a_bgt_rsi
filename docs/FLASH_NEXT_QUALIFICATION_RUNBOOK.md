# Qwen3.8-Flash-Next C0 qualification runbook

This runbook covers the first, bounded GPU qualification of the exact C0
runtime. It does not authorize a broad A/B, an optimization arm, or production
adoption. The controller uses the existing canonical resource lease and
restores the current containers by their captured IDs; it never removes or
recreates a resident.

## Frozen inputs

- Controller commits: `29dbb0c41b61c675d7caca3cce2468a6ad7720b9`,
  followed by race hardening commit
  `e1595bfbb48cdac6c71ee21a00b09017483ce011`.
- Controller SHA-256:
  `a8ef83e79a1ba809dae7b3d80be680eb30504ac98c41352edf074cc9a0bd0bd4`.
- External contract:
  `/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/runtime/launch-contract.c0.json`.
- Contract SHA-256:
  `3757f596d03bd3d386ac30d21b7b2397fbe0c4910b8fab95a5d1b72cd58486f1`.
- Image ID:
  `sha256:345bea72ff3bb548594d88f6a7661636c07cd3e7367f8e54b0e4a98494e5a48d`.
- Model revision:
  `nvidia/Qwen3.8-Flash-Next-NVFP4@fc694b54fb0174e0913e6adf86691ef85a4ead47`.
- Model-manifest SHA-256:
  `54e961084a2fca63b0dcd32d542eb340a7baa20224298b00030ffa7e59145063`.
- Docker argument-vector SHA-256:
  `744d465e7e561cdf73e199e5994973918c2a5d9e3e46d5d891225701b3e826ec`.

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
BF16 KV, FP32 recurrent state, exact top-k, MTP0, prefix cache off, and async
scheduling off. It must contain no remote URL, host network, privileged mode,
arbitrary extra argument, or API key.

## One qualification invocation

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
3. verify all checkpoint SHA-256 values and the exact ARM64 image;
4. recheck the idle queues and capture both resident IDs and the Nara user
   service state;
5. create the stopped `vllm-qwen-ab-flash-20260915` container, which makes the
   existing watchdog stand down, before stopping Nara or either resident;
6. stop Nara only if it was active, then stop the two exact resident IDs;
7. start the challenger and require `/health`, the exact `/v1/models` identity,
   two fixed exact answers, and one fixed parsed tool call;
8. capture bounded candidate logs, stop and verify the candidate, start and
   health-check the exact resident IDs, restore Nara only after both residents
   are healthy, then remove the stopped watchdog sentinel.

The one-second monitor runs from before any service stop through restoration.
It cancels the request and stops the exact challenger ID on any
`MemAvailable < 30 GiB`, increase in host `pswpout`, candidate OOM, candidate
restart, disappearance, or unexpected stop. A stale lifecycle sample is ignored
after restoration disarms that same candidate ID.

## Result gate

The run is eligible for a broader local A/B only when `result.json` has all of:

- `schema == "qwen-flash-next-qualification-result/v1"`;
- `status == "passed"`;
- `restoration.status == "verified"`;
- the frozen contract, plan, and model-manifest hashes;
- `probe_count == 3`;
- `min_mem_available_gib >= 30` and `pswpout_delta_pages == 0`;
- `weekly_budget_debit == false`, `paid_api_calls == 0`, and
  `production_change_authorized == false`.

`challenger_gpu_seconds` and `all_gpu_research_seconds` are the same conservative
upper bound, measured from the candidate start attempt to its stop confirmation.
They exclude subsequent resident boot verification. The raw one-second samples,
model verification, readiness response, probe provenance, bounded candidate
log, durable state, result, and supervisor receipt stay inside that run's
isolated directory.

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
