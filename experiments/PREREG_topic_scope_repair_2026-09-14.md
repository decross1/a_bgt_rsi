# Game-theory topic repair: paired diagnostic

**Status, 2026-09-14:** not executed. The owner chose “Keep game theory;
correct the generated topics.” This freezes a development diagnostic for the
planner/hypothesis prompt correction. It does not broaden R0, launch calls,
schedule work or establish scientific improvement.

## Change and causal comparison

The old planner described every suggestion as already scope-vetted. The old
hypothesis prompt assumed its input was game theory and preferred a specific
topic verbatim. Machine-mined titles satisfy neither assumption.

Compare control prompts from commit
`d4eaeee2813ecf78b2542ed36e6428c928b98bce` against the prompts delivered with this
document. Before calls, record the candidate commit, exact rendered prompt
hashes, input-table hash, model/runtime configuration and grader instructions.
Use the installed Gemma generator for both arms. Keep weights, runtime,
sampling, context, token caps and tool menu fixed; change one prompt at a time.

Two stages separate effects:

1. **Hypothesis generation:** same literal topic, old/new HYPOTHESIZE system
   prompt; temperature 0.7, top-p 0.95, max output 512 tokens, seeds 17 and 29.
   Eight topics × two arms × two seeds = 32 attempts. Preserve raw completion
   and parsed candidates; an unstructured fallback is a protocol failure in
   this diagnostic even if the production worker annotates it as passed.
2. **Planner selection:** same frozen state/tool menu/budget, old/new planner
   prompt, with hypothesis generation excluded. Four states × two arms × two
   seeds = 16 attempts. Freeze the current planner sampling/cap values before
   execution. Validate the existing action schema and budget. Score the selected
   topic; no planned action is dispatched. `run_loop_iteration` accepts only
   `topic`, so do not request an additional explanation field for that action.

Alternate AB/BA by case and reverse task order for the second seed. Retain
timeouts, missing results, parse failures and noops in the declared denominator.
Two seeds are repeatability observations, not independent task replication.

## Frozen development topics

Seven inputs are synthetic; T6 was transcribed from the recurring seed in the
frozen `memory/loop_memory.jsonl` snapshot identified by the
[local starvation audit](../docs/research/weekly-upgrade-2026-09-14/topic_starvation_audit.md):
8,564,469 bytes, SHA-256
`542427d9a73f16dd840b07b21a8eebfccbe41bfa3e11516a312166a43b84b2c6`.
The audit reports one recurring seed but deliberately omits its text. T6 was
separately verified against that pinned source prefix. No paper body or private
findings are included. These are public development
cases, not a hidden confirmation set. The criteria below are grading anchors,
never part of the generation prompt.

| ID | Literal input topic | Scope anchor |
| --- | --- | --- |
| T1 | In a finite two-player zero-sum game, if both players' average external regret vanishes, do their empirical mixed strategies approach a Nash equilibrium? | Pure theoretical GT is in scope: preserve the assumptions and formally checkable property; do not require an empirical experiment. |
| T2 | Do LLM bidders shade bids differently from the symmetric risk-neutral equilibrium in first-price auctions with independent private values? | In scope: bidders, strategies and equilibrium benchmark matter. |
| T3 | How does allowing delegation cycles in liquid democracy change the concentration of voting power under heterogeneous voter preferences? | D-075 in scope: do not reject collective-choice questions merely for lacking a named classical game. |
| T4 | Can strategic participation decisions bias preference representation in a sortition-selected citizens' assembly? | D-075 in scope: participation and preference aggregation are the mechanism. |
| T5 | Compressing federated model updates increases training throughput on bandwidth-limited devices. | Engineering claim: do not preserve as a GT finding or launder with game terms. A new actual game question is distinguishable from this claim. |
| T6 | Test-Time Collaborative Classification over Multi-Agent Networks | Observed failing seed: classification/consensus accuracy alone is not a strategic or collective-choice mechanism. |
| T7 | Rewarding Raft replicas for cooperative message batching improves consensus throughput at equilibrium. | Vocabulary camouflage: throughput of a fixed distributed protocol alone is outside scope. |
| T8 | In federated learning with private contribution costs, does a posted-payment mechanism make truthful participation a best response compared with equal payments? | Legitimate incentive question within an ML setting; do not ban every ML-related topic. |

For an off-domain input, the candidate may formulate a genuinely new game or
collective-choice hypothesis. Count it as useful only if its participants,
actions/votes, incentive or aggregation mechanism, comparison and observable
outcome or formally checkable property are substantive. Record `grounded_transfer`
(a defensible relation to the seed), `scope_safe_reset` (an explicit fresh start)
and `unrelated_redirect` separately. Only grounded transfer supports a claim
that paper-gap sourcing contributed value; the other two do not count as useful
repairs for the screening decision. Count any invented attribution to an input paper as
an error. Repeating the same generic Prisoner's Dilemma hypothesis for every
input is scope compliance without useful diversity; report it separately.

## Frozen planner states

Build minimal states using existing menu/schema fixtures, with no in-flight
run and equal nonzero ideation budget. Freeze their full JSON and hashes before
calls; do not read the live idea ledger or paper store during this test.

| ID | Suggestions, in order | Required behavior |
| --- | --- | --- |
| P1 | T5 as `agenda`, T1 as `finding_followup`, T6 as `arxiv_pick` | Prefer the in-scope human follow-up over the unvetted off-domain agenda title. |
| P2 | T3 as `agenda`, T2 as `finding_followup`, T6 as `arxiv_pick` | Preserve agenda preference within scope; do not drop the D-075 extension. |
| P3 | T7 as `coordinator_propose`, T6 as `arxiv_pick` | If selecting a seed, copy it exactly for provenance. Score schema/provenance here; Stage 1 scores whether generated hypotheses make a useful in-domain transfer. A raw title selection alone is not a scope success. Record another action or noop separately. |
| P4 | T8 as `agenda`, T5 as `coordinator_propose` | Preserve a real incentive question even though its application is federated learning. |

Classify a noop separately from a useful in-scope research selection. A system
that rejects everything has not solved topic generation. The planner keeps a
chosen seed verbatim, including adjacent seeds: the hypothesis worker performs
the scientific reframing, while exact-copy source/consumption receipts retain
the original input. Merely selecting an adjacent title does not certify it as
an in-domain hypothesis. New hypotheses must not be attributed to a paper/human
suggestion; the downstream gate judges them under its existing rules.

## Independent grading and unchanged R0

Blind arm labels for semantic review. Review all candidates, with the chosen
hypothesis as the primary outcome. Record separate judgments of domain,
mechanistic testability, fidelity to in-scope inputs, unsupported attribution
and duplicate/generic output. Freeze annotations before revealing the arm.
Do not use a substring/keyword count as the semantic grader. Human review or
separate subscription sessions may provide annotations; the proposing model
must not be the sole judge. Disagreements stay unresolved until adjudicated.

Optionally replay the unchanged primary topicality prompt on the 32 chosen
outputs (one per attempt; no call for a missing output). Record literal
`on`/`off`/`unsure`/error separately from independent annotations. Missing,
unsure or failed judgments are not in-domain successes. Do not enable/demote
R0, change corpus anchors or rewrite live findings to increase eligibility.

Report exact counts by case/arm/seed, all-candidate scope, chosen-hypothesis
scope, substantive mechanism, repeated/generic outputs, valid/useful planner
selections, noops, parse failures, unsupported attribution and total elapsed
time including failures. Report R0 disagreement; an increased pass rate alone
is not scientific improvement or evidence of a more accurate gate.

## Resource reservation and decision

Reserve **at most 40 Spark GPU-minutes** from the shared 120-minute weekly
upgrade allowance: 32 generation calls × 30 seconds = 16 minutes;
16 planner calls × 30 seconds = 8 minutes; at most 32 primary-topicality calls
× 15 seconds = 8 minutes; 8 minutes for GPU-using preflight/recovery and
remaining overhead. These are hard design maxima, not observed latency.
Subscription/CPU-only annotation consumes no Spark time and has no paid fallback.

All calls are serial, outside production ledgers, under a whole-request
deadline with SDK retries disabled. Use a dedicated harness that calls the
frozen rendered prompts through `wrapper.call_sync` with explicit `seed`,
`request_timeout_s` and `log_path` inside the isolated artifact directory.
Do not assume the production `hypothesize()`, `plan()` or `topicality.check()`
entry points enforce these caps: they lack those seed/deadline controls, the
planner can discard malformed raw output, and `topicality.check()` can add a
Qwen skeptic call. Replay only the frozen primary topicality prompt directly;
do not invoke that secondary path. Save every raw response before parsing.
No coordinator action, retrieval pipeline
or new runtime is executed. The registered dispatcher now records
queue/memory/production-idle checks inside a shared canonical reservation and
holds the cooperative execution, coordinator and GPU leases. Its registered
form includes the primary R0 replay: 80 declared attempts, a fixed 2,370-second
evaluator payload and a 2,400-second total reservation including supervision.
Require the existing 30 GiB memory floor and unchanged serving identity.
Defer if contention, remaining balance or week-boundary timing prevents the
complete reservation. Charge failed/uncertain work; preserve partial results.
An active or fully charged 40-minute reservation cannot coexist with the
112.5-minute Qwen pilot. After a trusted terminal receipt releases unused time,
that pilot can start only if at least 6,750 seconds remain in the shared week;
all prior charges combined must be at most 450 seconds. This experiment takes
priority over that pilot.

**EVALUATE-LARGER** only if the candidate has more useful grounded in-scope
outputs than control across the six T5–T7 attempts, and no fewer valid in-scope
outputs across the ten T1–T4/T8 attempts. Require no increase in unsupported
attribution or protocol failures, and no decrease in correct P1/P2/P4 topic
selections or exact-copy provenance across all planner cases. These are tiny
development counts, not significance or promotion thresholds. Report
generic-output and time tradeoffs independently; do not conceal them in one
score. **NO-MATERIAL-SIGNAL** if the improvement is only more noops, vocabulary
changes or R0 pass rate. **INVALID/INCOMPLETE** for drift, missing work or
unresolved grading. All labels are diagnostic; none proves production benefit.

The dedicated topic harness and
[frozen manifest](topic_scope_repair_2026-09-14.json) now include fully rendered
planner states/menu, paired raw artifacts, source/policy fingerprints and a
blind-only grading package. Contract, recovery and artifact-tamper tests pass.
Actual calls and independent semantic annotations remain unperformed. Follow
the [execution runbook](../docs/weekly_upgrade_implementation.md#evaluation);
unit tests and protocol completion establish no scientific improvement.
