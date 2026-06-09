# Literature-falsification accuracy battery

Answers the human's headline question: **does the literature pipe FALSIFY
with high accuracy, or does it need further refinement?**

## Why this exists

The 2026-06-09 autonomous iteration (`iter-2026-06-09-001`) exposed a
research-integrity failure. An OFF-DOMAIN topic — *FASE: Fast Adaptive
Semantic Entropy for Code Quality* — was run against the game-theory
corpus. Retrieval returned 9 topically-irrelevant game-theory books, and:

- `novelty_classify` said **novel** (because the GT corpus omits semantic
  entropy), and
- `critic_loop_v0` said **survives** (because that irrelevant corpus
  "contains no contradiction").

Both verdicts were artifacts of irrelevant retrieval — a false positive.
The fix added a retrieval-relevance low-confidence gate
(`workers/retrieval_relevance.py`), wired into both verdict workers and
stamped by the orchestrator (`orchestrator/nara.py`, ~L660:
`payload["relevance"] = relevance(neighbors, hypothesis)`).

This battery **measures whether that fix holds** and whether the pipe
falsifies non-novel theses correctly, against a labelled known-answer set.

## What's in here

- `cases.jsonl` — 13 labelled known-answer theses spanning the
  falsification modes. Each row:
  `{case_id, topic, hypothesis, expected_novelty, expected_critic,
  expect_low_confidence, domain ("on"|"off"), rationale}`. Coverage:
  - **3 genuinely-novel ON-domain** GT theses (expect `novel`/`survives`,
    gate off) — grounded so retrieval is on-topic but the corpus lacks the
    specific result.
  - **3 known rediscoveries** grounded in the foundational corpus
    (tit-for-tat reciprocity, the folk theorem, quantal-response) —
    expect `rediscovery`/`restated`.
  - **2 OFF-domain regression guards**: the FASE case from
    `iter-2026-06-09-001` (`expect_low_confidence` **true**, NOT
    novel/survives) plus a second off-domain case (DB index tuning) so the
    gate isn't overfit to the FASE wording.
  - **2 nonsense/malformed** (word-salad + a definitional truism) — expect
    `nonsense`/`malformed`, gate off (they name GT terms, so retrieval is
    nominally on-topic).
  - **2 refutable claims grounded in a corpus result**: finite-horizon PD
    "cooperate to the end" (refuted by backward induction) and "tit-for-tat
    is dominant" (refuted by the folk-theorem / Axelrod literature) —
    expect `falsified` with a `contradicting_paper_id`.
- `battery.py` — the harness. Mirrors the real Nara call path
  (`retrieve_literature` -> stamp `relevance` -> per-iteration cache ->
  `novelty_classify` + `critic_loop_v0` by `iteration_id`), then scores.
- `tests/test_lit_falsification_battery.py` — self-tests for the SCORING
  logic with stubbed verdicts under `MOCK_LLM` (no model, no cache).

## How to run it FOR REAL (the integrator's serial smoke)

```bash
env -u MOCK_LLM ./.venv-chroma/bin/python -m experiments.lit_falsification_battery.battery
```

`env -u MOCK_LLM` is REQUIRED. Under the default `MOCK_LLM=1`, the LLM
workers (`novelty_classify`, `critic_loop_v0`) are silently stubbed and the
`query_chroma` neighbors are synthetic — so the verdict-accuracy numbers are
**meaningless**. The harness detects `MOCK_LLM` and prints a banner saying
so, and never reports a real pass/fail in that mode. **The real-Gemma run is
the integrator's serial smoke, not a workflow-limb step.**

A JSON + markdown report is written to `runs/battery_<UTC-timestamp>.{json,md}`
and the markdown is echoed to stdout. The process exits non-zero when the
proposed pass bar fails (real-model runs only), so it can gate CI.

## What each number means

- **combined verdict accuracy** — exact-enum match across both axes
  (novelty + critic), `verdict_correct / (2 * cases)`. This is the headline
  "does it falsify accurately" number. An off-by-one verdict is a MISS,
  reported as a miss (inviolate rule 4 — never coerced).
- **low-confidence-gate recall** — of the cases that MUST flag
  (`expect_low_confidence` true, i.e. the off-domain regression guards),
  how many actually fired the gate. This is the direct measure of whether
  the 2026-06-09 fix holds. Incomplete recall is a FAIL.
- **off-domain UN-GATED novel/survives** — count of off-domain cases the
  pipe scored `novel` or `survives` **without** the low-confidence flag set.
  This is the exact 2026-06-09 regression (verdict asserted on irrelevant
  retrieval with no gate); it **must be 0**.
- **off-domain GATED novel/survives** — count scored `novel`/`survives`
  **with** the flag set. The gate fired but the verdict enum didn't move —
  honestly tempered, NOT the bug, but surfaced as a verdict-enum-refinement
  signal (the workers carry no dedicated "low-confidence verdict" enum, so
  the model is told to flag low confidence rather than change the verdict).
  Reported; does not fail the bar.
- **novelty / critic confusion** — expected->actual matrices. A worker that
  emits a non-enum value lands under an explicit `<invalid>` column (never
  silently dropped).

Note on off-domain scoring (rule 4, applied honestly): an off-domain case
*passes* iff the gate fired when required AND there is no UN-GATED
novel/survives. The exact non-novel verdict is allowed to vary (`unclear` /
`falsified` / `restated` / `malformed` are all legitimate honest tempering on
irrelevant retrieval), so we do NOT demand exact-enum on off-domain — but the
per-axis exact-enum result is still recorded honestly in the confusion matrix
and the per-case `*_correct` flags. We never silently recode a non-matching
verdict as correct. We also split the regression signal in two so the bug
(`novel`/`survives` with the gate OFF) is never conflated with honest
tempering (`novel`/`survives` with the gate ON) — only the former fails the
bar; the latter is surfaced for verdict-enum refinement.

## PROPOSED PASS BAR

The pipe is judged to falsify with sufficient accuracy (no further
refinement needed *for these modes*) when ALL three hold:

1. **combined verdict accuracy >= 80%** (`VERDICT_ACCURACY_BAR`, locked in
   `battery.py`; mirrors the critic-eval 0.80 bar) — 21 of 26 verdict
   decisions across 13 cases; AND
2. **every off-domain case is low-confidence-flagged** (gate recall = 1.0
   over the required cases — the FASE regression guard fires); AND
3. **zero UN-GATED novel/survives on off-domain cases** (the specific
   2026-06-09 regression — verdict asserted on irrelevant retrieval with the
   gate OFF — does not recur). A GATED novel/survives is reported separately
   and does NOT fail the bar.

If (2) or (3) fails, the gate needs refinement regardless of the headline
accuracy. If only (1) fails, the verdict workers (not the gate) need work.
A high GATED-novel/survives count with the bar otherwise green is the
signal that the gate fires correctly but the verdict enum could move too
(a verdict-prompt refinement, not a gate failure).
The harness reports each independently so the failure mode is legible — it
does not collapse them into a single coerced pass.

## What the integrator's real run will measure

Running `battery.py` under `env -u MOCK_LLM` against live Gemma + the real
ingested Chroma corpus produces, for all 13 cases:

- the real `novelty_classify` / `critic_loop_v0` verdicts and the real
  `retrieval_relevance` gate decision, scored against the labels;
- the three pass-bar signals above (verdict accuracy, gate recall on the
  off-domain cases, off-domain false-novel/survives count);
- the per-case table and the two confusion matrices;
- a written `runs/battery_<ts>.{json,md}` artifact for the journal.

That run is what answers the human's question. This limb only proves the
SCORING logic is correct under MOCK_LLM (the self-tests); it deliberately
does NOT run the model.
