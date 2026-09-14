# LOOP_V2 — campaign-centered research and measured improvement

> **V2 foundation and operating plan.** Existing resident serving and research
> gates are retained. Campaign activation is recorded separately from this
> immutable source declaration; §10 defines the required deployment evidence.
> Starting a controlled model-game study has its own additional gates.

## 1. Objective

V2 should make one complete unit of research legible and measurable:

> A bounded game-theory question becomes a traceable set of topic attempts,
> iterations, evidence tests, adversarial dispositions, findings, and explicit
> human verdicts, while a separate evaluation loop measures whether changes to
> the apparatus improve correct work per unit time.

The goal is not a larger volume of generated hypotheses. The goal is more
verified scientific and coding work with fewer ambiguous links, retries, and
human recovery steps.

## 2. Research scope

The domain stays:

- game theory;
- behavioral game theory;
- learning in games;
- strategic behavior and mechanism design among model agents.

The working program question is:

> How do incentives and access to information affect cooperation, delegation,
> and strategic behavior among agents?

This program frame now has one prepared calibration campaign. It is not a
novelty claim or a completed model experiment.

### Selected first calibration

Campaign `v2-agentic-game-theory-20260914` asks:

> How do individual versus shared payoff objectives and access to
> player-identified interaction history affect cooperation and
> utility-consistent behavior in repeated public-goods games among LLM agents?

The prepared design varies own-payoff versus joint-payoff objectives and
own-outcome versus public player-identified history. Four players choose to
retain or contribute five units; the public pool doubles and is divided equally.
The CPU calibration enumerated all 16 stage profiles and 64 unilateral
comparisons for each utility definition, then recorded 81 scripted-policy
assignments under four objective/observation invariance conditions: 324
eight-round simulations. These are not 324 independent behavior samples. The
calibration made zero model calls.

The CPU result verifies payoff, regret, and harness invariants. It does not test
whether a model responds to an objective instruction and is not a benchmark win
or scientific finding. Own payoff plus own contribution already reveals total
aggregate contribution, so the observation treatment mainly adds player
identity and history. After independent subscription review, the first model
study was narrowed to one LLM seat against three known scripted opponents. It
varies the declared utility objective while making aggregate history, the fixed
horizon, and opponent policies explicit. Player-identity/history manipulation
is deferred; this first study addresses only the incentive slice of the broad
campaign question.

This is a calibration. The literature screen in
[`docs/v2/research/EXTERNAL_CONTEXT.md`](docs/v2/research/EXTERNAL_CONTEXT.md)
shows that incentives, communication, horizon, and framing are established
research directions. Novelty must be tested after the exact design is fixed.
The agents are model systems, not human subjects; their behavior cannot be
reported as human behavior.

The exact manifest and preregistration are
[`experiments/agentic_game_theory_v2_calibration_2026-09-14.json`](experiments/agentic_game_theory_v2_calibration_2026-09-14.json)
and
[`experiments/PREREG_agentic_game_theory_v2_calibration_2026-09-14.md`](experiments/PREREG_agentic_game_theory_v2_calibration_2026-09-14.md).
Before any model trial, complete the recorded literature/novelty, frozen
configuration, budget, counterbalancing, strict-action, paired-analysis, and
information-leakage gates.

## 3. V2 unit of work

V2 introduces a campaign-level view over existing records:

```text
Campaign
  -> ResearchQuestion
  -> TopicAttempt(s)
  -> ResearchIteration(s)
  -> EvidenceAssessment(s)
  -> PromotionReview(s)
  -> Finding(s)
  -> HumanVerdict(s)
```

A parallel maintenance graph remains separate:

```text
EvaluationCampaign
  -> ChangeHypothesis
  -> Configuration
  -> Trial(s)
  -> EvaluationResult
  -> PromotionDecision
```

The graphs may share source commits, model identities, and run hashes. They do
not share semantic verdicts. An apparatus upgrade cannot turn a weak scientific
claim into a valid one, and a scientific result cannot authorize its own runtime
change.

## 4. Research lifecycle

### Phase 0 — select and preregister

Record:

- the exact research question and domain rationale;
- hypotheses and disconfirming outcomes;
- treatments, controls, units, outcomes, and analysis plan;
- model checkpoint, runtime, inference profile, prompts, tools, and context;
- seed/repeat policy and stopping rules;
- literature packet identity and known overlap;
- resource budget and abort conditions.

No model-generated prose can silently modify the preregistration after outcomes
are visible.

### Phase 1 — attempt and dispatch

Every attempt receives a stable ID before dispatch. Record accepted, returned,
timeout, error, refused, and not-run-budget states separately. A dispatch
completion must bind to an iteration through an exact ID and request digest.
Substring similarity is not lineage.

### Phase 2 — build an iteration record

The bounded local chain forms a hypothesis, retrieves evidence, checks scope and
novelty, critiques the claim, and writes an iteration record. Every model call
records the resolved inference policy and terminal state. Missing downstream
records remain missing.

### Phase 3 — earn evidence

Use the existing cumulative ladder:

- L0: assertion;
- L1: literature-consistent, relevant, novel, and critique-surviving;
- L2: valid synthetic experiment;
- L3: replication or cross-tier evidence;
- L4: automatic adversarial qualification;
- L5: explicit human `valid` verdict.

The next test owed is part of the state. A rejection is retained with its reason
and reopening condition. A refinement loop is bounded and may not relabel a
failed prerequisite as passed.

### Phase 4 — human judgment

L4 findings enter the human review queue. The human may validate, reject,
request revision, or leave the item unresolved. Only the explicit valid outcome
earns L5. Publication is a later, separately governed decision.

### Phase 5 — learn from the campaign

At campaign close, record:

- funnel counts and coverage;
- scientific outcomes and negative results;
- reliability, wall time, model calls, and human interventions;
- linkage or instrumentation failures;
- which conclusions are causal, descriptive, or unresolved;
- follow-up tests and exact reopening conditions.

The report must preserve raw-source hashes and distinguish observation time from
projection generation time.

## 5. Measurement

V2 tracks a vector instead of one overall score:

```text
research question completion
scientific rubric credit
coding task completion
transport and tool reliability
scope and lineage coverage
repeatability / RSR_2of3
correct task throughput
wall-clock to correct result
local compute and frontier-session use
memory peak
human interventions
```

### Research-pipeline progression

For one explicit cohort and time window, report:

1. topic attempts;
2. completed dispatches and dispatch failures;
3. exact linked iteration records;
4. explicit in-scope assessments;
5. L1+ evidence;
6. promotion skeptic reviews;
7. L4 automatic validations;
8. L5 human validations.

Also report ambiguous links, unlinked records, missing records, rejections, and
coverage denominators. Zero after a verified available source is different from
an unavailable source. A current partial week is not a completed trend.

The first post-fix cohort starts from the validated Nara activation receipt at
`2026-09-14T16:17:51.902964Z`. At the v2 preparation snapshot, no fresh research
dispatch had yet been observed after that cutoff. The correct status is
`not_yet_observed`, not success or failure.

### Apparatus progression

The weekly benchmark portfolio separates:

- transport completion;
- recorded evaluation;
- objective task success;
- uncertainty with its named metric and denominator;
- comparison eligibility under an identical cohort fingerprint;
- budget charges versus measured runtime.

One measured week establishes a baseline. It does not establish an upgrade or a
trend.

## 6. Weekly improvement loop

The Sunday process remains review-only by default:

```text
snapshot
 -> independent OpenAI and Claude analyses
 -> adversarial cross-review
 -> one structured change hypothesis
 -> preregistered local trial, only when explicitly allowlisted
 -> objective and reliability evaluation
 -> recorded decision
```

Limits:

- subscription frontier sessions only;
- at most two frontier calls per weekly review;
- no more than 120 Spark minutes charged to the weekly ledger;
- one production-affecting hypothesis at a time where practical;
- no automatic promotion;
- no model, runtime, policy, or scaffold gain claimed when another surface
  changed without a causal design.

Most weekly reviews should record `NO_CHANGE`. Review-only execution does not
rerun benchmarks automatically.

## 7. V2 data rules

1. Append-only source records remain immutable.
2. Every new public record carries a schema version.
3. IDs and cryptographic digests establish lineage.
4. Campaign membership requires one exact registered campaign link. Timestamp
   or topic-text similarity never relabels legacy work as campaign progress.
5. Projections expose source availability, bounded read coverage, malformed-row
   counts, and raw-source hashes without exposing private payloads.
6. Duplicate or ambiguous IDs are withheld from successful conversion counts.
7. Human validation is read only from explicit human feedback.
8. Historical evidence is retained with its original score and configuration.
9. A new fixture, grader, cohort, or denominator starts a new comparable series.
10. Source `recorded_at`, activation/cutoff time, and projection `generated_at`
   remain distinct.
11. Storage migration is additive and reversible until every writer and reader
    has passed compatibility checks.

## 8. Product flow

The intended operator journey is:

1. **Now:** see health, alerts, active work, and whether intervention is needed.
2. **Research:** inspect the evidence ladder and the next test owed.
3. **Record library:** read the complete provenance for a chosen record.
4. **Evaluations:** inspect experiment execution and objective outcomes.
5. **Benchmark progress:** see week-to-week apparatus results and the current
   research funnel without turning missing observations into scores.
6. **Operations / Calls / Trace history:** diagnose transport, policy, worker,
   or linkage failures.
7. **Human action:** use only the explicit verdict or bounded action seams and
   verify the resulting append-only receipt.

V2 should add campaign navigation across these views before adding more top-level
pages.

## 9. Preparation sequence

1. Preserve and verify v0/v1 research and documentation.
2. Establish the dated deployed-state architecture and coherent front doors.
3. Complete end-to-end research-pipeline and weekly benchmark projections.
4. Run the bounded inference-policy, diversity, role-effort, context, and
   historical-repair evaluations already preregistered.
5. Reconcile prompt and document-authority pointers.
6. Bind the fresh campaign to the runtime with a reversible activation receipt.
7. Execute a bounded fresh-topic canary through the full observable path.
8. Adversarially review data lineage, scientific claims, UX language, and
   operational rollback.
9. Adopt through reviewed Git history, then verify the live services and write a
   deployment receipt.

No preparation step authorizes a model replacement, runtime cutover, automatic
research promotion, paid API call, live trade, or scientific publication.

## 10. Foundation activation and study execution

Foundation adoption requires these inspectable artifacts:

- a reviewed campaign declaration with exact question/topic hashes and additive
  cycle, iteration, and finding contracts;
- verified archive provenance and unchanged historical evidence;
- passing compatibility, benchmark, API and frontend checks, with a local
  desktop/mobile smoke and no unresolved adversarial release blocker;
- an activation pointer binding the exact campaign manifest for both daemon and
  cron, plus a deployment receipt identifying code, services and rollback;
- a research funnel that distinguishes missing, ambiguous, rejected, surfaced,
  and human-validated states without importing old-campaign successes.

The canonical `run_state/v2_preparation/deployment_receipt.json` records adoption.
`run_state/active_research_campaign.json` selects the current runtime campaign;
removing an operator-created pointer returns to the legacy/global cohort.
A separately bound closure receipt ends a campaign without editing its manifest.
Never remove a human pause as part of rollback. A fresh linked topic attempt
must retain its exact dispatch/outcome lineage; before an eligible attempt runs,
the panel must say that execution is not yet observed and show any budget gate.

The controlled model-game study is the next research phase, not a prerequisite
for activating this foundation. It still requires a separately frozen execution
manifest with model/policy identity, tasks, controls, outcomes, repeats, budget,
abort conditions, counterbalancing, analysis, and literature/novelty evidence.
Adding a future study must use an additive registration receipt bound to the
campaign, or a new declared campaign revision; never edit an activated manifest.

CPU controls already verify 324 deterministic condition records and twelve
known-opponent optimal-response cells with zero model calls. These establish
measurement mechanics only. The current campaign registers CPU calibration;
its controlled model study remains `not_registered`. L4 and human L5 outcomes
remain later research evidence, not acceptance tests that engineering can invent.

## 11. Historical boundary

[`LOOP_V0.md`](LOOP_V0.md) and [`LOOP_V1.md`](LOOP_V1.md) are preserved as
build records. Their pre-v2 state is available from Git reference `3c443e6` and
the verified archive in
[`docs/v2/RESEARCH_ARCHIVE.md`](docs/v2/RESEARCH_ARCHIVE.md). V2 may reuse prior
literature and failure knowledge with provenance, but it does not count prior
findings as new-campaign successes.
