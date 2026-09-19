# Flash personal research recovery — September 18, 2026

**In progress.** The optimized Mia endpoint completed useful scientific and
coding work. MTP, recurrent-state, child-image, and FP8-KV comparisons are
complete. The independent NVIDIA/SGLang comparison remains; this is not a final
model selection or a production route change.

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
| Serving | MTP3, 47,149-token draft vocabulary, V2 runner, FULL decode graphs, CUDA-graph capture size 4 |
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
| Five science tasks × off/medium | 10/10 completed; machine-graded final objects passed | Explanatory prose had errors; not open-ended discovery |
| Five file repairs × off/medium | 10/10 completed; 6/10 passed | Four validation failures, described below |
| Clarified validation arm | 3/4 completed and passed | Separate task contract; one off-policy attempt exhausted tool turns |
| Historical repository repair | Completed in 85.8 s | Generated patch passed focused checks and all 22 tests in the relevant repository test module |
| Real paper + two continuation turns | 3/3 completed | Source-based calculations correct; experimental proposal only partial |
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
after every turn and stops on disagreement. CPU replay reproduced all six
saved counts across both earlier paper conversations. All six subsequent
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

## Remaining comparisons and use

The independently reviewed NVIDIA/SGLang recipe and checkpoint reached a live
HTTP server on the first local attempt, but the task comparison remains pending.
The first start materialized 51.2 GB of file-backed PLE in 201.2 seconds. The
server then reported 558.98 seconds loading weights and 617.69 seconds through
tokenizer startup. These stages are startup costs, not decode measurements.

The local readiness controller incorrectly expected the requested `NEXTN` name
in server metadata. The pinned SGLang source normalizes that name to `EAGLE`
and uses the target model as the native draft; the observed metadata matched
that behavior, including the same `/model` draft path and three steps/four
draft tokens. No evaluation calls were issued before the exact source guard
stopped this attempt for a controller correction. This is a controller
metadata mismatch, not a quality or hardware rejection of the model. The
corrected controller reached HTTP readiness on the second attempt, but another
recorder error stopped it before task generation: the controller passed the
source manifest to a helper that needed the runtime lock. The checkout also
contains a newer runtime lock than the pinned image. These are evaluation
plumbing failures, not evidence against the model's answer quality.

A CPU-only inspection extracted the image's own runtime lock and verified all
3,623 declared installed Python files, with zero missing or mismatched files.
That lock has SHA-256
`ac017ebaf18adf13637c63a713fd4e94a327edadc85e21aad8e35725a924325e`,
installed SGLang commit `84cf99860e3086ee0a458a71178343a8ac04fdab`, and tree
`4957f519e185bfa0388299d8fec3792f4f96102d`. The corrected recorder must bind
that installed identity separately from the host-side helper checkout. The
second attempt reached HTTP readiness at 01:45:21 UTC, retained at least
22.70 GiB available memory with zero candidate swap/OOM, and completed verified
restoration at 01:51:55 UTC. It issued no evaluation calls.

The initial arm uses 32K/C1 and three native speculative steps; the only launch changes from
the supplied one-step bring-up profile are three steps and four draft tokens.
It inherits no qualification from the upstream release's different 262K/C2
configuration. A checkpoint and runtime change is a bundle comparison, not an
isolated weight effect. Final runtime selection therefore remains in progress;
the completed Mia evidence already supports bounded personal use.

**Personal endpoint ready for use: yes, through a finite monitored session.**
The qualified `mtp3-fp32-auto` parent remains the conservative working baseline
while final selection is open. A ready session serves
`qwen3.8-flash-next-mia` on loopback port 8012; it does not change the lab's
normal routes. The main observed Mia limitations are occasional excessive
reasoning without a final answer and substantive errors inside otherwise
completed scientific prose. The next comparison is the pending SGLang bundle,
not a prerequisite to using the working Mia endpoint.

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
