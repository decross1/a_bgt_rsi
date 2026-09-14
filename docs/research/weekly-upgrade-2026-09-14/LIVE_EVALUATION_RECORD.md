# Live weekly-upgrade evaluation record

Updated 2026-09-14 UTC. This record separates completed measurements from
implementation, diagnosis and production activation. Raw completions and private
grading maps remain outside Git.

## Canonical adoption

Public PR [#18](https://github.com/decross1/a_bgt_rsi/pull/18) merged as
`d920cba71077480035690cd0389a74b42077b231`. The canonical checkout adopted it in
the local-only merge `bf7561188c03e2759196abd03066bd955af8ba27`, preserving its
private history. All nine pre-existing dirty tracked files were preserved
byte-for-byte, as were 20,365 unrelated untracked files. Four identical
untracked colliders were retained in a recoverable sibling backup before their
identical public versions became tracked. No private history was pushed.

The daemon running since September 2 was not restarted. Its imported Python
code predates adoption. The existing coordinator lock still coordinates its
ordinary cycles with the diagnostic; broader participation in the new wrapper
lease requires a separately authorized reload. No schedule, model role,
runtime, context limit or production scientific gate was changed by this run.

## Shared accounting and artifact locations

The canonical `run_state/weekly_upgrade_budget.jsonl` is the one 7,200-second
UTC ISO-week ledger. Private artifacts for this campaign are under
`/home/decross1/projects/a_bgt_rsi_upgrade_runs/2026-W38/`.

Before the first registered trial, five earlier smoke/probe groups were imported
as a **180-second conservative accounting debit**. Their evidenced timing
totals 16.885197 seconds; the remaining 163.114803 seconds is an explicit policy
buffer. Two call logs lack outer setup/cleanup timing. The debit is neither a
measured total nor a proven worst-case upper bound. The private report binds
the original file and session-record byte-range hashes without exporting their
contents. Its SHA-256 is
`4b9e7a0876b4bed4fd4f0861a31e1a7bd129673407a5ae181019c1c90e52e380`.

## Topic-scope diagnostic v1: a planner protocol regression

The preregistered manifest
`experiments/topic_scope_repair_2026-09-14.json` was executed through the
registered manual dispatcher using committed code `ace866c91859c4234632c0806cf77700121dc40f`.
The fixed reservation was 2,400 seconds, with a 2,370-second payload. The
trusted terminal receipt charged **136.967069 seconds** and released the unused
reservation. Both resident runtimes retained their identities and returned to
idle. The ledger balance after the historical debit and this run was
**6,883.032931 seconds**.

Manifest SHA-256:
`aab09640a9d377fc0a2a1c830223f5cd8b4e7e20299ac968d7bd01f2512b06a2`.
Trial ID: `2026-W38-aab09640a9d377fc0a2a1c83`.

| Stage | Declared attempts | Returned calls | Protocol-valid results |
|---|---:|---:|---:|
| Hypothesis generation | 32 | 32 | 31 |
| Planner selection | 16 | 16 | 8 |
| Unchanged primary R0 | 32 | 31 | 31 |

All eight candidate planner responses used the key `name` instead of the
required wire-format key `action`. The existing production validator also
rejects this output; it is not merely an evaluator mismatch. All eight control
planner responses satisfied the diagnostic contract. One control hypothesis
on T6/seed 29 violated the candidate/chosen contract, so its R0 call was
recorded as missing rather than sent on an invented replacement.

The declared 80 attempts remain in the denominator, including the unsent R0
attempt. The terminal evaluation is `incomplete_transport`, with a failed
dispatcher receipt. No result was retried, removed, repaired in place or
relabeled as success. This is useful negative evidence about the prompt
change, not evidence of better scientific output.

The blind export contains 90 gradable hypotheses and no private arm map. Its
SHA-256 is `75ca190dd896ec53f8bb688b79446b62ab456e8abd0fe2b2efbf1f4923e080c0`.
Independent subscription-only Claude annotation completed in 147.077 seconds
within its finite 300-second deadline and one-attempt limit. All 90 candidate
annotations passed the local coverage/schema checks. The reviewer identified
itself as `claude-opus-5`; the CLI receipt reports that model plus
`claude-haiku-4-5-20251001` in its model-usage metadata. No model tools, web
requests or paid API fallback were used. Annotation SHA-256:
`8818a016d442a02c7bd994df95f47704df125b4ba90e3e669216376b8ad20413`.

| Semantic/operational measure | Control | Candidate |
|---|---:|---:|
| Valid chosen hypotheses on the ten positive GT cases | 10/10 | 10/10 |
| Useful grounded repair on the six adjacent-topic cases | 0/6 | 1/6 |
| All candidate hypotheses independently judged out of scope | 15/45 | 13/45 |
| Generic candidate hypotheses | 0/45 | 2/45 |
| Valid planner responses | 8/8 | 0/8 |
| Primary R0 `on` judgments | 10/16 | 14/16 |
| R0 disagreement with independent chosen-hypothesis annotations | 0 | 3 |

The locked summary is **`INVALID/INCOMPLETE`**. Positive GT retention is
encouraging, but a one-case grounded repair cannot overcome the planner
regression. R0 admitted three candidate outputs that the independent reviewer
judged out of scope; its higher pass rate is therefore not evidence of better
scope fidelity. These are small public development cases graded by one
independent model, not a calibrated human gold standard. The planner repair
and any hypothesis-policy follow-up require new preregistered evidence.

## Qwen effort pilot admission

After the topic diagnostic, the ledger had capacity for the entire
preregistered three-repeat maximum: **6,750 seconds**. The admission receipt
freezes all three manifest hashes and that initial balance. Execution uses a
separate, immutable measurement checkout at `ace866c`, so subsequent coding
changes cannot alter an in-flight experiment.

The pilot compares the same Qwen weights/runtime and sampling at `xhigh`
versus `medium` effort. All three seeds and six task templates are required
for its locked decision. Admission and an in-progress run do not establish a
policy benefit; terminal receipts and repeat-aware grading remain required.

The first repeat (seed 17) attempted all twelve cells and charged **686.981549
seconds**. Under the frozen graders, xhigh passed 4/6 and medium passed 3/6.
Their failure-inclusive call time was 485.315622 and 199.942412 seconds,
respectively. Xhigh reached its 180-second deadline on the theorem case;
subsequent calls returned normally and the dispatcher confirmed unchanged
serving identities and idle postflight. The receipt is `failed` with evaluator
status `incomplete_transport`, retaining the timeout as a failed planned cell.

The operator driver paused on that nonzero evaluator status. Inspection found
a bounded request deadline, rather than a serving/lease failure or an omitted
dispatch. The remaining two original seeds were then continued under the same
immutable code, task definitions and caps. Seed 17 was not retried. The locked
summary remains unable to support a gain when transport is incomplete. A
separate post-hoc audit checks for false-negative grading before interpreting
the pass counts as model quality; it cannot change the frozen outcomes.

That [grader audit](PILOT_GRADER_AUDIT.md) found two high-confidence
fixture/grader false negatives on the attrition task: both arms selected an
explicitly offered answer that the evidence supports, but the grader admitted
only another simultaneously true label. Medium effort also gave a correct
theorem decision/reasoning while missing the requested exact reason code. Its
circular-critic decision was a substantive error. A diagnostic semantic audit
would give 5/6 to each arm, retaining the xhigh timeout, but **those post-hoc
counts cannot replace 4/6 versus 3/6 in the locked study**. The original labels,
scores and artifacts remain intact. Any ambiguity or taxonomy correction needs
a new fixture/grader version and a separately preregistered comparison.

### Complete three-repeat execution and reporting limitation

All 36 planned task/arm/seed cells were attempted. Seeds 29 and 43 completed
their transports and charged 478.599992 and 668.162487 seconds, respectively.
The resulting frozen counts are:

| Seed | Xhigh successes | Medium successes | Xhigh call seconds, failures included | Medium call seconds, failures included |
|---|---:|---:|---:|---:|
| 17 | 4/6 | 3/6 | 485.315622 | 199.942412 |
| 29 | 4/6 | 4/6 | 260.591468 | 216.348720 |
| 43 | 5/6 | 5/6 | 440.091541 | 227.071658 |
| Total | 13/18 | 12/18 | 1,185.998631 | 643.362790 |

RSR 2-of-3 is 4/6 task templates for xhigh and 5/6 for medium. Descriptive
failure-inclusive correct-task throughput is 39.460417 and 67.147185 tasks
per arm-hour, respectively. These are six repeated public development
templates, with the grader ambiguity described above. They establish neither
a production capability gain nor a sound trade of reliability for speed.

The original repeat reader rejected the first repeat's correctly recorded
`failed` controller status and returned **`INVALID`**. Its artifact remains
preserved. A narrow reporting repair now accepts a hash-bound ordinary
incomplete evaluator exit (`failed`, return code 3, no controller error) while
retaining all canonical ledger/journal, runtime and artifact checks. It still
rejects interrupted, crashed or drifted execution. The revised, separately
written summary is **`INCOMPLETE`, `supports_gain=false`**. This changes the
classification of negative evidence, not any fixture, answer, score or
promotion threshold; it was written after observing the reader defect.

After the three repeats, the shared weekly ledger records **2,150.711097
seconds consumed (35.845185 minutes)**, including the earlier debit and topic
diagnostic, with **5,049.288903 seconds remaining** and no active reservation.
The public runtime and policy remain unchanged.

### Live resume verification

Reopening the original topic diagnostic with the same immutable code, plan
and output returned its existing failed terminal receipt. The raw call log,
terminal result and canonical budget ledger stayed byte-identical. It made
zero new model calls and charged zero additional time. The external
`topic-scope-resume-proof.json` records these hashes; a failed scientific or
protocol result is not silently retried by resume.

## First complete manual weekly review: revision required

The new cycle passed readiness from the immutable `0e498f9` measurement
checkout. It refreshed eight configured primary sources and completed both
subscription review attempts. Codex requested `gpt-6-astra` and returned in
95.101 seconds; its receipt provides no resolved model IDs. Claude requested
`claude-opus-5`, returned in 100.240 seconds, and reports that model plus
`claude-haiku-4-5-20251001` in CLI usage metadata.

Claude returned `revise`; the review is **`REVISION_REQUIRED`** and the cycle
is **`REVIEW_COMPLETE`**. The card was not admitted, no local trial started,
and no Spark reservation was consumed. Both provider attempts and the
unchanged rejected report remain under
`a_bgt_rsi_weekly_upgrade_runs/2026-W38/`.

The review exposed a real snapshot defect: executable entries supplied arm
IDs and caps but omitted their fixed settings. The proposal consequently
could not name a concrete difference. It also proposed a semantic repair
pass rate without a precise denominator or an executable independent grader.
The corrected snapshot supplies actual public arm settings, ordering,
resource limits, preregistration text and the distinction between local
objective grading and topic outputs requiring independent blind annotations.

Other objections are useful limits rather than proof of implementation
failures. The topic matrix is deliberately reused public development data;
it cannot establish held-out scientific benefit. The existing dispatcher
already interleaves the fixed matrix, takes the coordinator/GPU locks,
validates effective call settings, and gives the evaluator 2,370 seconds
inside a 2,400-second reservation. The original topic diagnostic had no
timeout; that failure occurred in the separate Qwen pilot.

The previously preregistered v2 planner diagnostic remains a separate manual
development measurement, with explicit operator admission and one separately
budgeted blind-annotation call. It is not execution of the rejected weekly
card. Its first two launch attempts met the occupied ordinary coordinator
lock before any reservation or model call; both refusal logs are preserved.
