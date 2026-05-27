# exp003 — Vickrey rediscovery — notes

Slice-1 of the Phase-2 / Loop-v1 trajectory per
`.claude/plans/peaceful-brewing-seal.md` (committed plan). Tier-2
semi-synthetic sandbox per ARCHITECTURE.md §3.2 Rung 1.

## Question

In a single-round sealed-bid second-price (Vickrey) auction with N=4
LLM bidders drawing independent private valuations from U[0, 100] and
**no prompt-level priming on auction theory**, do the bidders converge
on truthful bidding — the dominant strategy under Vickrey's theorem?

Rediscovery probe: the model has near-certainly seen Vickrey, BGT, and
Myerson in pre-training. Does it apply the result to a mechanism it is
not told is Vickrey?

## Files

- `auctioneer.py` — pure-Python sealed-bid 2nd-price (no LLM). Tie at
  the top broken uniformly at random; ties resolve to price = max_bid.
- `bidder.py` — LLM bidder. System prompt states mechanics only
  (sealed-bid, four bidders, winner pays second-highest). Does NOT
  mention "truthful," "dominant strategy," "Vickrey," or "report your
  value." Lenient JSON-object extraction with parse-failure fallback
  (bid := private_valuation, reasoning prefixed `parse_failure:` so
  the failure is observable in `analyze.py`, never silent).
- `run.py` — driver. CLI: `--trials N --seed S --backend ... --temperature ...`.
  Each trial draws 4 fresh valuations + 4 fresh bidder calls + resolves
  the auction. Writes one JSONL row per trial to `results/trials.jsonl`.
- `analyze.py` — reads `trials.jsonl`, computes pooled + per-trial
  residual stats, applies a **pre-registered verdict threshold**
  (YES iff >=75% of trials have mean |bid - valuation| <= 5), writes
  `results/summary.md`.
- `loop_bridge.py` — generates a topic seed from `summary.md` and runs
  a LOOP_V0 iteration via `orchestrator.nara.run_iteration` with the
  experimental outcome threaded into the iteration_record's new
  `experiment_outcome` field (schema/iteration_record.schema.json).
  Default is `--dry-run` (no LLM call); `--live` runs the chain.
- `../../tests/test_exp003_auctioneer.py` — unit tests for the
  auctioneer (winner selection, tie-break, NaN + arity validation).

## Reproducing

Small smoke (2 trials, ~80 s — requires vllm-gemma on :8000):

```
env -u MOCK_LLM ./.venv-chroma/bin/python \
    experiments/exp003_vickrey_rediscovery/run.py --trials 2
./.venv-chroma/bin/python experiments/exp003_vickrey_rediscovery/analyze.py
./.venv-chroma/bin/python experiments/exp003_vickrey_rediscovery/loop_bridge.py
```

Headline run (50 trials = 200 LLM calls, ~17 min):

```
env -u MOCK_LLM ./.venv-chroma/bin/python \
    experiments/exp003_vickrey_rediscovery/run.py --trials 50
./.venv-chroma/bin/python experiments/exp003_vickrey_rediscovery/analyze.py
env -u MOCK_LLM ./.venv-chroma/bin/python \
    experiments/exp003_vickrey_rediscovery/loop_bridge.py --live
```

## Verdict threshold (pre-registered)

YES iff fraction of trials with mean |bid − valuation| <= 5 is >= 75%.

`analyze.py` enforces this threshold; the verdict is written verbatim
into the first line of `summary.md`. `loop_bridge.py` parses the
fraction back out and threads it as `experiment_outcome.value` into
the LOOP_V0 iteration record.

## What gets bridged into LOOP_V0

The `experiment_outcome` field (schema additive, landed in commit
81dfcea):

```
{
  "experiment_id": "exp003_vickrey_rediscovery",
  "metric": "truthful_bid_fraction",
  "value": <float in [0, 1]>,
  "trials": <n>,
  "summary": "Verdict=YES|NO. Fraction of trials with mean |bid - valuation| <= 5: NN%.",
  "results_path": "experiments/exp003_vickrey_rediscovery/results/summary.md"
}
```

Plus a Tier-2-shaped topic seed for the chain to evaluate (the
experimental finding restated as a hypothesis).

## Headline findings (factual) — 2026-05-27 50-trial run

**Tier-2 result (exp003): perfect Vickrey rediscovery.**

| | |
|---|---|
| Trials | 50 (errors: 0) |
| LLM calls | 200 (parse failures: 0) |
| Truthful fraction at eps=5 | **200/200 = 100.0%** |
| Pooled residual mean / sd | +0.00 / 0.00 |
| Per-trial mean abs-residual | min=+0.00 max=+0.00 |
| Wall-clock | 292.1 s (~4m52s) |

Every one of the 200 bidder calls returned a bid equal to the private
valuation to floating-point precision. The bidder reasoning *explicitly
named the mechanism* on the very first call:

> "This is a second-price sealed-bid auction (Vickrey auction). In such
> auctions, the dominant strategy is to bid one's true private
> valuation. Bidding higher risks paying more than the item is worth,
> and bidding lower reduces the chance of winning without changing the
> price paid if I win."

— the system prompt deliberately does NOT contain the words "Vickrey",
"second-price", "dominant strategy", or "report your value". Gemma is
inferring the mechanism + naming the theorem + applying it from the
mechanics description alone.

**Tier-3 result (LOOP_V0 iter-2026-05-27-028, journal/iterations/054.md):**

- novelty: `rediscovery` (top neighbor: `osborne_rubinstein-chunk-127`
  — Osborne & Rubinstein §2 Nash Equilibrium, the chunk that states
  "in a second-price auction, bidding one's valuation is a weakly
  dominant action")
- critic: `survives` — engaged with the auction-theory literature,
  noted that *while the theory is established, there is no empirical
  literature on LLM-bidder convergence in this setting*, so the claim
  cannot be falsified or restated
- `experiment_outcome` correctly threaded into the iteration_record
  (`value=1.0`, `trials=50`, `summary` + `results_path`)
- retrieval top-5: 2 live arXiv auction papers + 3 Osborne & Rubinstein
  Nash-equilibrium chunks. The Osborne & Rubinstein chunks dominated
  the critical citation. Camerer BGT chapters did NOT appear in the
  top-10 — possible retrieval gap.

## Reflection anchors (human writes the prose)

_(Reflective prose is the human's per CLAUDE.md inviolate rule #9.
Anchors below for the human to react to in
`human/retrospectives/`, not as prose for me to write.)_

- 100.0% truthful + 0.00 residual is suspiciously clean. **Worth
  deciding**: is this real evidence of mechanism reasoning, or is the
  model pattern-matching "sealed-bid + second-highest wins" → "output
  the valuation" without actually deriving the dominant strategy? The
  bidder's reasoning text *names* the theorem — that's a signal the
  inference is at least linguistic, but it doesn't prove derivation.
- The critic's distinction is sharp: theory is rediscovery, but
  *empirical LLM behavior in this setting is a genuine open question*.
  That framing matters — it's the Tier-2 sandbox doing the work the
  literature loop alone can't.
- Camerer BGT didn't surface in retrieval despite being in the
  expanded Chroma. **Tested and answered** (see `paraphrase_probe.py`
  + `results/paraphrase_probe.md`): the gap IS phrasing-dependent.
  Camerer BGT only reaches top-10 under a Camerer/behavioral-econ
  phrasing (seed B, `camerer_bgt-chunk-71` at rank 5); under the
  original-seed phrasing, mechanism-design phrasing, and textbook
  phrasing it stays out of the top-15. Osborne & Rubinstein dominates
  every phrasing — same chunk-127 the critic cited reaches its highest
  score (0.7534) under the textbook phrasing.

  **Implication for Slice 2 ML-Intern threshold trigger.** Threshold
  evaluation from `paraphrase_probe.py`:

  | threshold | fires on | verdict |
  |---|---|---|
  | 0.55 (Agent β's original spec) | 0/4 | dead — never escalates |
  | 0.65 | 2/4 (A, B) | fires on original + behavioral |
  | **0.70 (bumped)** | **3/4 (A, B, C)** | misses only textbook phrasing D |
  | 0.75 | 3/4 (A, B, C) | same as 0.70 — no seed in the 0.6833→0.7534 gap |

  **0.70 is the right bump** for Slice 2's `RETRIEVAL_ESCALATION_THRESHOLD`.
  At 0.55 the trigger is dead; at 0.70 it fires for vocabulary-mismatched
  topic seeds (A/B/C) but stays quiet for the textbook phrasing (D)
  where the Osborne & Rubinstein chunks are an exact lexical match.

  **Tension worth carrying into Slice 2 design:** seed B already
  surfaces Camerer BGT in its top-10 but has the LOWEST max score
  (0.6174) — it would escalate even though it has the BEST literature
  coverage of the four. The max-score heuristic alone doesn't capture
  coverage diversity. A potential compound trigger:
  `max_score < 0.70 AND distinct_books < 3` would skip B (which has
  4 distinct books in top-10) and still fire on A/C/D when retrieval
  is genuinely narrow.
- This is the first LOOP_V0 iteration with a bridged `experiment_outcome`
  — the schema extension + the bridge contract both worked on the first
  real attempt. Slice 1 is end-to-end validated.

## What this slice DELIBERATELY excludes

- ML-Intern install (Slice 2 — Agent β died on API overload, deferred
  to a next session).
- Karpathy autoresearch install (Slice 3).
- Nara dispatching the experiment herself (Slice 4 / full Loop v1).
- Rung-2+ auctions (first-price, English, combinatorial).
- Learning across trials — each trial is fully fresh.
