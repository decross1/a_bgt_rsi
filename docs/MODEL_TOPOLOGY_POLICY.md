# Model topology policy — owner amendment, 2026-09-15

## Context amendment — 2026-09-22

The owner instructed:

> i am approving the max content length that we can do inside the headroom

> set a goal for bringing up the model with the best possible context length

Flash now serves 262,144 total tokens (the model's native maximum) through
frozen helper `sglang_session_s3_v8.py`, a copy of v7 that selects the
`nextn-262k-c1-s3.json` profile and changes nothing else: BF16 KV, MTP, one
running request, the 10 GiB monitor and 8 GiB guard stay as they were. The
2026-09-22 evaluation (`a_bgt_rsi_v2_artifacts/2026-09-22/`) measured, at
262K: lowest MemAvailable 21.5 GiB including a 241K-token prefill, 100%
needle recall at 8K/97K/241K tokens, cold time to first token 3.7 s / 48 s /
130 s, 1.05 s when the long prefix is cached, and about 40 tokens/s decode
(the same as the 32K baseline). A short request queued behind a 241K prefill
waited 128 s, because the server admits one request at a time. Multi-hop
variable tracking at 241K also named the decoy chain (precision 0.5, 1.0 at
23K). The 64K and 131,072 tiers were not tested: the pinned container runtime
only admits 32,768 or 262,144.

A cold start at 262K requires the supervisor's startup page-cache evictor;
without it the load logged driver big-page retry lines and the unchanged kernel
guard stopped it. Consumers with their own memory floors (the Oracle planner's
20 GiB check, shadow tasks) see about 22 GiB idle, which interactive sessions
can push below 20. Clients still advertise 32K until each is updated.

## Host reserve amendment — 2026-09-21

The owner instructed:

> lets change the max cap floor to 10 GiB - there will be times when I am sshing into the box.

That morning the resident guard stopped Flash when a VS Code Remote-SSH login
pushed host `MemAvailable` to 19.80 GiB. The steady-state host reserve is now
10 GiB. Frozen helper `sglang_session_s3_v7.py` is a copy of v6 that changes
only the monitor floor from 20 to 10 GiB, the guard backstop from 16 to 8 GiB
and the matching launch-record check. Readiness admission and
`config/model_deployment.json` use the same 10 GiB value. Unchanged: the
104 GiB prelaunch admission, the memory-pressure (PSI) stop, the 112 GiB
container limit, zero container swap, the driver-fault stop and the same-boot
fault latch. The container limit and zero swap bound only CPU-side charges;
the host floor is what bounds Flash's unified-memory GPU allocations. Evidence is under
`flash-personal-recovery/reserve-breach-20260921/`.

Studies that preregistered a 20 GiB deployment keep their own recorded
contract. Their runtime-binding checks now fail closed against the 10 GiB
deployment until the owner amends or re-registers them. Their own per-call
memory floors are study protocol and were not changed.

## Permanent resident decision — 2026-09-19

The owner explicitly selected Flash as the permanent local model, ended further
benchmarking, and requested migration of other projects' Gemma consumers. The
selected deployment is recorded in `config/model_deployment.json`: NVIDIA
Flash-Next NVFP4 on the reviewed SGLang image, 32K total context [2026-09-22:
262K, see the context amendment above], one running
request, FP32 recurrent state, BF16 KV, native NEXTN three-step speculation,
and a 4 GiB resident cache for NVMe-backed PLE. The host reserve is 20 GiB.
[2026-09-21: superseded by the host reserve amendment above; the resident
reserve is now 10 GiB.]

This changes the production topology. Historical pair-restoration rules below
remain evidence about prior experiments; they do not undo this decision.
Gemma and Qwen 27B containers are retained as stopped, manual rollback options.
Generator and critic role calls route to Flash with truthful model/runtime
provenance. Their shared weights do not provide model-family independence.

Selection is distinct from availability: `run_state/flash_resident.json` and
live endpoint identity determine whether Flash is actually serving. The
`flash-resident.service` unit starts it at login/boot with user lingering,
keeps resource guards running, and prevents automatic same-boot retries after
a serving fault. Research callers wait for readiness; no benchmark or model
promotion is inferred from starting the service. See
[`FLASH_RESIDENT.md`](FLASH_RESIDENT.md) for operation and reboot follow-up.

## Earlier topology amendment

The owner instructed:

> if there are any rules about running two models concurrently, scratch those, we have other ways to vary critic model and such.

Two concurrently resident models are not a requirement. The Gemma generator /
Qwen critic pair is the measured incumbent and rollback configuration, not a
permanent architecture constraint. The former fixed-role G5 restriction is
superseded for candidate research and future evidence-backed topology choices.

A single primary model may serve all local roles in an evaluation. It must not
be rejected solely because author and critic share weights or because a second
model is not resident. Other arrangements may load a critic sequentially, use
an on-demand critic, or use the already authorized subscription review sessions.
This amendment does not authorize paid API calls or automatically deploy a
candidate that has not passed evaluation.

Evaluate critic missed faults, false accusations, evidence use, task correctness,
reliability, latency, and resource use. Record which model, policy, evidence, and
runtime actually supplied each contribution. Same-checkpoint reviews remain
correlated; different-checkpoint reviews are not automatically correct. Neither
topology substitutes for executable checks, source fidelity, or human scientific
validation.

The current resident services remain the restoration target of isolated tests
until an explicit deployment decision changes that baseline. Restoring that
baseline is cleanup, not a requirement that future deployments run two models.
For the current Flash research program, the owner separately authorized a
20 GiB available-memory floor and uncapped local R&D outside the weekly allowance.
[2026-09-21: that research floor is distinct from the resident's own reserve,
which the host reserve amendment above lowered to 10 GiB.]
Every invocation remains bounded and records its resource and restoration data.

Historical decisions and benchmark results retain their original context. New
agents must apply this amendment instead of reintroducing a fixed two-model or
concurrent-residency veto from an older handoff. Current hard-coded production
routes describe the installed implementation; they are not evidence that this
policy change has already deployed a single-model lab.
