# Permanent local Flash resident

The owner selected this deployment on 2026-09-19 and requested no further
benchmarks. This selection uses the already measured SGLang v5 bundle; it is
not a new claim of universal benchmark superiority. Prior comparisons remain
in [the results report](FLASH_PERSONAL_RESULTS_20260918.md).

| Setting | Selected value |
|---|---|
| OpenAI-compatible URL | `http://127.0.0.1:30080/v1` |
| Exact request model | `nvidia/Qwen3.8-Flash-Next-NVFP4` |
| Checkpoint revision | `fc694b54fb0174e0913e6adf86691ef85a4ead47` |
| Runtime | SGLang image `sha256:2ee545cf877ae8497c123637e061b6e6313c624e30018f975969b1d554e27f56` |
| Capacity | 32,768 total tokens; one running request |
| Precision | NVFP4 weights, FP32 recurrent state, BF16 KV |
| Speculation | Native NEXTN, 3 steps / 4 draft tokens |
| PLE | File-backed on NVMe, 4 GiB resident cache |
| Allocator | `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` |
| Resource limits | 112 GiB container, zero container swap, 20 GiB host reserve |

The service deliberately depends on the reviewed, hash-verified local bundle
at `a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/sglang-fallback-prep`
and its frozen helper checkout. Preserve those directories, the checkpoint and
Docker image. This is a host-specific deployment, not a portable installer.

`systemctl --user status flash-resident.service` shows lifecycle status.
`journalctl --user -u flash-resident.service` shows startup/errors.
`.venv-chroma/bin/python -m orchestrator.flash_resident check-ready` performs
read-only admission: supervisor boot/PID/heartbeat, exact served model, and
available host memory. The Now dashboard labels Flash as the resident and the
old pair as rollback options. An offline selected model stays visibly offline.

The supervisor takes the shared lab locks only while changing services, then
releases them for research. It stops Nara during the transition and resumes it
after readiness. Both Nara and cron check actual Flash readiness on every pass.
The old pair's Docker restart policies are disabled during cutover, and the
watchdog/launcher respect the new selection. Normal service stop does not
restore the pair. A deliberate rollback requires stopping Flash first, removing
the Flash deployment selection and restoring the old client routes, then
starting the retained containers. The watchdog also refuses pair startup while
any owned SGLang Flash container remains running.

Normal shutdown stops Nara, reacquires the transition locks and drains requests.
An explicit stop has a bounded drain; if callers never release the endpoint,
the owned engine is cancelled and that condition is recorded. Memory and driver
faults keep immediate-stop priority. A systemd stop-post hook also cleans up the
exact owned container if the supervisor crashes, preventing an unmonitored
Docker process from surviving a killed service.

The weekly Sunday 05:30 UTC frontier hook remains review-only. No new model
panels or automatic production switches are scheduled by this deployment.

## Other local consumers

The 2026-09-19 connection sweep migrated active clients, preserving archived
benchmarks and old experiment definitions with their original model identities.

| Consumer | Connection change |
|---|---|
| Lab wrapper and direct workers | Generator/critic role routes resolve to `sglang-flash`; actual model/runtime are logged |
| Brain (`agent_system`) | Live immutable release uses `127.0.0.1:30080/v1`, exact NVIDIA model, thinking off for short calls |
| Sous web and Telegram (`food-app`) | Defaults and private environment use the same endpoint/model and explicit thinking off; services restarted |
| NemoClaw / OpenShell | Stored provider `vllm-local` now selects NVIDIA Flash; stopped sandbox needs host bridge connectivity before recovery |

The model port remains loopback-only. Changing the sandbox's stored URL does
not make that listener accessible from its Docker bridge. The separate
maintenance todo requires a private relay or supported network arrangement and
reconciliation of the old container's immutable environment before it is
restarted. No legacy sandbox was revived. Detailed local evidence is in
`flash-personal-recovery/cross-project-flash-migration-20260919.md`.

## Owner follow-up: scoped reboot

The owner will choose a reboot window. Do not reboot automatically. A pending
maintenance task appears in the human todo queue. Before reboot, account for
interactive Codex/Claude/SSH sessions and session-only services using the
service audit under `flash-personal-recovery/service-recovery-audit-20260919`.
After reboot, verify Docker/NVIDIA device readiness, the unchanged selected
image/checkpoint, Flash endpoint identity, Nara, UI, Brain and remote access.
Do not resume benchmarking. Normal `/v1/models` and health checks suffice.

A driver/allocation or resource fault stops Flash and latches its failure for
the current boot, preventing a restart storm. A new boot admits one fresh
startup. Startup failures and the need for a reboot are reported separately
from model capability. Neither a successful cold start nor a model selection
guarantees a later cold start on the same fragmented host.
