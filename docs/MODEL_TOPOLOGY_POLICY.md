# Model topology policy — owner amendment, 2026-09-15

## Permanent resident decision — 2026-09-19

The owner explicitly selected Flash as the permanent local model, ended further
benchmarking, and requested migration of other projects' Gemma consumers. The
selected deployment is recorded in `config/model_deployment.json`: NVIDIA
Flash-Next NVFP4 on the reviewed SGLang image, 32K total context, one running
request, FP32 recurrent state, BF16 KV, native NEXTN three-step speculation,
and a 4 GiB resident cache for NVMe-backed PLE. The host reserve is 20 GiB.

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
Every invocation remains bounded and records its resource and restoration data.

Historical decisions and benchmark results retain their original context. New
agents must apply this amendment instead of reintroducing a fixed two-model or
concurrent-residency veto from an older handoff. Current hard-coded production
routes describe the installed implementation; they are not evidence that this
policy change has already deployed a single-model lab.
