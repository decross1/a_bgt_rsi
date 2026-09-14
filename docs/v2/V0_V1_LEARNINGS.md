# V0/v1 learnings carried into v2

**Prepared:** 2026-09-14
**Evidence boundary:** repository code, immutable manifests, machine-written run
artifacts, and recorded experiment summaries. This document does not interpret
researcher prose under `human/`. It labels direct observations separately from
engineering interpretations.

## What the evidence establishes

### 1. A parse or serving failure is not a scientific judgment

**Observed facts.** Two Qwen3.8 stage-3a critic runs on 2026-08-15 recorded all
22 fixtures as unparseable. One ended after 54.3 seconds; another consumed
6,855.2 seconds. A 2026-08-16 run reduced the unparseable count to three but
still failed the liveness and kill checks. The 2026-08-17 Qwen3.8 run recorded
zero unparseable fixtures and passed all checks in 3,490.6 seconds.

Evidence:

- `bench/critic_eval/runs/stage3a_qwen3.8-27b-nvfp4-mtp_20260815T063602Z.json`
- `bench/critic_eval/runs/stage3a_qwen3.8-27b-nvfp4-mtp_20260815T083124Z.json`
- `bench/critic_eval/runs/stage3a_qwen3.8-27b-nvfp4-mtp_20260816T203420Z.json`
- `bench/critic_eval/runs/stage3a_qwen3.8-27b-nvfp4-mtp_20260817T093138Z.json`

**Engineering interpretation.** The early failures cannot support a claim that
Qwen3.8 was a weak critic. They primarily establish interface and liveness
failure under those exact configurations. V2 must record transport, protocol,
schema, substantive grader, timeout, and budget failures separately.

### 2. Small matched panels support bounded comparisons only

**Observed facts.** In the three-candidate Qwen 3b runs, Qwen3.6 and Qwen3.8
both returned nine of nine parseable skeptic votes and zero empty-at-cap calls.
The Qwen3.8 arm took 934.8 seconds and the Qwen3.6 arm took 1,075.8 seconds.
Both 3c arms returned visible attacker content on all three cases. Both 3d arms
parsed all four canonicalization and judge cases, while their semantic verdicts
differed on individual fixtures.

Evidence:

- `bench/qwen_ab_3bcd/runs/3b_qwen36_20260818T015313Z.json`
- `bench/qwen_ab_3bcd/runs/3b_qwen38_20260818T023233Z.json`
- `bench/qwen_ab_3bcd/runs/3c_qwen3.6-27b-nvfp4-mtp_20260818T020154Z.json`
- `bench/qwen_ab_3bcd/runs/3c_qwen3.8-27b-nvfp4-mtp_20260818T024312Z.json`
- `bench/qwen_ab_3bcd/runs/3d_qwen3.6-27b-nvfp4-mtp_20260818T021114Z.json`
- `bench/qwen_ab_3bcd/runs/3d_qwen3.8-27b-nvfp4-mtp_20260818T025057Z.json`

**Engineering interpretation.** These runs establish liveness for a narrow
surface and provide descriptive time measurements. Three or four fixtures do
not establish a general intelligence, science, or latency advantage. V2 needs
matched cohorts, explicit denominators, repeated seeds, and confidence
intervals before an upgrade claim.

### 3. The scaffold can dominate the apparent model result

**Observed facts.** The original Gemma red-team prompt left five of 24 cases
unscored, marked all 12 parsed known-bad cases fatal, and also marked six of
seven parsed known-good cases fatal. It failed the calibration bars. The
revised prompt produced zero unscored cases, caught nine of 12 known-bad cases,
and marked zero of 12 known-good cases fatal; it passed the preregistered bars.
The Qwen3.8 arm left 18 of 24 cases unscored and produced no parsed known-good
case, so it failed the run-validity bars.

Evidence:

- `bench/redteam_cal/runs/gemma-current_20260818T060805Z.json`
- `bench/redteam_cal/runs/gemma-revised_20260818T061029Z.json`
- `bench/redteam_cal/runs/qwen38_20260818T061255Z.json`

The later re-adjudication run retained all 88 target cases and both control
classes. The old arm condemned eight of nine parsed known-good controls. The
new arm condemned one of 12 known-good controls, caught nine of 12 known-bad
controls, and agreed on 18 of 20 repeated draws. In the corrected paired
analysis, 66 of 88 target rows moved from old-fatal to new-proceed, 17 remained
fatal under both, and five involved an old-arm unscored result. The run itself
records selection and calibration caveats.

Evidence:

- `bench/readjudication/runs/old_20260819T052824Z.json`
- `bench/readjudication/runs/new_20260819T051107Z.json`
- `bench/readjudication/runs/pair_corrected_20260819T054320Z.json`

**Engineering interpretation.** A large measured shift can come from the
prompt, parser, retry policy, or evaluation instrument while weights remain
fixed. V2 must compare models under the same scaffold and compare scaffold
changes with the model held fixed. A critic also needs known-good controls;
catching bad claims alone rewards indiscriminate rejection.

### 4. Negative and insufficient experiment results were retained

**Observed facts.** The checked-in summary artifacts report:

| Experiment | Recorded verdict |
| --- | --- |
| `experiments/exp006_mechanism_design/results/summary.json` | `NO` |
| `experiments/exp007_polymarket/results/summary.json` | `BELOW_MARKET` with `n=18` |
| `experiments/exp008_qat_eval/results/summary.json` | `INSUFFICIENT` |
| `experiments/exp009_cournot/results/summary.json` | `NO` |
| `experiments/exp010_audit_collusion/results/summary.json` | `NO` |
| `experiments/exp011_matching_reconstruction/results/summary.json` | `NO` |
| `experiments/exp012_lqg_spectral/results/summary.json` | `NO` |

**Engineering interpretation.** The apparatus can preserve an unfavorable
outcome rather than force promotion. The verdict vocabulary and summary shapes
vary, so cross-experiment aggregation needs an explicit adapter and cannot
treat every `NO` as the same statistical conclusion.

### 5. One measured week is a baseline, not a trend

**Observed facts.** The benchmark-progress deployment receipt records eight
terminal trials, eight operator-recorded evaluation summaries, five complete
executions, six benchmark families, zero comparable transitions, and no
established candidate upgrade for 2026-W38. It also states that operator
summaries are unverified and that no new model calls were made to build the
dashboard.

Evidence:

- `run_state/weekly_upgrade/benchmark_progress_mvp.json` in the canonical
  checkout
- `run_state/weekly_upgrade/evaluations/2026-W38-*.json` in the canonical
  checkout

The three initial Qwen reasoning-effort cohorts recorded 13/18 objective
successes for the current xhigh arm and 12/18 for medium. Aggregate observed
wall time was approximately 1,186 seconds for xhigh and 643 seconds for medium.
The difference in successes is too small for a quality claim. A later fresh
role panel produced 5/6 successes for xhigh, 2/6 for medium, and 5/6 for an
adaptive arm, with recorded task wall times of 166.94, 189.61, and 222.72
seconds respectively. That panel had only two tasks per role, one seed, and an
adaptive timeout; it contradicts a blanket claim that medium effort is faster
or quality-equivalent without establishing a generally superior arm. The
context panel exercised approximately 8K and 14K inputs; it did not test 32K
or 64K. The first diversity panel recorded 3/5 objective successes for its
control and 0/5 for the diverse-selection arm.

**Engineering interpretation.** The earlier aggregate timing made medium a
reasonable hypothesis for a larger matched test, while the fresh role panel
shows that the apparent efficiency did not replicate under a different small
task mix. Reasoning effort remains role- and task-dependent until repeated
matched cohorts establish otherwise. The first diversity result rejects that
particular candidate scaffold and does not reject diversity plus selection in
general. Context-lane labels must name the measured input size rather than
advertise an untested model maximum. `docs/v2/BENCHMARK_FINDINGS.md` is the
authoritative record for the latest follow-through measurements.

## What worked in v0/v1

1. **Append-only evidence preserved mistakes and corrections.** Early broken
   critic runs, later valid runs, negative experiment verdicts, and
   re-adjudication all remain inspectable.
2. **Independent critical roles exposed false confidence.** Known-good and
   known-bad controls made over-condemnation visible; paired re-adjudication
   localized much of the change to the instrument.
3. **Executable tests provided stronger coding evidence than prose.** The
   historical-repair v2 panel now reconstructs one-file patches and runs fixed
   offline graders inside a bounded sandbox.
4. **Explicit safety and memory gates supported iteration.** Challenger work
   could be prepared without silently changing the resident model/runtime or
   promotion policy.
5. **Negative results remained useful.** A `NO` or `INSUFFICIENT` result was
   retained as evidence and can prevent repeated work when its provenance and
   reopening condition are clear.

## What failed or remained stuck

1. **Protocol failures were too easy to read as capability failures.** Some
   runs had no parseable verdict at all yet occupied the same report surface as
   semantic outcomes.
2. **Scaffold changes confounded model judgments.** Prompt and parser changes
   produced large shifts without a weight change.
3. **Some panels were too small for broad claims.** Several useful liveness
   checks had three or four cases, and the first weekly week has no prior
   comparable cohort.
4. **Global deterministic inference left controlled exploration untested.**
   The old wrapper default applied temperature zero broadly. Whether a
   role-aware sampling policy improves search is a hypothesis for matched
   experiments, not a measured conclusion or promoted production default.
5. **Diversity-selection v0 did not work.** It produced fewer objective
   successes than the control, and protocol/substance failures were not
   separated finely enough to diagnose the scaffold from one score.
6. **Large-context claims outran measurements.** Existing weekly data covers
   only the 8K/14K class. It cannot answer whether 32K or 64K improves research
   quality.
7. **Research lineage and document authority drifted.** Several records lack
   exact cross-ledger IDs. The stale agent-facing plan pointers found during
   this audit were corrected during v2 preparation; future activation still
   needs one synchronized authority update.
8. **Public-checkout portability is incomplete.** Some tests depend on ignored
   canonical-host ledgers or a local environment link without declaring that
   dependency.

## Rules carried into v2

### Measurement

- Score objective task completion before raw tokens per second.
- Report transport returned, protocol-valid, grader-evaluable, and objective
  success denominators separately.
- Count every declared attempt, including timeout, error, refusal, and
  not-run-budget.
- Use paired fixtures and repeated seeds. Report uncertainty using its named
  metric and denominator.
- Compare week to week only when the cohort fingerprint binds task inputs,
  graders, arm roles, repeats, seeds, budgets, and evaluation semantics.
- Preserve missing as unknown. A source that exists with zero events differs
  from an unavailable source.

### Causal attribution

- Change model, runtime, quantization, inference policy, or scaffold one
  surface at a time when making a causal claim.
- Give incumbent and challenger equivalent inference budgets and scaffolds.
- Let a frontier model propose and attack changes. Local preregistered evidence
  decides whether a candidate advances.
- Keep CPU game-mechanics calibration, LLM behavioral experiments, and novelty
  review as three separate claims.

### Scientific workflow

- Keep the domain in game theory and strategic model-agent behavior.
- Start the first v2 campaign with mathematically checkable actions and
  payoffs, explicit treatments, counterbalanced framing, fixed identities,
  multiple seeds, and disconfirming outcomes.
- Treat self-reported reasoning as an auditable output, not direct evidence of
  why an action occurred.
- Keep L4 automatic qualification distinct from L5 human validation.
- Carry failed claims, rejected hypotheses, and exact reopening conditions
  forward without turning them into new-campaign successes.

### Engineering

- Require strict structured output at the experiment boundary. Classify
  markdown wrapping, reasoning-channel leakage, malformed JSON, schema errors,
  and substantive grader failures separately; do not silently salvage them.
- Bind results to immutable manifests, source hashes, runtime identities,
  budgets, raw outcome rows, and graders.
- Use bounded reads and exact path/ID joins in every UI projection.
- Treat operator annotations as annotations. They cannot mint objective facts.
- Keep weekly review and benchmark execution separate, with production
  promotion disabled by default and a tested rollback for any later cutover.

## First v2 research boundary

The accepted program frame is game theory, agent behavior, and agentic game
theory: how incentives and access to information affect cooperation,
delegation, and strategic behavior among agents. The current CPU calibration
can test game arithmetic, deterministic controls, randomization, and whether a
proposed treatment is identifiable. It cannot measure local-model behavior.

One adversarial identifiability result already matters for design: in a public
goods-style payoff rule, an agent that sees its own payoff and own contribution
may infer the aggregate contribution. A treatment described as hiding the
aggregate can therefore change contributor identities while leaving the total
recoverable. The preregistration must define the information sigma-field from
all observables, including payoffs, rather than from prompt wording alone.

After that calibration passes, a fresh LLM study should freeze the game,
prompt, model/runtime/policy, randomization unit, outcome definitions, seed
cohort, stopping rule, and literature packet before model outcomes are visible.
The first study is a calibration of strategic behavior under those exact
conditions. Scientific novelty requires a later literature and replication
case; it does not follow from a technically successful run.
