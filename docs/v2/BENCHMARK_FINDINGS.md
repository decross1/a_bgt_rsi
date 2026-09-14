# V2 preparation: measured benchmark findings

**Measured 2026-09-14. Verdict: retain the production model/runtime/policy configuration.** These development panels expose concrete workflow failures; they do not establish a model upgrade. All scheduled task denominators include failures. Human scientific validation is separate.

## Fresh structured output and diversity

The versioned scaffold defines exact JSON keys, a lowest-valid-index selector, proposal-specific search directives, and separate protocol versus substantive diagnoses. It does not silently strip fences or salvage malformed JSON. It does not enable server-enforced structured decoding.

| Arm | Returned calls | Protocol-valid calls | Successful tasks | Valid proposals | Distinct valid proposals, summed within tasks |
| --- | --- | --- | --- | --- | --- |
| One deterministic generation | 5/5 | 4/5 | 1/5 | 3 | 1 |
| Three diverse generations plus selector | 20/20 | 15/20 | 0/5 | 8 | 6 |

The trial charged 21.44 seconds including supervision. More diverse valid proposals did not produce more selected correct answers. Recorded diagnoses include five malformed JSON responses, one field-schema failure, sixteen substantive proposal failures, and three substantive selection failures. Those categories operate at different levels and must not be added as a task-failure denominator.

This is a new five-task panel, not a repeat of the older diversity fixture set. Its scores cannot be plotted as a longitudinal improvement against the earlier task set. The highest-value next work is selector and proposal correctness under a reliable response contract, followed by independent fresh-task confirmation.

Trial: `2026-W38-0cf6b1e426f1572df3f2b743`. Manifest: [diversity v1](../../experiments/diversity_selection_v1_2026-09-14.json). Raw run SHA-256: `dedc8f98b54c0bc4086be83a47d0a4ca6b19c1457676eca37d6b8fac410d891d`.

## Qwen reasoning effort by role

Same resident Qwen model, six tasks per arm, one seed, rotated arm order. Each task-arm has a cumulative 4,096-token/90-second budget. Adaptive criticism starts at xhigh; extraction/tool-selection starts at medium and can use its remaining budget for one xhigh retry after a public protocol/uncertainty signal. Hidden expected answers never route retries.

| Arm | Critic | Evidence | Tool selection/arguments | Total | Task wall time, including failures | Actual calls |
| --- | --- | --- | --- | --- | --- | --- |
| xhigh | 2/2 | 2/2 | 1/2 | 5/6 | 166.94 s | 6 |
| medium | 2/2 | 0/2 | 0/2 | 2/6 | 189.61 s | 6 |
| adaptive | 2/2 | 1/2 | 2/2 | 5/6 | 222.72 s | 9 |

The adaptive arm made three escalations, all after schema failures; none of the responses supplied `needs_review=true`. One adaptive task ended in timeout. The controller therefore correctly records the overall execution as incomplete/failed, despite retaining all eighteen task outcomes and useful partial measurements. Charged runtime was 580.20 seconds.

Medium was neither faster nor more successful on this panel. Adaptive recovered some protocol failures but did not improve total success over xhigh and consumed more time. This contradicts any blanket inference that lower reasoning effort reduces task latency. It does not establish xhigh superiority on all roles: there are only two tasks per role, one seed, and no independent confirmation set. No global policy change follows from this result.

Trial: `2026-W38-c21302f88972a71141ca3b2d`. Manifest: [role effort v1](../../experiments/weekly_role_effort_v1_2026-09-14.json). Raw run SHA-256: `2c50326c581f08c745fca44fe4a2c9b387fe02e1537a673a69b6ad8c041cde79`.

## Actual historical coding attempts

The six public historical tasks now receive model-generated repair attempts against their exact base files. The sandbox has verified base-fail/fixed-pass controls and requires structured pytest execution receipts; a printed success summary or early exit does not earn credit. Fix-side code and graders are excluded from the model request. These remain public-history tasks, not contamination-resistant hidden benchmarks.

The resident Gemma `coding_precise` experimental profile returned six attempts in 63.49 charged seconds. **Zero patches were applicable, so no generated repair reached the correctness grader.** Five attempts failed the strict JSON envelope; one failed the diff-path/header contract. The measured result is 0/6 completed repair workflows. It is not evidence that all six underlying code solutions were semantically wrong.

This identifies serialization and edit delivery as a bottleneck. The separately preregistered plain-diff follow-up kept the model, tasks, graders, sandbox and budgets fixed. Original failed attempts remain immutable.

Trial: `2026-W38-30cfdabdf87d7feff55f6086`. Manifest: [historical panel v2](../../experiments/weekly_historical_coding_panel_v2_2026-09-14.json). Raw run SHA-256: `8448f9d8edb0972a449e7fd386017a38e99b8d61c01848588923fab01ebb71c1`.

### Plain-diff response-contract follow-up

The follow-up returned all six attempts in **40.37 charged seconds**, with **0/6 valid patches and 0/6 graded repairs**. All completions began with the expected diff header but omitted the required final LF. A post-run diagnostic that appends only LF passes the raw grammar for four responses; the remaining two also fail hunk grammar. That diagnostic does not rescore the frozen run, run graders, or earn repair credit.

The model followed the broad raw-diff instruction, but the exact delivery contract still failed. This is a reason to evaluate a purpose-built editing/tool interface with an explicitly declared normalization contract on fresh tasks. It is not a reason to weaken historical scores or claim the underlying code changes were correct. No additional live follow-up is scheduled by this change.

Trial: `2026-W38-ff6e3c57698694ed9e80838a`. Manifest: [raw patch wire v1](../../experiments/weekly_historical_coding_patch_wire_v1_2026-09-14.json). Raw run SHA-256: `1faea55c4fd145fbda803a32645a525e8a823605551d086259c5c6059f55aa81`.

## Research pipeline and the fresh campaign

The projection now measures dispatch, completed iterations, retrieval/criticism, evidence levels, promotion, and human validation using exact identifiers and explicit source availability. A planned action is not an executed iteration; missing or truncated sources cannot establish a zero.

The stale-topic fix was activated at `2026-09-14T16:17:51.902964Z`. In the initial audited post-activation window, ten coordinator cycles contained no research iteration dispatch. Budget gating dominated. That observation is **not yet observed**, not proof that the corrected topic pipeline succeeds or fails. The new campaign has a separate activation/identity contract so these older events cannot be relabeled as fresh v2 research.

The selected initial question concerns incentives, player-identified interaction history, cooperation and utility-consistent behavior in repeated public-goods games. The [CPU calibration](../../experiments/PREREG_agentic_game_theory_v2_calibration_2026-09-14.md) verified 324 deterministic condition records (81 scripted assignments × four objective/visibility conditions) and exact stage-game equilibria with zero model calls. Own payoff already reveals aggregate contributions; the visible-history manipulation adds player identities. These records are deterministic checks, not 324 independent observations. This is a validated measurement control, not an LLM capability result or a novel scientific finding.

Claude’s completed independent review identified a stronger first model phase: one model agent against three known scripted opponents, with objective-only treatment and a finite-horizon optimal-response oracle. The [supplemental controls](../../experiments/PREREG_agentic_game_theory_v2_best_response_controls_2026-09-14.md) separate repeated-game utility regret from cooperation: a selfish best response to known grim-trigger opponents cooperates for seven rounds and defects in the eighth. Exhaustive short-horizon checks validate the dynamic-programming oracle. No controlled model-game study has been run or registered for execution; the identity-history factor is deferred until this apparatus is established.

## Reading these results over time

The live [benchmark page](http://spark-7eeb:5173/benchmarks) binds each operator summary to its immutable trial/result/artifact hashes. The new recorder replays those receipts before writing an annotation. It distinguishes planned task attempts from extra adaptive calls, and repair-task success from internal pytest case counts. One-arm historical and three-arm effort panels remain descriptive instead of inventing a two-arm upgrade trend.

Longitudinal comparison requires unchanged fixture, grader, budget, model, policy, scaffold and denominator identities. Changed panels get distinct series. Maintain an untouched confirmation panel and repeated stochastic runs before promoting a policy. The four trials above charged 705.49 seconds in total; production model weights, serving runtime and default role policy were unchanged.

Three initial operator annotations used the wrong JSON encoding for the result checksum. The recorder was corrected, the original annotations were preserved in an explicit correction journal, and new annotations bind the actual durable result bytes. Raw trial and evaluation files were unchanged.
