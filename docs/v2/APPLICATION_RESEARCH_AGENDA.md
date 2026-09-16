# Mechanism-led application research

**Owner direction recorded 2026-09-16:** retain game theory and agent behavior.
Investigate options first, while allowing prediction markets and suitable
crypto when the mechanism fits. A convenient existing Bitcoin collector does
not determine the research subject. This is a proposed research agenda, not a
new campaign activation, data entitlement, trading strategy or execution order.

The machine-readable counterpart is
[`research_application_agenda.json`](research_application_agenda.json). The UI
serves its source hash and displays it separately from executed evidence.
The active campaign still resolves from the canonical activation pointer.

## The bridge from agent games to a market study

The lab has observed failures in payoff arithmetic and a difference between
own-payoff and joint-payoff behavior. Those observations motivate better
instruments and bounded mechanism tests. They do not establish market alpha.
The bridge must supply four pieces of evidence:

1. **Construct:** define the incentive, information constraint or strategic
   response. Separate action validity, payoff arithmetic and actual behavior.
2. **Identification:** name observable treatment and outcome variables, the
   competing explanation, and a test that can reject the proposed mechanism.
3. **Transfer:** show why the synthetic mechanism applies to the selected venue,
   then test it on data that were not used to select the hypothesis.
4. **Economic evaluation:** distinguish a predictive or calibration improvement
   from returns after spread, fees, latency, funding and execution assumptions.

The stable model benchmark measures whether the apparatus can perform the
required reasoning and tool work. It does not score a market thesis as true.

## Candidate applications and adversarial checks

| Application | Mechanism worth testing | First decisive artifact | Strong reason to stop |
| --- | --- | --- | --- |
| Options, preferred investigation | Demand pressure interacting with incomplete hedging, inventory constraints or asymmetric information | Observable-variable specification and a small, time-aligned option/underlying sample | The mechanism requires dealer positions that the available data do not reveal, or a result disappears after costs and risk controls |
| Prediction markets | Belief aggregation, information arrival and reporting incentives | As-of forecast/market/outcome panel with exact settlement rules | Look-ahead, selective resolved-event coverage, or a calibration score being presented as trading profit |
| Crypto, only if justified | A named venue's liquidity, funding or strategic participation mechanism | Explicit venue/instrument choice and a coverage/cost audit | Choosing the asset because the collector exists, or claiming that spot evidence transfers to derivatives |

The options candidate is an inference from relevant mechanism literature,
not a claimed replication. Gârleanu, Pedersen and Poteshman model the effect of
demand when options cannot be perfectly hedged and use a special dealer/end-user
position dataset for their empirical analysis. Ordinary volume should not be
treated as that position data. [Demand-Based Option Pricing](https://www.nber.org/papers/w11843)

A feasible options data contract must specify expiry, strike, option type,
timestamp, bid/ask, underlying state and any Greek/IV construction. Cboe's
interval product documents these fields, optional calculations and coverage;
it also notes a quote-size definition change on June 22, 2026. A study spanning
that boundary must account for the change. The product's availability does not
mean this lab has purchased or validated it. [Cboe Option Quote Intervals](https://datashop.cboe.com/option-quote-intervals)

For prediction markets, theoretical conditions connect prices with beliefs,
while risk preferences and the belief distribution can affect interpretation.
That supports testing calibration rather than declaring quoted prices to be
ground-truth probabilities. [Wolfers and Zitzewitz](https://www.nber.org/papers/w12200)
Kalshi documents separate live and historical data with moving cutoff
timestamps. A retrospective sample needs both coverage paths where applicable;
a current endpoint response cannot prove past coverage.
[Kalshi historical data](https://docs.kalshi.com/getting_started/historical_data)

## Four-week sequence

This is a proposed sequence, with each step contingent on its evidence.

| Week | Deliverable | Completion criterion |
| --- | --- | --- |
| 1 | Mechanism and data feasibility memo | One observable hypothesis, two alternative explanations, an available sample and a declared rejection test |
| 2 | Reproducible baseline and frozen protocol | As-of joins pass; temporal split, primary metric, cost assumptions and stop conditions are published before the holdout |
| 3 | Matched empirical test and independent critique | All declared attempts retained; uncertainty and missingness reported; no outcome-driven edits to the primary protocol |
| 4 | Future paper evaluation or explicit no-go | A supported transfer claim and feasible paper study, or a documented failure that narrows the next question |

Do not promise a profitable strategy on a calendar deadline. A well-supported
no-go can be a useful research result; a plausible model narrative is not one.

## UI interpretation and history

Research should show question → evidence → criticism → refinement → next owed
test. Unknown or absent stages stay visible. An ordinary completed iteration
is not automatically a validated finding, and an authored next agenda is not
an executed experiment.

Existing H1/BTC and prediction-market records retain their original identities,
source bindings and results. They belong in historical evidence. They cannot
be relabeled as options studies or merged into a fresh benchmark baseline.

Sources were checked on 2026-09-16. The NBER records are abstracts/working-paper
metadata for mechanism selection; this memo does not claim a full empirical
replication or an exhaustive finance-literature review.
