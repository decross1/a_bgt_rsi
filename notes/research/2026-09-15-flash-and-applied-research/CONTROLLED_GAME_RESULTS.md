# Controlled quote-versus-abstain instrument: observed development results

The 32-cell expected-payoff grid in [NEXT_AGENT_GAME.md](NEXT_AGENT_GAME.md)
was run on the exact restored resident Gemma endpoint. All three schedules
completed and raw SSE/metadata/oracle replay passed. These are sequential,
repeated development tasks with no held-out confirmation or market claim.
The strict parser, payoff oracle and all planned denominators remain unchanged.

| Arm | Intervention | Strict valid | Oracle optimal | Interpretation |
|---|---|---:|---:|---|
| A | Thinking off, 128 tokens, JSON-only wording | 0/32 | Unavailable | Every emitted answer was wrapped in a JSON Markdown fence. |
| B | Explicit raw JSON/no Markdown wording; same policy/cap | 32/32 | 17/32 | Formatting was repaired, but disclosed-payoff decisions remained weak. |
| C | B wording; thinking on and 1,024-token cap | 0/32 | Unavailable | All returned substantial text in the content channel; 23 exhausted the cap and nine stopped. No separate reasoning-channel content was recorded. |

For B, mean expected-payoff regret was 0.1671875 units per valid cell. A
posthoc fence-strip diagnostic made all A answers parseable and found 18/32
optimal, but this is not A's original grade and is not a published rescue.
C changes thinking and budget jointly, so it cannot isolate either lever.
Its 346.66-second schedule is an operational observation, not a matched
throughput comparison against A/B because the resident service was shared.

The research implication is to validate the instrument before interpreting
agent behavior. Keep an exact arithmetic oracle and separate response-format
validity, computation, action selection and strategic interaction. These small
controlled choices identify no equilibrium, dealer inventory, order-flow
causality, or trading edge. A/B were not tuned on disjoint arithmetic practice
items; all subsequent reuse is explicitly development. A fresh confirmation
needs new numeric instances and an untouched scoring contract.

Raw manifests, immutable private streams and public numeric records are under
`a_bgt_rsi_v2_artifacts/2026-09-15/overnight-research/quote-abstain-control-20260915-{a,b,c}`.
The private source copy in each arm preserves the exact executed implementation.
