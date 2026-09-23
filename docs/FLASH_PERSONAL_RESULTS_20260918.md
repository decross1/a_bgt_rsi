# Flash personal research recovery — September 18, 2026

**Comparison complete; reliable warm handover remains unfinished.** Both
Flash bundles completed useful science/coding work and measured serving tests.
However, the final Mia restart and then the exact previously successful
SGLang restart both encountered fresh NVIDIA allocation faults before
readiness. The guards restored the original pair. Flash is a viable candidate;
this report does not claim a current live Flash endpoint, a completed model
cutover, or a completed personal-serving goal. The next experiment concerns
host allocation/restart reliability, not another benchmark panel.

This recovery follows the owner's two September 18 handoffs. The existing
Gemma/Qwen pair is the rollback configuration, not a required topology. Earlier
benchmark grades remain unchanged. These are small development diagnostics,
not a held-out demonstration that Flash is a superior scientist.

## Mia comparison baseline

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

The first container-start-to-ready interval was **603.5 seconds**, excluding
controller model/PLE verification and resident shutdown. The final handover
spent a separate 183 seconds verifying model/PLE files, then about 39 seconds
in transition and resident shutdown before container start. During 295 startup
samples, minimum `MemAvailable` was **32.25 GiB** against the declared 20 GiB
floor. Candidate cgroup swap and OOM events were zero. Host pageout totaled
2,828.2 MiB; several already-running processes gained swap. Those observations
do not fully attribute the pageout to particular processes or prove it harmless
in every run. Maximum observed memory PSI `full avg10` was 6.88%.

The previous host-pageout-only startup abort was therefore not reproduced as a
candidate OOM or failure to serve. The new diagnostic retains physical-memory,
candidate-swap/OOM, sustained-pressure, identity, and responsiveness stops.
It does not disable host swap or drop caches.

## Speed against the resident pair

The final resident replay completed six serial calls after verified restoration.
The prompt, output cap of 512, seed 17 and temperature-zero policy match the
saved Flash CSV controls. These are complete-bundle speed diagnostics: every
output intentionally ends at its length cap, without a task-quality score.

| Bundle | Median first generated token | Median full request | Three rates, tokens/sec | Median rate |
|---|---:|---:|---:|---:|
| Gemma 4 26B A4B | 0.291 s | 5.547 s | 53.33 / 92.30 / 95.61 | 92.30 |
| Qwen 3.8 27B | 0.414 s | 25.880 s | 18.99 / 19.78 / 19.80 | 19.78 |
| Mia Flash | 0.181 s | 11.790 s | 40.96 / 43.43 / 43.52 | 43.43 |
| NVIDIA/SGLang Flash | 0.429 s | 12.166 s | 37.62 / 42.09 / 44.48 | 42.09 |

Rates include first-token latency. Gemma's first request took 4.384 seconds
before its first token, versus 0.291 and 0.106 on later calls; the first Qwen
request took 1.543 seconds versus 0.414 and 0.334. These request-order effects
are not measured model boot times. Three runs do not establish a steady-state
distribution. Models, tokenizers and templates differ; Gemma uses 84 input
tokens versus 78 for the others. Resident requests omit `top_k` rather than
sending the Flash runtimes' `0`; thinking is disabled explicitly for Qwen and
by the installed Gemma template's default. The raw streams and all six hashes
were independently checked.

This workload places Flash at about 2.2 times resident Qwen's rate and less
than half Gemma's rate. It does not measure scientific intelligence. The saved
matched context probes show Mia/Qwen first-token times of about 1.04–1.05 /
1.33–1.46 seconds at 2K input, and 3.96–4.20 / 4.54–4.55 seconds at 8K input.
At 2K both produced 62 tokens, with full times of 5.22–5.31 / 4.00–4.12 seconds:
shorter first-token latency alone does not establish faster completion.
The larger-context probes remain historical diagnostics, not an optimized
64K qualification or isolated server prefill measurement.

Evidence: `resident-csv-live-comparison.md` and
`resident-csv-replay-live-20260919/` under the artifact root below; the result
SHA-256 is `6ee1cc9c01b0cf41a1b892498d07ba07c6ae8b051f2e933c6128259da5e423a6`.

## Practical answers and repairs

The following table records the Mia bundle's practical results. The
matched SGLang replay is reported separately below so its raw grades, grader
limitations, and runtime identity remain visible.

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
770.3 seconds after controller start. This includes its controller preparation
and uses a previously verified checkpoint; its timing origin differs from the
Mia 603.5-second container-start interval. These are not matched end-to-end
startup measurements. Literal response, tool call, and retained
reasoning/tokenizer checks passed. During that session it served
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

Through the completed v5-001 session, available memory remained at least
**21.96 GiB**, above the unchanged 20 GiB floor, with zero candidate swap/OOM
and no new NVIDIA allocation/Xid fault. This is an observed minimum for this
run, not an indefinite guarantee. The controller stopped normally and verified
exact restoration at 04:56:30 UTC; its final resource receipt remains with the
session artifacts.

The completed practical replay used the same 20 tasks, order, seed, policies,
tools, graders, and sandbox contracts as the Mia panel. The intended initial
wire difference was the served model identity. All 20 attempts completed for
both bundles without transport, parser, missing-final, repetition, deadline,
or runner failures, and neither received human intervention.

| Matched practical evidence | Mia parent MTP3 | NVIDIA/SGLang NEXTN3 | Reading |
|---|---:|---:|---|
| Frozen panel grade | 16/20 | 16/20 | Tied headline score; the failures differ |
| Science | 10/10 | 8/10 | Both SGLang Bayes answers have the correct posterior, payoff, action, source ID, and valid JSON; they use `Action`/`action` where the hidden answer requires `act`, although the public schema says only `decision: string`. The frozen `wrong_semantics` grades remain, but this is an undocumented lexical constraint rather than a math error. |
| Coding | 6/10 | 8/10 | Both bundles accept nonfinite CSV amounts under the ambiguous v1 wording. SGLang correctly rejects float interval endpoints in both policies; Mia does not. |
| Full panel elapsed | 864.25 s | 884.97 s | SGLang is 20.72 s, or 2.4%, slower. Its per-turn time includes a separate tokenizer HTTP preflight. |
| Historical repository repair | Pass, 85.80 s | Pass, 42.37 s | Both produce the identical 667-byte patch and final source SHA-256 `28bf931aaf9893d6b9eae52e2de3a350b21d12b6c1506b4002b62ff40b827124`, passing 2 visible cases and 6 hidden scenario groups. The separately saved 22-test replay was run on the Mia artifact; the final bytes are identical. |
| Panel plus repair | 950.06 s | 927.34 s | SGLang is 22.71 s, or 2.4%, faster overall and has the stronger result on this small coding panel. |

A preexisting root cache-drop cron fired during both practical panels
(22:00:07 UTC for Mia and 04:30:15 UTC for SGLang). Its effect was not isolated.
Together with tokenizer preflight and different generated trajectories, this
prevents treating the small elapsed-time difference as a causal runtime gain.

SGLang's Shapley explanations also avoid the two incorrect cumulative totals
in the Mia medium explanation. Raw usage must be read from the streams:
SGLang places `reasoning_tokens` at the top level, while the frozen convenience
projection expects the Mia-style nested field. The saved panel totals are
9,943 SGLang reasoning tokens and 9,474 Mia reasoning tokens, not a null or
zero SGLang count. SGLang used 56 model tool events and Mia 58; both had zero
human interventions.

| Existing matched request cohort | Mia parent MTP3 | NVIDIA/SGLang NEXTN3 |
|---|---:|---:|
| Three forced 512-token CSV calls, median completion/wall rate | 43.43 tok/s | 42.09 tok/s |
| Paper first turn, same frozen source | 51.34 s | 55.60 s |
| All three paper turns | 92.70 s | 81.54 s |
| Delegation code, strict JSON plus 4 executable cases | Pass, 524.06 s | Pass, 404.83 s |
| External-regret code | Pass, 72.45 s | Completed in 538.81 s; frozen sandbox contract rejected; separate ordinary-Python diagnostic passed 5/5 |

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

The regret response used 12,326 completion tokens, including 11,982 reasoning
tokens, and took 7.44 times Mia's completion time. The frozen grader rejected
its `try` statement before behavioral execution. A separate diagnostic permitting
`try` alone passed the three arithmetic cases but failed both malformed-input
cases because its exception handler referenced standard exception classes
absent from the evaluator's builtins. With only those four safe exception classes
also supplied, the same five isolated behavioral cases passed. The code is
therefore correct on these cases under ordinary Python, while violating the
original evaluator's restricted contract; its original rejection remains fixed.
This is not an established arithmetic failure or a replacement benchmark grade.

The longest individual legacy-task times are close, **524.06 seconds for Mia
and 538.81 seconds for SGLang**. The material difference is pair-level completion
and contract compliance: Mia passes both in 596.51 seconds total; SGLang takes
943.65 seconds and has one compliant pass. For descriptive accounting only,
panel, repair, paper, and both legacy tasks total 1,639.26 seconds for Mia and
1,952.53 seconds for SGLang. These are heterogeneous tasks, not a benchmark
score or a causal runtime comparison.

### Unscored owner-client smoke

The canonical SGLang client then ran one realistic coordination-game prompt
under each reasoning policy. These were delivery smokes with no matched Mia
call, no hidden grade, and no benchmark credit.

The thinking-off response completed in 53.01 seconds and correctly identified
the two pure equilibria, the symmetric mixed probability `2/3`, and the
payoff-dominant equilibrium. It incorrectly called `(C,C)` risk-dominant. Its
deviation loss at `(C,C)` used `4-0=4`; the deviator actually receives 3 when
the other player stays at C, so the loss is `4-3=1`, below the loss 2 at
`(D,D)`. It also called `(C,C)` the unique stable static equilibrium after
having identified two pure equilibria.

The medium-policy response took 90.59 seconds and corrected the equilibrium
math: `(D,D)` is risk-dominant because the deviation losses are 2 versus 1.
Its proposed experiment is still degenerate. Both policies start at `(C,C)`;
copying the opponent preserves `(C,C)`, while frequency best response sees a
C frequency of 1, chooses C, and also preserves `(C,C)`. Neither condition has
randomness, so changing a seed cannot make 200 replications differ and the
stated disconfirmation frequencies are not informative. The answer also says
a one-shot agent *should* use the mixed strategy, overclaiming a unique choice
when the game has two pure equilibria as well as the interior mixed one. Medium
reasoning repaired the immediate dominance calculation but did not make the
experiment sound.

### Provisional preference before the final startup check

The completed task review initially selected **Mia `mtp3-fp32-auto`**. The choice
weights its stronger source fidelity on the paper, two compliant legacy-task
passes, shorter time across that pair, and larger observed startup headroom.
It is a practical selection for source-grounded research and coding, not a
claim of universal model superiority.

SGLang's counterevidence remains material: it passes both interval repairs
that Mia misses, reproduces the identical repository repair in about half the
time, completes the panel-plus-repair cohort 22.71 seconds faster, solves the
delegation task faster, and shows useful subsecond first output on prefix-reused
paper continuations. It remains a reviewed code-focused alternative rather
than a failed candidate.

The compared bundles change model artifact, checkpoint revision,
quantization packaging, serving engine, and speculative implementation.
Consequently, none of these differences is attributable to the runtime alone.
The panel is one sample per task and policy, and the paper and legacy evidence
are single conversations. Mia was the provisional preference on this workload-
weighted evidence; the preserved SGLang artifacts support revisiting that
choice if the owner's workload becomes predominantly bounded repair work.

## Final operational finding

The final Mia restart used the same pinned parent image, weights and
`mtp3-fp32-auto` profile, with the newly delivered kernel monitor. At
05:11:55–05:11:56 UTC on September 19, the host logged four fresh
`NV_ERR_NO_MEMORY` errors from `_memdescAllocInternal`. The controller stopped
before readiness and began exact resident restoration. No evaluation request
was sent. Minimum observed available memory was 33.75 GiB. The last controller
sample, after the fault, recorded 38.05 GiB; an independent fault-aligned sample
recorded about 34.8 GiB. Candidate swap, container OOM events and restarts were
zero. These facts do not establish the failing allocation's size, process,
or whether the server might have recovered without intervention. They do
establish failure of the declared driver-error gate. The earlier Mia task
runs did not have this kernel monitor, so they cannot establish absence of
comparable host-driver events.

The next handover attempted **NVIDIA/SGLang v5**, which had
completed its full comparison and owner calls without a kernel fault while its
candidate monitor was armed, then verified exact restoration at 04:56:30 UTC.
An independent journal audit found 22 allocation errors at 04:56:26–04:57:00
during restoration and the subsequent resident replay. These precede the fresh
candidate boundaries; they remain unresolved host evidence. Its known science defects
remain visible above. The operational selection does not rewrite earlier
machine grades or turn an allocation problem into a model-intelligence claim.

| Preferred clean-host recovery bundle | Value |
|---|---|
| Model | `nvidia/Qwen3.8-Flash-Next-NVFP4@fc694b54fb0174e0913e6adf86691ef85a4ead47` |
| Image | `sha256:2ee545cf877ae8497c123637e061b6e6313c624e30018f975969b1d554e27f56` |
| Runtime | SGLang commit `84cf99860e3086ee0a458a71178343a8ac04fdab` |
| Context / concurrency | 32,768 total tokens / one request |
| Precision / PLE | NVFP4 weights, FP32 recurrent state, BF16 KV, file-backed PLE with 4 GiB resident cap |
| Speculation | Native NEXTN, 3 steps / 4 draft tokens; runtime reports normalized EAGLE |
| Allocator | `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` |
| Resource policy | 20 GiB available-memory floor, zero candidate swap, fresh kernel-fault guard |
| Endpoint while ready | `http://127.0.0.1:30080/v1`, model `nvidia/Qwen3.8-Flash-Next-NVFP4` |

Fresh session `session-s3-readiness-v5-002` used the same pinned bundle and
`expandable_segments:True`, but logged a fresh cluster of NVIDIA allocation
errors at 05:22:51–05:22:52 UTC during loading. The guard stopped it before
readiness, canaries, or an owner request and verified restoration of the exact
original pair and Nara at **05:31:22 UTC**. Minimum observed available memory
was **31.53 GiB**, with zero candidate swap. At 05:37 UTC, independent HTTP
checks confirmed both resident identities online, the UI healthy and in
resident mode, Flash offline, and Nara active.
This second failure removes the basis for treating a runtime switch alone as
a repeatable fix. Both failed requests counts are zero; no extra benchmark
grade was awarded or removed.

The host currently runs NVIDIA driver **580.142** and kernel
**6.17.0-1018-nvidia**. A post-failure buddy allocator snapshot contains no large
Normal-zone blocks at orders 11–13. This is consistent with fragmentation,
but neither proves the requested allocation order nor establishes a cause.
The existing reboot-required flag names AppArmor, not a pending NVIDIA driver.

The recommended next experiment is one coordinated reboot with versions
unchanged, followed by one identical guarded SGLang startup and a real owner
request if ready. This distinguishes a fresh-host effect before adding a driver
upgrade confound. Rebooting interrupts every service/session on the Spark and
requires a coordinated owner-approved window. This coordinating session did
not issue a reboot, driver installation, cache drop, swap change or compaction.
A preexisting system root cron independently runs a global cache drop every
30 minutes. The journal records its 05:00 invocation during Mia verification;
neither the controller nor the model verifier issues that operation. The
scheduled drop did not prevent the later failure. Preserve this host condition
in the recovery record rather than assuming the machine had no cache drops.

[NVIDIA's release notes](https://docs.nvidia.com/dgx/dgx-spark/release-notes.html)
describe improved unified-memory OOM handling in the July release. A
[first-hand vLLM report](https://github.com/vllm-project/vllm/issues/56824)
shows similar allocation messages on a newer driver too, including messages
that may reflect retries. Neither source proves our root cause or promises that
an update fixes it. The declared kernel hard stop remains in force.

The concrete local plan is `CONTROLLED_HOST_RECOVERY_PLAN.md`; startup evidence
is in `final-mia-startup-failure-audit.md`,
`shared-flash-restart-failure-audit.md`, `cache-drop-attribution-20260919.md`,
`final-restored-health-20260919.json`, and the two final session directories.
The benchmark-validity and subscription-critic questions remain deferred by
the owner's instruction.

### September 19 follow-up: reboot is not proven necessary

At 06:27 UTC the responsive GPU reported `GPU Recovery Action: None`, with no
new allocation/Xid messages since restoration. The earlier reboot recommendation
is a proposed experiment, not proof that the hardware requires a reboot. A
separately prepared compaction trial could test another recovery hypothesis;
it has not been run and requires a root operation unavailable to this session
without OS authentication. No driver-error or resource guard is relaxed.

The subsequent system/user service audit found configured boot coverage for
the main services, but two concrete ordering gaps: Docker can precede NVIDIA
CDI generation, and Nara's user-unit `After=docker.service` does not order it
after the system Docker daemon or model readiness. Active terminal sessions
and several ad-hoc helpers do not automatically return. The audit's read-only
checker passed 22 core process/HTTP/model-identity checks on the current boot;
these are not proof of a future reboot or a functioning research pipeline.

The new audit, recovery commands, privilege evidence and proposed alternative
are in `service-recovery-audit-20260919/README.md` and `no-reboot-options.md`
under the artifact root. This supplements the earlier clean-host plan and
preserves all measured failures and raw grades. Neither recovery option nor
any startup-configuration change was executed during that audit.

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

**Current handover: no Flash endpoint is claimed live.** Both final startups
failed their driver-allocation gate, and exact restoration returns the original
Gemma/Qwen services and Nara. SGLang v5 remains the preferred unchanged bundle
for one clean-host recovery experiment; final selection remains conditional on
actual readiness and a completed client/Now verification.

See [personal session instructions](../archive/docs-2026-09/FLASH_PERSONAL_RESEARCH.md) for the client,
explicit reasoning controls, session limits, and exact-ID rollback. Endpoint
availability must be taken from that handover receipt rather than this evidence
report. The session controllers pause the autonomous lab while Flash owns
memory and are configured and tested to restore the captured residents and
caller state when a session ends. The first Mia session completed verified
exact-ID restoration at 00:13:42 UTC on September 19, without errors;
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
`sglang-practical-v5-001/`, `sglang-screen-v5-001/`,
`owner-sglang-client-smoke/`, `owner-sglang-science-medium/`,
`sglang-practical-v5-vs-mia-independent-comparison.md`,
`sglang-paper-v5-independent-audit.md`,
`sglang-v5-legacy-practical-comparison.md`,
`final-endpoint-selection-independent-view.md`,
`final-personal-selection.json`,
`controls-child-auto-vs-fp8-independent-audit.md`, and
`paper-mtp3-bf16-child-fp8-independent-audit.md`. The control audit SHA-256 is
`902eaf692e88270dee1ff60986e6f66406e89cd3c2b70d4320e3574febf754cc`;
the FP8 paper audit SHA-256 is
`dce98879e9af959c08278d3c1a02bd4353929bb424f16d36e48fb5f28629762e`.
The additional `graph-acceptance-identity-audit.md` (SHA-256
`02d9678656deb0fba4eb16e735a005db76e56f0afa074becf0f8a319b77d1be7`)
records the graph-observability gap, incomplete workload-specific acceptance
evidence, and the separation of runtime and evaluator identity.
The completed SGLang practical comparison audit SHA-256 is
`3574916641c47ac04bcfe82071e8acad8c31cee9156341a9bc8f7f679d347e77`;
the final selection record SHA-256 is
`b1dddb340512054439355408372ec7700c4b7a655b0997ff139cb0e1a45ab989`.
The raw owner-smoke summary SHA-256 values are
`02ed8c91d9a8b3e60b94308140d5ef0a1e7f57a02913868d5d47140a30395f99`
for thinking off and
`fa381d72ba8dba9e38e4cc7339eef01632254227c5e17720fcf26cd16c126821`
for medium.
