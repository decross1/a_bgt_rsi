# Flash personal research recovery — September 18, 2026

**In progress.** The optimized Mia endpoint completed useful scientific and
coding work. MTP, recurrent-state, child-image, and FP8-KV comparisons are
complete. NVIDIA/SGLang is now serving and its matched practical comparison is
in progress; this is not a final model selection or a production route change.

This recovery follows the owner's two September 18 handoffs. The existing
Gemma/Qwen pair is the rollback configuration, not a required topology. Earlier
benchmark grades remain unchanged. These are small development diagnostics,
not a held-out demonstration that Flash is a superior scientist.

## Observed working baseline

| Setting | Observed value |
|---|---|
| Checkpoint | `Mia-AiLab/Qwen3.8-Flash-Next-NVFP4@925d7be6c14c6c9442ef83e8f05b5a3c39304f69` |
| Image | `sha256:29eab5a29b765eef8b6405bbe0f2d385fc1e7b5e3c7ae18ae70382a68a0a2201` |
| Profile | `mtp3-fp32-auto`, `mia-925d7be6-mtp3-reduced47k-v2opt-v1` |
| Serving | MTP3, 47,149-token draft vocabulary, V2 runner; FULL decode graphs configured and captured at size 4; replay coverage unmeasured |
| Precision | NVFP4 weights, FP32 recurrent state, auto/BF16 KV |
| Capacity | 32,768 total context, one request, explicit 2 GiB KV allocation |
| PLE | Existing packed, file-backed table on local NVMe |
| Session endpoint (while ready) | `http://127.0.0.1:8012/v1`, model `qwen3.8-flash-next-mia` |

The first boot reached readiness in **603.5 seconds**. During 295 startup
samples, minimum `MemAvailable` was **32.25 GiB** against the declared 20 GiB
floor. Candidate cgroup swap and OOM events were zero. Host pageout totaled
2,828.2 MiB; several already-running processes gained swap. Those observations
do not fully attribute the pageout to particular processes or prove it harmless
in every run. Maximum observed memory PSI `full avg10` was 6.88%.

The previous host-pageout-only startup abort was therefore not reproduced as a
candidate OOM or failure to serve. The new diagnostic retains physical-memory,
candidate-swap/OOM, sustained-pressure, identity, and responsiveness stops.
It does not disable host swap or drop caches.

## Practical answers and repairs

| Probe | Result | Interpretation |
|---|---|---|
| Five science tasks × off/medium | 10/10 final structured objects passed the narrow machine grader | Manual audit found prose/proof defects; not ten wholly correct scientific responses or discovery |
| Five file repairs × off/medium | 10/10 completed; 6/10 passed | Four validation failures, described below |
| Clarified validation arm | 3/4 completed and passed | Separate task contract; one off-policy attempt exhausted tool turns |
| Historical repository repair | Completed in 85.8 s; 2 visible unit cases and 6 hidden scenario groups passed | Independent post-run loading of the exact generated module passed 22 tests in `tests/test_research_ops_status.py`; not the full repository suite |
| Real paper + two continuation turns | 3/3 completed | Bounds 1.0 and 0.5 were correct; scope prose and proposed experiment were incomplete |
| Historical delegation prompt, longer budget | Strict JSON and 4/4 behavioral cases passed | 524.1 s, including 12,038 reasoning tokens; excessive deliberation remains a practical problem |
| Historical external-regret prompt, longer budget | Strict JSON and 5/5 behavioral cases passed | 72.4 s; no formatting adapter needed |

The matched MTP0 delegation attempt exhausted all 16,384 output tokens in
1,134.1 seconds, including 16,340 reasoning tokens, and left an incomplete
JSON/code answer. It is an incomplete-output failure, not a parser-only
rejection or an admitted semantic pass. MTP3 completed this prompt correctly
but still took 524.1 seconds. Disabling speculation did not resolve the
excessive-deliberation problem on this paired development attempt; this does
not establish a general quality advantage for speculation.

The MTP0 external-regret attempt also exhausted its full 16,384-token allowance
in 1,129.9 seconds, entirely in the reasoning channel with no final output.
The same MTP3 request completed in 72.4 seconds with a behaviorally passing
answer. Both no-draft failures are preserved as exhaustion; they received no
semantic pass and no formatting rescue.

The primary panel completed 20/20 attempts and passed 16/20. Both off and medium
passed 8/10. There were no transport, parser, no-final, output-budget, deadline,
repetition, or sandbox-runner failures in that panel. It used 69 generation
turns and 28,066 completion tokens, including 9,474 reasoning tokens. Human
interventions were zero. The historical receipt field `interventions=58`
counts model-initiated tool calls, not human rescues.

Across those 69 generation turns, median time to the first parsed SSE data event
was 0.612 seconds and median time to the first emitted reasoning, final, or tool
channel was 0.643 seconds. Neither is completed-answer latency. Across the 20
full attempts, median elapsed time was 35.4 seconds, with a range of 18.3 to
113.6 seconds; that measure includes generation, tools, and grading but excludes
the 603.5-second cold start and panel setup.

| Request policy | Machine-graded passes | Sum of attempt times | Graded passes / attempt-hour |
|---|---:|---:|---:|
| Thinking off | 8/10 | 283.4 s | 101.6 |
| Medium thinking | 8/10 | 580.8 s | 49.6 |

Attempt time includes each recorded task's generation, tools, and grading;
these rates exclude model startup and panel setup. They describe this small,
single-seed development panel and the grading limitations below. They do not
establish off as universally better for research, but support trying it on
routine, testable tasks before paying for extended reasoning.

Both CSV repairs accepted `NaN`; both interval repairs accepted a float
endpoint. The CSV prompt did not explicitly define nonfinite amounts as
invalid. The interval prompt did specify integer pairs, but its rejection
clause did not explicitly mention floats. Their original grades stay fixed. A separately versioned
clarification explicitly required finite amounts and integer endpoints.
Three of its four attempts completed successfully. The fourth produced a
functionally passing file but exhausted its tool-turn allowance, made an
out-of-scope file attempt, and left debug prints. It remains an incomplete
attempt, not an upgraded pass.

The science grader checks the final structured calculation, not every line of
explanation. An independent reading found two cumulative vote totals stated as
5 instead of 4 in the medium Shapley explanation, despite the correct final
pivotal counts. The off-policy Vickrey answer's three examples do not by
themselves prove global dominance. Thus 10/10 final-object passes do not mean
ten entirely correct scientific responses.

The real repository task repaired a historical null-failure projection in
`orchestrator/research_ops_status.py`. Its generated two-line conditional
preserved null, known, and unknown failure distinctions. An independent
post-run check loaded that exact generated module and passed all 22 tests in
`tests/test_research_ops_status.py`; this was not the repository's full suite.

The paper task used Benjamin Heymann's September 16 preprint,
[On the Role of Tie-Breaking Rules in the Convergence of Fictitious Play for
Symmetric First-Price Auctions](https://arxiv.org/abs/2609.18848).
Flash retained the key numerical assumptions and calculated bounds 1.0 and
0.5 correctly. Some wording overgeneralized the equilibrium construction and
the scope of the compared mechanisms. Its proposed experiment did not
fully specify the population, state/time mapping, comparison arms, replication,
or tolerances. A finite LLM simulation would not by itself refute the paper's
asymptotic theorem. This is useful paper assistance with a concrete scientific
limitation, not a validated new research finding.

## Speed and correctness are separate

Three repeats per workload, each forced to 512 output tokens, gave:

| Workload | MTP3 | MTP0 | MTP3 / MTP0 |
|---|---:|---:|---:|
| Prose | 27.58 | 14.68 | 1.88× |
| Scientific explanation | 32.52 | 14.63 | 2.22× |
| Code generation | 33.19 | 14.49 | 2.29× |
| Tool arguments | 25.14 | 14.63 | 1.72× |
| Historical greedy CSV diagnostic | 43.43 | 14.78 | 2.94× |

Rates are median completion tokens per total request second. MTP0 necessarily
uses CUDA-graph capture size 1 rather than 4, so this is a serving-bundle
comparison. Image, checkpoint, request bodies, FP32 recurrent state, auto/BF16
KV, context, and request capacity are held fixed.

The first four are matched prompt families in the new speed panel. The CSV
diagnostic differs and must not replace those figures. Its top-k field is
explicitly 0 where the old request omitted it, so it is not an exact historical
wire replay. All fixed-length speed requests intentionally ended at their
token cap; speed measurements are not task-success grades. Counts come from
server token accounting, not SSE chunk counts.

The MTP0 timing runner initially rejected a tool stream because its parser
reported `tool_calls` despite reaching exactly 512 output tokens. The guard
was corrected to accept that finish reason for the speed-only tool probe.
Ten already recorded calls were retained with exact request/runtime evidence;
the remaining eight were run once. No original response was replaced or
counted twice. The capped tool arguments are not a tool-correctness pass.

The entire MTP3 18-request control window, including six one-token probes and the
12 speed streams, accepted 1.65 draft tokens per verification step, or 55.05%
of proposed draft tokens. Three short and three longer greedy
first-token controls returned identical top-five logprobs within each prompt.
They generated only the first token `3`, not the complete answer `323`, and do
not establish full-trajectory determinism.

The saved runtime logs confirm graph capture, but `cudagraph_metrics=False`
and the saved metrics lack replay/fallback counters. They do not establish
what fraction of generation actually replayed graphs. Exact speculative
acceptance was captured across each complete control window, rather than
separately for each workload. A later per-request metrics diagnostic can close
those observability gaps without repeating the practical acceptance panel.

MTP0 also repeated identical top-five probabilities within each prompt. Across
the two serving bundles, probabilities and some secondary-token rankings
differed despite byte-identical requests; both still selected `3`. For the
short prompt, that token's logprob was -0.00143 with MTP3 and -0.00799 with
MTP0. This is a reproducible numerical difference between bundles, not evidence
of within-profile instability, semantic loss, or lossless logprob parity.

## Recurrent-state comparison

The parent-image BF16 arm completed all 18 controls with byte-identical requests
to the FP32 arm. The launch arguments differ only in recurrent-state precision.
Median wall rates were 27.83 tok/s prose, 31.52 science, 33.12 code, and 24.50
tool output: changes of +0.9%, -3.1%, -0.2%, and -2.5%, respectively. Three
repeats and these mixed differences do not establish a speed improvement.

Reported cache-token capacity increased from 41,391 to 54,038 under the fixed
2 GiB allocation. Configured context remained 32,768; this is not a tested
54K or 64K context lane. The repeated first-token probes remained stable within
each arm, but changing recurrent precision changed logits and some secondary
rankings. It does not establish numerical equivalence.

The BF16 paper continuation completed all three turns in 48.3, 14.0, and 26.7
seconds. These calls included optional dashboard trace observation, and later
turns naturally contained different generated history, so their timing is not
a clean speed comparison. The source audit identified a substantive wording
error: a bound on unilateral deviation gain was described as distance from
an optimal payoff. Completion therefore does not mean all three answers were
scientifically correct.

The audit also found that the Mia chat-tokenization endpoint undercounted
retained reasoning in continuation history: the BF16 second and third calls
reported 862 more input tokens in generation usage than in preflight. The
earlier FP32 continuation has the same issue. All recorded requests still fit
comfortably within 32K, but those preflight counts are not exact.

The corrected continuation runner now serializes retained reasoning exactly
as the pinned Mia chat template does for token counting, while leaving the
generation messages unchanged. It checks generation usage against that count
after every turn and stops on disagreement. Offline CPU token-count
reconstruction reproduced all six saved input-token counts across both earlier
paper conversations. All six subsequent
child-auto and FP8-KV paper calls also matched their live generation counts
exactly and remained inside the configured 32K input-plus-output context.

## Child image with ordinary KV

Before enabling FP8, the new image ran the same 18 controls with ordinary KV
and BF16 recurrent state. Requests and launch arguments matched the parent
BF16 arm; the image changed. Median rates were 28.76 tok/s prose, 32.90 science,
33.32 code, and 24.87 tool output. The small differences across three repeats
are descriptive, not a demonstrated general speed gain from the image.

Its paper conversation completed in 57.7, 13.3, and 27.4 seconds. The second
answer correctly treated epsilon as a bound on unilateral deviation gain.
The first answer still incompletely specified the experimental construction,
and the third overgeneralized how LLM agents relate to the paper's assumptions.
These are three completed turns, not three wholly correct scientific answers.

## FP8-KV comparison

The FP8-KV arm completed the same 18 controls on the child image. All request
files were byte-identical to child auto-KV, and the 95-entry launch argument
arrays differed only where `--kv-cache-dtype auto` became `fp8`. The startup log
independently resolved FP8 KV. Both arms retained MTP3, BF16 recurrent state,
the fixed 2 GiB KV allocation, one request, and the configured 32,768-token
context.

| Workload | Child auto KV | Child FP8 KV | FP8 change |
|---|---:|---:|---:|
| Prose | 28.76 | 27.90 | -3.0% |
| Scientific explanation | 32.90 | 31.05 | -5.6% |
| Code generation | 33.32 | 33.74 | +1.3% |
| Tool arguments | 24.87 | 24.65 | -0.9% |

These are median completion tokens per total request second over three forced
512-token repeats. The mixed changes do not establish a throughput advantage.
FP8 reported 80,591 cache tokens versus 54,038 for auto KV under the same 2 GiB
allocation, a 49.1% increase. That is cache-capacity evidence only: configured
single-request context remained **32,768**, and neither 54K nor 80K context was
tested. Draft acceptance in these windows was 53.56% with FP8 and 56.62% with
auto KV, 3.07 percentage points lower with FP8. Sampled continuations differed,
so this is descriptive rather than an isolated kernel-quality estimate.

Both profiles selected `3` on every repeated short and long first-token probe,
with identical top-five lists within each profile. FP8 changed logits and parts
of the top-five lists across profiles. This does not establish full-trajectory
or numerical equivalence. FP8 reached readiness in 678.7 seconds, but there is
no matched clean auto-KV cold-start result for a startup comparison.

The FP8 paper conversation completed all three turns in 55.4, 13.9, and 30.2
seconds. The second answer correctly computed and interpreted the 1.0
deviation-gain bound. The third correctly halved it to 0.5 and reached the right
core theorem-scope conclusion, but categorically denied that an LLM could ever
be embedded in the theorem's dynamics. The first answer made a material
comparator error by labeling the original uniform-split equilibrium `γ₁*`
as the zero-on-tie target. It also omitted bid zero from the full grid,
abbreviated Assumption 1 below its policy-and-every-selector requirement, and
did not map observed frequencies into the paper's Poincaré section. Transport
completion was 3/3; manual source fidelity was mixed, not 3/3. One sampled
conversation cannot attribute these wording or semantic differences to KV
dtype.

## Next scientific improvement

The highest-value next change is a compact source-verification contract. Ask
the model to identify each important theorem, equilibrium, assumption, or
derived number by its source anchor; preserve its scope and quantifiers; and
show the calculation when applicable. For proposed experiments, require the
mapping from observable measurements to the theoretical state, the comparator,
and the specific extension claim that a failed result would reject. This
should replace repetitive exposition within the existing answer budget.

This recommendation follows the observed source-object, scope, and numerical
consistency errors. The paper runs already used medium reasoning, and their
completed but incorrect answers would not trigger a timeout or no-final
fallback. Simply escalating every answer to more reasoning is therefore not
supported by these results.

The contract is **proposed, not a measured improvement**. At the next evaluation
window, compare the current prompt against this suffix on four fresh,
source-bound questions, with a frozen answer key, unchanged runtime and request
policy, alternating arm order, and no retries. Record material source errors,
completion, time, and tokens. The local `next-single-improvement.md` artifact
contains the exact proposed suffix and the eight-call validation plan.

## Independent NVIDIA/SGLang serving comparison

The v5 session reached admitted readiness on September 19 at **04:02:47 UTC**,
770.3 seconds after controller start. Literal response, tool call, and retained
reasoning/tokenizer checks passed. It serves
`nvidia/Qwen3.8-Flash-Next-NVFP4` on `http://127.0.0.1:30080/v1`, with 32,768 total
context, one request, FP32 recurrent state, BF16 KV, and three native NEXTN steps
(four draft tokens; the server reports the normalized `EAGLE` implementation).
The image is
`sha256:2ee545cf877ae8497c123637e061b6e6313c624e30018f975969b1d554e27f56`,
the NVIDIA checkpoint revision is
`fc694b54fb0174e0913e6adf86691ef85a4ead47`, and installed SGLang is
`84cf99860e3086ee0a458a71178343a8ac04fdab`.
File-backed PLE remains on NVMe with a 4 GiB cache cap. The allocator uses
`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.

Through the 04:15 UTC observation window, available memory remained at least
**21.96 GiB**, above the unchanged 20 GiB floor, with zero candidate swap/OOM
and no new NVIDIA allocation/Xid fault. This is an observed minimum for this
run, not an indefinite guarantee. The exact final resource receipt remains
with the session artifacts.

| Existing matched request cohort | Mia parent MTP3 | NVIDIA/SGLang NEXTN3 |
|---|---:|---:|
| Three forced 512-token CSV calls, median completion/wall rate | 43.43 tok/s | 42.09 tok/s |
| Paper first turn, same frozen source | 51.34 s | 55.60 s |
| All three paper turns | 92.70 s | 81.54 s |
| Delegation code, strict JSON plus 4 executable cases | Pass, 524.06 s | Pass, 404.83 s |

The CSV requests use the same explicit greedy policy; reaching the fixed cap
is deliberate and is not a completed CSV-task success. Three repeats do not
establish a material throughput difference. The SGLang paper first turn had
15,293 input tokens and first emitted reasoning after **11.79 s**. This is
request-to-output latency, not isolated GPU prefill time. Continuation first
outputs arrived after 0.654 and 0.391 seconds. The complete conversation was
12% faster, but generated histories diverged after the common first turn.
The delegation answer used 8,808 completion tokens, including 8,410 reasoning
tokens, versus Mia's 12,301/12,038; its 22.8% lower completion time is partly a
shorter reasoning trajectory, not an isolated decode gain.

The independent source audit found SGLang paper turn 1 partial and turn 2
materially wrong: it described the epsilon bound as closeness to a true Nash
equilibrium instead of a bound on unilateral deviation gain at the specified
strategy. Turn 2 also exceeded its 100-word limit. Turn 3 computed 0.5 and
correctly rejected the proposed theorem-refutation claim, with an overbroad
caveat about LLM agents. Mia FP32 was stronger on source semantics in these
sampled answers. Neither the three transport completions nor one conversation
establishes scientific superiority.

The remaining legacy task and replay of the existing practical panel/repair
are separate from this interim table. The owner explicitly prioritized useful
serving and completed work over every-fixture perfection. The known paper
error is retained in the comparison rather than used to prevent the remaining
practical evaluation. No new benchmark prompts or hidden answers were added.

## Startup diagnosis

The independent recipe initially needed 201.2 seconds to materialize 51.2 GB of
file-backed PLE, then reported 558.98 seconds loading weights and 617.69 seconds
through tokenizer startup. These are startup stages, not decode measurements.
The NVIDIA artifact contains 132.7 GB of files; loading weights, initializing
its sparse/recurrent paths, loading the speculative draft and warming the
server are substantial work even when the live request fits comfortably.

Earlier failed sessions remain preserved:

| Attempt | Observed issue |
|---|---|
| S3-001 | Controller expected `NEXTN`; installed server correctly normalized it to `EAGLE` |
| S3-002 | Recorder used the helper source manifest where the installed runtime lock was required |
| S3-003 | Real kernel `NV_ERR_NO_MEMORY` during weight loading; no generation completed |
| Allocator-v4 | Model loaded and literal output was correct; observer polled health before internal warmup finished |
| Readiness-v5 | Corrected observer; ready, exact canaries passed, comparison requests completed |

CPU inspection verified all 3,623 installed Python files against the image's
own runtime lock, with zero mismatches. v4/v5 explicitly enable expandable
allocator segments, but two successful loads do not prove allocator
fragmentation caused the earlier driver failure. The failed run did not
record global free/cache memory, so that attribution cannot be reconstructed.

The installed `/health` handler can generate a token and reports 503 during
startup. v5 waits for explicit startup health once, then uses passive
`/v1/models` identity checks during serving, excluding the response's dynamic
creation timestamp. Those controller fixes change neither request policies
nor the historical grades. Failed attempts restored the exact resident pair
and Nara; the first Mia restoration took 394.1 seconds.

**Personal endpoint live at 04:15 UTC: NVIDIA/SGLang, comparison in progress.**
Gemma, Qwen and Nara are intentionally paused while its controller owns the
memory lease. The finite session stops the candidate by **11:45 UTC** and
reserves restoration through **12:00 UTC** on September 19. Final selection
and an owner-client handoff remain to be completed. The qualified Mia
`mtp3-fp32-auto` parent remains an already demonstrated personal-use option.

See [personal session instructions](FLASH_PERSONAL_RESEARCH.md) for the client,
explicit reasoning controls, session limits, and exact-ID rollback. Endpoint
availability is tied to the live monitored session; this report does not imply
an indefinitely deployed service. The controller pauses the autonomous lab
while Flash owns memory and is configured and tested to restore the captured
residents and caller state when the session ends. The first session completed
verified exact-ID restoration at 00:13:42 UTC on September 19, without errors;
restoration took 394.1 seconds after the candidate stopped. The subsequent
child/FP8 session also ended without an error and completed verified exact-ID
restoration at 01:01:11 UTC; its restoration took 396.2 seconds.

Raw requests, streams, grades, runtime observations, and independent audits
are under the local artifact root
`a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/`, especially
`panel-run-a/`, `clarified-contract-arm-run-a/`, `real-repo-repair-run-a/`,
`paper-mtp3-fp32-auto/`, `legacy-mtp3-fp32-auto/`,
`legacy-mtp0-fp32-auto/`, `controls-mtp3-bf16-child-auto/`,
`controls-mtp3-bf16-child-fp8/`, `paper-mtp3-bf16-child-auto/`,
`paper-mtp3-bf16-child-fp8/`, `session-fp8-b/`,
`controls-child-auto-vs-fp8-independent-audit.md`, and
`paper-mtp3-bf16-child-fp8-independent-audit.md`. The control audit SHA-256 is
`902eaf692e88270dee1ff60986e6f66406e89cd3c2b70d4320e3574febf754cc`;
the FP8 paper audit SHA-256 is
`dce98879e9af959c08278d3c1a02bd4353929bb424f16d36e48fb5f28629762e`.
The additional `graph-acceptance-identity-audit.md` (SHA-256
`02d9678656deb0fba4eb16e735a005db76e56f0afa074becf0f8a319b77d1be7`)
records the graph-observability gap, incomplete workload-specific acceptance
evidence, and the separation of runtime and evaluator identity.
