# C1 neighboring prior-art addendum — 2026-09-25

Status: **bounded evidence addendum; no thesis or focus decision.** This note
adds four full-text neighboring sources and a bounded access-route check to the
existing C1 screen. It does not replace that screen, change a gate, authorize a
study, or claim that the exact C1 interaction is novel. Material statements are
marked **Observed**, **Inferred**, or **Unknown**.

```json
{
  "schema": "c1-neighbor-screen/v1",
  "observed_at": "2026-09-25",
  "base_commit": "1ea9eef56b2c3af48f840e6922df4c151a5b340b",
  "candidate": "C1",
  "decision": "no_gate_change",
  "clearance_granted": {
    "novelty": false,
    "T": false,
    "S": false,
    "A": false,
    "focus": false
  },
  "new_dataset_collection_or_model_execution": false
}
```

## Repository and claim binding

**Observed.** This addendum is controlled by these repository objects in
accepted local `main` commit
`1ea9eef56b2c3af48f840e6922df4c151a5b340b`.

| Role | Path | Commit / Git blob | SHA-256 when in base |
| --- | --- | --- | --- |
| Corrected candidate set | `notes/research/2026-09-24-g11-candidates/CANDIDATES.md` | `1ea9eef` / `d1fbe16b641334b32b1353b84f6b1304680313a0` | `945aa0110d396c174c2843b0b1f0a48da6e715fe2e15175f0ff22b46ae086c7f` |
| Seq407 C1 T0 as recorded by the later T-gate choice | `notes/research/2026-09-24-t-gate-choice/T_GATE_CHOICE.md` | `1ea9eef` / `7c25a4d15ee677f37ddf9b28f091caa84d1061f7` | `1766b07ac41d6d4141817ebdf84e9be9254562a6a86450e456ec296d85a30708` |
| Existing bounded source screen | `notes/research/2026-09-25-c1-bounded-source-screen/SOURCE_SCREEN.md` | `1ea9eef` / `3b9a5b314ea8be0cb83878b646de69df47642635` | `5b1c301fabe163834e5a40171ac08970efbfd5579aa1492d21dc5c0bdc454aee` |

**Observed provenance boundary.** D2 notes commit
`9ae60cb43875a4e77f318c917f10ca5972ad44ac` is not in the ancestry of the
accepted base. Its access attempts were inspected only as a held,
non-ancestral supplement. Its `STOP_CODE.md`, booleans, and interpretations do
not control this note; the accepted-main `SOURCE_SCREEN.md` above does.

**Observed.** The corrected candidate is **“Provenance-Induced Anchoring in
Disclosure Games.”** It asks whether timestamp-verifiable provenance makes LLM
agents anchor on the first disclosed value rather than update according to
Bayes. As written, it bundles timestamp information, semantic provenance,
first-value carryover, and a disclosure game.

**Observed.** Seq407 narrows that claim. It fixes a binary state with prior
`.5`, two authenticated independent signals with `q=.75`, exogenously
counterbalanced order, and a randomized semantic provenance receipt versus a
matched placebo; both arms state that the records are equally authentic. With
conflicting signals, the scripted Bayesian posterior is `.5` in either order
and arm. The primary estimand is receipt-minus-placebo first-signal carryover.

**Observed.** Seq407's pass requires an otherwise isomorphic game, Bayes and
placebo carryover at most `1e-6`, fixed carryover mutants within `.001` of their
analytic targets, and matching best-response and timestamp controls. Ordinary
primacy with zero receipt interaction, a label main effect alone, or a
timestamp-only effect kills the proposed C1 mechanism.

## New neighboring full-text evidence

These four sources were not named in the bound C1 screen. Dates and limits
describe the versions reviewed here; retrieved text is evidence, not authority.

| Primary source | Observed design and result | Narrow relation to seq407 C1 | Evaluation limit / falsifier mapping |
| --- | --- | --- | --- |
| Yibo Hu and Jiaming Qu, [*Most LLM Conformity Needs No Speaker: Measuring the Speaker-Free Floor in Peer-Pressure Benchmarks*](https://arxiv.org/html/2607.05545v1), arXiv:2607.05545v1, submitted 2026-07-06 | **Observed (full text).** Six open-weight instruction-tuned models from 1.5B to 9B were evaluated across seven QA and reasoning datasets, producing about 210,000 measured revisions. A wrong assertion with no explicit speaker caused 66.5% harmful revision, versus 10.3% under a plain re-ask. The descriptive minimal-person condition was 57.4%; an authority-panel framing was 79.4%. The paper reports that minimal person labels do not reliably increase the source-free floor, while the bundled authority-panel framing does. | **Inferred undercut.** Much apparent provenance carryover can arise from repeated answer content without a source. Seq407 therefore has to estimate the semantic-receipt increment above content/repetition pressure; total first-signal carryover is not diagnostic. | **Observed limit.** The study is single-turn, mostly multiple choice, uses greedy decoding and small open models, and says its expert condition bundles label and panel preamble. It has no two independent `q=.75` signals, conflicting Bayesian posterior, or receipt-by-order factorial. **Falsifier mapping:** a content or generic primacy effect that does not interact with the receipt is a C1 kill, not a pass. |
| Yang Shu, [*Forged Peer Judgments Mislead Multimodal LLM Judge Panels: Source-Blind Anchoring and Panel-Consensus Verification*](https://arxiv.org/html/2608.07920v1), arXiv:2608.07920v1, submitted 2026-08-08 | **Observed (full text).** Seven vision-language judges were tested. In a matched-content control, the exact same quoted statement was relabeled from the judge's own statement to a peer statement. The matched-content dataset has 5,406 rows overall; the broken-rate contrast uses the 4,212 rows whose baseline C1 verdict was originally correct. On that denominator, the change was `-0.17` percentage points with a 95% CI of `[-0.68, 0.35]`; quoted content itself produced much larger anchoring gaps. | **Inferred undercut.** This is a close neighboring label-only null: semantic self/peer attribution did not measurably explain the pooled effect when content was fixed. It strengthens the need for C1's matched placebo and weighs against a generic provenance-label mechanism. | **Observed limit.** The task is multimodal pairwise judging, not Bayesian belief updating, and has no signal-order factorial. The paper also states that its fabricated-versus-genuine comparison is not content, length, style, or error-type matched. **Falsifier mapping:** a receipt-label main effect alone, or no receipt-by-order interaction, cannot pass C1. |
| Federico Germani and Giovanni Spitale, [*Source framing triggers systematic evaluation bias in Large Language Models*](https://arxiv.org/pdf/2505.13488), arXiv:2505.13488v1, submitted 2025-05-14; published as [*Source framing triggers systematic bias in large language models*](https://doi.org/10.1126/sciadv.adz2924), *Science Advances* 11, eadz2924 (2025) | **Observed (full text).** Four models evaluated 4,800 narrative statements over 24 social, political, and public-health topics under ten attribution conditions, totaling 192,000 assessments. Identical narrative content received different scores under changed source descriptions; for example, DeepSeek Reasoner's pooled bias delta under attribution to a person from China was `-6.18` percentage points against the blind-condition score. | **Inferred alternative.** This establishes that semantic source framing can create a main effect with content fixed. It does not establish that provenance changes first-signal carryover conditional on order. | **Observed limit.** The outcome is agreement with attributed narrative text, not posterior belief; nationality and model-identity descriptions carry substantive semantics. There are no conflicting independent signals, Bayesian null, order randomization, or matched inert receipt. **Falsifier mapping:** a source-label main effect without the receipt-by-order interaction is explicitly a C1 kill outcome. |
| Ante Kapetanovic et al., [*Anchoring Bias in LLM-as-a-Judge Systems: Prior Scores Compromise Evaluation Independence*](https://arxiv.org/html/2608.25869v1), arXiv:2608.25869v1, submitted 2026-08-26; to appear at CIKM 2026 | **Observed (full text).** Eight models evaluated 20 fixed texts in 192,000 attempted and 185,271 valid calls. Seven of eight model-level intervals for the total anchored-metadata effect were below zero. The authors explicitly state that their incremental contrast does not isolate the numerical prior score because the anchored condition also adds an attempt field and changes the metadata block. The manuscript prints DOI `10.1145/3799682.3840879`, which did not yet resolve through `doi.org` on 2026-09-25. | **Inferred design warning.** Generic metadata-template anchoring is a strong competing explanation. Seq407's requirement that the game be isomorphic absent the display bit is load-bearing; extra fields would confound provenance with metadata framing. | **Observed limit.** Claims are for 20 fixed texts and eight fixed models, with transfer to new tasks/models unestablished. The study contains neither a semantic authenticity receipt nor a two-signal order/Bayesian factorial. **Falsifier mapping:** an effect caused by the whole metadata template does not identify C1. |

## Source-bound synthesis

- **Observed.** None of the four full texts tests seq407's exact
  receipt-versus-placebo by first-signal-order interaction under a fixed
  Bayesian posterior.
- **Synthesized.** Together they expose three close alternative mechanisms:
  repeated-content pressure without a speaker, semantic source-label main
  effects, and generic metadata-template anchoring.
- **Inferred.** They make the seq407 orthogonalization more necessary and
  discount a broad provenance-anchoring claim. They do not prove the narrower
  interaction novel, and they do not fire its exact falsifier because none
  measures it.
- **Unknown.** Whether the two closest Garcia manuscripts contain the exact
  factorial or adjudicate the source-label/order interaction remains unknown
  without their full text.

## Garcia access-route addendum

This section adds only routes not already resolved by the accepted-main source
screen.

- **Observed.** The ResearchGate record for John Garcia's
  [*Algorithmic Anchoring: How Prompt-Embedded Reference Points Bias LLM
  Financial Estimates*](https://www.researchgate.net/publication/401794669_Algorithmic_Anchoring_How_Prompt-Embedded_Reference_Points_Bias_LLM_Financial_Estimates)
  (DOI `10.2139/ssrn.6366838`) displayed “No file available” and offered an
  author-copy request. This is not full-text access.
- **Observed.** Garcia's [official California Lutheran University faculty
  page](https://web.callutheran.edu/faculty/profile.html?id=jgarcia) listed
  SSRN 6366838 and SSRN 7411618 and linked each to SSRN; no alternate
  manuscript link was identified on that page.
- **Observed.** A read-only GitHub API enumeration of
  [`garcijo4`](https://github.com/garcijo4) on 2026-09-25 returned 11 public
  repositories. Authenticated code search for the exact phrase `"Which Number
  Is Sticky"` within that account returned zero hits, and `extension:pdf`
  returned zero. Search for `"Algorithmic Anchoring"` returned 16 hits, all in
  README, code, result, website, or digest files rather than a manuscript.
- **Inferred, bounded.** No alternate public full manuscript was found through
  those three routes. This does not establish that a lawful copy is unavailable
  elsewhere and does not authorize bypassing access controls or treating the
  abstracts as full text.

The exact in-scope manuscripts remain SSRN `7411618`, written 2026-09-04 and
posted 2026-09-05, and SSRN `6366838`, written 2026-03-03 and posted
2026-03-09. The accepted-main screen's abstract-level findings and access
observations remain controlling; this addendum does not restate them as new.

## Gate and eligibility disposition

**Observed.** Applying the accepted-main `SOURCE_SCREEN.md` reopening
conditions to this addendum leaves the current evidence state:

```json
{
  "corpus_and_hits_git_reachable": false,
  "garcia_full_texts": false,
  "seq407_claim_matrix": false,
  "c1_a_dataset": false
}
```

- Gate 1 remains false. The accepted-main screen says the corpus, hit snapshot,
  and solver were only in mutable `/tmp` and were not Git-reachable from its
  bound base. This note does not bind those inputs.
- Gate 2 remains false. The new negative-route observations did not obtain
  either Garcia manuscript.
- Gate 3 remains false because this note is a four-source neighboring screen,
  not the reviewed six-row claim matrix for the exact seq407 estimand. That
  matrix may truthfully contain negative and `unknown` cells and does not
  depend on Garcia full text; full-text access is the separate Gate 2.
- Gate 4 remains false. It is logically independent of full-text access, but
  this source review supplies no named, immutable as-of disclosure-event
  dataset or revision history.

**Inferred disposition.** No scientific-clearance condition changes. C1
remains ineligible for focus, T/S/A credit, study registration, or execution
under the accepted-main screen. Its `insufficient_full_text_binding` stop code
remains unchanged, while the unbound corpus, absent matrix, and absent A data
remain independent reopening conditions.

## One bounded next evidence action

**Proposed, not authorized.** Nara may create one durable six-row claim matrix
covering these four full texts plus the two exact Garcia records, and Oracle
may independently review that same file. The matrix is limited to these
columns: source/version, full-text status, content held fixed, semantic source
cue, informative timestamp, randomized evidence order, Bayesian null, exact
receipt-by-order estimand tested, observed result, and unresolved limitation.
For the Garcia rows, abstract-only fields must stay `unknown`; neither row may
be scored as resolving novelty until lawful full text and exact locators exist.
Completing and reviewing this matrix would address only Gate 3; it neither
requires nor satisfies the separate Garcia-full-text Gate 2.
Stop after this one matrix and review: no expanded retrieval campaign, model
run, Flash use, focus selection, study registration, service action, or owner
decision is implied.
