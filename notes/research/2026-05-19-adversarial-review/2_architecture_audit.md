# Architecture audit — where each validated insight lands

> Stage 3. For each insight that survived Stage 2, locate where in the
> current design it is already handled, silently assumed, or absent.
> Then sort findings into the three buckets defined by the handoff
> prompt's guardrails.

## Inventory of architecture / planning / diagram artifacts

What I can see and treat as authoritative:

1. `PROJECT_CONTEXT.md` — full project background, §3 "Key principles,"
   §4 Week 1 plan summary, §5 (presumably) Anthropic policy, §6 "Open
   scoping items"
2. `ARCHITECTURE.md` — apparatus architecture walkthrough:
   §2 hardware/runtime, §3 three-tier sandbox, §4 knowledge base
   (three layers), §5 orchestration/tools/sandboxing, §6 the
   eight-step intelligence loop, §7 compute/cost budget, §8 what the
   apparatus deliberately does NOT do, §9 first-boot verification
3. `DECISIONS.md` — D-001 through D-022 plus open decisions (notably
   "General architecture re-scope" open)
4. `plan.yaml` — frozen Week 1 plan with Appendix A "Deviations from
   research program v2" and a long-form structure per day
5. `docs/diagrams/architecture_v4.svg` — static architecture diagram
6. `docs/diagrams/intelligence_loop_v4.svg` — behavioral diagram
7. `docs/diagrams/README.md` — diagram versioning convention

Note that `research_program_v2.pdf` and
`research_apparatus_technical_plan_v1.md` are referenced as
"docs/sources/…" but **not present** in the project (per
`docs/sources/README.md`). The visible canonical summaries are the
operative authority.

---

## (a)/(b)/(c) map — where each insight sits today

Notation: **a** = already handled · **b** = silently assumed ·
**c** = absent

### C1 — Self-evaluation circularity, generator ≠ novelty-checker
- (b) **silently assumed.** `ARCHITECTURE.md` §6 step 6 says "Automated
  check surfaces candidates; human makes the final call in Step 8."
  Doesn't specify which model performs the automated check. If it's the
  same Gemma 4 endpoint generating hypotheses, the circularity is
  inside the loop.
- (a) **partly handled** by the human-in-the-loop design at Step 8.
- Fix locus: `ARCHITECTURE.md` §6 (add "different model OR retrieval-
  only OR human-sample" requirement) and `architecture_v5.svg` (label
  the novelty-checker node distinctly).

### C2 — Truth-feedback edge from experiment back to generator
- (b) **silently assumed.** `ARCHITECTURE.md` §6 step 8 says
  "Assessments feed back into Layer 3 of the knowledge base — closing
  the learning loop." But this is the *human's* assessment of novelty,
  not the *experiment result itself* feeding into the generator. The
  loop closes via human, not via experiment outcome.
- (c) **absent** for direct experiment → generator conditioning. The
  Day 7 plan's `day7_block2_run_experiment` produces a measured
  cooperation rate; the only downstream consumer is the human gate.
- Fix locus: `ARCHITECTURE.md` §6 (add explicit edge, mark Phase 2,
  gated by Step 8), `intelligence_loop_v5.svg` (new edge experiment →
  Layer 3 → generator, dashed/Phase 2 styling).

### C3 — Hypotheses:experiments ratio metric
- (c) **absent.** No place in the current architecture tracks this
  ratio. The architecture has the *components* (run-log JSONL,
  experiment IDs) but no explicit ratio metric.
- Fix locus: `ARCHITECTURE.md` §6 or a new §6.x "Degradation metrics."
  Implementation is just a query against existing logs.

### C4 — Human-intervention typed event in run log
- (b) **silently assumed.** Run-log has events like `gate_clear` and
  human attestations, but the human's actual *edits* and *redirections*
  inside agent-executable / human-assisted tasks aren't typed
  distinctly. The state file tracks `human_gates_pending`; that's
  about which gates are pending, not about counts of edits.
- (c) **absent** as a typed counted event with subtypes
  (`edit_prompt`, `edit_code`, `reject`, `redirect`, `manual_decision`).
- Fix locus: `ARCHITECTURE.md` §5 or §6 (specify the event type); the
  *schema* change touches Week 1 (Day 2 JSONL schema) and goes in
  frozen-plan change proposals.

### O1 — Adversarial critic before experiment dispatch
- (c) **absent.** `ARCHITECTURE.md` §6 step 2 (generate hypothesis)
  goes directly to step 3 (run experiment). No critic node.
- Fix locus: `ARCHITECTURE.md` §6 (add a step 2.5 "Critic / red-team
  review"), `intelligence_loop_v5.svg` (new node between hypothesis
  and experiment). Marked Phase 2.

### O2 — Active meta-review synthesis worker
- (b) **silently assumed.** Layer 3 (loop memory) is described as
  "accumulates what's been tried" — passive. Step 1 (literature scan)
  queries all three layers but as retrieval, not synthesis.
- (c) **absent** as an active synthesis worker producing distilled
  conditioning text for the next generation cycle.
- Fix locus: `ARCHITECTURE.md` §6 (add a "Meta-review synthesis" step
  before step 2), `intelligence_loop_v5.svg`. Phase 2.

### O3 — Per-hypothesis compute budget on orchestrator
- (a) **partly handled.** `ARCHITECTURE.md` §7 tracks memory and
  electricity. The Day 2 wrapper records `latency_ms` per call.
- (c) **absent** as a per-hypothesis compute *cap* with early-stop
  semantics, and as a cost-aware reward in the bandit (which itself is
  Phase 2 per D-010).
- Fix locus: `ARCHITECTURE.md` §5 (orchestrator description) and §7
  (budget section), `architecture_v5.svg` (annotate orchestrator).

### Lower-priority insights — landing spots

- **Six-role taxonomy as worker menu.** Lands in Week 2+ planning note.
  Architecture docs reference the menu without committing to all six in
  Phase 1.
- **Calibrate auto-eval on synthetic ground truth.** Lands in Week 2+
  planning as a calibration experiment, with success criterion.
- **Rediscovery-with-holdout protocol.** Lands in Week 2+ planning,
  executed when corpus + semi-synthetic tier are running.
- **Test-time-compute scaling as tuned knob at 26B.** Lands in Week 2+
  planning as an experiment (does self-critique help or hurt at 26B?).
- **N-collapse symmetry.** Methodological commitment, lands in preprint
  framing notes (not architecture).

### Missed gaps from §"What the prior analysis missed"

- **M1 — Retrieved-literature provenance.** (b) silently assumed —
  reproducibility commitment is named in `PROJECT_CONTEXT.md` §3 but
  the schema doesn't yet log retrieved doc IDs per generator call.
  Fix locus: `ARCHITECTURE.md` §6 (specify the requirement), schema
  change touches Week 1 → frozen-plan change proposal.

- **M2 — Researcher's calibration as research data.** (c) absent. Fix
  locus: Week 2+ planning note (the calibration log event type) and
  preprint framing.

- **M3 — Novelty checker's pre-arXiv blind spot.** (b) silently
  assumed — the foundational corpus *includes* pre-arXiv textbooks
  (§4.2) but the novelty checker relies on BGE-M3 similarity which is
  sensitive to surface form. Fix locus: `ARCHITECTURE.md` §6 step 6
  (add structured-claim search alongside semantic retrieval).
  Implementation: Phase 2.

- **M4 — Model-degradation detector.** (c) absent. Fix locus:
  `ARCHITECTURE.md` §5 (orchestrator description) or §7 (degradation
  metrics). Implementation: Phase 2.

- **M5 — Robustness battery ≠ tournament.** (a) handled, but the
  current architecture description doesn't explicitly distinguish
  *falsification* (robustness) from *exploration* (tournament).
  Fix locus: `ARCHITECTURE.md` §6 (clarify in step 4 and add note that
  multi-candidate exploration with bandit selection is a separate Phase
  2 layer, not part of step 4).

---

## Three-bucket split

The handoff prompt's guardrails define three buckets by where the fix
belongs. Here is every fix sorted.

### Bucket 1 — Architecture documents / diagrams (updatable now)

These get applied in Stage 4.

1. `ARCHITECTURE.md` §6 — add the Critic / red-team step (O1) and the
   Meta-review synthesis step (O2) as labeled Phase 2 additions.
   Annotate step 6 (novelty evaluation) with the
   model-separation/retrieval-anchor requirement (C1) and the
   structured-claim-search addition (M3).
2. `ARCHITECTURE.md` §6 — add the truth-feedback edge from experiment
   result back into the generator, gated by Step 8 and Phase 2 (C2).
3. `ARCHITECTURE.md` §5 — annotate orchestrator with per-hypothesis
   compute budget; reference the cost-aware bandit reward (O3).
4. `ARCHITECTURE.md` §5 or §7 — add a "degradation metrics" subsection
   covering: hypotheses:experiments ratio (C3), model-degradation
   canary task (M4), retrieved-literature provenance requirement (M1).
5. `ARCHITECTURE.md` §6 — clarify robustness battery is falsification,
   not exploration; note tournament-style exploration with bandit is a
   separate Phase 2 layer (M5).
6. `architecture_v5.svg` — annotate the orchestrator with the compute
   budget; everything else on this diagram is likely unchanged.
7. `intelligence_loop_v5.svg` — add critic node between step 2 and
   step 3 (O1, Phase 2 label); add meta-review synthesis node between
   step 1 and step 2 (O2, Phase 2 label); add the experiment →
   generator edge gated by Step 8 (C2, Phase 2 label); annotate step 6
   to call out the generator/novelty-checker separation (C1).
8. `docs/diagrams/README.md` — describe the v5 diagrams.
9. `DECISIONS.md` — add new D-NNN entries documenting the v5 diagrams
   and the architecture changes.

### Bucket 2 — Week 2+ planning (notes only)

These go in the new `week2_plan_seed.md`-shaped note. The handoff
prompt is explicit that Week 2's full plan is a separate task; this
note seeds it.

1. **Calibration experiment.** Score Gemma 4 on synthetic-tier
   outputs against ground truth, measure agreement, decide whether the
   auto-evaluator is trustworthy for semi-synthetic.
2. **Test-time-compute knob experiment.** Does one round of
   self-critique improve hypothesis quality at 26B, or amplify errors?
3. **Rediscovery-with-holdout protocol.** Designed as a Phase 2 entry
   point.
4. **Six-role agent taxonomy as worker menu** — name the agents that
   land in Weeks 2–4 (Generation, Reflection, Ranking; Evolution +
   Meta-review come later).
5. **Concurrency design.** Week 2 is when concurrency can land per the
   plan's "no concurrency in Week 1" rule.
6. **Active meta-review synthesis worker** — implementation work.
7. **Critic agent** — implementation work (prompt pattern on single
   model, no second model required).
8. **Compute-budget supervisor** — implementation work in the
   orchestrator.
9. **Cost-aware bandit reward** — implementation work in the bandit
   keep/discard ratchet.
10. **Researcher's calibration log** — new event type (M2).
11. **Structured-claim novelty search** alongside semantic retrieval
    (M3).
12. **Model-degradation canary task** (M4).

### Bucket 3 — Frozen Week 1 (proposals only)

These all touch the JSONL schema, the `human_only` task taxonomy, or
similar Week 1 surfaces. They are PROPOSALS for Huchi's explicit
approval. They are NOT applied.

1. **Add `human_intervention` event type to the run-log schema**
   (C4). Subtypes: `edit_prompt`, `edit_code`, `reject`, `redirect`,
   `manual_decision`, plus a free-text `reason`. Cost: ~30 min schema
   change + wrapper instrumentation. Touches:
   `schema/call_log.schema.json` (Day 2 artifact). Rationale: preprint
   defensibility — the most important Stage-2 finding.
2. **Add `retrieval_context` field to wrapper call records** (M1). A
   list of `{doc_id, content_hash, chunk_offset}` for each retrieved
   chunk in the prompt. Cost: ~1 hour. Touches: same schema. Rationale:
   reproducibility commitment requires it.
3. **Add `calibration_entry` event type** (M2). Fields:
   `pre_experiment_expected_range`, `post_experiment_observed`,
   `experiment_id`. Cost: ~30 min. Touches: schema. Rationale: makes
   the human's calibration improvement a measurable apparatus output.

For each proposal, the change is small and additive (no breaking
changes to existing schema fields). The proposals are detailed in a
separate deliverable.

Nothing in Bucket 3 changes Day-by-Day task structure, version pins,
human-only blocks, or human gates.

---

## What does NOT change

- The Day 7 publication review gate. Untouched.
- The Block 1 human-only rule. Untouched.
- Version pins (`vllm/vllm-openai:v0.21.0`, CUDA 13.0, BGE-M3,
  `--moe-backend marlin`, NVFP4 weights path). Untouched.
- The graduated autonomy principle. Reinforced (the C2 feedback edge
  is explicitly gated by Step 8).
- The single-model Phase 1 design (D-012). Preserved — the critic
  agent (O1) is a prompt pattern, not a second model.
- The decision to exclude Sakana-style automated peer review (D-011).
  Preserved — none of the new additions automate novelty calls; the
  novelty-checker model separation (C1) is about not having the *same*
  model both generate and surface-similarity-grade. The human still
  makes the call in Step 8.
- The decision to use the bandit, not SCORE (D-010). Preserved — the
  cost-aware reward (O3) is an enhancement to the bandit, not a
  replacement.

Stage 4 follows.
