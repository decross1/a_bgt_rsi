# Stable benchmark 1.0 resident prompt–grader audit

Recorded 2026-09-16 by `/root/flash_final_validation` after the admitted resident reference run. This is a read-only measurement review. It does not rerun inference, alter a receipt, or rescore release 1.0.0.

## Disposition

The release 1.0.0 lifecycle and receipt chain remain verified. Its 21 task outcomes remain immutable historical commissioning evidence. Four non-credit outcomes came from task-design defects, so the model-capability and system panel rates are not suitable as comparative quality baselines. Five other non-credit outcomes are valid end-to-end operational failures under the declared stack, and one is a valid strategic-regret error. Eleven passes remain valid task-level observations. No overall score is defined or inferred.

Release 1.0.0 should carry a measurement-validity notice and must not be retrospectively rescored. A prospective 1.1.0 release corrects only the four task-design defects: the two evidence oracles and the two code tasks affected by undisclosed sandbox constraints. The strict response parser, tool transport, model policies, and output budgets remain unchanged, so operational failures are not silently rescued.

## Evidence boundary

- Published definition SHA-256: `75de9dc0dc324a4559332f88ae6e5ae861ba0d6f683334d85395d082bbaf04df`
- Resident run SHA-256: `2efa93513ba3ea1eabd416f80206dad634b4b9267b09149e43c8c0a9556bc5e1`
- Verified replay SHA-256: `e3eb8c812770d20b29706875843e570a0189b23681430cb558a43dcdb8d79cd9`
- Admission SHA-256: `697c7f1e018293ccfa8e258f348e3b27e68c5ed56f591756d0d2c50c2e69ac12`
- Private raw-evidence log SHA-256, inspected in place and not copied here: `4dab1d01fb23a09fd4741cbcfeef94afed6099d5d79c42a0dd0b25e5d316beab`
- Frozen task, grader, runner, and sandbox source SHA-256 values: `52f8cfef93afb5c9991bae2fc3abaf2cd7b34d6e857b38f1047fb117b7d3fd86`, `66068fb055b3d9cb0431e037bde29b4b6180dae3b0e74455e06071aba1ef961d`, `81efee388d2fac34fef3da41dfa9fde5b8ed29836a462b444b90e9f174986c39`, and `db611859025f05344af0b6c1ce741d94bb3165355624a09995147189c6210983`

The audit compared every published prompt with its frozen grader, the public run outcome, and bounded private transport metadata. It did not use private completions as new benchmark answers.

## Task-by-task findings

| Task | Observed result | Audit class | Finding |
| --- | --- | --- | --- |
| `SCI-MARKOV-001` | passed | clean task-level pass | Prompt fields, tolerance, derived stationary oracle, and observed JSON agree. |
| `SCI-RCT-001` | passed | clean task-level pass | Prompt fields and exact randomized-rate oracle agree. |
| `EVID-SUPPORT-001` | failed / substantive | task-design defect | The claim includes the 30-day qualifier, which only DOC-B establishes. The 1.0 oracle required DOC-A and DOC-C and rejected the logically sufficient DOC-A/B/C response. |
| `EVID-ABSTAIN-001` | abstained / substantive | task-design defect | DOC-E alone establishes the missing denominator, while the 1.0 oracle required DOC-D/E despite asking for the minimal set. The prompt also showed bracketed labels without saying that citation values had to be bare IDs. |
| `CODE-MERGE-001` | invalid output | task-design defect | The response used ordinary list `.sort()` after copying the input. The visible prompt prohibited imports and extra functions but did not disclose the sandbox method allowlist, which excludes `.sort()`. |
| `CODE-WEIGHTED-MEDIAN-001` | invalid output | task-design defect | The response used `sorted(..., key=lambda ...)`. The visible prompt did not disclose that `Lambda` is banned. |
| `CODE-DRAWDOWN-001` | passed | clean task-level pass | The response satisfied the visible function contract, sandbox contract, mutation check, and all cases. The shared sandbox disclosure is still corrected prospectively. |
| `CODE-WATERFALL-001` | passed | clean task-level pass | The response satisfied the visible function contract, sandbox contract, mutation check, and all cases. The shared sandbox disclosure is still corrected prospectively. |
| `TOOL-SINGLE-001` | invalid output | operational failure | The exact required tool call and grounded final values were produced, but a chat-template channel marker preceded the final JSON. The strict one-object parser correctly rejected the end-to-end completion. |
| `TOOL-PARALLEL-001` | invalid output | operational failure | Both exact tool calls and the grounded final object were produced, but the same channel marker preceded the JSON. This is a declared-stack serialization failure, not an oracle defect. |
| `TOOL-NOCALL-001` | passed | clean task-level pass | No tool was called and the exact grounded object was returned. |
| `TOOL-DEPENDENT-001` | invalid output | operational failure | Both dependent calls, arguments, results, and final values were correct, but the channel marker made the visible completion non-JSON. |
| `GAME-PUBLIC-GOODS-101` | passed | clean task-level pass | Action 0 has zero exact best-response regret under the published mechanism. |
| `GAME-PUBLIC-GOODS-211` | passed | clean task-level pass | Action 0 has zero exact best-response regret under the published mechanism. |
| `GAME-VICKREY-101` | passed | clean task-level pass | Bid 8 has zero exact best-response regret. The grader also permits other zero-regret bids. |
| `GAME-VICKREY-211` | failed / positive regret | strategic-regret error | Bid 8 wins against the known bid 7 at a price above value 5, giving utility -2 versus best utility 0. The prompt and exact regret oracle agree. |
| `GAME-COURNOT-307` | passed | clean task-level pass | Quantity 7 has zero exact best-response regret; quantity 6 is also accepted as an optimum. |
| `GAME-BRIER-401` | passed | clean task-level pass | Report 65 exactly maximizes expected Brier utility for belief 0.65. |
| `SYSTEM-PAYOFF-001` | invalid output | operational failure | The actor selected the correct tool and the trusted tool receipt was exact. The xhigh critic consumed the fixed 1,536-token output allowance, ended for length, and produced no visible final artifact. This is an end-to-end policy/budget result, not a grader defect. |
| `SYSTEM-AUCTION-001` | invalid output | operational failure | The actor returned two JSON objects despite the injected exact three-field actor contract. The tool was therefore not executed. The parser and mission oracle behaved as specified. |
| `SYSTEM-EVIDENCE-001` | passed | clean task-level pass | Actor selection, trusted tool result, and critic artifact all match the mission contract. |

## Counts and claim limits

| Audit class | Tasks | Meaning |
| --- | ---: | --- |
| Clean task-level pass | 11 | Descriptive evidence for the named task only. |
| Task-design defect | 4 | Outcome is preserved but must not support a model-quality failure claim. |
| End-to-end operational failure | 5 | Valid observed failure of the exact frozen model, transport, parser, policy, and scaffold. It is not a weights-only claim. |
| Strategic-regret error | 1 | Valid model action error under the published finite game. |

These counts are an audit partition, not an overall quality score. They do not produce a corrected 1.0 rate, a candidate comparison, or a promotion decision.

## Prospective release requirements

Release 1.1.0 must be published and preregistered before any model call. It keeps the same 21 task families and the 2026-10-14 review boundary while applying these prospective changes:

1. Require DOC-A/B/C for the full randomized, 30-day, higher-rate claim and explicitly define bare citation IDs.
2. Require only DOC-E for the minimal missing-denominator justification and explicitly define bare citation IDs.
3. Disclose the complete unchanged code sandbox contract, including source size, banned syntax, allowed calls and methods, isolation, memory, file-descriptor, deadline, result-size, and non-mutation rules.
4. Run a model-free preflight covering one gold contract for each of all 21 tasks plus valid alternative answers such as unordered citation sets and multiple zero-regret actions.
5. Retain strict JSON parsing, current tool transport, current role policies, and current output-token ceilings. Any separate policy experiment must use a distinct preregistered comparison.
