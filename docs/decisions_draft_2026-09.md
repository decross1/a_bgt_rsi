# Draft decisions from the September 2026 related-work review

Status: **DRAFT — not ratified, not executable authority**.

These entries are deliberately outside `DECISIONS.md`. They translate the
positioning review into bounded options for the owner. Nothing in this file
changes the active ladder, runtime, schema, model roles, or publication policy.

State basis: `56c1b3abae968c8288471b30946000c29ae6f228`.

## DRAFT-D-078 — Native claim-evidence integrity audit before L4

**Tier.** S.

**Context.** The current claim-extraction path records iteration, journal, and
results references, and the evidence ladder governs L0–L5 progression. It does
not independently verify artifact identity, numerical reproduction, citation
support, specification fidelity, or method-code alignment. ScientistOne,
XScientist, Kosmos, Agon, MLR-Bench, and the local code make this gap concrete.

**Draft decision.** Add a feature-flagged `integrity_audit` that emits:

- an artifact manifest with content hashes;
- claim-to-output mappings and deterministic recomputation for numerical
  claims where possible;
- specification-compliance checks;
- citation locators plus an explicit support/unsupported/unresolved field;
- method-code alignment checks;
- auditor identity, version, and provenance.

Run it dark first against historical L2/L3 material. Prefer deterministic
checks. Humans adjudicate every flag and a preregistered sample of negatives.
An LLM-only audit remains unscored until calibrated. After a separate owner
ratification, a failed or unresolved audit would block L3→L4 without erasing
lower-rung evidence; L5 remains human-only.

**Alternatives considered.** Preserve the present ladder; immediately adopt
XScientist's full artifact format; rely on manual post-hoc audits only.

**Rationale.** This tests integrity properties that workflow success and
reviewer scores cannot establish while preserving the existing ladder's
semantics.

**Reversibility.** Additive and feature-flagged; dark-run data can be discarded
without changing promotions.

**Relationship.** Would amend D-059, D-061, and D-075 only after ratification.

**Likely touchpoints.** `workers/claim_extract.py`, a new
`workers/integrity_audit.py`, `workers/evidence_ladder.py`,
`orchestrator/finding_promotion.py`, iteration schema, audit artifacts, and
tests.

**Ratification questions.** Which deterministic checks are mandatory? What
negative-sample rate is large enough to estimate false negatives? Is every
unresolved audit blocking, or only named integrity classes?

## DRAFT-D-079 — Temporal-holdout benchmark for agenda and topic changes

**Tier.** P for the experiment; any production enforcement is S.

**Context.** Retrospective self-scoring does not test prospective research
judgment. ForeSci demonstrates a cutoff-aligned pattern and, importantly,
separates evidence retrieval from selection of the correct research object.

**Draft decision.** Build an offline, preregistered behavioral-game-theory and
social-choice benchmark with:

- a frozen, cutoff-aligned corpus;
- hidden post-cutoff outcomes used only for evaluation;
- a contamination and leakage audit;
- separate evidence-retrieval and research-decision scores;
- abstention, confidence calibration, and decision-family breakdowns;
- a comparison between the current agenda selector and a corpus-first
  candidate.

Keep the result advisory until a human validates the task set and scoring.
Never auto-accept an agenda, frontier, or topic change from this benchmark.

**Alternatives considered.** Retrospective evaluation only; adopt ForeSci
wholesale; use unrelated cross-domain benchmarks.

**Rationale.** The experiment measures the exact prospective judgment the
apparatus claims to amplify and prevents good retrieval from masquerading as a
good decision.

**Reversibility.** Additive offline benchmark.

**Relationship.** Would amend D-060, D-063, and D-075 only if its results are
adopted operationally.

**Likely touchpoints.** `bench/forward_judgment/`,
`orchestrator/morning_topic.py`, `orchestrator/domain_anchor.py`, a frozen data
manifest, preregistration, and tests.

**Ratification questions.** What historical cutoff and task families are
defensible? Who blinds and scores the outcomes? What baseline and calibration
threshold would count as useful rather than merely above chance?

## DRAFT-D-080 — Operationalize the existing human-intervention ledger

**Tier.** P; intervention content remains human-authored.

**Context.** `schema/events.jsonl.schema.json` already defines
`human_intervention`, but the live ledger at the reviewed state contains five
calibration entries and no intervention rows. Peer systems show that edits,
candidate selection, redirects, laboratory work, and final judgments remain
scientifically material.

**Draft decision.** Add explicit CLI and UI capture for in-task edits,
rejections, redirects, and manual decisions. Each event carries the human's
reason and a context hash. Report monthly, by stage:

- generated;
- survived unchanged;
- edited;
- rejected;
- redirected.

Keep intervention events distinct from gate clearance. Start observationally.
Never infer, autocomplete, or rewrite the human's rationale.

**Alternatives considered.** Do nothing; reconstruct intervention from git and
chat history; treat every gate clearance as an intervention.

**Rationale.** A denominator is needed for honest attribution and for testing
the program's claim that the human's judgment improves over time.

**Reversibility.** Append-only capture helper and presentation layer. Existing
event semantics remain intact.

**Relationship.** Operationalizes the existing schema and would extend D-063
observability without changing current gate semantics.

**Likely touchpoints.** A new `orchestrator/intervention_cli.py`, runtime hooks,
UI endpoint and rendering, documentation, and tests. The schema changes only if
a later ratified subtype cannot fit the existing contract.

**Ratification questions.** Which actions must be logged? When does steering
become an intervention rather than ordinary task specification? What context
may safely be hashed or retained?

## DRAFT-D-081 — Corpus-first local problem-formulation A/B

**Tier.** P experiment; adoption is S.

**Context.** Fifty-two of 98 recorded recent iterations were off-field. That
supports testing a repair but does not identify the cause. SGHA provides a
relevant corpus-first, local, evidence-linked formulation hypothesis.

**Draft decision.** Preregister an A/B comparison between:

- current seed → hypothesis; and
- domain corpus → typed gap/problem object → hypothesis.

Hold local model, corpus, compute budget, and seeds constant. Measure
topicality, duplicate rate, routability to an explicit experiment,
evidence-link coverage, and blinded human preference, with a negative control.
Leave production unchanged unless the preregistered thresholds and a human gate
both pass. Do not introduce frontier-model runtime generation.

**Alternatives considered.** Keep D-075 anchors alone; replace the current path
immediately; add an external frontier generator.

**Rationale.** This isolates formulation order from model scale and tests the
closest plausible mechanism behind the observed drift.

**Reversibility.** Isolated experiment; no production contact.

**Relationship.** Would amend D-075 only if adopted and remains consistent with
D-014.

**Likely touchpoints.** `workers/hypothesize.py`,
`orchestrator/domain_anchor.py`, `bench/problem_formulation/`, preregistration,
artifacts, and tests.

**Ratification questions.** What is the blinded topicality rubric? How many
seeds provide a useful uncertainty bound? What failure pattern would falsify
the corpus-first hypothesis?

## Shared adoption gate

No draft above should enter `DECISIONS.md` from this document alone. Each needs:

1. owner ratification of scope and tier;
2. a frozen success/failure instrument;
3. a bounded implementation or experiment plan;
4. an explicit rollback;
5. validation that reports every criterion independently.
