# Known-opponent payoff representation diagnostic, v1

The admitted 2026-09-15 utility pilot returned strict focal/sum strings for all
12 comprehension calls but passed the combined focal-and-total check 0/12.
Some focal values alone were correct. This
prospective diagnostic asks whether presenting the same four actions as words
or a numbered seat table changes arithmetic response. It does not test a
strategy improvement, scientific novelty, equilibrium, or trading performance.

The calibrated game has four seats, endowment 5, multiplier 2, and binary
contribute/retain actions. For each of three fresh four-action tuples, ask
focal seats 0 and 3 under both views: 12 calls, six matched pairs. Both prompts
state the same payoff rule, seat order, focal question, answer format and no
worked example. Only the action presentation varies. Pair seeds are identical;
view order alternates before outcomes. The local Gemma route is the exact
passed resident qualification/artifact used in the utility pilot, with
thinking off, temperature 0, top-p 1, top-k 64, 64 output tokens and 30 s per
call. A 900 s study cutoff and 1500 s supervised outer deadline reserve 300 s
for exact resident/watchdog/Nara restoration. All 12 scheduled slots stay in
the denominator; timeout, malformed or wrong output is not corrected later.

Panel A is eligible 2026-09-15 19:00–2026-09-16 00:00 UTC and uses, in seat
order, `[C,R,R,R]`, `[R,C,R,C]`, `[R,C,C,C]`. The exact oracle focal seat 0,
seat 3 and total material payoffs are respectively `(5/2,15/2,25)`,
`(10,5,30)`, `(25/2,15/2,35)`. Panel B is a separately fresh-input follow-up,
eligible 2026-09-16 03:30–08:00 UTC after the scheduled 03:00 ingestion window,
using `[R,R,R,C]`,
`[C,C,R,R]`, `[C,C,C,R]`; it is not the same input under a new seed. The model,
rule and per-pair seed matching are fixed in source before either panel runs.

The future timer makes 16 bounded availability checks at 15-minute intervals
from 03:35 through 07:20 UTC; it is not a success guarantee. Dispatch refuses
unless the full 1860 s service envelope, including the 1500 s worker ceiling
and bounded parent emergency restoration, fits before the 08:00 expiry.
If production leases, resident idleness or the host margin are unavailable,
the dispatcher refuses before its irreversible reservation and the job stays
eligible for operator-reviewed dispatch until expiry. A post-reservation
interruption remains one observed, unadmitted attempt. Exactly one distinct
`-r1` window is permitted only for an independently replayed typed occupied
lease refusal with zero issued calls and verified no mutation. An issued,
unknown or differently failed attempt requires a new prospectively reviewed
job/version to repeat. Queue status never treats mere
receipt existence as independent admission.

Independent admission reconstructs the exact resolved request body and raw
private SSE, parses `focal=<number>;sum=<number>` strictly and compares both
values with exact rational payoff controls. Report strict-shape, focal-correct,
total-correct and both-correct counts separately. Full admission requires 12
attempted calls and verified resident restoration. These counts are an
instrument diagnostic; they are not evidence that a different strategy is
better. Any later strategy or market experiment needs its own registration.
