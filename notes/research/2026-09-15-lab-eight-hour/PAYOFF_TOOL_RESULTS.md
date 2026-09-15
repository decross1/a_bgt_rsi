# Native payoff-calculator diagnostic — closed without execution

**Status: closed unissued; zero model calls and no quality result.** The final preflight was refused because the ordinary coordinator still held its resource lock. Its active research receipt had cleared by 23:24:42 UTC, but the coordinator was only observed absent after the 23:25 launch cutoff. No supervisor reservation, resident mutation, calculator invocation, evaluation directory, or completed-window admission exists. The [bound non-execution receipt](payoff-tool-not-issued.json) preserves this disposition; a later run needs a new window and decision. The [preregistration](../../../experiments/payoff_tool_arithmetic/PREREGISTRATION.md) declares six paired inputs, twelve direct/tool conditions, and eighteen scheduled model-call slots. An invalid or missing parsed tool call causally skips that condition's final slot; the skipped slot stays in the denominator. This tests native function invocation and payoff arithmetic, not game strategy, new theory, trading ability, or a model replacement.

The three action tuples are exact-input fresh relative to payoff-representation panels A and B and the earlier known-opponent pilot's comprehension tuple. Panel B is registered for later execution; no B result is used here. They retain the same four-seat binary public-goods mechanism, so freshness does not make them independent task families or a held-out generalization sample. Panel A/B use endowment 5 and multiplier 2; this panel varies both. Seats 0 and 1 are paired for every tuple.

| Game | E | m | Actions in seat order | Shared return | Focal seat 0 | Focal seat 1 | Total |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| G1 | 3 | 3/2 | 0,1,0,0 | 9/8 | 33/8 | 9/8 | 27/2 |
| G2 | 7 | 5/2 | 1,0,0,1 | 35/4 | 35/4 | 63/4 | 49 |
| G3 | 11 | 7/3 | 1,0,1,1 | 77/4 | 77/4 | 121/4 | 88 |

I independently recomputed each focal payoff and total with calibration.payoffs and checked all six runner fixture rows. Each action tuple differs from A's (1,0,0,0), (0,1,0,1), (0,1,1,1), B's (0,0,0,1), (1,1,0,0), (1,1,1,0), and the pilot arithmetic tuple (1,0,1,0). Prelaunch source hashes at this audit: runner c71ab99f143f8716708c2d879a0f86fa3e9be536f28e6522fd2bb7c149601956, calibration 88182c3475181cb2d2ccdde7e4377283ff85b9108076d67f98609db34a3a88ae, preregistration 6fcd8eb8b275c79fd3e35e0a53c5ee5b8c2faeeeb732f43d89063caba0834aeb. The published [plan](payoff-tool-plan.public.json) has SHA-256 `45a29a0f04f700b5a0c62bbe531b2a0d595f555026270237666059f493878d84`; the [window](payoff-tool-window.public.json) has SHA-256 `e49b3f4d0872bb03f6ec35efcceab9f5b4ed784cd05608ab15f36336996d5e58`. PR #52 was created at 23:11:06 UTC, before the final preflight. The non-execution receipt SHA-256 is `95341e159bdb32c82acc3b8165e8c7025ea22391ba26a5383209cecffbaf2259`. There is no completed-window receipt or admitted arithmetic score.

| Paired input | Direct condition | Native tool-first | Tool-final slot | Strict final shape / focal / total / both |
| --- | --- | --- | --- | --- |
| G1 seat 0 | unissued | unissued | unissued | no result |
| G1 seat 1 | unissued | unissued | unissued | no result |
| G2 seat 0 | unissued | unissued | unissued | no result |
| G2 seat 1 | unissued | unissued | unissued | no result |
| G3 seat 0 | unissued | unissued | unissued | no result |
| G3 seat 1 | unissued | unissued | unissued | no result |

A later, separately issued run should report the exact admitted plan/window/result hashes, clean restoration and raw-SSE/grade-replay proofs before numeric counts. Keep eighteen scheduled slots visible, with issued, returned, timeout/error, causally skipped, and unissued counts separately. For the native tool-first calls, distinguish parsed function invocation, argument shape, exact argument correctness, and calculator execution. For each final answer, report strict bare-JSON shape, exact rational focal payoff, exact rational total payoff, and both correct; wrong-but-well-formed answers count separately from malformed output. Direct and tool outcomes should be compared by paired input, without calling the repeated six inputs twelve independent games.

A parser miss or wrong tool argument prevents the calculator from being executed and supplies no treated final-answer grade. A correct shared-return tool value followed by a wrong focal or total answer would show a remaining decomposition error. No outcome in this diagnostic alone changes the production-model or scientific-gate decision.

The implementation passed 18 focused runner/controller tests, a full core suite of 3,570 passed and five skipped, and Ruff. Independent source review checked the native-call requirement, exact emitted arguments, preserved first-turn content, six-per-arm denominators, conditional final-slot skips, fixed seeds/policy/timeout, and raw SSE replay. These are implementation checks, not observations of model performance.
