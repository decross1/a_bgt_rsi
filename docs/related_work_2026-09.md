# Related work and defensible positioning — September 2026

Status: evidence-backed positioning memo, not a novelty or priority proof.

State basis: `56c1b3abae968c8288471b30946000c29ae6f228`.

## Question

Where does this apparatus sit relative to current AI-scientist systems, and
what contribution can it claim without treating workflow completion, a polished
paper, or an LLM review as evidence of valid science?

The bounded answer is deliberately narrow. The literature already contains
multi-agent hypothesis refinement, end-to-end paper generation, laboratory
feedback loops, social-science simulation, corpus-first problem formulation,
long-running research-state management, claim/evidence integrity checks, and
agent publication infrastructure. None of those components is novel by itself.

The still-defensible positioning hypothesis is:

> A longitudinal case study of one independent researcher using modest local
> compute for behavioral game theory, with a pinned local principal
> investigator, off-box development-time falsifiers, an explicit L0–L5
> evidence ladder, diversity accounting, synthetic/semi-synthetic/applied test
> tiers, durable run/gate/intervention provenance, and measured repair
> dynamics.

No system in this bounded review visibly combines all of those constraints.
That is a comparison result, not a first-of-kind claim. It remains provisional
until the apparatus has prospective benchmarks, artifact-integrity audits,
and externally inspectable scientific outcomes.

## Review method and boundary

This memo reuses the 2026-09-02 sweep rather than rerunning it. The source
artifact contains 324 deduplicated targets: 159 systems, 78 critiques, 53
benchmarks, 13 surveys, and 21 venues. Seventeen sweepers and two completeness
critics produced that pool. A subsequent three-pass refinement closed the
owner-named seeds, selected the smallest load-bearing comparison set, and read
the primary papers or official records directly.

The review is broad enough to support positioning, but it is not a systematic
review and cannot establish priority. Most 2026 entries are new preprints or
author-run evaluations. Domain, compute, cost, human labor, and outcome quality
are rarely comparable across papers. Reported numbers below are therefore
attributed to their authors unless an independent evaluation is named.

Raw sweep: `notes/research/2026-09-02-teams/rw_targets_raw.json`.

## Nearest systems

| Relevance | System | What it establishes | Boundary for this project |
| --- | --- | --- | --- |
| A | [ScientistOne](https://arxiv.org/abs/2605.26340) (2026-05-25) | Chain-of-Evidence plus score, specification, reference, and method-code audits. The authors report 0/337 hallucinated references, 12/12 score checks, and 14/15 method-code alignments for their system. | Mostly deterministic systems tasks; some positive examples were human-corrected. Citation existence is not entailment, domain transfer is not established, and false negatives remain insufficiently bounded. |
| A | [AgentSociety 2](https://arxiv.org/abs/2607.11895) (2026-07) | The closest social-science peer: AI social scientists and simulated participants share an executable research environment while humans retain high-level agency. | Seven illustrative studies, not a longitudinal behavioral-game-theory program; results are preprint self-report. |
| A | [SGHA](https://arxiv.org/abs/2608.17501) (2026-08-18) | Corpus-first, evidence-linked research-problem formulation using a locally served open-weight 9B model. | Covers problem discovery rather than the full longitudinal research loop. |
| A | [ForeSci](https://arxiv.org/abs/2606.00644) (2026-05-30) | 500 cutoff-controlled tasks, offline pre-cutoff knowledge, post-cutoff validation, and separate evidence-versus-decision diagnostics. | Forecasting research directions is not autonomous scientific discovery. |
| A | [Google AI co-scientist](https://www.nature.com/articles/s41586-026-10644-y) (2026-05-19) | Generation, reflection, ranking, evolution, proximity, and meta-review agents, with scientist steering and persistent context. | Biomedical focus; small and partly subjective expert evaluation. |
| A | [Robin](https://www.nature.com/articles/s41586-026-10652-y) (2026-05-19) | A continuous hypothesis/literature/data-analysis loop connected to wet-lab feedback. | Humans selected candidates, wrote or executed laboratory protocols, ran experiments, and returned results. |
| A | [XScientist](https://arxiv.org/abs/2607.12301) (2026-07-14) | A git-like long-running research protocol with exploration DAGs, hashes, claim/evidence anchors, replay hooks, repairs, gates, failed branches, and daemon operation. | A very recent preprint. Its existence is verified, but the name match does not prove it was the owner's intended “X-scientist.” |
| A | [AI scientists produce results without reasoning scientifically](https://arxiv.org/abs/2604.18805) (2026-04-20) | More than 25,000 author-reported runs expose scaffold and epistemic failures that outcome-only evaluation misses. | Domains differ from this program and the evaluation remains author-reported. |
| A | [Kosmos](https://arxiv.org/abs/2511.02824) (2025-11-04) | Long-running literature/code analysis with structured shared state and report-level provenance. | Its scale, cost, 79.4% statement accuracy, and time-saved estimates are reported by the system authors. |
| A | [Agon](https://arxiv.org/abs/2606.24177) (2026-06-23) | Machine-checkable validation paired with explicit residual human judgment and an author-derived failure taxonomy across 444 iterations. | Recent preprint and system-authored evaluation. |
| B | [MLR-Bench](https://arxiv.org/abs/2505.19955) (2025-05-26) | 201 open-ended ML tasks; the authors report fabricated or invalid experimental results in about 80% of coding-agent attempts. | Workshop-derived ML tasks, not longitudinal science. |
| B | [CodeScientist](https://arxiv.org/abs/2503.22708) (2025-03-20) | Hundreds of automated experiments and a multi-stage external review, code review, and replication funnel. | Only 6 of 19 returned discoveries survived as at least minimally sound and incrementally novel. |
| B | [Curie](https://arxiv.org/abs/2502.16069) (2025-02-22) | Intra-agent rigor, inter-agent rigor, and shared experiment knowledge, evaluated on 46 questions. | The reported 3.4× improvement is author-reported and not directly comparable to this program. |
| B | [The AI Scientist](https://www.nature.com/articles/s41586-026-10265-5) (2026-03-25) | End-to-end ideation, coding, experimentation, manuscript drafting, and self-review. | A workshop-scale result does not demonstrate broad scientific validity. |
| B | [AI Scientist-v2](https://arxiv.org/abs/2504.08066) (2025-04-10) | Template-free progressive agentic tree search. | Three manuscripts were evaluated; one cleared a workshop threshold. |
| B | [Independent AI Scientist evaluation](https://arxiv.org/abs/2502.14297) (2025-02-20) | Independent evidence of coding failures, weak novelty, outdated references, and hallucinated results. | The tested setup may not represent later system versions. |
| B | [LLM-as-a-Reviewer](https://arxiv.org/abs/2605.25415) (2026-05-25) | Measures reviewer overrating, topical divergence, and prompt-injection exposure. | Reviewing is not research execution, but it constrains the use of LLM promotion oracles. |
| B | [Expert study of AI-assisted review](https://arxiv.org/abs/2605.20668) (2026-05-20) | Forty-five experts identify complementary criticism coverage as well as recurrent AI weaknesses. | Supports assistance, not sole-oracle status. |
| B | [FunSearch](https://www.nature.com/articles/s41586-023-06924-6) (2023-12-14) | Strong evaluator-guided program search, using on the order of one million samples. | A boundary case that depends on cheap, objective scoring of candidate programs. |
| B | [SCP](https://arxiv.org/abs/2512.24189) and [aiXiv](https://arxiv.org/abs/2508.15126) (2025) | Federation, lifecycle, authorization, archival, review, revision, and publication infrastructure. | Infrastructure and venue layers do not validate the underlying research loop. |

Sakana's narrower workshop account also matters. Humans chose and submitted
three AI-generated papers; one reportedly averaged 6.33, was withdrawn before
publication, and received no meta-review. This should be described as a
workshop review result, not a general autonomous-publication result. See the
[authors' account](https://sakana.ai/ai-scientist-first-publication/).

## Mechanism-level comparison

### Generation, debate, ranking, and evolution

Google AI co-scientist, Curie, and the AI Scientist family establish that
multi-agent generation/ranking/reflection is now standard design space. The
apparatus should evaluate its version of those mechanisms rather than claim
them. The relevant local questions are calibration, independence of critics,
failure visibility, and whether a ranking predicts later evidence.

### Auditable research artifacts

ScientistOne, XScientist, Kosmos, and Agon make provenance and integrity a
separate target from producing a good-looking output. Local claim extraction
currently records iteration, journal, and results references in
`workers/claim_extract.py`, but does not content-hash artifacts, anchor exact
supporting spans, recompute numerical claims, or check method-code fidelity.
The L0–L5 ladder in `workers/evidence_ladder.py` governs progression but does
not independently establish those integrity properties.

This is the clearest near-term technical gap. It motivates DRAFT-D-078 rather
than a novelty claim about provenance.

### Prospective research judgment

ForeSci's cutoff-aligned design separates retrieving relevant evidence from
choosing the right future research object. That distinction maps directly to
this apparatus's topic and agenda selection. Retrospective agreement with the
eventual result is not enough: a useful evaluation needs a frozen pre-cutoff
corpus, hidden post-cutoff outcomes, leakage checks, abstention, and calibrated
confidence. DRAFT-D-079 proposes that test in behavioral game theory and
social choice.

### Human contribution

Robin, Google AI co-scientist, AgentSociety 2, and Agon all leave material work
or judgment with humans. The local event schema already defines
`human_intervention`, but the live event ledger at this state basis contains
five calibration entries and zero intervention rows. The missing piece is
capture and coverage, not another overlapping event type. DRAFT-D-080 keeps
human rationale human-authored and separates intervention from gate clearance.

### Corpus-first local formulation

SGHA shows that a local, evidence-linked corpus-first problem-formulation path
already exists. The local observation that 52 of 98 recent iterations were
off-field is enough to justify an experiment, but not enough to name the cause.
DRAFT-D-081 therefore proposes a preregistered A/B against the current
seed-to-hypothesis path instead of an immediate replacement.

### Open-ended versus objective evaluation

FunSearch illustrates the favorable case: a candidate can be cheaply executed
and scored. Behavioral game theory, semi-synthetic societies, and applied
prediction-market work often lack such a single objective evaluator. This is
why the project needs separate claim integrity, robustness, temporal judgment,
and human review rather than one scalar “scientific quality” score.

## Critiques that constrain the claims

1. **Outcome success is not process validity.** Ríos-García et al. report that
   scientific agents can complete workflows while ignoring or failing to
   revise on evidence. MLR-Bench and the independent AI Scientist evaluation
   show that polished artifacts can contain invalid or fabricated experiments.
2. **Citation presence is not support.** A valid identifier only proves that a
   source exists. Entailment, exact supporting location, and method fidelity
   remain separate checks.
3. **LLM judges are useful but not sovereign.** The two reviewer studies support
   complementary criticism while documenting overrating, divergence, recurrent
   blind spots, and injection sensitivity.
4. **Acceptance is a weak proxy.** Workshop scores and self-selected
   submissions do not substitute for artifact inspection, replication, or
   prospective validation.
5. **Human labor must be counted.** Candidate selection, protocol design,
   physical execution, correction, and final judgment materially affect the
   result even when the agent performs most intermediate steps.
6. **Cost and compute comparisons are presently unsafe.** Papers count calls,
   rollouts, time, hardware, and human effort differently.

## Named-seed resolution

The review explicitly closed the unfinished names from the 2026-09-02 critic.

| Seed | Resolution |
| --- | --- |
| FunSearch | Verified: [Nature](https://www.nature.com/articles/s41586-023-06924-6). |
| Boiko Coscientist | Verified and kept distinct from Google's later system: [Nature](https://www.nature.com/articles/s41586-023-06792-0). |
| CodeScientist | Verified: [arXiv:2503.22708](https://arxiv.org/abs/2503.22708). |
| Curie | Verified: [arXiv:2502.16069](https://arxiv.org/abs/2502.16069). |
| MLR-Bench | Verified: [arXiv:2505.19955](https://arxiv.org/abs/2505.19955). |
| ScientistOne | Verified: [arXiv:2605.26340](https://arxiv.org/abs/2605.26340). |
| ForeSci | Verified: [arXiv:2606.00644](https://arxiv.org/abs/2606.00644). |
| SCP | Corrected to **Science Context Protocol**, not “Scientific Criticism Protocol”: [arXiv:2512.24189](https://arxiv.org/abs/2512.24189). Its 1,600+ resource count is author-claimed. |
| aiXiv | Verified and kept distinct from AiraXiv: [arXiv:2508.15126](https://arxiv.org/abs/2508.15126). |
| Agon | Verified: [arXiv:2606.24177](https://arxiv.org/abs/2606.24177). |
| XScientist | Existence verified: [arXiv:2607.12301](https://arxiv.org/abs/2607.12301). Owner-intended identity remains unresolved. |
| Autoscience Mira | Vendor-only partial evidence: [Autoscience](https://autoscience.ai/mira). No public paper, reproducible evaluation, or reliable publication date was found in the bounded pass. Do not conflate it with Deep Principle's separate [MIRA](https://agentmira.io/blog/mira-towards-a-general-ai-scientist). |
| ERA | Unresolved after the three-pass cap. The cached lead resolved to Google co-scientist/Robin material, so no relabeling was made. |

## Claims this project should not make

- first multi-agent research loop;
- first research operating system or daemon;
- first claim-evidence or provenance chain;
- first corpus-first local research system;
- first human-in-the-loop AI scientist;
- first social-science simulation system;
- autonomous discovery, scientific validity, or productive advantage merely
  because a workflow completed;
- an entirely “one-box” process without explicitly excluding authorized
  off-box development-time falsifiers.

The bounded sweep found no direct game-theory-specific end-to-end peer. That is
useful positioning evidence, but it is not an exhaustive priority claim.

## Decisions and next evidence

The actionable consequences are drafted, not ratified, in
`archive/docs-2026-09/decisions_draft_2026-09.md`:

- DRAFT-D-078: native claim-evidence integrity audit before L4;
- DRAFT-D-079: temporal-holdout benchmark for agenda/topic judgment;
- DRAFT-D-080: operationalize the existing human-intervention ledger;
- DRAFT-D-081: corpus-first local problem-formulation A/B.

The evidence that would most change this positioning is an externally audited
artifact from this apparatus, a prospective temporal benchmark, a measured
human-intervention denominator, and a stronger peer comparison focused on
behavioral game theory rather than AI-for-science in general.
