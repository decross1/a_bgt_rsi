# Two-axis novelty rubric (T1b) — pre-registered

**Status:** pre-registered 2026-06-09, BEFORE any live promotion uses it.
D-041 still gates autonomous promotion: nothing in this rubric grants the
loop authority to promote a finding on its own. This document fixes the
decision rule in advance so later relabeling cannot be quietly fitted to
whatever the loop happens to produce.

**Implements:** `workers/novelty_classify.py` (axes + deterministic
mapping), `workers/critic_loop_v0.py` (undecidable verdict, ordered
decision procedure, coverage bar). Motivated by the 2026-06-09
lit-falsification battery and the iteration-068 review.

## The axes

The model emits three axis judgments; it does NOT pick the final class.

| Axis | Values | Question it answers |
| --- | --- | --- |
| `phenomenon` | `known` \| `novel` | Is the underlying effect/regularity already stated in the retrieved literature? |
| `substrate` | `studied_llm` \| `unstudied_llm` \| `na` | Is the claim about a population the retrieved literature covers, an uncovered LLM substrate, or not substrate-specific? |
| `predicted_direction` | `matches` \| `deviates` \| `silent` | Relative to the known phenomenon, does the claim predict the published direction, a different direction/boundary, or commit to none? |

Two prompt-level sentinels never reach the output axes:
`phenomenon: "incoherent"` (malformed / no falsifiable content /
out-of-domain) and `phenomenon: "ambiguous"` (neighbors give too little
signal). Both produce `novelty_axes: null`.

## The decision rule (deterministic code, not the model)

| phenomenon | predicted_direction | Legacy class |
| --- | --- | --- |
| `novel` | any | `novel` |
| `known` | `deviates` | `novel` |
| `known` | `matches` or `silent` | `rediscovery` |
| `incoherent` (sentinel) | — | `nonsense` |
| `ambiguous` (sentinel) | — | `unclear` |

Invalid axis values fail closed: a bad `predicted_direction` on a
`known` phenomenon yields `unclear` (the class-determining axis is
unusable); a bad `substrate` defaults to `na` with a logged warning
(it is not class-determining).

## The transfer/replication bucket

`known + matches` is **transfer/replication, not discovery** — even on
an `unstudied_llm` substrate. "No one has run model X on game Y" is a
near-null novelty signal by itself. These land in legacy class
`rediscovery` and are a low-priority bucket: legitimately worth running
as cheap replications, never promotable as novel findings.

Two calibration rules the classifier is prompted with:

- A well-formed claim that is FALSE is **not** nonsense — falsity is the
  critic's job. Classify substance, not truth.
- A definitional truism stating a textbook fact with no falsifiable
  claim **is** nonsense.

## The low-confidence trigger

When the cached retrieval-relevance gate stamps `low_confidence: true`,
a derived class of `novel` is deterministically overridden to `unclear`
(`verdict_overridden_from: "novel"` + `override_reason` recorded; the
model's axes are preserved). An omission in an off-topic corpus is not
novelty.

On the critic side the same signal is a coverage-adequacy bar: a raw
`survives` is overridden to `undecidable` when the relevance `category`
exists and is not `"ok"`, or when `low_confidence` is true. "Not
contradicted" only counts as survival when the retrieval was adequate
to check. Sub-agent failures (schema_mismatch, timeout) also default to
`undecidable` — a failure to run the check is never evidence of
survival. Novelty and critic share one neighbor set, so their agreement
is NOT independent corroboration; the optional skeptic seam
(`NARA_SKEPTIC=1`, own retrieval) exists to break that blind spot.

## Worked example: iteration-068

Hypothesis (paraphrased): *Gemma-4 agents in a p-beauty contest will
converge toward the equilibrium over repeated rounds in the level-k
pattern documented for human subjects.*

- Old scheme: labeled `novel` / `survives` — the corpus had no chunk
  about Gemma on p-beauty, and nothing contradicted the claim. Both
  signals were artifacts: the *phenomenon* (level-k convergence in
  p-beauty) is published.
- This rubric: `phenomenon: known` (level-k / p-beauty convergence is in
  the retrieved literature), `substrate: unstudied_llm` (Gemma-4
  specifically is not), `predicted_direction: matches` (it predicts the
  published pattern). Derived class: **`rediscovery`** — the
  transfer/replication bucket. Had it instead predicted that Gemma
  *fails* to converge or converges by a different depth pattern, that
  would be `known + deviates` -> `novel`.
- Critic side: a `survives` here must name the closest level-k neighbor
  and say why it does not already state the claim — which it cannot, so
  the ordered procedure yields `restated` at STEP 1.

## Change control

Threshold or mapping changes to this rubric require a DECISIONS.md
entry superseding this pre-registration. Per D-041, promotion of any
finding scored under this rubric remains human-gated.
