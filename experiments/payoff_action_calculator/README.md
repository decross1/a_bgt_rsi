# Action-aware payoff calculator

This directory contains a deterministic, development-only instrument for the
four-player public-goods study. It addresses the shakedown's observed failure:
the resident model could call a payoff-table tool exactly but often selected
the wrong row when converting a disclosed joint action into focal and group
payoffs.

The calculator evaluates one supplied joint action. It provides no optimal
action, recommendation, future utility, regret, or opponent prediction. It is
not an experiment, scientific verifier, L2 receipt, model evaluation, or
evidence of an intervention effect.

## Exact contract

Input is exactly:

```json
{
  "E": 3,
  "m_num": 3,
  "m_den": 2,
  "joint_action": [0, 1, 0, 1],
  "focal_seat": 0
}
```

`E`, `m_num`, and `m_den` are positive exact integers; the multiplier must be
reduced. `joint_action` has exactly four binary integer entries, and
`focal_seat` is an integer from 0 through 3. Booleans, extra keys, non-finite
values, and unreduced multipliers are rejected.
Inputs, response bytes, numeric token digits, and decimal exponents are bounded
before any potentially large `Fraction` construction.

For `k = sum(joint_action)` and `m = m_num / m_den`, the calculator uses:

```text
shared_return = m * E * k / 4
player_payoff[i] = E * (1 - joint_action[i]) + shared_return
total_payoff = sum(player_payoff)
```

Every payoff is returned as an exact object with `numerator`, positive
`denominator`, and canonical integer-or-fraction text. The output includes all
four player payoffs, focal and total payoff, the evaluated action and focal
seat, total and other-contributor counts, and a false strategy-advice flag.
Per-player values are an audit surface for this exact calculation, not
additional strategic information.

## Independent response scoring

`score_response` expects a JSON object with exactly `probe` and `actions`.
The caller supplies the trusted calculator input and a frozen plan horizon from
4 through 12. The scorer recomputes the expected probe itself; it never trusts
a caller-supplied expected payoff object.
It reports these dimensions separately:

- JSON and field validity;
- declared exact-number representation validity;
- diagnostic numeric parseability using `Decimal` and `Fraction`, never float;
- binding and contributor-count correctness;
- exact arithmetic correctness;
- binary action-array validity; and
- action scoreability at the declared horizon.

Each dimension is marked `passed`, `failed`, or `unassessed`. Dependent
diagnoses are emitted only when their prerequisites were measurable: invalid
JSON cannot be called an arithmetic failure, an unparseable number cannot be
called arithmetically wrong, and an invalid action array cannot be called a
horizon mismatch. Deeply nested JSON is contained as a parse failure.

The strict contract uses exact-number objects. The diagnostic arithmetic path
also understands exact JSON integers/decimals and canonical rational strings,
so representation failure can be distinguished from substantive arithmetic
failure. A malformed or wrong probe does not erase an otherwise valid action
vector. Conversely, a bad plan does not erase a valid arithmetic observation.

## Acceptance boundary

The tests exhaust all 16 one-round joint actions and all four focal seats,
exercise player permutations and endowment scaling, reject malformed numeric
inputs, and verify the scoring dimensions remain independent. Passing them
establishes deterministic instrument correctness only. Any shakedown or study
using this module requires its own source-frozen plan, raw evidence replay,
review, and admission decision.
