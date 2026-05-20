# Adversarial review memo — co-scientist vs. a_bgt_rsi

> Stage 1 + Stage 2 of the handoff prompt. The prior analysis is treated
> as a set of hypotheses to break, not conclusions to implement. Per-claim
> verdict at the end of each section. Citations are to the Google AI
> co-scientist blog post ("Blog") at
> `research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/`
> and to the arXiv paper abstract ("Paper") at `arxiv.org/abs/2502.18864`.
> Where a finer claim would require the paper body and I do not have it,
> I say so.

## Stage 1 — what the co-scientist actually is

Re-derived from the Blog and Paper abstract, without filtering through
the prior analysis:

- **Architecture.** A multi-agent system on Gemini 2.0, with six named
  specialized agents — Generation, Reflection, Ranking, Evolution,
  Proximity, Meta-review — coordinated by a Supervisor. The Supervisor
  parses the goal into a research-plan configuration, assigns workers,
  and "allocates resources." The Paper abstract names "an asynchronous
  task execution framework for flexible compute scaling." (Blog, "AI
  co-scientist overview"; Paper abstract, contribution 1.)

- **Generation method.** "Self-play–based scientific debate for novel
  hypothesis generation." (Blog, "Scaling test-time compute.") The Paper
  describes a "generate, debate, and evolve approach." Reflection
  performs "recursive self-critique" using tool use. (Blog, same
  section.)

- **Self-improvement signal.** An Elo auto-evaluation derived from
  ranking tournaments. The Paper abstract calls this a "tournament
  evolution process for self-improving hypotheses generation." The Blog
  states: "The system's self-improvement relies on the Elo
  auto-evaluation metric derived from its tournaments." It also says:
  "The Elo is an auto-evaluation and is not based on an independent
  ground truth" (caption of the GPQA chart).

- **External validation.** The Blog reports a correlation between Elo
  ratings and GPQA diamond accuracy ("higher Elo ratings positively
  correlate with a higher probability of correct answers"). For 15 open
  research goals, seven domain experts curated goals and "best guess
  solutions"; on 11 of those, experts assessed novelty/impact and
  preferred the co-scientist's outputs. (Blog, same section.)

- **Validation experiments.** Three biomedical use cases — AML drug
  repurposing, liver fibrosis targets, and the cf-PICI gene-transfer
  mechanism — with wet-lab follow-up. The Blog states all three
  "involved expert-in-the-loop guidance." The cf-PICI work was a
  rediscovery: the co-scientist re-derived a hypothesis that "had
  already been subject to novel discovery in their group, but had not
  yet been revealed in the public domain." Validation was performed in
  "the original novel laboratory experiments performed prior to use of
  the AI co-scientist system."

- **What the Blog does NOT claim.** It does not claim the wet-lab
  results were used to update the system. It does not describe a
  feedback edge from experimental validation back into the Generation
  agent. The Meta-review agent feeds back into Generation, but Meta-review
  is itself a synthesis over the tournament — the same closed loop.

This is the source-of-truth picture I will judge prior claims against.

---

## Stage 2 — per-claim verdicts

### C1 — Self-evaluation circularity

**Prior claim.** The Elo metric is at once the optimization target, the
self-improvement signal, and the headline evidence; the only external
anchor is a correlation with GPQA, which has answer keys that open
research goals lack.

**Re-derivation.** The Blog states explicitly that self-improvement
relies on the Elo auto-evaluation and that Elo is not based on
independent ground truth. The Paper abstract names "automated
evaluations show continued benefits of test-time compute," which is the
same Elo. The GPQA correlation is on a benchmark *with* answer keys; the
15 research goals were scored by Elo plus expert preference on 11 of
them. So the circularity claim is correctly identified: the
self-improvement loop runs on a metric the system produces.

**Falsification attempt.** Could one argue the expert preference
assessments (Blog, "Novelty and Impact" figures) break the circularity?
Partially — experts rated novelty/impact on 11 goals, and the Blog says
"these human expert preferences also appeared to be concordant with the
previously introduced Elo auto-evaluation metric." But the
*self-improvement loop itself* uses Elo, not expert preference. Expert
preference is a *correlational check on the metric*, not a feedback
signal that changes what the system does. So the prior claim survives.

**Analog tightness for this project.** The prior analysis names this
project's novelty-evaluation rubric (Step 6 of the intelligence loop) as
the analog. Inspecting `ARCHITECTURE.md` §6: Step 6 is structured as
"Automated check surfaces candidates; human makes the final call in
Step 8." The synthetic tier *also* has ground truth (rediscovery of
known equilibria), so Step 7's quicklook against TFT cooperation rates
on Day 7 is checked against a pre-computed expected range
(`plan.yaml` `day7_block2_quicklook`). The semi-synthetic tier (the
mechanism-design ladder, Rungs 2+) has no such ground truth and is the
analog site of risk.

**Mitigation check.** Three options were proposed: (a) novelty checker
on a different model from the generator, (b) anchor to retrieval (novel
⇔ literature search fails to find it), (c) human sample with logged
sample rate. (a) costs another model in memory, which collides with
D-012's exclusion of a dual-model routing layer in Phase 1 — but the
exclusion is "no automatic routing," not "no second model"; the worker
contract is designed to accept a model field per task (D-012,
"Reversibility"). So (a) is feasible in Week 2–3 once Qwen 3.6 lands.
(b) is *already* the design — Step 6 surfaces the 5 most similar known
results and Step 1 queries all three knowledge layers. The mitigation is
just to formalize that "novel" requires the retrieval pass to surface no
sufficiently-similar result, with the threshold logged. (c) is the
cheapest and worth doing immediately as part of human-intervention
instrumentation (see C4).

**Verdict: HOLDS.** The circularity is real in the co-scientist, the
analog site in this project is correctly identified, and the
mitigations are reasonable and mostly cheap. The novelty-checker
model-separation in particular is more important than it looks because
the same Gemma 4 endpoint is also the experiment's *subject* in the PD
runs (per Day 7); having it grade its own outputs in novelty evaluation
is the same circularity in miniature.

### C2 — No truth-feedback into the generator

**Prior claim.** The co-scientist is generate→rank→evolve; Evolution
improves only the winners; losers drop out; nothing is penalized for
being wrong; wet-lab results don't re-enter the loop.

**Re-derivation.** The Blog describes Evolution as "an 'evolution'
process for quality improvement" within the tournament. Reflection
performs self-critique. Wet-lab validation is reported as outcome, not
as input that changed system state. The Blog explicitly describes the
cf-PICI work as "the AI co-scientist system independently proposed
that…" — the wet-lab work had already been done. There is no claim of a
training or conditioning update from validation. The asynchronous task
framework named in the Paper abstract is about *compute scheduling*, not
about validation feedback.

**Falsification attempt.** Could Meta-review serve as truth-feedback?
The Blog describes Meta-review as part of the "coalition of specialized
agents… that use automated feedback to iteratively generate, evaluate,
and refine hypotheses." But "automated feedback" here means feedback
within the tournament/Elo system — the same closed loop. Without access
to the paper body I cannot rule out a buried mechanism for validation
re-entry, but the abstract's contribution list (1: multi-agent
architecture with async task framework; 2: tournament evolution) does
not name one, and the Blog's discussion of limitations explicitly cites
"enhanced literature reviews, factuality checking, cross-checks with
external tools" as opportunities for improvement, which implies they
are not currently in.

**Analog tightness.** Day 7's experiment is a real falsification
apparatus — the LLM-vs-TFT cooperation rate is checked against a human's
*pre-written* expected range, with a hard checkpoint that aborts the day
if outside the range (`plan.yaml` `day7_block2_run_experiment` →
`on_failure: escalate_to_human`). This is much better than the
co-scientist's design. But the signal currently terminates at the human
gate — there is no edge from the experiment result back to the
generator's prompt or knowledge base except via Step 8 (human
assessment → Layer 3 of the knowledge base). That's the same
single-bottleneck topology, just routed through a human rather than a
tournament.

**Mitigation check.** "Wire the experiment result back as conditioning
on the generator" with a keep/discard bandit for selection. This is
sensible but needs care: the Phase 1 design has a human gate between
experiment result and journal publication for good reason (graduated
autonomy). The right phrasing is: experiment results condition the
*next* generation only after passing the human gate, and the bandit
handles keep/discard among *human-cleared* hypotheses. That preserves
graduated autonomy. The cost is one new edge in the loop and one new
field in the run-log schema.

**Verdict: HOLDS, with refinement.** The analog is real and the
mitigation is right; the refinement is that the feedback edge must be
gated by Step 8 to avoid eroding graduated autonomy. The architecture
update should label this edge "Phase 2" (the loop-memory growth that
matters for cross-run learning) and explicitly mark its
human-gate dependency.

### C3 — Generate-and-filter with no cost to being wrong

**Prior claim.** Hypothesis generation is cheap; experiments are
expensive (one Spark, 26B model). The natural drift is to generate many,
validate few, which quietly reshapes the loop into the co-scientist's
form. Track a hypotheses:experiments ratio as a degradation metric.

**Re-derivation.** The Blog confirms generation is cheap in the
co-scientist (it scales test-time compute precisely *because* generation
is cheap). The Blog's headline charts (Elo progression vs. baselines)
are explicitly time-on-compute curves: "the system spends more time in
computation. This can be seen in the automated Elo metric gradually
improving." That's exactly the asymmetry the prior claim names.

**Falsification attempt.** Is this a fair characterization of the
co-scientist's design, or is it a property of any LLM research system?
Both — but the co-scientist *specifically* relies on the asymmetry as a
feature (test-time-compute scaling is one of the headline contributions
in the Paper abstract). So calling it a co-scientist-style property is
fair.

**Analog tightness.** This project's Phase 1 design has explicit
counter-pressure: every experiment goes through the robustness battery
(Step 4) and cross-tier replication (Step 5), both of which are
*more* expensive than the experiment itself. So the project's design
*already* makes experiments expensive on purpose. The risk is that
under time pressure (or under a Week 2+ autoresearch budget that's
limited), the loop will naturally chew through hypotheses without
finishing Steps 4 and 5. The hypotheses:experiments ratio is the right
canary.

**Mitigation check.** Tracking the ratio costs almost nothing — it's a
counter in the run-log and a query against the existing JSONL schema.
The trigger threshold should not be set now; let Phase 1 produce a
baseline first. Adding it as a *measured* metric, not yet as a *gate*,
is the right Phase 1 move.

**Verdict: HOLDS.** Cheap to instrument, real risk, and the architecture
already has the counter-pressure (robustness + cross-tier) the metric
would help defend.

### C4 — Expert-in-the-loop hides the autonomy gap

**Prior claim.** Every co-scientist validation involved expert
scaffolding (curated goals, "best-guess" solutions, novelty judgments)
so the paper cannot separate AI lift from expert framing. The preprint
will face the same "how much was you?" question. Instrument human
intervention as a typed, counted event distinct from human gates, so the
preprint can report N generated / M survived / K human edits.

**Re-derivation.** The Blog is explicit: "Seven domain experts curated
15 open research goals and best guess solutions in their field of
expertise." For the validation experiments, "These settings all involved
expert-in-the-loop guidance." The cf-PICI rediscovery used a topic the
expert team had *already* worked on. So the prior characterization is
accurate.

**Falsification attempt.** Is it fair to demand the co-scientist
separate AI lift from expert framing? Arguably the system is designed as
"a collaborative tool for scientists" (Blog) and the framing is part of
the workflow. But the headline claims — outperforming "unassisted human
experts" on the Elo metric, generating "novel research hypotheses" — are
not about a co-equal collaboration; they're about the system's
contribution. The Blog itself names "larger-scale evaluation involving
more subject matter experts" as a limitation. So the prior is on
defensible ground.

**Analog tightness.** This is the tightest analog of the four. The
project's headline claim is precisely "an at-home research loop run by
an independent researcher can produce findings at the productive edge."
That claim is unbreakable without a clean accounting of where the human
ended and the loop began. The handoff prompt notes this is also the
preprint's most likely critique.

**Mitigation check.** "Instrument human intervention as a typed, counted
event distinct from human gates." This is the most important and
*cheapest* mitigation of the seven. The run-log JSONL schema already
exists (Day 2, `day2_block2_jsonl_schema`). Adding a `human_intervention`
event type with subtypes — `gate_clear`, `edit_prompt`, `edit_code`,
`reject`, `redirect`, `manual_decision` — costs hours, not weeks. But it
*does* touch Week 1 (the JSONL schema), so per guardrails it goes in
"Frozen-plan change proposals" and not into `plan.yaml` directly.

**Verdict: HOLDS, and the most important of the four.** The mitigation is
cheap and the upside is the preprint's defensibility. Architecture
documents should specify the schema; the Week 1 schema addition itself
is a change proposal.

### O1 — Adversarial critic before the experiment stage

**Prior claim.** The co-scientist generates via self-play debate and
has a Reflection agent for recursive self-critique. This project's
generator (Weeks 2+) is not specified as adversarial. Add an explicit
red-team / critic agent before experiment dispatch, to protect scarce
experiment budget.

**Re-derivation.** The Blog confirms self-play debate and Reflection's
recursive self-critique. These are the co-scientist's primary internal
quality-control mechanisms before any external evaluation. (Blog,
"Scaling test-time compute.")

**Falsification attempt.** Does the current architecture *already* have
a critic? Step 4 (robustness battery) and Step 5 (cross-tier
replication) are post-experiment quality controls. Step 6 (novelty
evaluation) is post-experiment. There is no pre-experiment critic. The
mechanism-design ladder uses *evolved* mechanisms but the evolution is
within an experiment, not before it. So no, the current architecture
does not have this.

**Cost-benefit at 26B.** A critic agent doubles the generator's compute
per hypothesis. If hypotheses are cheap and experiments are expensive
(C3), spending more compute *on* the hypothesis before running the
experiment is a clear win. The cost is one extra prompt cycle per
hypothesis, dominated by the cost of the experiment itself. This is
unambiguously a good trade on a single Spark.

**Tension with the project's "single model" stance.** The critic *could*
be the same model with a different prompt (`devil's advocate` system
prompt). That's how Reflection works in the co-scientist. So the
overlay does not require a second model; it requires a structured
prompting pattern. Phase 1 is single-model by design (D-012), but the
critic doesn't violate that.

**Verdict: HOLDS.** Cheap, clearly net-positive, and consistent with
the single-model constraint if implemented as a structured prompt
pattern. Phase 2 architecture should add a Critic node.

### O2 — Active meta-review synthesis

**Prior claim.** The co-scientist's Meta-review agent synthesizes
patterns across the tournament and feeds them back into Generation.
This project's "loop-memory" knowledge layer (Layer 3 of the knowledge
base) is structurally a *passive* ChromaDB collection — a library
nobody is required to read. Add a synthesis worker that actively
distills "what kept winning/losing" into the next generation prompt.

**Re-derivation.** The Blog confirms the Meta-review agent as one of
the six. The Paper abstract's "self-improving" claim is partly carried
by this agent. The exact behavior (active vs. passive) isn't in the
Blog; the Blog calls it a "Meta-review" agent in a coalition that "use
automated feedback to iteratively generate, evaluate, and refine
hypotheses." Active synthesis is the natural reading.

**Falsification attempt — is loop-memory really passive?** Looking at
`ARCHITECTURE.md` §4.4: "Layer 3 accumulates what's been tried, what's
been found, what's already known, and what assessments the researcher
has made. **This is the mechanism by which the apparatus gets smarter
over time.**" The mechanism is described as accumulation, not synthesis
— the hypothesis generator "should not propose experiments that test
things already known" (§6 step 2), but the language is "should not"
(constraint), not "shall be conditioned on" (active read). Step 1
queries all three layers but reads them as retrieval, not synthesis.

So yes, loop-memory as currently designed is passive. The risk: a
generator that *retrieves* from loop memory will avoid duplicating
prior hypotheses but will not see the cross-cutting patterns ("the
LLM always defects against grim trigger after round N") that an
active synthesis would surface.

**Cost-benefit.** A synthesis worker is a Week 2+ item. The unit of
work is small: a prompt that summarizes the last N journal entries into
3–5 generator-prompt-ready bullets. Cost is one inference call per
generation cycle; benefit is the loop sees its own history coherently.
This is a clear win.

**Verdict: HOLDS.** Architecture should specify the synthesis worker as
a distinct loop step (let's call it "Step 0.5" — runs between literature
scan and hypothesis generation, conditioning the latter). Implementation
is Week 2+.

### O3 — Compute-budgeting Supervisor

**Prior claim.** The co-scientist's Supervisor allocates resources and
scales compute. This project's orchestrator dispatches workers but has
no compute budget per hypothesis; on one Spark, GPU-hours are the binding
constraint. Add a compute budget tracked by the orchestrator, and a
cost-aware keep/discard bandit (skill-per-GPU-hour, not raw skill).

**Re-derivation.** The Blog states: "The Supervisor agent assigns the
specialized agents to the worker queue and allocates resources. This
design enables the system to flexibly scale compute and to iteratively
improve its scientific reasoning toward the specified research goal."
The Paper abstract's first contribution names "an asynchronous task
execution framework for flexible compute scaling." So compute-budgeting
is unambiguously a feature of the co-scientist.

**Falsification — is GPU-hours really the binding constraint?** Yes.
Memory budget is already tracked in `ARCHITECTURE.md` §7 (peak total
~60–90 GB of 128 GB). But the time budget — how many hours of Spark
runtime to spend on hypothesis X — is not. With the bench at ~69 tok/s
single-stream (D-022), every hypothesis carries a non-trivial token
budget. Without per-hypothesis caps, a runaway robustness sweep or a
multi-round LLM-vs-LLM experiment could consume the day.

**Cost-benefit.** Tracking compute in the orchestrator is essentially
free — the orchestrator already logs to JSONL and the wrapper already
records `latency_ms` per call (Day 2 schema). What's missing is an
*allocator*: a budget per hypothesis, deducted as the experiment runs,
that triggers early-stop if exceeded. The keep/discard bandit's reward
function should normalize by compute consumed. This is a clean Phase 2
addition.

**Verdict: HOLDS.** Architecture should specify (a) per-hypothesis
compute budget in the orchestrator and (b) cost-aware reward function
in the bandit. Phase 2+.

---

## Lower-priority items — verdicts

These are the "learnings / value-adds" the handoff prompt asked to test
as a group. Each gets a short verdict; supporting reasoning is shorter
than the C/O sections because they're lower-priority.

- **Six-role agent taxonomy as a worker menu for Week 2+.** HOLDS as
  taxonomy reference, but only some roles map cleanly. Generation,
  Reflection, Ranking, Evolution, Meta-review map directly. Proximity
  (clustering hypotheses by similarity) is a nice-to-have. Supervisor
  is already the orchestrator. The right move: name the agent roles in
  the Week 2+ planning note, do not commit to all six in Phase 1.

- **Calibrate the auto-evaluator against synthetic-tier ground truth
  before relying on it semi-synthetic.** HOLDS, and important. The
  synthetic tier *has* ground truth (Nash equilibria, known cooperation
  rates against fixed strategies). The semi-synthetic tier doesn't.
  Before relying on Gemma 4 to score semi-synthetic outputs, run a
  calibration experiment: have Gemma 4 score synthetic-tier outputs
  against ground truth, measure agreement, decide whether the score is
  trustworthy. This belongs in Week 2+ planning.

- **Rediscovery-with-holdout evaluation protocol.** HOLDS. Withhold a
  known result from the loop's literature access (e.g., remove all
  papers on McKelvey & Palfrey 1995 QRE from the foundational corpus,
  ask the loop to characterize behavioral deviations from Nash in
  matching pennies, score whether the loop rediscovers QRE-shaped
  behavior). This is the cleanest test of "is the loop actually adding
  signal." Belongs in Week 2+ planning, executed once the corpus and
  semi-synthetic tier are running.

- **Test-time compute scaling as a deliberately tuned knob.** HOLDS,
  with the caveat that *at 26B* the co-scientist's headline curves may
  not transfer. The co-scientist's improvement curves are on Gemini 2.0
  (a frontier model). A 26B model's critique→evolution loop may
  amplify errors (the model is not strong enough to reliably catch its
  own mistakes). This itself is a worth experiment — explicitly: does
  one round of self-critique improve hypothesis quality at 26B, or make
  it worse? Belongs in Week 2+ planning.

- **The "N collapses where the claims get interesting" symmetry.**
  HOLDS as a self-aware observation. Synthetic tier N is large (500
  rounds × 5 opponents on Day 7 alone). Semi-synthetic N will be
  small (mechanism-design ladder runs are slow). Applied N is Phase 2+.
  The same thinness the co-scientist has on its 15 research goals will
  show up on this project's semi-synthetic findings. The right
  response is to be *explicit* about it in the preprint and to lean on
  cross-tier replication as the disambiguator. Not an architecture
  change; a methodological commitment.

---

## What the prior analysis missed — additional gaps

The handoff prompt asks for at least three. Here are five.

### M1 — Provenance and reproducibility of *retrieved* literature

The co-scientist queries tools including web search; the project's
literature pipeline is ML-Intern with arXiv + Semantic Scholar. Both
systems retrieve external content into prompts. The co-scientist Blog
does not discuss how retrieved content is tracked for reproducibility.
This project's reproducibility commitment is load-bearing
(`PROJECT_CONTEXT.md` §3 "Reproducibility is load-bearing"). But the
current architecture does not specify how each retrieved abstract /
chunk gets pinned in the JSONL so that the *exact* literature context a
hypothesis was generated against can be reconstructed. Without this,
"every model call is a research observation" is not actually true —
retrieval is part of the prompt, and retrieval drifts as the corpus
grows. The fix is small: log retrieved document IDs (and their content
hashes) as a list on each generator call. This is a gap the prior
analysis did not name, and it's a co-scientist-style flaw the project
could inherit.

### M2 — The Day 7 expected-range gate is operating on *a single
researcher's pre-belief*

This is a structural artifact of solo research and not really a fix the
prior analysis missed, but it deserves naming. The Day 7 hard checkpoint
fires if the LLM-vs-TFT cooperation rate is outside the human's
pre-written expected range (`plan.yaml` `day7_block2_run_experiment`).
That range is a one-person prior. Over Phase 1, repeated calibration of
*the researcher's* expected ranges against measured outcomes is itself
research data — if the researcher's calibration improves, the apparatus
is teaching the human; if it doesn't, the human is the bottleneck. Add
a "calibration log" event type that pairs pre-experiment expected
ranges with post-experiment observed values. Per-person calibration
metrics over time are publishable on their own.

### M3 — The novelty checker's blind spot: pre-arXiv literature

`ARCHITECTURE.md` §4.2 explicitly notes that the foundational
game-theory literature is mostly pre-arXiv (Nash 1950, von Neumann &
Morgenstern, Schelling, Smith & Price, McKelvey & Palfrey, Camerer
2003). The architecture has handled this by embedding the textbooks
during Days 1–60. **But** the novelty checker at Step 6 surfaces "the 5
most similar known results" by ChromaDB similarity. ChromaDB returns
nearest-neighbors in BGE-M3 embedding space. The risk: a finding that
restates Schelling's focal-point argument in different terminology
might miss the nearest-neighbor cutoff because the prose is too
dissimilar (Schelling 1960 prose is not modern arXiv prose). This is a
co-scientist-style flaw — the co-scientist also relies on retrieval, and
the cf-PICI rediscovery worked precisely because Penadés et al.'s
preliminary writeups *were* in the corpus. Fix: have the novelty
checker run *both* semantic retrieval AND a structured-claim search
("is there any literature that asserts X about Y under conditions Z?"),
where X/Y/Z are extracted from the candidate finding. This goes in the
novelty-evaluation rubric as a sub-research-problem and is Phase 2.

### M4 — No degradation detector on the orchestrator model itself

The co-scientist's Reflection agent does self-critique but does not, as
far as the Blog discusses, detect that the *base model* is failing —
e.g., the model is producing increasingly degenerate hypotheses because
something in the loop has gone wrong (prompt context too long, retrieval
returning irrelevant results, temperature drift). This project has the
same gap: the JSONL captures everything, but there's no automated
"the model is degrading" signal. The Day 1 silent-failure-mode safeguard
(MARLIN backend check, MoE backend log line) is one specific instance
of this concern, but there's no generalized degradation detector. A
canary task — fixed prompt, fixed seed, run every N cycles, score
against a stored baseline — would catch silent model drift. Cheap.
Phase 2.

### M5 — The robustness battery is unsourced from the co-scientist analog

The co-scientist runs tournaments over many candidate hypotheses; the
project runs a robustness battery (prompt/seed/model variation) over
each finding. These are not the same. The tournament is *exploration* —
which hypothesis ranks highest. The robustness battery is
*falsification* — does this single hypothesis survive perturbation. The
prior analysis didn't separate them. The project should keep both: the
robustness battery is the project's contribution and is more
methodologically defensible than the tournament; the tournament-like
exploration (multiple candidate hypotheses per generation cycle) is
worth adding *separately* as a Phase 2 mechanism, with the keep/discard
bandit as the selector. This is a clarification rather than a new gap,
but it matters for how the architecture talks about itself.

---

## Summary table

| # | Claim | Verdict |
|---|---|---|
| C1 | Self-evaluation circularity | HOLDS |
| C2 | No truth-feedback into generator | HOLDS, with refinement |
| C3 | Generate-and-filter with no cost to being wrong | HOLDS |
| C4 | Expert-in-the-loop hides autonomy gap | HOLDS — most important |
| O1 | Adversarial critic before experiment | HOLDS |
| O2 | Active meta-review synthesis | HOLDS |
| O3 | Compute-budgeting Supervisor | HOLDS |
| Lower | Six-role taxonomy as worker menu | HOLDS (partial mapping) |
| Lower | Calibrate auto-eval on synthetic ground truth | HOLDS |
| Lower | Rediscovery-with-holdout protocol | HOLDS |
| Lower | Test-time-compute scaling as tuned knob | HOLDS (with 26B caveat) |
| Lower | N-collapse where claims get interesting | HOLDS (methodological note) |
| M1 | Retrieved-literature provenance | Missed by prior |
| M2 | Researcher's calibration as research data | Missed by prior |
| M3 | Novelty checker's pre-arXiv blind spot | Missed by prior |
| M4 | No model-degradation detector | Missed by prior |
| M5 | Robustness battery ≠ tournament | Missed by prior (clarification) |

Nothing was judged `wrong` or `overstated`. This is a stronger
endorsement of the prior analysis than I expected. Two reasons it's
warranted: (a) the co-scientist Blog supports each claim with direct
text, and (b) the project's existing architecture *already* has many of
the right counter-pressures, so the claims are reading the apparatus
correctly when they describe what's there and what isn't.

A note of intellectual humility: my access to the 81-page Paper body is
limited; some claims about what the co-scientist does or doesn't do may
turn out, on deeper reading, to be addressed in the appendix. Treat
each "HOLDS" as "holds given the Blog and abstract"; if Huchi finds the
paper says otherwise, the verdict should be revisited.

Stage 3 follows.
