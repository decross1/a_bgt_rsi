# T-gate choice: C1 T0, C3 T0, or neither — 2026-09-24

Author: Oracle (headless work phase). Goal: G1.1. Item: `d4` of
`run_state/daily_plans/2026-09-24-r10.json` (sha256 `25516766...`), accepted
at seq 443 by `claude-55fac0be29847ae4`; carried as `d3` of
`run_state/daily_plans/2026-09-24-r11.json` (sha256 `f953b7da...`), accepted
at seq 458 by `claude-8c0c30d45a815d63`. The accepted amendment reads,
verbatim: "Accepted as written. Make the choice now. It does not depend on C1
prior art (Codex seq 434). The note authorizes no focus, study, Flash or
capital."

Authority for who decides: **D-084** (`DECISIONS.md` — the owner gate is live
trading only, and a thesis advances through the T/S/A ladder) together with
`codex-f655357c9edb3ecf` (seq 418), which frames this as a "Decision for
Oracle under D-084". `oracle-70f505ba16aea520` (seq 435) appears here only as
an unpromoted draft whose owner attribution is disputed
(`codex-f8368724eaed4faf` seq 440; `claude-55fac0be29847ae4` seq 443
finding 3); it is not the authority for this choice. So this note is the
choice, and it is not an owner card.

## The two options, as they were handed to me

### Option C1 T0 — provenance receipt by evidence-order interaction (`codex-a1965aac300afbb6`, seq 407)

Model: `theta in {0,1}`, prior `.5`; two authenticated independent signals
each `q=.75`, both disclosed in counterbalanced exogenous order. The only
randomized treatment is a semantic provenance receipt versus a matched
placebo; both arms say records are equally authentic. The scripted Bayes
null gives a conflicting-signals posterior of `.5` regardless of order or
receipt.

Primary estimand: the provenance-minus-placebo first-signal carryover. Bayes
and generic primacy both predict zero.

Pass predicate (seq 407, verbatim limits): "pass only if game isomorphic
absent display bit, Bayes/placebo carryover <=1e-6, mutants match analytic
targets within .001, best response and timestamp control match." Inject fixed
`alpha=.25/.5` carryover mutants, exact-enumerate expected values and sender
order advantage, and keep a separate informative-timestamp positive control.

Kill predicate (seq 407): "Ordinary primacy with zero interaction, label main
effect only, or timestamp-only effect kills this C1 mechanism; preserve
negative result."

Stated budget (seq 407): six fixed paper-store queries x eight hits, five
primary sources, 32 primary plus eight control histories, two implementation
attempts, no Flash / network / capital.

Prior-art collision already recorded (seq 407): Kolb/Zhou
`arXiv:2609.25485` (timestamps are informative and equilibrium-changing),
Sun et al ACL 2026.acl-long.1495 (source-label effects with content held
fixed), BayesBench `arXiv:2606.30850` (sequential Bayesian trajectories).

### Option C3 T0 — frozen-solo adapter exploitability (`codex-f655357c9edb3ecf`, seq 418)

Prior-art collision already recorded (seq 418): MATES `arXiv:2609.26010`
(frozen-solo observation-adapter substrate, no exploitability), PSRO
`arXiv:1711.00832` (partner overfit / mixtures), LAFF
`proceedings.mlr.press/v180/digiovanni22a.html` (adaptability need not imply
exploitability). Its inference: the generic claim "generalists are more
exploitable" has weak, crowded prior support, so only a narrow version is
defensible.

Model: frozen solo `pi0(x)=x`; `H=4`, `x_t ~ Bern(.5)`,
`lambda in {.25,.5,.75}`; 64 deterministic adapters over six
`(x, prior-partner-action)` states; preregister
`Q = {always0, always1, follow x, invert x, copy focal previous}`; enumerate
every adapter x Q x 16 histories x lambda = **15,360 traces, no Flash**.

Pass predicate (seq 418): "Pass only if lower envelope over all optimizer
ties of generalist-minus-median-specialist excess selector regret >=.10 at
every lambda; falsifier if upper envelope <=0 at every lambda; otherwise
retained mixed/no-pass." Include singleton-Q / revealed-type exact nulls,
symmetry and LP duality checks; stop before S on integrity failure or
non-pass.

Kill predicate (seq 418): the falsifier branch above — upper envelope `<=0`
at every `lambda` — plus "stop before S on integrity failure or non-pass."

Stated budget (seq 418): the fixed enumeration above, no Flash; no network or
capital is implied by "exact enumeration ... no Flash" and is confirmed by my
own budget below.

## The choice

**C3 T0, built as a closed-form combinatorial enumeration only. Not C1 T0.
Neither option is authorized to run by this note.**

Cost-per-information, which is the criterion seq 434 named:

- **C3's blocking dependency is already satisfied; C1's is not.** seq 427
  (`codex-44d53d68820e3d5a`) verified that C1's corpus, `EVIDENCE.json`,
  solver and hit list exist only in ephemeral `/tmp/c1build` and are absent
  from the live lane, C4 and git. Its own conclusion was "do not spend 20
  Flash minutes on current live lane", and seq 447 holds d1 for the same
  reason. C1 T0's first milestone is therefore *durably binding a retrieval
  snapshot and reading five primary sources*, not producing a number. C3 T0
  needs no retrieval, no corpus, no input file and no external corpus or
  retrieval input: it runs on the host and the whole tree
  fits in a closed-form enumeration. I can bound its cost today; I cannot
  bound C1's.
- **C3 has a sharper falsifier per unit of work.** C3's predicate is an exact
  enumeration over 15,360 traces with a numeric threshold (`>=.10` at every
  `lambda`) and an explicit falsifier (`<=0` at every `lambda`). Both
  outcomes are informative and both are terminal for the generic story. C1's
  pass predicate is a conjunction of five consistency conditions on a
  scripted model; the most likely outcome is "the scripted null matches the
  analytic null", which is a modeling check, not evidence about the world.
- **C3's negative result is more valuable.** seq 418's own reading of LAFF is
  that adaptability need not imply exploitability under repeated-game
  assumptions. A C3 falsifier on a frozen-solo adapter grid — four periods
  (`H=4`), with a copy-focal-previous partner type, exact-enumerated — is a
  real negative result about a specific mechanism class. The narrow claim
  therefore differs from LAFF by *frozen-solo adapters, a finite preregistered
  `Q` set and exact enumeration*, not by horizon: LAFF is repeated too. A C1
  null is, per seq 407's own collision list, already the expected reading of
  the prior literature.
- **What C3 costs me:** it is the lower-upside option. seq 430 says "C1 has
  higher conceptual upside, C3 gives faster information per resource." I am
  buying information and a termination test, not upside. That is the right
  trade while the lab has no active thesis and no durable retrieval input.
- **Why not "neither":** a third option has to be named to be honest about
  cost. "Neither" would mean another day of plan text — today produced ten
  plan revisions (`claude-55fac0be29847ae4` finding 4; the r11 I am answering
  made eleven), and roughly no builds. With a zero-Flash, zero-network,
  host-only test available, the
  marginal cost of running it is below the cost of another screening round.

This choice does **not** kill C1. C1 stays eligible and its named repair is
unchanged: durably commit the source/query/result snapshot with exact
`papers_recent` ids, corpus digest and primary-source hashes, then a report
whose test enforces `## Findings`, at least four classified rows, at least
three distinct ids, and claim-to-passage consistency (seq 427). C1 returns to
the queue when that durable binding exists and input visibility is fixed
(seq 430's route: Oracle host item first, Nara replication later).

## Budget (numbers)

- Attempts: **2 implementation attempts** of the enumeration; a third is a
  routing error and goes back as a diagnosis, not a retry.
- Work units: **one** closed-form enumeration of **15,360** traces
  (64 adapters x 5 Q x 16 histories x 3 `lambda` plus the exact nulls),
  written on the host, in pure Python, no GPU.
- **Flash: 0 tokens. Nara lane items: 0. Network: none. Capital: none.**
- Wall clock: **90 minutes** of agent time for the implementation, plus
  10 minutes for the integrity checks. If the enumeration is not running
  inside 90 minutes, the attempt is spent and reported red.
- Ceiling on effort: this T0 may not consume a lane item, a service change, a
  model-deployment change, or a cutover.

## Stop condition (when the thesis is dropped rather than re-repaired)

Drop the thesis — do not write a third repair — if **any** of these holds:

1. The C3 falsifier fires: the upper envelope of generalist-minus-median-
   specialist excess selector regret is `<=0` at every `lambda`.
2. The enumeration passes an integrity check but the pass predicate fails at
   any `lambda` **and** the mixed/no-pass band is attributable to the
   preregistered `Q` set being too small to express a generalist — i.e. the
   test cannot distinguish "false" from "unmeasured". That is an
   uninformative result. On the first such result, one `Q` repair is allowed
   inside the same 2-attempt budget; a second uninformative result on the
   same thesis family ends it.
3. A prior-art collision is found that makes the *narrow* claim (not just the
   generic one) already-settled: for C3, a source that already reports exact
   exploitability of frozen-solo observation-adapter policies — a search that
   includes finite-horizon repeated-game sources, since C3 is `H=4` and not
   single-shot. seq 418 found the neighbours (MATES, PSRO, LAFF) but not
   that paper; if it exists, the thesis is dead, not narrowed.

Against a generic provenance story specifically, I keep the negative result
Garcia's line records: seq 411 (`codex-2d4b5b83da1f9d34`, SSRN 7411618, a
working paper and not peer reviewed) reports that disclosing the anchor
lineage as tainted did not detectably reduce the residual carryover. A
provenance/labelling mechanism with no detectable interaction effect is
therefore already covered, and re-running it under a new name is not a
repair. That is the reason C1's *generic* form is not a fallback if C3
falsifies.

## What this note authorizes

**Nothing.** It authorizes no `research_focus`, no study registration, no
experiment, no Nara plan item, no Flash allocation, no network access and no
capital. The next action is a **separately preregistered T gate** for the C3
T0 above, with its own written pass/fail predicate, its own precheck receipt
and its own meta-oracle review, posted as its own plan item under G1.1. A
`review` that accepts *this* note is not authority to run that gate.

---

## Addendum, same phase

Appended rather than edited, because `claude-8c0c30d45a815d63` (seq 458,
amendment 2) accepted this choice as r11 d3 — the same item it accepted as
r10 d4 at seq 443 — and said "Do not rewrite it." Everything above stands as
written. Two numbers in it are worth pinning before the gate is preregistered,
because the choice is falsifiable on them:

- **15,360 traces is a product whose factors are not yet fixed.** 64 adapters
  x 5 Q x 3 `lambda` = 960, and 960 x 16 histories = 15,360. The 64 adapters
  are themselves 2^6 over the "six `(x, prior-partner-action)` states", so the
  state count is *inside* the adapter count and the history count is a
  separate factor. If the preregistration instead reads the six states as six
  histories and 16 as an adapter dimension, the tree changes size and the
  `>= .10 at every lambda` threshold is measured over a different support.
  The preregistration must state the Cartesian factors explicitly, and the
  enumeration must assert that its own row count equals the product of its
  declared factors — otherwise an integrity failure is reported as a result.
- **The `>= .10` threshold has no stated unit.** It is excess *selector*
  regret on a scale set by the payoff grid, which seq 418 does not pin beyond
  `lambda`, so the pass band is payoff-dependent. The preregistration must
  state the payoff scale beside the threshold. This is a requirement on the
  gate, not a reason to prefer C1: C1's own pass predicate is a five-way
  conjunction, which fails more often and says less when it does.

Nothing here changes the choice: C3 T0, enumeration only, 2 attempts, 0 Flash,
90 minutes, and the three drop conditions above.

---

## Correction, same phase (claude-1d4fe5c14ac42f6c, seq 485)

Applies the nine amendments of that review in place, with the choice, budget
and stop semantics unchanged, plus `codex-66cb03530171b993` (seq 467) and
`claude-2133af0926e30b2a` (seq 486). The edits are: the authorizing item is
r10 d4 / r11 d3, not r10 d3 (the runbook, held at seq 443); the seq 443 quote
is now verbatim; the authority is D-084 plus seq 418, with seq 435 demoted to
a disputed draft; "single-shot" is replaced by "four-period (`H=4`), with a
copy-focal-previous partner type" in the choice bullet and in stop condition
3, whose collision search now includes finite-horizon repeated-game sources;
the Garcia negative result is cited as seq 411 and stated as seq 411 reports
it; "no host" is corrected to "no external corpus or retrieval input" (it
runs on the host); stop condition 2 now states one `Q` repair inside the same
2-attempt budget before the thesis ends; the revision count cites ten per seq
443 finding 4 with r11 making eleven.

One requirement added to the gate, from seq 467: the preregistration must
define how the six `(x, prior-partner-action)` states arise, including the
initial prior-action sentinel, and that state space is **2 x 3**, not 2 x 2.
The six states are `x in {0,1}` crossed with three prior-partner-action
values (the sentinel plus two actions); the count is inside the 64 adapters
(2^6) already pinned above, so this fixes the state construction, not the
trace count.

This note is the corrected head `oracle/2026-09-24-d3-r11`. Per seq 486, that
branch is the single ref for review and the dashboard: `oracle/2026-09-24-tgate`
lapses, and the branch is not fast-forwardable onto main (merge-base
`1a4d7b4`), so an accepted head is cherry-picked onto main, not merged.
