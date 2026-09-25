# C1 bounded primary-source screen — 2026-09-25

This is an evidence-binding stop report, not a thesis decision. It separates the
original C1 candidate from the later, narrower C1 T0 design and records negative
and inaccessible evidence. Material statements below are marked **Observed**,
**Inferred**, or **Unknown**.

```json
{
  "schema": "c1-bounded-source-screen/v1",
  "observed_at": "2026-09-25T01:29:04Z",
  "base_commit": "27747a8f90a16c9309ec02e329ac6fe20a2a205d",
  "candidate": "C1",
  "decision": "stop",
  "decision_scope": "bounded_source_screen",
  "stop_code": "insufficient_full_text_binding",
  "c1_a_data": "absent",
  "clearance_granted": {
    "novelty": false,
    "T": false,
    "S": false,
    "A": false,
    "focus": false
  },
  "new_dataset_collection_or_model_execution": false,
  "ephemeral_digest_verification_only": true
}
```

## Repository binding

**Observed.** This screen is based on local `main` commit
`27747a8f90a16c9309ec02e329ac6fe20a2a205d` and these exact Git objects:

| Role | Path | Git blob | SHA-256 | Bytes |
| --- | --- | --- | --- | ---: |
| Original three-candidate artifact | `notes/research/2026-09-24-g11-candidates/CANDIDATES.md` | `d1fbe16b641334b32b1353b84f6b1304680313a0` | `945aa0110d396c174c2843b0b1f0a48da6e715fe2e15175f0ff22b46ae086c7f` | 6,041 |
| Oracle screen | `notes/research/2026-09-24-g11-screen/ORACLE_SCREEN.md` | `3d9e42f8e708db23e9dc54b9ee644bcb3375e191` | `717ec587067a5142da5f3bee92ec5cbe0b95b923e3e36686b788e9c9001c265b` | 14,688 |
| Later T-gate choice recording the seq407 C1 T0 design | `notes/research/2026-09-24-t-gate-choice/T_GATE_CHOICE.md` | `7c25a4d15ee677f37ddf9b28f091caa84d1061f7` | `1766b07ac41d6d4141817ebdf84e9be9254562a6a86450e456ec296d85a30708` | 14,591 |

The distinction matters:

- **Observed.** Original C1 bundles a timestamp-verifiable provenance treatment,
  first-value anchoring, and departure from Bayesian updating without specifying
  the state, likelihood, posterior, or an information-neutral provenance arm.
- **Observed.** The later seq407 C1 T0 instead fixes two independent authenticated
  signals at quality `q=.75`, prior `.5`, counterbalances exogenous signal order,
  and randomizes only a semantic provenance receipt versus a matched placebo.
  Its primary estimand is receipt-minus-placebo first-signal carryover. Its own
  kill outcomes include ordinary primacy without an interaction, a label main
  effect alone, and a timestamp-only effect.

## Ephemeral retrieval evidence (not an admissible input)

**Observed.** The following host files still existed under `/tmp/c1build` when
checked. A deterministic digest-only rerun reproduced the logical digests; no
retrieval, dataset collection, or model inference was run here.

| Ephemeral file | Shape | File SHA-256 |
| --- | --- | --- |
| `/tmp/c1build/CORPUS.json` | 2,195 records; 310,693 bytes | `4b4c2fe48c7c1b7b89d98c681f75ca648d2d54e6fe91502eec75ac5c29ef75f0` |
| `/tmp/c1build/EVIDENCE.json` | 20 hits; 4,846 bytes | `3cc94c78e520835178037954dae89cb81810f54de13c173d623b729b5d8cab8d` |
| `/tmp/c1build/PRIOR_ART_SOLVER.py` | digest checker; 9,023 bytes | `ed7bc24e7c6d317bd9fb1bf600983344f5a5ffc986ba79594e5796ee5956f614` |

The recomputed logical corpus digest was
`616064bb531288efc9595551dffc8b614691c5be0a1cbb80b62b99a144a7b48d`;
the recomputed retrieval digest was
`54ca0c6e7c2cb7320912afa4189dde8ccc06581682a7a2c8b542886ac69d2849`.

**Observed.** None of the expected C1 report, snapshot, solver, or corpus paths
is Git-reachable from the bound base commit. `/tmp` is mutable and disposable.
These hashes are recovery evidence only: they do not make the corpus or hits a
durable, reviewable input and must not be represented as such.

## Five-source primary screen

All remote bytes and pages in this section were checked on 2026-09-25 UTC.

### 1. Kolb and Zhou — dynamic disclosure with timestamps

Source: Aaron Kolb and Beixi Zhou, [*Dynamic Disclosure with(out)
Timestamps*](https://arxiv.org/pdf/2609.25485), arXiv:2609.25485v1,
submitted 2026-09-21. The observed PDF was 689,787 bytes with SHA-256
`c856a596c100d1ea97658c5ae943f448b7315c28bf6e584fec51a11db3610071`.

- **Observed (full text).** This is a continuous-time sender-receiver model
  with a binary Markov state, at most one privately observed hard-evidence
  arrival, a passive Bayesian receiver, and perfect-Bayesian-equilibrium
  analysis. A timestamp reveals evidence age and therefore changes information,
  beliefs, and disclosure incentives. In the timestamped equilibrium, good
  evidence is disclosed immediately; bad evidence is never disclosed when the
  bad state is absorbing and otherwise is disclosed after a deterministic,
  timestamp-dependent delay.
- **Inferred collision.** This directly collides with original C1's treatment
  of a timestamp as a psychologically neutral provenance marker. It supplies a
  rational, equilibrium-changing timestamp mechanism that can resemble an
  order or anchoring effect.
- **Observed limit.** The paper does not study LLMs, semantic source labels,
  two conflicting independent signals, or a receipt-by-order factorial.
- **Inferred.** It invalidates the original bundled C1 construct but does not
  resolve the narrower seq407 semantic-receipt interaction.

### 2. Sun et al. — semantic source-label effects

Source: Xin Sun et al., [*Label Effects: Shared Heuristic Reliance in Trust
Assessment by Humans and LLM-as-a-Judge*](https://aclanthology.org/2026.acl-long.1495/),
ACL 2026 (July), pages 32378–32392. The observed official PDF was 22,743,717
bytes with SHA-256
`35e3307d3326375bd3e4b388d304fe107fbf219977764909d7ebe0b13876748f`.

- **Observed (full text).** A 2x2 health-QA design crosses actual answer source
  with a displayed Human/AI source label while holding answer text fixed under
  counterfactual label swaps. The study uses 150 health QA pairs; its human
  eye-tracking arm has 40 non-medical participants, each seeing 12 pairs. It
  reports higher trust for Human-labeled than AI-labeled identical content in
  humans and LLM judges. A `[TAG]` placebo controls label position/format for
  part of the model-side analysis.
- **Inferred collision/negative.** This establishes a semantic label main
  effect in a neighboring task. A label main effect without receipt-by-order
  interaction is explicitly a seq407 C1 kill outcome, not a pass.
- **Observed limits.** The domain is health trust assessment, not disclosure
  games or financial estimates; there is no two-signal order factorial. The
  authors limit generalization beyond health and two labels, and characterize
  attention/logit analyses as correlational rather than a complete causal
  account. Human gaze and transformer attention are not treated as the same
  mechanism.
- **Inferred.** This source raises the prior probability of a generic label
  effect while providing no evidence for C1's specific receipt-by-order
  interaction.

### 3. Samanta et al. — sequential Bayesian-reference trajectories

Source: Ankur Samanta et al., [*BayesBench: Evaluating LLM Belief Trajectories
Under Multi-Turn Evidence Accumulation*](https://arxiv.org/pdf/2606.30850),
arXiv:2606.30850v1, submitted 2026-06-29. The observed PDF was 1,786,962 bytes
with SHA-256
`07252af708e2865ef1b06115c47911bb94a2327780ef5e760cb548adcc5fcf42`.

- **Observed (full text).** BayesBench evaluates seven open-weight Llama and
  Qwen models from 3B to 70B across sequential coin, recommender, social
  judgment, and medical-triage environments. Larger models often recover
  latent structure better, yet can over-update and fail to convert that
  inference into calibrated downstream predictions.
- **Observed negative/limit.** Exact Bayesian posterior references are
  available only in the structured coin and recommender environments. The
  natural-language social and medical environments have no exact posterior
  reference. Multiple-choice probes elicit distributions but are not direct
  internal-belief measurements. The paper contains no provenance-receipt by
  evidence-order factorial.
- **Inferred.** It supplies a useful independent Bayesian-null methodology and
  warns that generic sequential miscalibration exists, but it neither supports
  nor falsifies the exact seq407 interaction.

### 4. Garcia — withdrawal and residual numerical carryover

Source: John Garcia, [*Which Number Is Sticky? What Survives Source Withdrawal
in Sequential LLM Financial Analysis*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7411618),
SSRN 7411618, written 2026-09-04 and posted 2026-09-05.

- **Observed (official abstract only).** The abstract describes a preregistered
  transcript-ablation experiment on three commercial model endpoints and 30
  fictional firms. After a randomized high/low external anchor is declared
  invalid, nine replay forms test what persists downstream. It reports that a
  prior estimate retains a small residual carrier; disclosing its tainted
  lineage did not detectably reduce that carrier. An exploratory three-firm-pair
  extension reports that withdrawal removes roughly 85% of the carryover from
  an unwithdrawn record.
- **Observed negative.** The abstract itself characterizes the pattern as a
  representation effect rather than a provenance effect. “Not detectably
  reduced” is not evidence of equivalence or a proven zero effect.
- **Observed access limit.** Direct SSRN retrieval returned HTTP 403, so the
  manuscript, methods, intervals, preregistration, and exact order controls were
  not inspected. No full-text claim is made here.
- **Unknown.** Whether the full design contains the exact semantic-receipt by
  first-signal-order contrast required by seq407.

### 5. Garcia — source-framed anchors in financial estimates

Source: John Garcia, [*Algorithmic Anchoring: How Prompt-Embedded Reference
Points Bias LLM Financial Estimates*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6366838),
SSRN 6366838, written 2026-03-03 and posted 2026-03-09.

- **Observed (official abstract only).** The abstract reports 51,000 API calls
  across three commercial models and fictional-company valuations. It says
  labeling the same number as a prior AI estimate increased estimated anchor
  sensitivity from 0.272 to 0.413, a 52% increase. This is a close semantic
  source-framing collision with C1, but the abstract does not expose C1's
  conflicting-signal/order design.
- **Observed access limit.** Direct SSRN retrieval returned HTTP 403. The full
  manuscript and its uncertainty estimates, hypothesis hierarchy, exclusions,
  and preregistration were unavailable.
- **Observed original-repository evidence.** The author's
  [`algorithmic_anchoring`](https://github.com/garcijo4/algorithmic_anchoring/tree/328a354d0e9d98ac81121202ffc716077eb736e1)
  repository at commit `328a354d0e9d98ac81121202ffc716077eb736e1`
  (2026-02-27) contains code, data, and results but no paper manuscript. Its
  pinned [`analysis_output_batch_4.txt`](https://raw.githubusercontent.com/garcijo4/algorithmic_anchoring/328a354d0e9d98ac81121202ffc716077eb736e1/results/batch/analysis_output_batch_4.txt)
  was 183,464 bytes with SHA-256
  `8c7bdf16126866fce3be9c26a14fb336417dfb161e07186411bdad54c9f133ad`.
  The output reports a base slope of `0.2717` and an adversarial interaction of
  `0.1415`; the cell-mean CR2 result gives `SE=0.0385`, Satterthwaite
  `df=6.95`, `p=0.00806`, while its 5,000-permutation within-company
  randomization inference reports `observed=0.141481`, `p=0.1406` for the same
  named interaction. The pinned
  [`R/analysis_pipeline.R`](https://github.com/garcijo4/algorithmic_anchoring/blob/328a354d0e9d98ac81121202ffc716077eb736e1/R/analysis_pipeline.R)
  was 122,811 bytes with SHA-256
  `59fb9ea93985fa21ecf2ef20434b5a46bc536a64169d960d9252e800adbfc939`.
- **Observed negative/limit.** The two reported inferential procedures disagree
  at a conventional `.05` threshold. Without the manuscript, this screen cannot
  determine their preregistered priority or safely map that interaction to the
  abstract's 52% headline.

## Bounded synthesis

- **Synthesized.** Original C1 is not scientifically identified: timestamps are
  informative in Kolb and Zhou, while semantic labels can independently move
  judgments in Sun et al. and Garcia's abstract. Those mechanisms cannot be
  bundled and called non-Bayesian provenance anchoring.
- **Synthesized.** Seq407 materially improves identification by separating an
  information-neutral semantic receipt from authenticated signal content and
  counterbalancing order. None of the three available full texts tests that
  exact receipt-by-order estimand.
- **Synthesized negative evidence.** Generic label effects and generic sequential
  over-/under-updating already exist, but each is a seq407 alternative rather
  than its pass result. Garcia 7411618 reports no detectable reduction from
  tainted-lineage disclosure in the abstract, and Garcia's repository exposes
  an interaction whose CR2 and randomization-inference conclusions differ.
- **Inferred.** The exact seq407 mechanism is narrower than the verified full
  texts, but its novelty probability should be discounted because the two
  inaccessible Garcia manuscripts are unusually close in construct, domain,
  and sequential framing.
- **Unknown.** Whether either Garcia manuscript contains the exact factorial,
  whether the conflicting repository inferences are adjudicated in the paper,
  and whether any still-unread source closes the remaining interaction.

This supports only `insufficient_full_text_binding`. It does not support
“prior art not found,” a novelty claim, or T/S/A/focus clearance.

## C1 A-data check

**Observed.** At the bound base, the candidate says only “historical crypto
asset disclosure events” and names no dataset or repository asset. The Oracle
screen records A as blocked. No committed C1-specific A-data artifact supplies
all of the minimum fields needed for an as-of audit: source identity, event and
asset timestamps, an immutable as-of snapshot, revision/correction history,
and a pre-event market-price observation with venue/timezone semantics.

Therefore the machine state is `c1_a_data: absent`. General crypto spot-price
captures are not a disclosure-event dataset and cannot silently substitute for
one.

## Conditions for reopening

Reopen this screen only after all of the following are durably bound and
reviewed:

1. lawful full-text access to both Garcia manuscripts, with exact page/passage
   locators and a reconciliation of CR2 versus randomization inference;
2. a Git-reachable corpus/hit snapshot if the vector retrieval is to be used;
3. a claim matrix testing the exact seq407 receipt-by-order interaction rather
   than generic label or primacy effects; and
4. a named C1 A dataset with the as-of and revision fields listed above, or an
   explicit decision to keep A blocked.

Until then, stop this source screen at `insufficient_full_text_binding`. This
note itself grants no authority to select C1, register a study, allocate Flash
to a C1 study/model run, or infer focus; it does not bar separately authorized
source-bound modeling or research.
