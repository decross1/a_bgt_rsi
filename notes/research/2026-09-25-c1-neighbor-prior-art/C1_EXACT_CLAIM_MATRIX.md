# C1 exact-claim matrix — 2026-09-25

Status: **bounded six-source evidence classification; unreviewed and not a gate
decision.** This matrix compares four inspected full texts and the two exact
García records with the narrow seq407 C1 estimand. It neither selects C1 nor
claims novelty, registers a study, grants T/S/A or focus credit, or authorizes
model execution. Material statements are labeled **Observed**, **Inferred**,
or **Unknown**.

```json
{
  "schema": "c1-exact-claim-matrix/v1",
  "observed_at": "2026-09-25",
  "accepted_main_commit": "1ea9eef56b2c3af48f840e6922df4c151a5b340b",
  "candidate": "C1",
  "matrix_rows": 6,
  "exact_receipt_by_order_result": {
    "four_full_text_rows": "no",
    "two_garcia_abstract_rows": "unknown"
  },
  "gate_state_changed": false,
  "clearance_granted": false,
  "new_dataset_collection_or_model_execution": false
}
```

## Claim and repository binding

**Observed.** The controlling candidate is *Provenance-Induced Anchoring in
Disclosure Games*. This matrix uses its narrower seq407 T0 specification as
recorded in `T_GATE_CHOICE.md`: binary state, prior `.5`, two authenticated
independent signals with `q=.75`, conflicting signals disclosed in exogenously
counterbalanced order, and a randomized semantic provenance receipt versus a
matched placebo. Both arms state that the records are equally authentic. The
scripted Bayesian posterior is `.5` in either order and arm. The exact estimand
is the receipt-minus-placebo difference in first-signal carryover—equivalently,
the semantic-receipt by first-signal-order interaction—not a label main effect,
generic primacy, timestamp effect, or metadata effect.

The evidence boundary is fixed by these repository objects:

| Role | Path | Commit / Git blob | SHA-256 |
| --- | --- | --- | --- |
| Corrected candidate | `notes/research/2026-09-24-g11-candidates/CANDIDATES.md` | `1ea9eef` / `d1fbe16b641334b32b1353b84f6b1304680313a0` | `945aa0110d396c174c2843b0b1f0a48da6e715fe2e15175f0ff22b46ae086c7f` |
| Seq407 specification | `notes/research/2026-09-24-t-gate-choice/T_GATE_CHOICE.md` | `1ea9eef` / `7c25a4d15ee677f37ddf9b28f091caa84d1061f7` | `1766b07ac41d6d4141817ebdf84e9be9254562a6a86450e456ec296d85a30708` |
| Accepted-main source screen | `notes/research/2026-09-25-c1-bounded-source-screen/SOURCE_SCREEN.md` | `1ea9eef` / `3b9a5b314ea8be0cb83878b646de69df47642635` | `5b1c301fabe163834e5a40171ac08970efbfd5579aa1492d21dc5c0bdc454aee` |
| Accepted neighboring-source screen | `notes/research/2026-09-25-c1-neighbor-prior-art/C1_NEIGHBOR_SCREEN.md` | `9f098382b930dbf7b0aeee80a0f605d89ac39bc6` / `eff7d9bcb5762dab259121321217080b08052039` | `f707a1efba72dd23b0e23df7212e269e7e1097d563249a918abec9d212d66773` |

Classification vocabulary: **Yes** means the component was directly observed
in the inspected full text; **No** means the inspected full text used a
different design or construct; **Partial** means a neighboring component was
reported but exact matching could not be established; **Unknown** means the
official abstract or record did not expose enough information. A **No** in the
“exact” column means “this source did not test the seq407 estimand,” not “the
source estimated the interaction and found a null.” An **Unknown** is never
silently converted to a negative result.

## Six-row matrix

| Primary source and access | Observed population, intervention, outcome | Seq407 components observed | Exact receipt × order? | Adjacent mechanism and unresolved limit |
| --- | --- | --- | --- | --- |
| Yibo Hu and Jiaming Qu, [*Most LLM Conformity Needs No Speaker: Measuring the Speaker-Free Floor in Peer-Pressure Benchmarks*](https://arxiv.org/html/2607.05545v1), arXiv:2607.05545v1, submitted 2026-07-06. **Observed access:** versioned full text inspected. | **Observed P/I/O.** Six open-weight instruction models (1.5B–9B), seven QA/reasoning datasets, and about 210,000 revisions; a fixed asserted answer is presented with no source, a minimal person, a richer peer, or an authority panel, with a plain re-ask baseline. Harmful revision was 66.5% without a speaker and 10.3% on re-ask; the descriptive minimal-person and authority-panel rates were 57.4% and 79.4%. | Content fixed across source-ladder arms: **Yes**. Semantic source cue: **Yes**. Informative timestamp: **No**. Randomized order of two independent signals: **No** (line-order variants are not the required signal-order factorial). Scripted Bayesian null: **No**. | **No (Observed).** There is no receipt/placebo × first-signal-order estimand under a fixed `.5` posterior. | **Inferred adjacent mechanism:** repeated-content pressure and bundled authority framing. **Observed limit:** single-turn, mostly multiple choice, greedy decoding, small open models; the expert arm bundles label and panel preamble. It cannot distinguish C1 from ordinary content-driven revision. |
| Yang Shu, [*Forged Peer Judgments Mislead Multimodal LLM Judge Panels: Source-Blind Anchoring and Panel-Consensus Verification*](https://arxiv.org/html/2608.07920v1), arXiv:2608.07920v1, submitted 2026-08-08. **Observed access:** versioned full text inspected. | **Observed P/I/O.** Seven vision-language judges on two datasets; a matched-content control relabels the exact same statement from the judge's own statement to a peer statement. There were 5,406 matched rows overall. Among the 4,212 rows whose baseline C1 verdict was originally correct, the broken-rate contrast was `-0.17` percentage points, 95% CI `[-0.68, 0.35]`. | Content fixed: **Yes**. Semantic source cue: **Yes**. Informative timestamp: **No**. Randomized order of two independent signals: **No**. Scripted Bayesian null: **No**. | **No (Observed).** The matched contrast is a label main-effect test, not a receipt × order test. | **Inferred adjacent mechanism/negative evidence:** a close label-only null weighs against generic self/peer provenance as the pooled cause; quoted content produces stronger anchoring. **Observed limit:** multimodal pairwise judging rather than posterior updating; the separate fabricated/genuine comparison is not matched on content, length, style, or error type. |
| Federico Germani and Giovanni Spitale, [*Source framing triggers systematic evaluation bias in Large Language Models*](https://arxiv.org/pdf/2505.13488), arXiv:2505.13488v1, submitted 2025-05-14; final article [*Source framing triggers systematic bias in large language models*](https://doi.org/10.1126/sciadv.adz2924), *Science Advances* 11, eadz2924 (2025). **Observed access:** full manuscript inspected. | **Observed P/I/O.** Four models rated 4,800 narratives spanning 24 social, political, and public-health topics under ten attribution conditions, yielding 192,000 assessments. Identical narrative content received different scores; DeepSeek Reasoner's pooled Chinese-person attribution contrast was `-6.18` **percentage points absolute** versus blind. | Content fixed: **Yes**. Semantic source cue: **Yes**. Informative timestamp: **No**. Randomized order of two independent signals: **No**. Scripted Bayesian null: **No**. | **No (Observed).** It estimates source-framing main effects, not conditional first-signal carryover. | **Inferred adjacent mechanism:** identity/source-label framing can move evaluations with content fixed. **Observed limit:** agreement ratings are not posterior beliefs; nationality and identity descriptions carry substantive semantics; there are no conflicting signals, matched inert receipt, or evidence-order factorial. A label main effect alone is a seq407 kill alternative. |
| Ante Kapetanovic et al., [*Anchoring Bias in LLM-as-a-Judge Systems: Prior Scores Compromise Evaluation Independence*](https://arxiv.org/html/2608.25869v1), arXiv:2608.25869v1, submitted 2026-08-26, to appear CIKM 2026. **Observed access:** versioned full text inspected. The manuscript prints DOI `10.1145/3799682.3840879`; its resolver returned 404 on 2026-09-25. | **Observed P/I/O.** Eight models rated 20 fixed texts in 192,000 attempted and 185,271 valid calls. Conditions add revision framing and then attempt/prior-score metadata. Seven of eight model-level intervals for the total anchored-metadata effect were below zero. | Evaluated text fixed: **Yes**, but the metadata block changes. Semantic authenticity receipt: **No**. Informative timestamp: **No**. Randomized order of two independent signals: **No**. Scripted Bayesian null: **No**. | **No (Observed).** Numeric/evaluation metadata anchoring is not a semantic receipt × signal-order interaction. | **Inferred adjacent mechanism/design warning:** generic prompt-metadata and numerical anchoring can mimic provenance effects. **Observed limit:** the authors state that the incremental contrast does not isolate prior score because an attempt field and the block also change; transfer beyond 20 texts/eight models is unknown. |
| John Garcia, [*Which Number Is Sticky? What Survives Source Withdrawal in Sequential LLM Financial Analysis*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7411618), SSRN 7411618, written 2026-09-04, posted 2026-09-05; official record lists 49 pages and CC BY 4.0. **Observed access:** official abstract/record only; no lawful full manuscript was obtained through the bounded routes recorded in `C1_NEIGHBOR_SCREEN.md`. | **Observed abstract-level P/I/O.** Three commercial endpoints, 30 fictional firms, and independent downstream calls; a randomized high/low upstream fair-value anchor is withdrawn, then a frozen valuation/rationale is replayed in nine controlled forms. The abstract reports a prior-estimate carrier difference of `0.027` of the clean center versus a byte-identical redacted control (about 6% of the upstream effect) and says tainted-lineage disclosure did not detectably reduce it. “Not detectably” is not equivalence. | Content fixed: **Partial/Unknown** (the abstract names frozen replay and a byte-identical control, but not the complete matching structure). Semantic source/lineage cue: **Yes at abstract level**. Informative timestamp: **Unknown**. Randomized order of two independent signals: **Unknown**. Scripted Bayesian null: **Unknown**. | **Unknown.** The abstract does not demonstrate the seq407 factorial, but abstract silence cannot establish its absence. | **Inferred adjacent mechanism:** residual numerical carryover after source withdrawal and a representation-versus-provenance contrast. **Unknown:** full methods, uncertainty intervals, preregistration, exact order controls, and whether any condition identifies receipt-minus-placebo first-signal carryover. |
| John Garcia, [*Algorithmic Anchoring: How Prompt-Embedded Reference Points Bias LLM Financial Estimates*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6366838), SSRN 6366838, written 2026-03-03, posted 2026-03-09; official record lists 94 pages and all rights reserved. **Observed access:** official abstract/record only; the author's pinned repository contains code/results but no manuscript. | **Observed abstract-level P/I/O.** The record reports 51,000 API calls to Claude Haiku 4.5, GPT-5-mini, and Gemini 2.5 Flash on fictional firms; randomized prompt anchors are presented, including the same number labeled as a prior AI estimate. Reported anchor sensitivity rises from `0.272` to `0.413` (52%). | Content fixed: **Partial/Unknown** (the same number is reported, but exact prompt matching is unavailable). Semantic source cue: **Yes at abstract level**. Informative timestamp: **Unknown**. Randomized order of two independent signals: **Unknown**. Scripted Bayesian null: **Unknown**. | **Unknown.** The abstract exposes a source-label interaction, not enough design detail to establish or exclude seq407's receipt × order estimand. | **Inferred adjacent mechanism:** source-framed numerical anchoring. **Observed repository limit:** at pinned commit [`328a354`](https://github.com/garcijo4/algorithmic_anchoring/tree/328a354d0e9d98ac81121202ffc716077eb736e1), [`analysis_output_batch_4.txt`](https://raw.githubusercontent.com/garcijo4/algorithmic_anchoring/328a354d0e9d98ac81121202ffc716077eb736e1/results/batch/analysis_output_batch_4.txt) labels both CR2 (`p=.00806`) and randomization inference (`p=.1406`) for the named interaction as PRIMARY. **Unknown:** manuscript priority, preregistration, exclusions, uncertainty treatment, reconciliation of those procedures, and any evidence-order factorial. |

## Source-bound disposition

- **Observed.** All four available full texts are exact-design negatives: each
  studies a neighboring label, content, or metadata mechanism, and none tests
  receipt-minus-placebo first-signal carryover with the seq407 Bayesian null.
  They are not null estimates of that unmeasured interaction.
- **Observed/Unknown.** The two García records are unusually close in construct,
  but only official abstracts and record metadata were available. Their exact
  seq407 cells therefore remain **Unknown**, not **No**.
- **Synthesized.** The six rows identify repeated-content pressure, source-label
  main effects, and generic numerical/metadata anchoring as live alternatives.
  They produce no exact positive hit, but this bounded result is not “prior art
  not found” and cannot establish novelty.
- **Observed governance boundary.** The accepted-main `SOURCE_SCREEN.md` remains
  controlling. This unreviewed matrix does not change any gate boolean or its
  `insufficient_full_text_binding` stop disposition. Independent review may
  determine whether the artifact satisfies the separate matrix deliverable;
  it cannot make the García full texts available, bind the ephemeral corpus,
  supply C1 A data, or grant thesis/focus/T/S/A clearance.

## Bounded next evidence action

**Proposed, not authorized.** Oracle or Nara may independently verify the six
row classifications against the four linked full texts and the two official
SSRN records, recording only corrections to source-access status, P/I/O, or
the exact-estimand cells. Stop after that review. Do not infer an absent García
factorial from the abstracts, expand retrieval, select a thesis, register or
run a study, use Flash, or change services on the strength of this matrix.
