# Flash personal research recovery — September 18, 2026

**In progress.** The optimized Mia endpoint completed useful scientific and
coding work. Precision and MTP comparisons are still running; this is not a
final model selection or a production route change.

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
comfortably within 32K, but those preflight counts are not exact. Future
continuation budgeting must account for the retained reasoning before using
this approach close to the context limit.

## Remaining comparisons and use

The separate FP8-KV-capable child still requires its live comparison. An
independently reviewed NVIDIA/SGLang recipe and checkpoint are acquired and
prepared as a fallback; it has no local quality result yet. A checkpoint
and runtime change would be a bundle comparison, not an isolated weight effect.

See [personal session instructions](FLASH_PERSONAL_RESEARCH.md) for the client,
explicit reasoning controls, session limits, and exact-ID rollback. Endpoint
availability is tied to the live monitored session; this report does not imply
an indefinitely deployed service. The controller pauses the autonomous lab
while Flash owns memory and is configured and tested to restore the captured
residents and caller state when the session ends. The live restoration receipt
is still required before reporting that this session restored successfully.

Raw requests, streams, grades, runtime observations, and independent audits
are under the local artifact root
`a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/`, especially
`panel-run-a/`, `clarified-contract-arm-run-a/`, `real-repo-repair-run-a/`,
`paper-mtp3-fp32-auto/`, `legacy-mtp3-fp32-auto/`,
`legacy-mtp0-fp32-auto/`, and `session-a/`.
