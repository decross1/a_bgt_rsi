# ARCHITECTURE.md — patch from adversarial review

> This document collects the edits to `ARCHITECTURE.md` derived from the
> adversarial review. Each block is written as a self-contained insertion
> or replacement, with the target section named at the top. Apply by
> editing `ARCHITECTURE.md` in place. The intent is that an honest reader
> of the merged document sees both the original eight-step loop *and*
> the additions, with Phase 1 vs. Phase 2+ clearly labeled so nothing
> creates the false impression that Phase 1 has machinery it doesn't.

---

## Patch 1 — REPLACE §6 "The intelligence loop"

Replace the current §6 with the version below. The original eight steps
are preserved unchanged; new steps and notes are added at the points
they belong, each labeled Phase 1, Phase 2, or "Phase 2 — gated by
Step 8" as appropriate.

```markdown
## 6. The intelligence loop

The loop runs steps 1–7 autonomously on the DGX Spark and gates on
step 8, which requires human judgment. The autonomy boundary moves up
over time as the apparatus's judgment on specific domains is validated
through Step 8 feedback. See `docs/diagrams/intelligence_loop_v5.svg`
for the current visual; the v4 diagram remains in
`docs/diagrams/` as the historical record (per the versioning
convention).

The loop has the *eight original steps* — the structural commitment
of the research program. Three additional pieces of machinery surround
them, each labeled with phase and rationale so that no reader mistakes
Phase 2 plans for Phase 1 implementation:

- A **Meta-review synthesis** step that runs between Step 1 and Step 2,
  distilling loop memory into conditioning text for the generator. New
  in Phase 2; not present in Phase 1.
- A **Critic / red-team** step that runs between Step 2 and Step 3,
  attempting to falsify the generated hypothesis before spending
  experiment budget on it. New in Phase 2; not present in Phase 1.
- An **experiment → generator feedback edge**, returning the
  experiment outcome (not just the human's novelty assessment) into
  the knowledge base and the next generation cycle, gated by Step 8.
  New in Phase 2; not present in Phase 1.

### The steps

1. **Literature scan.** Query all three knowledge-base layers. Ingest
   new arXiv papers. Surface relevant prior work for the current
   research direction.

   **(Phase 2)** *Meta-review synthesis.* Between scan and hypothesis
   generation, a synthesis worker reads recent loop-memory entries
   (last N journal entries, with N tunable) and distills 3–5
   conditioning bullets — *what kept winning*, *what kept losing*,
   *what surprised the human* — into the generator's prompt. This is
   the "active" reading of Layer 3 that the passive ChromaDB
   collection alone does not provide. Without this, the generator
   reads loop memory only as nearest-neighbor retrieval, missing
   cross-cutting patterns.

2. **Generate hypothesis.** The orchestrator synthesizes literature
   and accumulated data into a research question or trading thesis.
   Domain knowledge in the knowledge base constrains the hypothesis
   space — the agent should not propose experiments that test things
   already known.

   **(Phase 2)** *Critic / red-team review.* Before dispatching the
   experiment, a critic prompt attempts to falsify the hypothesis:
   what's the strongest counter-argument? what known result does this
   contradict? is the proposed experiment actually a test of the
   hypothesis? The critic is implemented as a structured prompt pattern
   on the same model (consistent with D-012's single-model Phase 1
   stance), not as a second model. The critic's output is logged and,
   if the critic's confidence in the falsification exceeds a
   threshold, the hypothesis is sent back to Step 2 with the critic's
   reasoning appended. Bounded retries (≤ 2) per generation cycle to
   prevent infinite loops.

3. **Run experiment in one tier.** Design and execute the experiment
   in the synthetic, semi-synthetic, or applied tier. If model
   training is needed, invoke autoresearch as a bounded tool. Most
   experiments are game simulations (seconds to minutes) or research
   synthesis (inference only), not training runs.

   **(Phase 2)** *Per-hypothesis compute budget.* The orchestrator
   maintains a GPU-time budget per hypothesis, deducted as the
   experiment runs. Early-stop if exceeded. The budget allocator is
   the project's analog of the co-scientist's Supervisor (cf. Paper,
   contribution 1). The keep/discard bandit's reward function (D-010)
   normalizes by compute consumed — *skill per GPU-hour*, not raw
   skill.

4. **Robustness battery.** Vary prompt, seed, and model version. Does
   the finding hold?

   **Methodological note.** The robustness battery is *falsification* —
   does *this* hypothesis survive perturbation. It is not *exploration*
   (which hypothesis among many ranks highest). Multi-candidate
   exploration with bandit selection is a separate Phase 2 layer over
   Step 2 (generation), and the bandit acts on already-cleared
   hypotheses (post-Step 8) rather than at this step. This
   distinction matters because the co-scientist's tournament conflates
   the two.

5. **Cross-tier replication.** Test whether the finding generalizes to
   other tier(s). A finding from the synthetic tier gets tested in
   semi-synthetic. A mechanism-design result gets tested against
   Polymarket dynamics (in Phase 2+; design-only in Phase 1).
   Tier-specific failure is diagnostic signal, not a discard.

6. **Novelty evaluation.** Check all three knowledge-base layers.
   Surface the 5 most similar known results. Classify: novel /
   rediscovery / nonsense / unclear. The hardest step and explicitly
   named as its own sub-research-problem. Automated check surfaces
   candidates; human makes the final call in Step 8.

   **Two requirements on the automated novelty checker:**

   - **(Phase 1 — minimum)** The retrieval pass is anchored to
     ChromaDB BGE-M3 similarity, *plus* a logged human-sample rate
     (a fixed fraction of automated novelty calls get reviewed by the
     human even when the automated call is "novel" — sample rate
     logged per assessment).

   - **(Phase 2)** When a second model lands (D-006: Qwen 3.6 in
     Week 2–3), the *novelty scorer* and the *generator* should be
     different models. Same-model scoring is structurally the
     co-scientist's Elo circularity in miniature (the model surfaces
     similar results from its own embedding/output space).

   - **(Phase 2)** Alongside semantic retrieval, run a
     *structured-claim search*: extract from the candidate finding the
     claim of form "X about Y under conditions Z" and run a structured
     query for any literature that asserts X about Y under Z — even
     when surface wording differs. This addresses the foundational-
     game-theory blind spot: a finding that restates Schelling's
     focal-point argument in different prose may miss BGE-M3's
     nearest-neighbor cutoff.

7. **Log to research journal.** Record in the structured format:
   claim, prior for novelty, literature search results, post-search
   assessment, what would change the assessment. Every non-trivial
   loop output gets this treatment.

   **Reproducibility requirement (Phase 1, additive).** Every
   generator call's prompt logs a `retrieval_context` field — a list
   of `{doc_id, content_hash, chunk_offset}` for each retrieved chunk
   that entered the prompt. This is the difference between
   "every model call is a research observation" being a slogan and
   being load-bearing — retrieval drifts as the corpus grows, and
   without pinning the retrieved content the generator's input cannot
   be reconstructed. *Schema change required; this is a frozen-Week-1
   change proposal.*

8. **Human evaluation.** Researcher validates the novelty assessment,
   approves or rejects trades (applied tier), updates the novelty
   evaluation rubric, publishes to the public research journal.
   Assessments feed back into Layer 3 of the knowledge base — closing
   the learning loop.

   **(Phase 2)** *Experiment-outcome feedback edge.* In addition to
   the human's novelty assessment (Phase 1, already in design), the
   experiment outcome itself (cooperation rates, robustness battery
   matrix, cross-tier replication result) is written into a
   `experiment_outcome` entry in Layer 3. The next generation cycle
   reads this entry via the Meta-review synthesis worker. The edge is
   **gated by Step 8** — outcomes only enter loop memory after the
   human clears them; this preserves graduated autonomy.

### Monthly red flags

The program names four diagnostic checks that fire monthly. These are
not loop steps; they are a periodic self-audit.
- Reading without doing? → build
- Doing without thinking? → read
- Am I the bottleneck on evaluating loop outputs? → that's the point —
  is that skill improving?
- Is the loop surfacing things I genuinely didn't know? If no for 30+
  days, something is wrong with the hypothesis generator or experiment
  design.
```

---

## Patch 2 — INSERT new §6.5 "Degradation metrics"

Insert after §6 (i.e., after the loop description and monthly red
flags), before §7. New section in full:

```markdown
## 6.5 Degradation metrics

The intelligence loop's structural form (generate → experiment → log)
is similar enough to the co-scientist's that the same failure modes
can creep in if not measured. The metrics in this section are designed
to *catch* drift toward those failure modes early; they are not
gates, and Phase 1 only needs to *log* them. Phase 2 sets thresholds
once a baseline is established.

### 6.5.1 Hypotheses-to-experiments ratio (C3 from review)

Track the count of hypotheses generated per experiment actually run to
completion (through Step 5 cross-tier replication). The natural drift
in any system with cheap generation and expensive experimentation is
for this ratio to rise. The co-scientist's tournament *is* the limit
case: many hypotheses, no experiments. This project's design pushes
the ratio toward 1:1 via the robustness battery and cross-tier
replication, both of which are themselves expensive. Logging the
ratio is essentially free — counters on existing JSONL events.

Threshold-setting is deferred to Phase 2 (need a baseline first).

### 6.5.2 Model-degradation canary (M4 from review)

A fixed prompt with a fixed seed, run every N hours against the live
orchestrator, scored against a stored baseline output. Catches silent
model drift — prompt context too long, retrieval returning irrelevant
results, temperature drift, MoE backend silently flipped. The Day 1
silent-failure-mode safeguards (MARLIN backend check, NvFp4 backend
startup log) catch the gross cases at startup; the canary catches the
slow cases at runtime.

Cheap. Phase 2.

### 6.5.3 Hypothesis-input provenance audit (M1 from review)

Each generator call records its `retrieval_context` (per §6 step 7
above). The audit is a periodic check that for any logged hypothesis,
the retrieval context can be re-fetched from ChromaDB and verifies
against the stored content hashes. If a hash mismatches, the corpus
has drifted under a prior hypothesis's feet, and any "rediscovery"
claim against that hypothesis is suspect.

Phase 2.

### 6.5.4 Researcher calibration log (M2 from review)

Pairs the human's pre-experiment expected range (already a Day 7
artifact for the PD experiment per `plan.yaml`
`day7_block2_run_experiment`) with the post-experiment observed value.
Over time, per-person calibration is itself research data — if the
researcher's calibration improves, the apparatus is teaching the
human; if it stays flat, the human is the bottleneck on what the
loop can surface.

Implementation: a `calibration_entry` event in the run-log JSONL.
*Schema change required; this is a frozen-Week-1 change proposal.*
```

---

## Patch 3 — ADD to §5.1 "The harness stack"

After the existing paragraph about Pi / OpenClaw / NemoClaw, insert:

```markdown
**Compute budgeting (Phase 2).** The orchestrator carries a
per-hypothesis GPU-time budget, deducted as workers run, with
early-stop when the budget is exceeded. This is the project's analog
of the co-scientist's Supervisor (cf. Paper, contribution 1:
"asynchronous task execution framework for flexible compute
scaling"). The budget is also the input to the cost-aware reward
function on the keep/discard bandit (see §6 step 3 and D-010's
"Reversibility" entry). Phase 1's orchestrator has only a memory
budget (§7), not a compute budget; Phase 2 adds the time dimension.

**Critic / red-team agent (Phase 2).** The orchestrator dispatches a
critic prompt against each generated hypothesis before any experiment
runs (see §6 step 2). The critic is the same Gemma 4 endpoint with a
red-team system prompt; no second model is required (consistent with
D-012). Implementation is in `workers/critic.py` (Phase 2).

**Meta-review synthesis worker (Phase 2).** A worker that reads the
last N loop-memory entries and emits 3–5 conditioning bullets for the
generator's next prompt (see §6 step 1). Implementation in
`workers/meta_review.py` (Phase 2).
```

---

## Patch 4 — ADD to §8 "What the apparatus deliberately does NOT do"

Add the following bullets at the end of the existing list:

```markdown
- **Same-model novelty grading in Phase 2+.** Once a second model
  lands (Week 2–3 per D-006), the novelty *scorer* must be a different
  model from the *generator*. Phase 1 mitigates the single-model
  configuration with logged human sampling on automated novelty calls
  (see §6 step 6). This is the project's response to the
  co-scientist's Elo circularity (the same model that *generates* also
  *ranks*, producing a self-confirming improvement curve).

- **Auto-publish of experiment outcomes back into the generator
  without the human gate.** Phase 2 adds an experiment → generator
  feedback edge (§6 step 8), but it is gated by Step 8 — experiment
  outcomes enter loop memory *after* the human has cleared them. The
  edge is for the loop to *learn from* outcomes, not to *react to*
  them autonomously.
```

---

## Patch 5 — ADD a paragraph at the end of §4.4 "Layer 3 — loop memory"

After the existing paragraph ending "primary differentiator from
systems like Sakana's AI Scientist that have no cross-run memory.":

```markdown
**Active vs. passive read (Phase 2).** Layer 3 as described above is a
ChromaDB collection — the hypothesis generator may retrieve from it,
but is not required to read it coherently. The co-scientist's
Meta-review agent synthesizes patterns across runs; this project adds
an equivalent in Phase 2 (the Meta-review synthesis worker, §5.1 and
§6 step 1's Phase 2 addition). Without it, loop memory is a library
nobody is required to read — accumulation without synthesis. With it,
"the apparatus gets smarter over time" is mechanism, not aspiration.
```

---

## Patch 6 — UPDATE §6 reference to diagram

The current text in §6 says:
"See `docs/diagrams/intelligence_loop_v4.svg` for the visual."

Change to:
"See `docs/diagrams/intelligence_loop_v5.svg` for the current visual;
the v4 diagram remains in `docs/diagrams/` as the historical record."

(Already incorporated in Patch 1's full replacement of §6 above.)

---

## Summary of changes to ARCHITECTURE.md

| Section | Change |
|---|---|
| §4.4 | Add active-vs-passive paragraph (O2, Phase 2) |
| §5.1 | Add compute-budgeting, critic, meta-review paragraphs (O1, O2, O3, Phase 2) |
| §6 | Replace in full: Phase 1 unchanged, Phase 2 additions interleaved with clear labels (C1, C2, M1, M3, M5, O1, O2, O3) |
| §6.5 (new) | Degradation metrics (C3, M1, M2, M4) |
| §8 | Add two negative-scope bullets (C1, C2) |
| Diagram reference | Update to v5 |

No version pins changed. No Phase 1 work item moved. Every addition is
labeled with phase and rationale. Three additions (the
`retrieval_context` field, the `calibration_entry` event type, and the
`human_intervention` event type) require schema changes that touch
Week 1 — those are proposals in deliverable 5, not edits here.
