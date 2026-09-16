# Stable canary 1.1.0 resident reference

**Execution status:** complete, replay verified, admitted, and restored. **Measurement status:** the known 1.0 task-contract defects were corrected prospectively and all 21 prompt/oracle contracts received independent model-free checks before release. The active catalog has no restrictive measurement notice (`measurement_review_sha256: null`), but that is not a formal measurement-review approval or broad quality certification. Release 1.1.0 remains a fixed canary with review required on 2026-10-14; its task and grader bytes stay frozen until that review.

This is one seeded resident reference run. Gemma used `precise` for capability tasks and actor steps; Qwen used `critic_current` with `xhigh` reasoning for critic steps. The result describes these exact model, policy, transport, and harness identities. It does not establish broad model quality or a production promotion.

Release 1.0.0 remains separate commissioning evidence. Its four task-contract defects and recorded outcomes were not converted or rescored. The 1.1.0 result is prospective and is not a before/after model comparison with 1.0.0.

## Recorded construct outcomes

| Frozen construct | Credited units | Recorded interpretation |
| --- | ---: | --- |
| Quantitative inference | 2/2 | Two strict task passes. |
| Evidence attribution | 1/1 | The corrected full-support contract passed. |
| Evidence abstention | 1/1 | The correct abstention received credit. |
| Isolated Python function | 2/4 | Two passes; two candidates used explicitly forbidden `lambda` syntax. |
| Single tool call | 0/1 | Calls and values were right; visible final JSON carried Gemma channel framing. |
| Parallel tool calls | 0/1 | Calls and values were right; visible final JSON carried Gemma channel framing. |
| Relevance / no call | 1/1 | Correctly made no tool call and returned strict JSON. |
| Dependent tool calls | 0/1 | Calls and values were right; visible final JSON carried Gemma channel framing. |
| Public goods | 2/2 | Both actions had zero exact own-utility regret. |
| Vickrey auction | 1/2 | One action passed; one valid action had exact regret 2. |
| Cournot | 0/1 | The valid action had exact regret 2. |
| Proper-scoring reporting | 1/1 | The action had zero exact regret. |
| Payoff actor-tool-critic workflow | 0/1 | The Qwen critic exhausted its output cap in reasoning and exposed no final artifact. |
| Auction actor-tool-critic workflow | 1/1 | Actor, trusted tool, and critic artifact passed. |
| Evidence actor-tool-critic workflow | 1/1 | Actor, trusted tool, and critic artifact passed. |

The model-capability panel recorded 11/18 credited units in 22 calls. The system micro-workflow panel recorded 2/3 in 6 calls. Those panel and construct results remain separate. There is no omnibus or cross-panel score.

The run accounted for all 21 units in exactly 28 calls, 6,748 input tokens, and 3,980 output tokens. Evaluation took 151.060931 seconds; the supervised lifecycle took 154.289782 seconds. The monitor recorded 183 samples, a minimum 33.217243 GiB MemAvailable, zero host pageout delta, and no guard breach. Nara was restored in 152.274577 seconds. Both resident containers retained their exact IDs, remained running, and had zero restarts and no OOM event.

Flash remained explicitly unissued: 21/21 units are recorded as unissued, with zero calls and zero tokens. There is no matched pair, Flash score, winner, loss, or promotion claim.

## Receipt and publication boundary

- Corrected causal source commit: `979f9616ef2afd22499af0d54b93d1f44490c8da`.
- Registration commit: `c8404668f1e222b122a8727893542060d3f6f43f`.
- Published definition SHA-256: `d2eb69d9c0fefc7b377cec6cb550f491979a5f137d38346dc99a607be5890006`.
- Registration SHA-256: `e219ebb7130f2878ee7766e48ba02aa3589a90b2f93982a4be237bdc594319e9`.
- Resident run SHA-256: `21551beb836e22ad50aee00dbea332040d0a790854252092cc825b5abe5d405f`.
- Replay SHA-256: `6ab0ef18f41cc33211f5fd89769197de0c594c4b22967d77184a13bbfa5add95`; zero mismatches.
- Admission SHA-256: `e5ca2d2cfaae80028500b965b3846eb0f21d5fb0509fc6675f5dcfb00a0026b8`.
- Supervisor-final SHA-256: `f8d6fa5af4296857f4768ff5f9b437bd724022bebb513e565fb5348d7e5a9e78`.
- Flash unissued run SHA-256: `1e3dfddb12415dc2feb097701fc7909b559d4a5a146e5f7c71c63ef443fd74ee`.
- [Public post-run verification receipt](resident-reference-v1_1-verification.public.json), SHA-256 `a50893dcbe56ff460a57522364b0c4e64cb7e2e2337ddd8f348edfba45b416b0`.

The pure registered-comparison verifier checked the frozen source map and receipt chain without inference, grading, repair, or rescoring. Terminal UI/API evidence showed release 1.1.0 active, the resident reference admitted, Flash unissued, and no matched result or winner claim.

## Read-only failure-mechanism audit

The audit used the frozen source and private transport evidence in place. It made no model call and did not change any recorded outcome. The raw-attempt log SHA-256 is `ee752b4c5adc0be23a0cbb5e3e9f9acb27d95a775986a174c3dafdd3cfbff30e`; the calls log SHA-256 is `f80b0c7d7892347285cb933f954e66ddf357607412adf2758d5f863a0c141896`.

### Gemma post-tool channel framing

All three failed native-tool finals contain the same leading bytes, `<|channel>thought\n<channel|>`, followed by the correct strict JSON payload. The exact behavior repeated in the 1.0 and 1.1 runs; the no-call control returned clean JSON both times.

The boundary trace is specific:

1. The live Gemma container uses image `sha256:f023269abe06db3a1a7cd9e170a0f5bd2b333a19ef9cb99ed8df97a70345bc25`, `--enable-auto-tool-choice`, and `--tool-call-parser gemma4`. It does not use `--reasoning-parser gemma4`.
2. The mounted Gemma template, SHA-256 `94899c0f917d93f6fe81c95744d1e8ddab2d21d39228d2e4aec1fb2a25bff413`, documents and emits an empty thought channel when thinking is disabled. After a tool response, it suppresses the usual generation prefix, so the model generates that channel prefix as response bytes.
3. The installed vLLM `gemma4` tool parser, SHA-256 `939d755cf19c1911e309ff8650909efbcb47b09359191c832a6a3cc5029a744a`, parses tool calls but returns non-tool content unchanged.
4. The frozen wrapper, SHA-256 `5ee8746587c7ab4e3bc77e317c8d586c7371341ad7f610444b10d25136d4ed0c`, copies `message.content` into the call record and runner result without applying a reasoning-channel parser.
5. The same installed image contains a Gemma reasoning parser, SHA-256 `64a1d3f05e22cee893ebc1f2507a150eaadf4d06e3efac5035c6ab94480a739e`, whose non-streaming contract separates `<|channel>...<channel|>` from the final content. A model-free check of its companion parser separated each observed final JSON payload and left the clean no-call payload unchanged.

The observed failure therefore enters at the server response boundary: the tool parser is enabled while the matching Gemma reasoning parser is not. The strict grader is behaving as published. Making the grader accept framed output would hide this transport contract failure and is not proposed.

### Code contract compliance

Both code responses ended normally and well below their 1,536-token caps. The corrected prompts explicitly forbid `lambda`, yet both returned the familiar `sorted(..., key=lambda ...)` pattern. `CODE-MERGE-001` did not need a key because ordinary sequence ordering suffices; `CODE-WEIGHTED-MEDIAN-001` likewise could sort value-weight pairs directly. These are valid instruction-compliance failures under the disclosed 1.1 contract, not transport, timeout, or hidden-sandbox defects. A parser configuration change cannot repair them.

### Qwen critic exhaustion

`SYSTEM-PAYOFF-001` reached exactly 1,536 output tokens, ended with `finish_reason=length`, exposed 6,423 reasoning characters, and returned an empty visible completion after 83.041 seconds. The same task did the same in release 1.0, with 6,954 reasoning characters and an empty final. By comparison, the two successful 1.1 critics stopped normally with 1,358 and 1,740 reasoning characters and non-empty finals. This is a repeatable `xhigh`-reasoning and fixed-cap interaction. It is not a transport error or supervisor timeout. A lower-effort critic is a separate policy hypothesis and must not be bundled into the Gemma boundary experiment below.

### Strategic regret and repeatability

The failed Vickrey response bid 8 with value 5 against highest other bid 7. It wins at price 7 for utility -2, while losing yields 0, so exact regret is 2. The failed Cournot response chose quantity 5 against quantity 5, yielding 40 rather than the optimum 42 at quantity 6 or 7, also exact regret 2. Both were clean seven-token JSON responses with normal stops. They are substantive action errors.

The Vickrey error repeated across 1.0 and 1.1. Cournot returned optimal quantity 7 in 1.0 and suboptimal quantity 5 in 1.1 despite the same nominal seed and policy. That variation is why a future causal trial needs a fresh contemporaneous reference arm; it must not reuse this run as if it were a deterministic counterfactual.

## Proposed single bounded experiment

**Status:** proposal only; unregistered and unissued. It authorizes no service change or call.

Proposed comparison ID: `stable-benchmark-v1-1-gemma4-reasoning-parser-20260916-a`. Its role is `diagnostic_harness`, not a new stable release or promotion panel.

The sole changed lever is the Gemma server flag `--reasoning-parser gemma4`:

- **Reference:** the exact current Gemma image, model artifact, command, `gemma4` tool parser, Gemma `precise` policy, Qwen route, scaffolds, and frozen 1.1 tasks and graders.
- **Candidate:** byte-identical reference configuration with only `--reasoning-parser gemma4` added to the Gemma server command.

The trial uses all 21 frozen 1.1 tasks in their published order. The full panel is necessary because the changed server parser is shared by every Gemma call; `TOOL-NOCALL-001` is the paired negative control and the remaining 17 non-target tasks are collateral controls. Task text, graders, strict JSON parser, tool implementations, role map, seed 17, temperatures, top-p values, reasoning settings, per-task token caps, and episode timeouts remain unchanged. No output stripping, JSON extraction, retry, repair prompt, grader relaxation, or historical rescore is allowed.

The primary endpoint is the three native-tool tasks `TOOL-SINGLE-001`, `TOOL-PARALLEL-001`, and `TOOL-DEPENDENT-001`, reported separately. Support requires the fresh reference to reproduce the visible channel prefix and strict failure on each primary task, while the candidate has zero visible channel prefixes, preserves every exact expected tool trace, and passes the unchanged strict grader on all three. `TOOL-NOCALL-001` must remain a strict pass in both arms. If the reference does not reproduce all three primary failures, the primary endpoint is `inconclusive_nonreproduction`. If candidate prefixes disappear but any primary trace or strict grade fails, it is `mixed_not_supported`; if any guard, source, replay, or restoration proof fails, the comparison is invalid or aborted. Every other task remains separately reported as a collateral outcome; there is no omnibus score. Visible `message.content` and any separate `reasoning_content` must be captured independently, and reasoning content is never eligible for grader credit.

Both arms must be fresh prospective executions. To keep startup state comparable while ending in the production configuration, the candidate Gemma service starts first from the registered spec, runs after readiness, then the exact reference service is restored, receives the same readiness and quiescence checks, and runs second. The fixed candidate-to-reference order is operational: it leaves the production resident running at exit. It is also time/order confounded, so one sequential pair can support only protocol-specific parser compatibility, not a general causal or model-quality claim. Qwen stays on the same registered runtime. Nara remains intentionally paused through the bounded lifecycle and is restored at the end. The payoff-study lease and timer remain protected. A new controller, service specs, source bundles, manifests, endpoint bindings, and public registration must be frozen before any call. The plan must bind identical image, environment, mounts, template, model, 32K context, MTP4, readiness, and quiescence identities for both Gemma specs; the only argv delta is `--reasoning-parser gemma4`.

The existing strict resource policy is the floor: 30 GiB preflight MemAvailable, 20 GiB monitored minimum, at most 10 seconds between samples, startup pageout limits of 512 MiB/5 seconds, 2 GiB/60 seconds, and 4 GiB total; serving limits of 32 MiB/5 seconds, 64 MiB/60 seconds, and 128 MiB total; zero candidate-cgroup swap or OOM events; 60 seconds of zero pageout after readiness; one candidate research startup and no evaluation retry; and no guard relaxation. Restoration and emergency recovery remain mandatory and are not a model retry. Any startup/readiness/identity/guard failure aborts the pair and restores the exact original reference container without a quality claim.

The frozen ceiling is 29 model calls and 25,088 output tokens per arm, 58 calls and 50,176 output tokens paired, 1,575 seconds of episode ceilings per arm, and 7,200 seconds for the supervised window. Paid API cost is zero. Calls below the ceiling are expected and must retain exact accounting for all 21 units.

Admission requires both arms complete, replay with zero mismatches, exact source and runtime identities, a complete monitor log, and verified restoration. Success supports only the named server-boundary hypothesis. It does not resolve the two Lambda violations, the Qwen cap exhaustion, or the strategic-regret errors, and it cannot by itself authorize production adoption or claim a model winner.
