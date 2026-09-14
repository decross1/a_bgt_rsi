# V2 adversarial review and design decisions

The implementation used three parallel engineering/design reviewers under one integrator, followed by cross-review of data lineage, resource accounting, grading and source preservation. A separate Claude subscription session reviewed a narrowed research-design packet. This was a design critique of supplied facts, not a claim that Claude inspected the repository or independently reproduced the experiments.

## Claude review provenance

The first larger packet timed out at its 300-second bound and produced no usable review. It earns no completed-review credit. A narrowed retry completed through the existing subscription-only maintenance adapter, with tools/hooks/MCP disabled. The receipt reports Claude Code `2.1.270`, subscription authentication, `mock=false`, exit code zero, and model IDs `claude-opus-5` plus `claude-haiku-4-5-20251001`. The receipt hash is `45bfe178cfb1ba9244371a7ed713a3d25cacae5711d13b5e32c895caf11be833`. Private text/transport evidence lives with the v2 preparation artifacts, and calls are recorded in `run_state/v2_preparation/frontier_calls.jsonl`.

## Research-design critique

| Critique | Assessment and resulting change |
| --- | --- |
| Cooperation and stage-dominant-action consistency can be the same information under different labels. | Accepted. The first LLM phase now uses an exact finite-horizon best-response oracle against known scripted opponents. Episode regret and cooperation can differ meaningfully. Stage-game controls remain arithmetic checks only. |
| Own payoff reveals aggregate contribution, but requiring arithmetic in only one arm confounds identity with salience. | Accepted. The first phase supplies aggregate information explicitly and defers the identity factor until a mechanism and matched salience are specified. |
| Four model players × eight rounds makes a broad factorial design expensive and the episode, not each round/player, is the independent sampling unit. | Accepted as a design constraint. Start with one model seat and three committed scripts. Measure actual latency before sizing repeated episodes. Do not infer per-call latency from six-task arm totals. |
| Without payoff comprehension, behavior could reflect misunderstanding of the objective. | Accepted. A matched comprehension check is specified before game play; failures stay visible and in the planned denominator. Neutral scoring-rule labels accompany the actual utility formula. |
| The 324 CPU records overstate experimental breadth if treated as independent behavioral samples. | Accepted. They are 81 policy assignments under four invariance conditions, with repeated/symmetric trajectories. They establish mechanics, not 324 independent discoveries or model samples. |
| Previous-majority needs initial and tie behavior. | Already implemented: cooperate initially, then cooperate when at least two of four agents contributed in the prior round. The source and tests specify this; the narrowed packet omitted that detail. |
| New-campaign promotion waits on L5 human validation. | Corrected. Existing surface eligibility is L4; L5 explicitly records a human `valid` verdict. Neither a model nor this cleanup manufactures that verdict. Human review remains necessary for human validation, not for every lower-rung transition. |
| Leniently salvage historical patch outputs before spending more calls. | Useful only as a separate diagnostic, never a rescoring. The inspected originals contain malformed diff structure as well as JSON/fence problems. The preregistered raw-diff treatment tests the response contract while retaining exact original results and grading rules. |

The [known-opponent control protocol](../../../experiments/PREREG_agentic_game_theory_v2_best_response_controls_2026-09-14.md) records the revised first phase. Against three grim-trigger bots, the individual-utility optimum is to cooperate for seven rounds and defect in the last round. The CPU oracle is checked against exhaustive four-round action sequences and verifies twelve eight-round control cells. A second engineering reviewer independently enumerated horizons one through eight, all three opponent mixes, both utility definitions and all four focal seats. Oracle values, realized utilities and regret telescoping matched. Review also separated `focal_cooperation_rate` from `group_cooperation_rate` in the versioned control output: a cooperative focal player facing three retainers yields rates 1.0 and 0.25 respectively. This is not an equilibrium claim about four unrestricted LLM agents.

## Engineering findings fixed before delivery

- The historical grader originally needed stronger evidence than stdout and an exit code. It now requires pytest execution-hook receipts, preserves time/output/guard failures, and rejects spoofed summaries and early exits.
- Adaptive reasoning routing uses public schema/uncertainty signals and cumulative token/time limits. Hidden expected answers cannot trigger escalation. Earlier-step failures and retry parentage remain in the trace.
- Trial process recovery now uses the same module registry as execution, including the new effort and historical runners. Real harmless-process tests verify exact module/output-path matching.
- The progress recorder binds the exact bounded bytes it parses to replayed artifact hashes. A race-after-validation regression proves changed evidence cannot be published under an earlier hash. Planned attempts, actual calls and internal grader cases remain distinct denominators.
- Weekly and UI readers accept the new trial kinds only through exact plan bindings; receipt hashes use the actual durable JSON encoding. Three initial annotations were corrected with preserved superseded copies, while raw trial evidence stayed unchanged. Opened-file bounded reads prevent file growth from defeating API memory bounds.
- Archive verification rejects extra files as well as changed/missing files, enforces bounds during copy, and accurately describes filename-based credential exclusions without claiming a secret scan.
- Pipeline review found that truncated or malformed source windows, invalid cycle identities, and missing health evidence could overstate completeness. Those conditions now withhold dependent counts or mark evidence unavailable; they cannot silently produce a zero or an unqualified success.
- Dead-code retirement required active caller, registry, scheduler, test and deployment checks. Fourteen obsolete files were preserved byte-for-byte as non-executable history. Manual experiment entrypoints were retained when they still had a valid role.

## Remaining interpretation limits

Small development panels are useful failure localization. They are not confirmation studies, and an output-contract change is a scaffold change. Public historical coding tasks are not contamination-resistant. None of the new results promotes a model, runtime, global inference policy or scientific claim. Legacy records are not backfilled into the fresh campaign by timestamps or topic similarity. Shared literature and explicitly relevant negative knowledge remain usable with provenance.
