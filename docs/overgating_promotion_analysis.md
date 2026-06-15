# Over-gating vs promotion-starvation — the binding constraint on `/todo` cockpit cargo

> **Analysis (2026-06-15), feeding a PENDING human decision.** Read-only
> investigation via the `overgating-understand` Dynamic Workflow (3 parallel maps
> → design → adversarial critique), with the load-bearing production numbers
> **independently re-verified by the primary**. NO structural change is made here;
> this records the verified evidence + the reframe options for the human's call.
> The structural decisions below are the human's (per the D-052 pattern: probes/
> analysis run autonomously; the apparatus-mechanism decision is ratified by the
> human).

## TL;DR

The cockpit has zero cargo (`memory/surfaced_findings.jsonl` is absent). This
investigation set out to fix the D-052 residual — the primary R0 Gemma topicality
judge over-gates `novel_on_02`. It found two things:

1. **R0 over-gating is NOT why the cockpit is empty.** Even a perfect R0 judge
   produces zero cargo.
2. **The over-gating itself is an inseparability that wants a reframe, not another
   prompt tweak** (confirmed a 4th time here).

Two problems had been conflated.

## Problem A — R0 over-gating (instrument / battery level)

The primary R0 judge (`orchestrator/topicality.py:_primary_check`, prompt `:40-55`;
call site `orchestrator/nara.py:791-811`; its `"off"` → `relevance.low_confidence`
at `workers/retrieval_relevance.py:297-321`) over-gates the on-domain novel case
`novel_on_02` and misses the off-domain `fase_off_01` (D-052 probe
`probe_20260614T035332Z`). The two are **mirror cells** — `novel_on_02` ("route
the critic to a different model family in a research loop") vs `fase_off_01`
("semantic entropy in multi-agent code-gen modulates Nash convergence"): a
hypothesis-text-only judge has no signal to separate novel-on-domain from
camouflaged-off-domain. The inseparability is confirmed 3× (D-045/D-050/D-052) and
a 4th time by this analysis.

## Problem B — zero cargo (the actual cockpit starvation)

**Verified from production data (primary re-counted, not the workflow's word):**

- `memory/loop_memory.jsonl` (**59** iterations): `low_confidence=True` on **1**
  (rejected for a *critic* verdict, not R0); the R0 `novel→unclear` downgrade
  (`workers/novelty_classify.py:434-442`) fired **0** times; **26** passed the
  threshold cleanly (`novel` + `survives` + not low-confidence).
- `memory/promotion_near_misses.jsonl` (**174**): **65** capped by `max_candidates`
  (44 at =3, 21 at =4); **10** "refuted by adversarial vote" (9 at 3/3, 1 at 2/2);
  **0** R0/low-confidence rejections; the rest upstream attrition (33 critic
  `None`, 39 non-`novel` class, 25 critic non-`survives`, 2 human-`invalid`).
- `memory/surfaced_findings.jsonl`: **ABSENT** (0 cargo confirmed).

**So even a perfect R0 produces zero cargo.** The cockpit is starved by (1) the
`max_candidates` cap and (2) the **adversarial promotion vote**
(`orchestrator/finding_promotion.py:234-307`, survive-iff-minority-refute at
`:297`) refuting 3/3 on every candidate that reached it — structurally the **same
independent-skeptic-refute pattern D-052 just retired at the relevance gate**, now
the binding constraint at the promotion stage. The S3 note's "skeptic refutes 3/3
— calibration question" is this.

## Reframe options (the human's decision)

1. **Demote primary R0 to a non-gating advisory** — D-052 outcome C applied to the
   primary judge: emit `topicality_advisory` (logged + surfaced), never set
   `low_confidence`. Dissolves Problem A by refusing to let an inseparable call
   gate anything; residual over-gating handled by logged human sampling.
2. **Replace "is it on-domain?" with "can THIS corpus ground a verdict?"** — a
   grounding-sufficiency gate (condemn only when retrieval is substantively
   empty/irrelevant, regardless of vocabulary). The only lever that adds a NEW
   signal (the corpus view) the falsified-anchor note (`topicality.py:3-10`)
   gestures at but never took.
3. **Attack Problem B (the real cargo lever):** raise/remove `max_candidates` for
   the cost-bounded local run AND re-examine the adversarial promotion vote (same
   pattern D-052 retired). Pre-register the falsifiable cargo experiment: re-run
   promotion with the vote demoted to advisory; pass = ≥1 finding reaches
   `surfaced_findings.jsonl`. A zero result answers the S3 calibration question
   (genuine novelty absence vs over-gating).

## Recommendation

- **Problem A:** option 1 (demote R0 to advisory) — the inseparability is confirmed
  4×; it wants to stop being a binary gate, not another prompt.
- **Problem B (higher priority — it is what empties the cockpit):** option 3 — the
  promotion-stage adversarial vote + `max_candidates` are the binding constraint;
  that vote deserves the same D-052 scrutiny the relevance skeptic got.

## Caveat for any future R0 prompt probe

The D-052 boundary-probe harness
(`experiments/topicality_instrument/boundary_probe.py`) hardcodes `_judge` to
`vllm-qwen` (line ~124); the only Gemma path (`_primary_check`, ~149) takes no
system-prompt argument. Testing new PRIMARY (Gemma) prompt variants requires
authoring a Gemma-backed, prompt-injectable judge first — it is NOT expressible by
extending `VARIANTS`. (Moot if option 1 is adopted.)

## Key file:line anchors

- Primary judge + prompt: `orchestrator/topicality.py:40-55`, `:92-138`; call site
  `orchestrator/nara.py:791-811`.
- R0 → `low_confidence`: `workers/retrieval_relevance.py:297-321`.
- `low_confidence` → novel-downgrade: `workers/novelty_classify.py:434-442`.
- Promotion threshold (does NOT read `low_confidence`):
  `orchestrator/finding_promotion.py:108-157`; `max_candidates` cap `:551-557`;
  adversarial vote `:234-307` (survival rule `:297`).
- Production evidence: `memory/loop_memory.jsonl`, `memory/promotion_near_misses.jsonl`,
  `memory/surfaced_findings.jsonl` (absent).
- Probe harness: `experiments/topicality_instrument/boundary_probe.py`; D-052
  artifact `experiments/topicality_instrument/runs/probe_20260614T035332Z.{json,md}`.
