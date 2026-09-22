# Permanent local Flash resident

The owner selected this deployment on 2026-09-19 and requested no further
benchmarks. This selection uses the already measured SGLang model/runtime bundle; it is
not a new claim of universal benchmark superiority. Prior comparisons remain
in [the results report](FLASH_PERSONAL_RESULTS_20260918.md).

| Setting | Selected value |
|---|---|
| OpenAI-compatible URL | `http://127.0.0.1:30080/v1` |
| Exact request model | `nvidia/Qwen3.8-Flash-Next-NVFP4` |
| Checkpoint revision | `fc694b54fb0174e0913e6adf86691ef85a4ead47` |
| Runtime | SGLang image `sha256:2ee545cf877ae8497c123637e061b6e6313c624e30018f975969b1d554e27f56` |
| Capacity | 262,144 total tokens (since 2026-09-22; was 32,768); one running request |
| Precision | NVFP4 weights, FP32 recurrent state, BF16 KV |
| Speculation | Native NEXTN, 3 steps / 4 draft tokens |
| PLE | File-backed on NVMe, 4 GiB resident cache |
| Allocator | `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` |
| Resource limits | 112 GiB container cgroup (CPU-side charges only), zero container swap, 10 GiB host reserve (8 GiB guard backstop) |

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

## Boot and recovery

The owner completed the scoped reboot on 2026-09-19. Do not reboot automatically
for future faults. Interactive Codex/Claude/Pi/SSH sessions still require an
explicit reconnect/resume; enabled application services are checked separately.

That boot exposed an ordering dependency: NVIDIA CDI refresh waited for
`multi-user.target`, while Plymouth's boot-screen wait held that target. Flash
exited before attempting any model load because `/var/run/cdi/nvidia.yaml`
never appeared during its five-minute readiness wait. Docker and the NVIDIA
driver were otherwise healthy. This is distinct from the earlier driver
allocation failure and swap-limit incident.

The installed [NVIDIA CDI service](../systemd/nvidia-cdi-refresh.service) now
orders device-spec generation after module loading and NVIDIA persistence,
and before Docker, without waiting for the desktop target. The vendor
conditions, module check, generator, environment and capability set are retained.
Use the full unit when applying this repair: dependency ordering cannot be
removed by an empty `After=` assignment in a drop-in. The administrator repair
backs up the prior unit and checks its expected hash before replacement.

After a restart, verify Docker/NVIDIA readiness, the nonempty CDI spec and
Docker GPU device resolution, then the unchanged Flash image/checkpoint,
actual endpoint identity and reserve. Confirm Nara, UI, Brain, Sous and remote
access separately. A running application process alone does not prove its
model connection works. Do not resume benchmarking; use operational readiness
and one short real response as appropriate.

Repair receipts and the guarded first post-repair launch are under
`flash-personal-recovery/post-reboot-20260919/`. Historical pre-reboot service
checks targeted the old model pair; do not use that pair-specific checker as
current Flash admission. The supported check remains
`.venv-chroma/bin/python -m orchestrator.flash_resident check-ready`.

A driver/allocation or resource fault stops Flash and latches its failure for
the current boot, preventing a restart storm. A new boot admits one fresh
startup. Startup failures and the need for a reboot are reported separately
from model capability. Neither a successful cold start nor a model selection
guarantees a later cold start on the same fragmented host.

## 2026-09-19 swap-limit persistence repair

At 08:23 UTC, the resident guard stopped Flash after its leaf cgroup swap-limit
read failed. The preceding 319 samples showed zero swap and no OOM; two systemd
daemon reloads triggered by snapd occurred between the last good sample and
failure. The failing raw token was not retained, so `max` is an inference,
consistent with [Moby issue 51446](https://github.com/moby/moby/issues/51446).

The v6 control helper uses a versioned v5 launch adapter that adds
`--annotation 'org.systemd.property.MemorySwapMax=uint64 0'`. This records the
zero-swap constraint in systemd as well as the kernel. The old adapter and helper
remain frozen. Image, checkpoint, inference profile, memory guard and reserve
are unchanged. Launch admission verifies the annotation and the exact container
scope's persisted `MemorySwapMax=0`; the continuous kernel check remains active.

A paired no-GPU check on this host showed that native equal memory/memory-swap
flags produce kernel zero but systemd infinity, whereas the annotation produces
zero in both. This mechanism is supported by the installed
[runc systemd annotation contract](https://github.com/opencontainers/runc/blob/v1.3.4/docs/systemd.md).
A deliberate system-manager reload test was unavailable without privileged
access, so it is not claimed as tested. No privileged workaround was used.

The existing same-boot fault latch remains in place. For this diagnosed repair,
maintenance archives the exact fault state and verifies removal with the old
helper before one supervised start with the repaired helper. This exception
is recorded with the fault-state and new-helper hashes; it does not enable
automatic retries after arbitrary faults or clear the pending reboot follow-up.

## 2026-09-21 reserve stop and 10 GiB floor

At 02:59 UTC the monitor stopped Flash with `physical_reserve_breached`. A VS Code
Remote-SSH login had pushed `MemAvailable` from 23.5 to 19.8 GiB (3.7 GiB)
within two minutes. There was no OOM, no container swap and no driver fault.
At the owner's request,
Claude archived the fault state, cleared the same-boot latch and started the
unchanged v6 helper once. Flash was ready at 04:21 UTC.

The owner then lowered the host reserve to 10 GiB (see the
[topology policy amendment](MODEL_TOPOLOGY_POLICY.md)). Helper v7 changes only
`HOST_FLOOR_GIB` (20 to 10), the guard's `--mem-available-floor-gib` backstop
(16 to 8) and the matching launch-record check (16.0 to 8.0). The guard stops
the container after five consecutive one-second samples below 8 GiB or any
sample below 4 GiB, and exits with code 8; the supervisor records that as
`guard_returncode`. GPU allocations come from unified memory and are not
charged to the container cgroup, so the host floor, not the 112 GiB limit,
bounds them. v6 remains frozen for rollback. The
supervisor pins v7 by hash, and `check-ready` uses the same 10 GiB floor.

Changing helper versions needs a handoff. Each helper re-validates the previous
run's launch record, including its exact guard floor, at startup and in the
stop-post cleanup. So stop the old service while the old pin is still in
place. Confirm the clean stop, then archive the state file. Move its
`artifact_dir` to `prior_artifact_dir` before pinning and starting the new
helper. A rollback to v6 is the mirror image. It must also restore
`HOST_RESERVE_GIB`, the exact `host_reserve_gib` check in
`agent_wrapper/deployment.py` and the value in `config/model_deployment.json`.
Restart any long-running process that imported the old deployment validator,
such as the Nara daemon. The supervisor restarts Nara after readiness. Update
`test_pinned_bundle_enforces_owner_reserve` with the pin. The supervisor now
records `bundle_sha256` in its state and refuses to start or clean up across a
helper change until this handoff is done. It checks before the new run writes
its state, so a retry refuses too. A record with an `artifact_dir` but no
`bundle_sha256` (v6 or v7) counts as a different helper. The 2026-09-21 cutover receipt and
archived v6 state are under `flash-personal-recovery/reserve-10gib-cutover-20260921/`.

The v6 stop and the handoff were clean. The first v7 cold start (14:10 UTC)
was stopped at 14:22 by the guard after four kernel `NV_ERR_NO_MEMORY` lines.
An earlier version of this section called that a reboot-class driver fault.
The investigation below shows it was a guard false positive.

**Investigation (2026-09-21, evidence in `v7-false-positive-restart-20260921/`).**

- The line `... returned from _memdescAllocInternal(pMemDesc) @ mem_desc.c:1359`
  is an `NV_CHECK_OK` log in the 580.142 driver. On GB10 the driver first tries
  physically contiguous 64 KiB big pages and, when that fails, retries with
  4 KiB pages (logged only at info level). A failure that reaches CUDA would add
  a second error line from `system_mem.c`. This host has 203 of the 1359 lines
  across two boots and no `system_mem.c` line.
- In none of the eight episodes with these lines did an engine fail. The 14:10
  engine finished the draft load, captured its CUDA graphs, printed "The server
  is fired up and ready to roll!" at 14:23:13 and answered its health request.
  The guard's stop is SIGTERM plus a 120 s Docker timeout; SGLang ignores
  SIGTERM while loading and was killed at 14:24:08.
- Page cache matters at one moment: the main-weight load reserves about
  84 GiB at "Load weight begin". On 2026-09-19 those loads logged the lines when
  MemFree was below about 100 GiB there (page cache 38-73 GiB). Today's 14:21
  lines came from the draft-model load and are not explained by page cache;
  the 12.7 GiB cached at 14:10 was an unrelated host read.

The supervisor now evicts the clean page cache of the checkpoint and PLE files
with unprivileged `posix_fadvise(DONTNEED)` before launch and records meminfo
and buddyinfo in the state's `prelaunch` field. It then requires at least
100 GiB `MemFree`, re-evicting every 30 s for up to 35 minutes so a
half-hourly host cache drop can clear unrelated cache. If that fails it
refuses without arming the latch. The first version gated on `Cached` at or
below 4 GiB; review showed that would have refused the 14:10 start, whose main
load passed with 102.6 GiB free, and left Flash down because the unit has
`Restart=no`. On an owner request the latch was cleared and Flash started once
at 19:04 with the first version; it was ready at 19:17 with no kernel lines.
No reboot was needed.

Helper v7 still stops Flash on any kernel `NV_ERR_NO_MEMORY` line. One of nine
SGLang draft-stage loads has been stopped that way. Making the exact
`mem_desc.c:1359` line non-fatal before readiness would avoid that, but it is a
host-safety trade-off: public GB10 reports show the same line during model load
shortly before compaction livelocks and hard resets, and this host was under
memory pressure at 14:21 (PSI rising, no free blocks at order 9 or above, swap
in use). Only the engine's survival was observed, not the host's safety. The
choice is the owner's; the hard stop stays until then.

Only on an explicit owner request for that specific stop, and only after a clean
reserve stop with no NVIDIA fault in the boot, the manual recovery is: copy `run_state/flash_resident.json` and the breach-window evidence into a
dated folder under `flash-personal-recovery/`, write a receipt with the state
hash, set the state's `phase` to `stopped`, start the service once, and verify
with `check-ready`. The restart must use the same helper pin as the stopped
run, or the handoff above applies. Each use gets its own receipt. This is not
an automatic or agent-initiated retry, and the same-boot latch stays in force.
Cold load takes about 12.5 minutes. A driver `NV_ERR_NO_MEMORY` fault is
different and still calls for an owner-chosen reboot.

## 2026-09-22 context evaluation and 262K cutover

At the owner's request the context tiers were evaluated with
`bench/flash_context_eval` (driver, probes, tests). Each tier stops the
resident, runs one candidate under the same guard and floors, probes it and
restores the resident. The 64K tier never started: the pinned container
runtime admits only 32,768 or 262,144. The first 262K attempt loaded and served
but the kernel guard stopped it on driver big-page retry lines logged while the
checkpoint filled page cache. The supervisor and the eval now run `LoadEvictor`,
which evicts the read-once checkpoint's page cache every 3 s until readiness
(never the PLE cache); with it the 262K load logged no such line and passed.
After the first attempt's guard stop the eval restored the 32K resident, as the
investigation above classifies those retry lines as a false positive. The driver
now makes that explicit: it restores the resident only when the boot's kernel
log since the eval began has no `NV_ERR` line from `system_mem.c` (a failure
that reached CUDA) and can be read. Otherwise it withholds the restore and
records why, for an owner-chosen reboot.

Helper v8 (`sglang_session_s3_v8.py`, sha `606d05f2...`) is v7 serving
`nextn-262k-c1-s3.json`. The cutover stopped v7 cleanly, archived the state
under `flash-personal-recovery/context-262k-cutover-20260922/`, and switched
together the v8 pin, the deployment's `context_length` and `profile_sha256`,
the exact validator in `agent_wrapper/deployment.py`, and the supervisor's
profile check. A rollback reverses those edits with the helper handoff above;
the pre-cutover files are archived next to the receipt. Measured results are in
the topology policy's context amendment.

