# exp004 — combinatorial-auction rediscovery probe

## Design

A single-round, sealed-bid **combinatorial auction** over two items
(0 and 1). Each bidder may bid on three bundles: item 0 alone `(0,)`,
item 1 alone `(1,)`, or the pair `(0, 1)`. Per trial:

1. Draw one fresh private valuation per bidder (`bundles.draw_valuation`):
   `v[(0,)], v[(1,)] ~ U[0, 50]`, `v[(0,1)] = max(0, v0 + v1 + U[-20, 20])`
   (positive synergy = complements, negative = substitutes).
2. Ask the LLM bundle-bidder (`bidder.compute_bundle_bids`) for one sealed
   bundle bid per valuation. The prompt states mechanics only — never
   "truthful", "dominant strategy", "VCG". This is the rediscovery probe.
3. Run **all three mechanisms** on the SAME bid profile and record, per
   mechanism: allocation, payments, revenue, the flat per-bundle residuals
   `(bid − valuation)`, and `allocative_efficiency` against the TRUE
   valuations.
4. `run.py` writes `results/trials.jsonl`; `analyze.py` writes
   `results/summary.md` + `results/summary.json` with a per-mechanism
   verdict.

The driver runs under `env -u MOCK_LLM` (real model). `run.py --n --bidders
--seed` is fully seeded; mechanisms are pure-Python and contribute no LLM
calls.

## The frozen contract

- Items are ints `0` and `1`. `BUNDLES = [(0,), (1,), (0, 1)]`
  (`bundles.py`).
- A valuation/bid is a dict mapping each of those 3 tuples → `float >= 0`.
- Every mechanism exposes one pure function:
  `clear(bid_profile, *, rng=None) -> {"allocation", "payments", "revenue",
  "mechanism"}`. The chosen allocation MAXIMIZES reported welfare over
  `feasible_allocations(len(bid_profile))`; ties broken with `rng`.
- `efficiency.py`: `optimal_welfare`, `realized_welfare`,
  `allocative_efficiency` (= realized/optimal, 1.0 when optimal == 0).

## Tier honesty

exp004 is the **HARDEST SYNTHETIC rung** of the sandbox spectrum:
combinatorial auctions over two items with a **KNOWN** optimal solution
(welfare-maximizing allocation and exact Clarke-pivot payments are
brute-forced over the small feasible set). It is the **on-ramp to — but is
NOT yet — the semi-synthetic mechanism-DESIGN tier**. The mechanisms here
are hand-written and verified against brute-force optimal welfare; the
model is probed only as a bidder. Do not overstate this as
"semi-synthetic".

## The three mechanisms + the designer seed

- **vcg** (`mechanisms/vcg.py`) — Clarke-pivot, the cross-rung
  strategyproof anchor. Winner `i` pays `W_{-i} − (W(A*) − b_i(A*_i))`.
  Truthful bidding is a dominant strategy, so it is the rediscovery signal
  bridged into LOOP_V0 (`loop_bridge.py`, metric `vcg_truthful_fraction`).
- **first_price** (`mechanisms/first_price.py`) — pay-your-bid; same
  welfare-maximizing allocation, each winner pays their own reported bid.
- **sequential_second_price** (`mechanisms/sequential_second_price.py`) —
  two independent single-item second-price rounds (reads only `(0,)` and
  `(1,)` bids); a bidder winning both rounds is recorded once as `(0, 1)`.
  Requires ≥ 2 bidders.
- **mechanism_designer** (`mechanism_designer.py`) — the semi-synthetic
  **seed**: asks the model to propose an allocation + payments, scored
  against VCG and brute-force optimal. This is a probe toward the next
  tier, not part of the truthfulness verdict.

## Verdict gate (carryover #4)

Per mechanism (`analyze.py`): `INVALID` if `parse_failure_rate > 0.25`
(OVERRIDES the truthful test — a parse failure defaults `bid := valuation`
and would falsely read as truthful); else `YES` if
`truthful_fraction >= 0.75`; else `NO`.

## Cross-rung wiring (Step 5)

`experiments/replication_driver.py --cross-rung` compares rung-1 (exp003
Vickrey single-item second-price truthful) vs rung-2 (exp004 combinatorial
VCG truthful) on the shared claim that an unprimed LLM rediscovers
strategyproof truthful bidding across auction complexity. Honest
cross-mechanism-FAMILY upgrade within the synthetic tier — NOT cross-tier.
