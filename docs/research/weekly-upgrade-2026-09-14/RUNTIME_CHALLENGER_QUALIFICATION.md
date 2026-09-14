# Runtime challenger qualification: Qwen3.8-27B on DGX Spark

**Date:** 2026-09-14 UTC
**Decision:** **WATCH**
**Question:** Is a same-weights SGLang challenger sufficiently qualified for a
bounded experiment under the shared two-Spark-GPU-hour weekly budget and the
current no-service-cutover contract?

## Verdict

**WATCH — prepare the artifacts and a maintenance-window experiment, but do
not dispatch a live challenger under the current contract.**

There is now primary upstream evidence that SGLang v0.5.19 can serve
Qwen3.8-27B NVFP4 with FP8 KV, native MTP, DFlash2, reasoning parsing, and tool
parsing on one DGX Spark. That evidence is strong enough to keep a challenger
track open. It does not validate this project's exact Inferact quantization,
the stable image omits a critical disconnect-cleanup fix, the post-fix image is
an unvalidated nightly, and the published Spark recipe's memory allocation
does not meet this project's 30 GiB physical-memory floor. A third runtime also
cannot plausibly co-reside with both current servers: the latest recorded idle
snapshot left only about 42 GiB available while the local Qwen checkpoint alone
contains 26.38 GB of safetensors.[^local-baseline]

The originally quoted **64–78 tok/s through 65K** is a real third-party result
for a narrow coding workload, but it is not a result for the production
checkpoint or production inference contract. At 65,842 prompt tokens the two
reported boots were 66.8 and 63.8 decode tok/s. The higher values occurred at
shorter contexts. The experiment used a different target quantization, a
community-quantized DFlash2 draft, BF16 KV, temperature zero, thinking disabled,
and decode-only timing that excluded time to first token.[^spark-reproduction]
The same author reports about 30 tok/s on mixed chat. It must therefore remain
a discovery signal, not a baseline or expected local speedup.

No model was called, no image or checkpoint was pulled, and no service was
started, stopped, or reconfigured during this qualification.

## Decision definitions

- **ADMIT:** all prerequisites are present and a live experiment can begin
  within the current runtime, memory, interruption, provenance, and budget
  contract.
- **WATCH:** credible benefit exists, but one or more blocking prerequisites
  remain.
- **REJECT:** evidence does not justify further preparation or the candidate
  fails a hard constraint with no bounded remediation.

This candidate is `WATCH`, rather than `REJECT`, because the official SGLang
release and cookbook now demonstrate the architecture on the same hardware
class. It is not `ADMIT` because exact-checkpoint, cancellation, memory, asset,
and service-window gates are unresolved.

## Current local baseline

The comparison target must remain the exact local deployment, not a generic
Qwen3.8 label.

| Property | Recorded production baseline |
| --- | --- |
| Runtime | `vllm/vllm-openai:v0.21.0` |
| Runtime RepoDigest | `vllm/vllm-openai@sha256:a230095847e93bd4df9888b33dab956fa9504537b828a23657d2b26fed57b5c9` |
| Target path | `/mnt/models/qwen3.8-27b-nvfp4-mtp` |
| Upstream target | `Inferact/Qwen3.8-27B-NVFP4` |
| Target revision | `6128240ebaf4eaa7bad2b3d1c72c37d677c5f462` |
| Local `config.json` SHA-256 | `267be2125ee2ec272555748c87cc636b25a96107946f05491bd6043151c7fe4e` |
| Local quant-config SHA-256 | `0c1004d622f835eef17ba193d8e966ecfd2d5218cbc8d25b7effff8cb4011893` |
| Local tensor-index SHA-256 | `f9ba0436d933e2362fb1bfa0508931c28b68f1fddbd5b94e6d50712e36a0636c` |
| Local safetensors bytes | `26,381,249,312` |
| Serving contract | text-only; context 16,384; max sequences 2; FP8 KV; ModelOpt; Qwen reasoning and coder-tool parsers |
| Production speculation | in-checkpoint `qwen3_5_mtp`, 3 speculative tokens |
| Recorded throughput | approximately 16.6 average generation tok/s in the D-074 production qualification |
| Physical-memory gate | `MemAvailable >= 30 GiB` with both resident servers |

The launcher is the authoritative reproducible command surface, while D-074
records the measured qualification and rollback basis.[^launcher][^decision]
The local Hugging Face metadata revision matches the current immutable Inferact
revision returned by the Hub. The model page's generic SGLang example is useful
load-path evidence, but it is not a version-, hardware-, quantization-, or
tool-path qualification.[^inferact]

## What upstream now proves

SGLang v0.5.19 is a meaningful advance over the evidence available when the
runtime track was first opened:

1. The signed v0.5.19 release is source commit
   `0bcd822377da7b5718e674eaf9c870d349424dd1`. Its release notes include
   Qwen3.8-27B support, DFlash2, quantized target-`lm_head` support for the
   DFlash2 selector, and a DGX Spark cookbook remeasurement.[^release]
2. The official cookbook says all 80 DGX Spark combinations in its matrix
   served on v0.5.19 at ISL 8,192, OSL 1,024, and concurrency one, then scored
   the full 1,319-question GSM8K set. The matrix includes no speculation,
   native MTP, and DFlash2, FP8 KV, both supported state dtypes, and multiple
   NVFP4 exports. It explicitly says throughput and acceptance length were
   **not** remeasured in that sweep.[^cookbook]
3. The v0.5.19 source includes `--language-model-only`, and the cookbook
   documents `qwen3` reasoning and `qwen3_coder` tool parsing. These are needed
   to reproduce the current local text-only interface rather than silently
   loading the vision encoder.[^language-only]
4. The stable official CUDA 13 image is immutable by multi-architecture digest
   `sha256:d6e7288627be8b02be88e4bba38e73f6d50e2826869f753c13a4c4385ab3eda9`;
   its arm64 manifest is
   `sha256:4cba07b0c68725991890c64843403396effb7faa39ac47261166b2299095c513`.
   OCI labels bind it to the release commit above.

These facts justify an experiment. They do not establish that the local
Inferact tensor layout loads correctly, that its native MTP is wired correctly,
or that its outputs and tools match vLLM. The cookbook's validated NVFP4 targets
are the RadixArk FP4-head export, the RadixArk BF16-head export, and NVIDIA's
ModelOpt export. `Inferact/Qwen3.8-27B-NVFP4` is not in that matrix.[^cookbook]

## Why the stable release is not the experiment candidate

SGLang PR #35255 fixes abort propagation after a streaming client disconnect.
It merged as `f478b2bb2d582c09e7f1b4e49f0c2d039da8747a` after v0.5.19 was cut. The
upstream PR discussion records v0.5.19 reproducing thousands of discarded
zombie outputs after timed-out streams. The official comparison graph also
shows the merge is absent from the v0.5.19 tag.[^abort-fix]

This matters directly to the weekly loop. Its supervisor must be able to stop
a timed-out request without the server continuing to consume the shared Spark
budget. A second open upstream issue describes a remaining batch-transition
window, especially with overlap scheduling and speculative decoding, in which
aborted requests can keep decoding.[^abort-open]

An exact post-fix artifact was available during this review:

| Field | Proposed target-only experiment image |
| --- | --- |
| Pull reference | `lmsysorg/sglang@sha256:73cbbede63cd3454f2146073c6f80f151a2abef4a65b0992431b9c7a9aae5e5f` |
| arm64 manifest | `sha256:c61ec2dad8d8fe040b4e341bc63ede3ff13f14598869e647ea28b4b1f36bd7d5` |
| OCI source revision | `4358a1617cad734fc37bf53d9e5c2092bd43d075` |
| OCI version label | `nightly-dev-20260914-4358a161` |
| Registry observation | 2026-09-14 01:10 UTC |

GitHub's compare API places that commit 457 commits after the #35255 merge.
Pinning the digest makes this particular image immutable even though `dev` is a
moving tag.[^postfix-image] It is still a nightly on a substantially diverged
history from the release, so the v0.5.19 cookbook sweep cannot be credited to
it. The open abort race also makes a local cancellation test mandatory.

If a stable release containing #35255 appears before experimentation, qualify
that release and prefer its immutable arm64 image digest over this nightly.

## Audit of the 64–78 tok/s claim

The reproducible third-party repository is useful and unusually explicit, but
it tests a different system at commit
`60639a9794c13ba8f988e0dd92fef77c68793d30`:[^spark-reproduction]

| Dimension | Third-party result | Required local comparison |
| --- | --- | --- |
| Target | `RadixArk/Qwen3.8-27B-NVFP4@554ebba...` | `Inferact/Qwen3.8-27B-NVFP4@6128240...` |
| Draft | community `maurienne-ai/...NVFP4-RTNcal@bd7a934...` | no draft in phase A; official DFlash2 only in a later phase |
| Engine | custom image/patch recipe | immutable official image digest |
| KV | BF16 | FP8, matching production |
| Reasoning | thinking off | matched per request; both configured modes eventually required |
| Sampling | temperature zero | identical request bytes between arms |
| Measurement | decode only, TTFT excluded | end-to-end wall-to-correct plus TTFT, prefill, decode |
| Output | 512 tokens | fixed matched caps and completed-task grading |
| Workload | code where draft acceptance was 7–9 | project code, tools, scientific prose, and cancellation fixtures |
| Context | 320 to 65K headline; 65K row 63.8–66.8 | first 2K/8K/16K; longer context only after qualification |

Because target weights, head layout, draft weights, KV precision, reasoning,
and timing all change, the result does not estimate the gain from replacing
vLLM with SGLang on this project. The official DFlash2 card's speed table is
also measured on one H200, not a GB10; it cannot fill this gap.[^dflash-card]

The defensible external claim is narrower:

> A third party measured roughly 64–78 decode tok/s on code from short context
> through most of a 65K ladder on one Spark using a specific RadixArk target,
> community NVFP4 DFlash2 draft, BF16 KV, thinking-off sampling, and a custom
> SGLang build. At the 65K point the two boots measured 63.8 and 66.8 tok/s;
> mixed chat measured about 30 tok/s. Local performance is unknown.

## Blocking gates

All six gates must clear before `WATCH` can become `ADMIT`.

| Gate | Current evidence | Required closure |
| --- | --- | --- |
| Exact target | Generic Inferact page says SGLang; no exact Spark matrix cell | Offline container load of the local revision, tensor-count/quant/backend log verification, text-only `/v1/models` and `/tokenize` smoke |
| Runtime | Stable v0.5.19 is validated but lacks #35255; pinned nightly has the fix but not the stable validation | Pin one arm64 digest and source commit; run abort/cancellation tests locally; reject any zombie decode |
| Memory | Official Spark recipe uses `--mem-fraction-static 0.80`; upstream says 0.85 triggered earlyoom and 0.80 served | Derive a lower single-request/16K allocation that preserves local `MemAvailable >= 30 GiB`; never copy 0.80 blindly |
| Isolation | Only about 42 GiB idle available with both production servers | Owner-scheduled maintenance replacement of Qwen, or another demonstrated isolation method; a third co-resident server is not admissible |
| Assets | Candidate image and DFlash2 draft were not pulled in this review | Separately stage and hash immutable artifacts before the budgeted window; no network fetch inside the trial |
| Budget | Weekly cap is one shared 7,200-second Spark budget; other trials may already consume it | Reserve atomically from the shared ledger; use a dedicated future week unless the actual remaining balance covers the entire maximum plus restore reserve |

The upstream `.80` memory choice is not a local recommendation. Eighty percent
of nominal unified memory leaves less than this project's 30 GiB floor even
before accounting for the other resident service and host variation. The first
local boot must start from a conservative, preregistered maximum and fail closed
if the floor is crossed. No lower fraction is asserted here because it has not
been measured.

The service condition is decisive. With zero interruption allowed, there is no
live experiment to run: the candidate needs Qwen's memory slot and port cannot
prove physical fit by itself. If “no cutover” permits a scheduled, reversible
maintenance replacement while prohibiting production adoption, the experiment
below becomes eligible after the other gates are prepared.

## Minimal same-weights experiment

This is a proposal for a **future dedicated week**, not an execution command or
an authorization to stop a service. It qualifies the runtime first and keeps
DFlash2 as a separate later factor.

### Frozen factors

- Exact target directory and the three local hashes in the baseline table.
- Text-only mode, one running request, 16,384 total context, FP8 KV, Qwen
  reasoning parser, Qwen coder tool parser, served model name, request JSON,
  seeds, prompt/token hashes, output caps, and deadlines.
- Same pre-recorded 2K, 8K, and at most 16K inputs. No 64K arm in this first
  qualification because production is capped at 16K and the budget is small.
- Speculation **off** in both phase-A arms. This isolates the target runtime
  before comparing two different speculative implementations.
- Artifact logs contain metrics and hashes only; private prompts and raw
  completions remain outside the published summary.

### Sequence under the exclusive cooperative lease

1. Confirm the weekly ledger can reserve the full declared maximum without
   crossing a UTC ISO-week boundary. Confirm no active run, pause control, or
   ordinary inference lease holder. Record both current production container
   identities and `/v1/models`.
2. Verify all images and model files are already local by immutable digest/hash.
   Verify `MemAvailable >= 30 GiB`. Abort before touching a service on any
   mismatch.
3. Replace the Qwen slot temporarily with a digest-pinned vLLM target-only
   scratch arm using the exact Inferact weights and all frozen factors. Run one
   warm-up, six transport/tool/cancellation sentinels, and five paired
   single-stream samples at each admitted context size.
4. Replace that scratch arm with the exact post-fix SGLang image above and the
   same target-only factors. Require READY, `/v1/models`, `/tokenize`, backend
   logs, restart count zero, and the 30 GiB floor before sending paired work.
5. Explicitly cancel a bounded streaming request. Within 30 seconds the server
   must report zero running requests, stop producing tokens for that request,
   and emit no repeated deleted-state/zombie pattern. The outer supervisor must
   kill the owned container/process group at its deadline even if the API
   cancellation fails.
6. Run the same paired samples. Record end-to-end time, TTFT, prefill, decode,
   completion tokens, pass/fail, retries, peak memory, and runtime identity.
7. Stop at the preregistered experiment deadline and restore the canonical
   Qwen service. The lease is released only after the restored identity,
   liveness, memory floor, and zero candidate processes are verified.

Phase A answers only whether SGLang can safely and usefully run the same target.
If it passes, a later experiment may compare native MTP inside SGLang. Official
`incoai/Qwen3.8-27B-DFlash2` at immutable revision
`dedf8df68adfb1afeaf7b7480c0a0243108177b4` is a third, separate factor; its
Apache-2.0 metadata resolves the old DSpark license concern, but it must not be
folded into the runtime attribution.[^dflash-card]

### Proposed 7,200-second outer envelope

The full maximum must be reserved before starting. Actual unused time may be
released only by a trusted terminal receipt after restored-service checks.

| Segment | Hard allocation |
| --- | ---: |
| Identity, lease, memory, and asset preflight | 600 s |
| vLLM target-only boot and matched baseline | 1,500 s |
| SGLang target-only boot and qualification | 2,400 s |
| Paired replay and cancellation/recovery checks | 1,500 s |
| Mandatory restore and verification reserve | 900 s |
| Supervisor shutdown envelope | 300 s |
| **Maximum** | **7,200 s** |

The supervisor should stop new experimental work by elapsed second 6,000 so the
last 1,200 seconds remain available for restore and forced cleanup. An
interrupted reservation remains charged according to the shared ledger
contract. Do not begin this experiment in a week whose actual balance cannot
cover the full 7,200 seconds; unused weekly time does not carry over.

### Qualification thresholds

This small experiment can authorize a larger A/B, not production promotion.

- Exact target loads and remains text-only with the intended ModelOpt/NVFP4
  path; otherwise record `NOT_SUPPORTED` and stop.
- All transport, parser, tool, and frozen deterministic-fixture invariants
  pass. Text differences are recorded and graded against objective facts and
  tool arguments rather than requiring byte equality across runtimes. No
  malformed or empty-at-cap response.
- Cancellation reaches zero running requests within 30 seconds and leaves no
  zombie work.
- `MemAvailable` never falls below 30 GiB; no swap-growth, earlyoom, container
  restart, or unexplained process survives cleanup.
- At least three paired samples per context complete. Report bootstrap intervals
  but make no quality claim from the throughput subset.
- Median end-to-end wall time improves at least 10% without median TTFT becoming
  more than 10% worse. Raw decode alone cannot qualify the runtime.
- Canonical Qwen restoration passes identity, liveness, and memory checks.

If phase A fails one hard gate, do not try DFlash2 to rescue it. If phase A
passes, preregister native-MTP and DFlash2 factor experiments separately with
their own budget and correctness gates.

## Restore proposal

The following is a reviewable future maintenance command sequence. It was not
run. It deliberately checks the locally present production image digest before
using the canonical launcher, which currently names a mutable tag.

```bash
cd /home/decross1/projects/a_bgt_rsi

docker image inspect --format '{{json .RepoDigests}}' \
  vllm/vllm-openai:v0.21.0 \
  | grep -Fq 'vllm/vllm-openai@sha256:a230095847e93bd4df9888b33dab956fa9504537b828a23657d2b26fed57b5c9'

bash cron/serve-models.sh qwen

curl -fsS http://127.0.0.1:8001/v1/models \
  | .venv-chroma/bin/python -c \
    'import json,sys; d=json.load(sys.stdin); assert [x["id"] for x in d["data"]] == ["qwen3.8-27b-nvfp4-mtp"]'

bash experiments/exp008_qat_eval/preflight_mem.sh 0
```

The future controller must additionally compare the restored container image
ID/RepoDigest, model mount, launch arguments, start time, and restart count
against its frozen preflight receipt. It must remove the candidate container
and confirm no candidate PID remains before releasing the exclusive lease. A
failed restore keeps the run terminally failed and the reservation charged; it
must not trigger a blind retry.

## What would change the verdict

Change `WATCH` to `ADMIT` only when all of the following are true:

1. A maintenance interruption is explicitly scheduled, or an isolation design
   demonstrates the challenger without interrupting resident service while
   preserving 30 GiB physical headroom.
2. The exact post-fix image is already local and digest-verified. Prefer a new
   stable release if one contains #35255 and passes fresh upstream review.
3. The exact local Inferact checkpoint and hashes are frozen in a trial
   manifest, and an offline preflight shows the image recognizes its
   quantization and text-only layout.
4. The current week's ledger can reserve the whole maximum through the planned
   end time without crossing the ISO-week boundary.
5. Cancellation, restore, and no-zombie checks are part of the executable
   controller rather than operator intentions.

Change `WATCH` to `REJECT` for this artifact if the exact Inferact target does
not load, needs an unreviewed patch stack, cannot preserve the memory floor, or
cannot be cancelled and restored reliably. A future stable release or a newly
validated official checkpoint can then be evaluated as a new candidate.

## Reproducibility record

The report used local file hashing, `git ls-remote`, GitHub's compare API,
Hugging Face model metadata, and Docker Hub/OCI registry metadata. Registry
inspection fetched manifests and config JSON only; it did not pull image
layers. The candidate `dev` tag is recorded solely through its observed digest,
manifest, and OCI source revision, so later tag movement cannot change this
report's identity.

The local source review covered:

- [`cron/serve-models.sh`](../../../cron/serve-models.sh)
- [`DECISIONS.md`](../../../DECISIONS.md), D-073 and D-074
- [`CODEX_RESEARCH_HANDOFF.md`](CODEX_RESEARCH_HANDOFF.md), especially the
  earlier external-claim audit
- [`weekly_upgrade_loop_handoff.md`](../../weekly_upgrade_loop_handoff.md),
  including the runtime gates and two-hour budget decision

## Sources

[^local-baseline]: Local baseline snapshot and runtime digest: [Codex research handoff](CODEX_RESEARCH_HANDOFF.md). Local checkpoint hashes and byte count were recomputed from `/mnt/models/qwen3.8-27b-nvfp4-mtp` on 2026-09-14; no tensor content was emitted.

[^launcher]: Project canonical launcher: [`cron/serve-models.sh`](../../../cron/serve-models.sh).

[^decision]: Project production decision and measured qualification: [`DECISIONS.md`, D-074](../../../DECISIONS.md).

[^inferact]: Inferact model artifact and generic serving examples: [Inferact/Qwen3.8-27B-NVFP4](https://huggingface.co/Inferact/Qwen3.8-27B-NVFP4), immutable local-matching revision [6128240](https://huggingface.co/Inferact/Qwen3.8-27B-NVFP4/tree/6128240ebaf4eaa7bad2b3d1c72c37d677c5f462).

[^release]: SGLang, [v0.5.19 release notes](https://github.com/sgl-project/sglang/releases/tag/v0.5.19), signed source commit [0bcd822](https://github.com/sgl-project/sglang/commit/0bcd822377da7b5718e674eaf9c870d349424dd1).

[^cookbook]: SGLang, [official Qwen3.8-27B cookbook](https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-27B), especially its checkpoint matrix, DGX Spark validation, memory notes, MTP/DFlash2 flags, and parser guidance.

[^language-only]: SGLang v0.5.19 source, [`ServerArgs.language_model_only`](https://github.com/sgl-project/sglang/blob/v0.5.19/python/sglang/srt/server_args.py#L3251-L3260) and [model configuration handling](https://github.com/sgl-project/sglang/blob/v0.5.19/python/sglang/srt/configs/model_config.py#L580-L640).

[^abort-fix]: SGLang [PR #35255](https://github.com/sgl-project/sglang/pull/35255), merged as [f478b2b](https://github.com/sgl-project/sglang/commit/f478b2bb2d582c09e7f1b4e49f0c2d039da8747a), and the [v0.5.19-to-fix comparison](https://github.com/sgl-project/sglang/compare/v0.5.19...f478b2bb2d582c09e7f1b4e49f0c2d039da8747a).

[^abort-open]: SGLang [issue #36876: batch-transition abort race](https://github.com/sgl-project/sglang/issues/36876).

[^postfix-image]: Docker Hub [official SGLang tag metadata](https://hub.docker.com/v2/repositories/lmsysorg/sglang/tags?page_size=100&name=dev) inspected on 2026-09-14, plus GitHub's [comparison from the cancellation fix to OCI revision 4358a161](https://github.com/sgl-project/sglang/compare/f478b2bb2d582c09e7f1b4e49f0c2d039da8747a...4358a1617cad734fc37bf53d9e5c2092bd43d075).

[^spark-reproduction]: Third-party discovery evidence: pangoleen, [Qwen3.8-27B on one DGX Spark](https://github.com/pangoleen/qwen3.8-27b-dgx-spark-dflash2/tree/60639a9794c13ba8f988e0dd92fef77c68793d30), including its exact checkpoints, conditions, context rows, and separate mixed-chat result. It is not an official SGLang or NVIDIA benchmark.

[^dflash-card]: Official DFlash2 artifact: [incoai/Qwen3.8-27B-DFlash2](https://huggingface.co/incoai/Qwen3.8-27B-DFlash2), immutable revision [dedf8df](https://huggingface.co/incoai/Qwen3.8-27B-DFlash2/tree/dedf8df68adfb1afeaf7b7480c0a0243108177b4). Its published throughput table uses an H200.
