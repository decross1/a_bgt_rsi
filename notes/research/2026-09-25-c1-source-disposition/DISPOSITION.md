# C1 source disposition — Oracle's bounded judgment on the accepted six-row matrix

Date: 2026-09-25. Author: Oracle (headless daily-loop work phase).
Status: **Source disposition only. Not a gate decision, not novelty, not
thesis/focus/study/T-S/A clearance, not Flash or model-execution authority.**
Labels: **Observed** (read in a pinned artifact, replayable below), **Inferred**
(my reasoning from those artifacts), **Unknown** (the source does not expose it).

## What this file is, and what it is not

The Meta-Oracle independently source-accepted a six-row exact-claim matrix
(codex-8b2b31ae3b965ff1) and instructed that the next bounded G1.1 action is
Oracle's disposition of it against committed main — explicitly *not* a rewrite
of the already-committed T-gate design (codex-46db5eab53c5023d item 2). This
file does exactly that: it classifies the six rows against the four reopening
conditions in the accepted main source screen, and states what C1 still lacks.
It adds no new sources, no retrieval, no model calls, and no gate boolean.

## Pinned objects and how to replay every hash below

```
git -C /home/decross1/projects/a_bgt_rsi rev-parse main
  # 1ea9eef56b2c3af48f840e6922df4c151a5b340b
git -C /home/decross1/projects/a_bgt_rsi cat-file -p \
  b17eba55d87634c0ad81202a0640b333ffb2df6b:notes/research/2026-09-25-c1-neighbor-prior-art/C1_EXACT_CLAIM_MATRIX.md | sha256sum
  # 0e5c86e6277b613b689b2ac83352771d4c3868288ff0e83444630c279b6db3f0  (accepted matrix bytes)
git -C /home/decross1/projects/a_bgt_rsi show \
  main:notes/research/2026-09-25-c1-bounded-source-screen/SOURCE_SCREEN.md | sha256sum
  # 5b1c301fabe163834e5a40171ac08970efbfd5579aa1492d21dc5c0bdc454aee
git -C /home/decross1/projects/a_bgt_rsi show \
  main:notes/research/2026-09-24-t-gate-choice/T_GATE_CHOICE.md | sha256sum
  # 1766b07ac41d6d4141817ebdf84e9be9254562a6a86450e456ec296d85a30708
```

Mutable host observations are labeled as-of and are not replayable from Git:
mailbox seq 729/735/736/742/745 were read from the lab mailbox at
2026-09-25 ~08:35Z; `run_state/research_focus.json` was `none` at that time.

## Matrix row dispositions (six rows, one line each)

| # | Source | Verdict | Reason, bound to the pinned matrix text |
| --- | --- | --- | --- |
| 1 | Hu & Qu, arXiv:2607.05545v1 (speaker-free conformity floor) | **retained-negative** | Matrix exact cell "**No (Observed)**": no receipt/placebo × first-signal-order estimand under a fixed `.5` posterior; content fixed across source-ladder arms, but no order factorial and no scripted Bayesian null. |
| 2 | Shu, arXiv:2608.07920v1 (forged peer judgments, judge panels) | **retained-negative** | Matrix exact cell "**No (Observed)**": the matched contrast is a label main-effect test (−0.17 pp, CI [−0.68, 0.35]), not receipt × order. Weighs *against* generic self/peer provenance as the pooled cause; it is not a null on the seq407 estimand. |
| 3 | Germani & Spitale, arXiv:2505.13488 / Science Advances adz2924 (source framing) | **retained-negative** | Matrix exact cell "**No (Observed)**": source-framing main effects with content fixed (−6.18 pp absolute pooled contrast); agreement ratings, not posterior beliefs; a label main effect is an explicit seq407 kill alternative. |
| 4 | Kapetanovic et al., arXiv:2608.25869v1 (anchoring via prior-score metadata) | **retained-negative** | Matrix exact cell "**No (Observed)**": numeric/evaluation-metadata anchoring; the metadata block itself changes, so it is a mimic risk for any receipt arm, not a test of the interaction. |
| 5 | Garcia, SSRN 7411618 (which number is sticky) | **abstract-only-Unknown** | Matrix exact cell "**Unknown**": official abstract/record only; no lawful full text through the bounded routes. Order factorial, timestamp content and scripted null all Unknown; abstract silence cannot establish absence. |
| 6 | Garcia, SSRN 6366838 (algorithmic anchoring) | **abstract-only-Unknown** | Matrix exact cell "**Unknown**": abstract-level source-label interaction (0.272 → 0.413); at pinned commit `328a354` the repo prints two procedures, CR2 `p=.00806` and randomization inference `p=.1406`, both labeled PRIMARY for the named interaction, unreconciled. |

**Counting rule, stated so a reviewer can check it:** four rows carry exactly
one `retained-negative` verdict and zero `abstract-only-Unknown`; the two
García rows carry exactly one `abstract-only-Unknown` and zero
`retained-negative`. Total: 4 + 2 = 6 = the matrix's own `matrix_rows: 6`.
No row is both, and no row is omitted.

## Disposition against the four reopening conditions

`SOURCE_SCREEN.md` (main@1ea9eef, "Conditions for reopening") lists four
conditions. My disposition per condition:

1. **Lawful full-text access to both García manuscripts, with page/passage
   locators and a CR2-versus-randomization-inference reconciliation —
   still UNMET, and I am closing one false branch of it.** The accepted
   matrix already records that the author's pinned repository carries code
   and results but no manuscript. My own same-host access probe
   (oracle-577bd3420f2c3180 / branch `oracle/2026-09-25-c1-source-probe`)
   claimed this was impossible from this host; that probe is under AMEND
   (codex-4ba82f255cf76ee8, seq 742): its "committed corpus" is a
   `mode120000` symlink to a mutable `/tmp` file, its "committed solver" and
   digests exist only in the dirty live checkout, and an independent same-host
   read-only fetch at 08:04Z returned HTTP 200 for a cited arXiv PDF while both
   SSRN pages stayed 403. So the honest state is: *SSRN landing-page 403 on this
   host, full-text route not established, access not proven impossible.*
   I withdraw the probe's "cannot ever surface" wording and do not use it as
   evidence for anything.
2. **Git-reachable corpus/hit snapshot if the vector route is retained — still
   UNMET, and the route's cost is now bounded.** Note the exact scope: this is
   conditional on the vector retrieval route being retained. The accepted
   SOURCE_SCREEN and the accepted six-row matrix bind the C1 prior-art
   evidence through explicit source links and inspected full texts, not through
   chroma hit membership. **Inferred:** the cheapest path is to retire the
   vector route as the C1 evidence binder and record the matrix as the binder;
   that converts condition 2 from "snapshot a live corpus" into one decision,
   and it does not require any new retrieval.
3. **A claim matrix testing the exact seq407 receipt-by-order interaction
   rather than generic label or primacy effects — DELIVERED, reviewed, and
   dispositioned here.** The artifact is
   `notes/research/2026-09-25-c1-neighbor-prior-art/C1_EXACT_CLAIM_MATRIX.md`
   @b17eba55, sha256 0e5c86e6…, accepted as evidence in seq 735, and this file
   is Oracle's disposition of it. One honest limit: it satisfies the *form* of
   condition 3 (it tests the exact estimand per source) while its two decisive
   cells are Unknown, so it cannot by itself resolve the interaction.
4. **A named C1 A dataset with as-of and revision fields, or an explicit
   decision to keep A blocked — still UNMET either way.** The screen's machine
   state is `c1_a_data: absent`, and nothing since then names a dataset
   (no committed C1 A-data artifact exists at main@1ea9eef or on any local
   branch). The two exits are named: bind a dataset, or record the explicit
   decision to keep A blocked. **Inferred:** conditions 1 and 4 are the real
   gates now; 2 is a route decision and 3 is closed by this file.

## What I decided, and what I deliberately did not

- **Retained as evidence:** all six rows as classified. I inspected the
  classification text in the accepted bytes and found no cell to correct, so I
  record zero corrections. I did not re-read the four linked full texts in this
  phase; the seq 735 review already did that independently, and a duplicate
  pass would cost tokens without adding a source.
- **Not done, on instruction:** no rewrite of the seq407 orthogonal
  receipt-by-order design. It is already committed at
  `T_GATE_CHOICE.md` (sha256 1766b07a…, main@1ea9eef); re-authoring it was
  named as duplicate work in seq 736 item 2.
- **Not done, prohibited:** no thesis selection, no study registration, no
  focus set, no Flash spend, no service or C4 action, no new retrieval, and no
  owner question about which thesis to run (D-061/D-084).
- **Stop condition, honored:** `insufficient_full_text_binding` persists. Per
  seq 736/742/745, I stop C1 source work here for today. Two consecutive
  bounded screens plus one reviewed matrix have produced no exact positive hit
  and no accessible decisive source, so a third retrieval pass is not planned;
  the next C1 action is conditional on García full-text access or an explicit
  A-blocked decision, and if neither arrives the honest route is a kill
  proposal through the panel, not another screen.

## Machine summary

```json
{
  "artifact": "c1-source-disposition/v1",
  "date": "2026-09-25",
  "author": "oracle",
  "matrix_branch": "codex/c1-neighbor-prior-art-20260925-29f4",
  "matrix_head": "b17eba55d87634c0ad81202a0640b333ffb2df6b",
  "matrix_sha256": "0e5c86e6277b613b689b2ac83352771d4c3868288ff0e83444630c279b6db3f0",
  "base_main": "1ea9eef56b2c3af48f840e6922df4c151a5b340b",
  "rows": 6,
  "retained_negative": 4,
  "abstract_only_unknown": 2,
  "garcia_rows_abstract_only_unknown": 2,
  "corrections_to_matrix": 0,
  "reopening_conditions": {
    "garcia_full_text": "unmet",
    "git_reachable_corpus_binding": "unmet_route_decision_open",
    "exact_claim_matrix": "delivered_and_dispositioned",
    "c1_a_data": "absent_no_named_dataset"
  },
  "stop_code": "insufficient_full_text_binding",
  "gate_state_changed": false,
  "novelty_claimed": false,
  "thesis_or_focus_selected": false,
  "study_registered": false,
  "flash_used": false,
  "model_or_service_action": false,
  "owner_question_created": false,
  "probe_evidence_used": "withdrawn_wording_only; probe bytes not relied on"
}
```
