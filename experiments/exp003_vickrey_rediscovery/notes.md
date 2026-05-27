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

## Reflection anchors (human writes the prose)

_(Reflective prose is the human's per CLAUDE.md inviolate rule #9.
Anchors below for the human to react to in
`human/retrospectives/`, not as prose for me to write.)_

- If verdict = YES: does novelty correctly flag `rediscovery` and does
  the critic cite Vickrey, Myerson, or Camerer BGT chapters? That's
  the cross-tier replication success-condition.
- If verdict = NO: what residual pattern? Systematic shading by some
  fraction of valuation, or noisy near-truthful? The shape of the
  failure is what's interesting — it tells you whether the model is
  reasoning about the mechanism at all.
- The chain's MAX literature signal on this topic is Camerer BGT
  ch.7-9 (auctions) — they're in the expanded Chroma. If retrieval
  surfaces those neighbors strongly, the critic has the prior to
  engage with. If it doesn't, that's a retrieval-side observation
  (and is part of what Slice 2's ML-Intern escalation is meant to fix).

## What this slice DELIBERATELY excludes

- ML-Intern install (Slice 2 — Agent β died on API overload, deferred
  to a next session).
- Karpathy autoresearch install (Slice 3).
- Nara dispatching the experiment herself (Slice 4 / full Loop v1).
- Rung-2+ auctions (first-price, English, combinatorial).
- Learning across trials — each trial is fully fresh.
