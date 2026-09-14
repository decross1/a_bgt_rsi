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

## Topic-scope diagnostic v2: format repaired, no material scope signal

The v2 diagnostic subsequently ran from the immutable `0e498f9` measurement
checkout. It repeated the complete v1 matrix: eight topics, four planner
states, two arms and seeds 17 and 29. Manifest SHA-256 is
`fbe8d2740e50c08af1f28a94ac5d45bcb6237418cb6f8cbddb428375414ab3f3`;
trial ID is `2026-W38-fbe8d2740e50c08af1f28a94`. All **80/80** declared
calls returned, the controller completed, and the trusted budget receipt
charged **139.203669 seconds** against the 2,400-second reservation. The
evaluator's failure-inclusive task time was 137.520397 seconds. Runtime
identity remained stable and all unused reserved time was released.

| Stage | Control | Candidate |
|---|---:|---:|
| Hypothesis protocol-valid | 16/16 | 16/16 |
| Planner protocol-valid | 8/8 | 8/8 |
| Planner preferred cases correct | 4/8 | 6/8 |
| Planner exact-copy provenance | 8/8 | 8/8 |
| Primary R0 returned and valid | 16/16 | 16/16 |

The single preregistered wire-format delta worked: all eight candidate planner
outputs used `action`/`args`, stayed within the frozen menu and budget, and
contained no menu-shaped `name` substitution. This supports the diagnostic
label **`FORMAT_CONTRACT_REPAIRED`**. It does not support
`PLANNER_SCOPE_SIGNAL`: P1, P2 and P4 chose their preferred topic on both
seeds, but P3 still selected an off-scope suggestion on both seeds. The
control did the same on P3. No action from any diagnostic plan was dispatched.

One subscription-only Claude annotation call covered all 93 blind candidate
items. It completed in 173.377 seconds, requested `claude-opus-5`, and reported
`claude-opus-5` plus `claude-haiku-4-5-20251001` in model-usage metadata. It
used no web search/fetch and had no paid API fallback or retry. The original
response was preserved. Its otherwise complete judgments arrived inside an
`annotation_template` envelope and used the invalid metadata value
`reviewer_kind=frontier_model`, which the operator prompt mistakenly requested.
A recorded format normalization only removed
that envelope and changed the reviewer-kind metadata to the receipt-consistent
`subscription_frontier`; all 93 judgment items retained the same canonical
SHA-256, `3ec783ddcd058b308c3d242db1ad787f154c8515fbc41672686a8a9f071c33b8`.
The normalized annotation SHA-256 is
`ae04f5087edd08f0d201eaa3a383cf35abd91ba7d03dbc37160a2443afa86bc1`.

| Independently graded measure | Control | Candidate |
|---|---:|---:|
| Strictly valid chosen results on the ten in-scope cells | 7/10 | 6/10 |
| Useful grounded repair on the six adjacent-topic cells | 0/6 | 1/6 |
| Chosen result judged in scope | 10/16 | 11/16 |
| Chosen result in scope, substantive and attribution-safe | 7/16 | 7/16 |
| All candidates judged out of scope | 18/48 | 11/45 |
| All candidates judged unclear | 0/48 | 2/45 |
| Unsupported attribution across all candidates | 6/48 | 11/45 |
| Primary R0 disagreement with the independent chosen annotation | 0 | 2 |

The locked semantic decision is **`NO-MATERIAL-SIGNAL`**. The candidate found
one grounded repair and reduced the count graded out of scope, but it regressed
from seven to six strict valid choices on the positive game-theory cells and
increased unsupported attribution from six to eleven candidates. It therefore
fails the preregistered larger-evaluation trigger. This public, reused,
single-reviewer development panel supplies no scientific-benefit or production
promotion claim. A resume check returned the existing terminal receipt with
zero new calls, zero additional budget charge, and byte-identical call, result
and ledger artifacts.

## Review-input qualification 02: invalid report, diagnostic says revise

A second bounded review qualified the newly exposed portfolio inputs from
commit `f35275544c551a632ac06e8a36907c771df5e074`. Its admission allowed exactly
two subscription calls within 600 seconds, no paid fallback and no production
authority. The target was the eight-task public synthetic portfolio manifest,
SHA-256 `a268fbf8eb2535066d97f6e7e15327300f35f0d1df727fdd039059b772bb10cf`.

Codex requested `gpt-6-astra` and returned in 104.868 seconds; its receipt does
not expose a resolved model ID. Claude requested `claude-opus-5`, returned in
181.324 seconds, and reported that model plus `claude-haiku-4-5-20251001`.
Both transports completed under subscription authentication. The proposal was
valid, but the adversary response was not strict JSON. It was not retried. The
authoritative report is therefore **`INVALID_REPORT`**, records independence
loss, contains no admitted experiment card, and authorizes no local trial.

For diagnosis only, a separate artifact removed the adversary response's
syntactic envelope without changing its content. That content says `revise`
and raises eight issues: a near-automatic pass rule without a material margin,
deadline/quality confounding, conflict with the week's earlier budget
allocation, incomplete handling of the prior pilot, underspecified time
attribution, single-sample family noise, a mislabeled change surface, and an
unstated clean-tree criterion. The diagnostic explicitly has no admission
authority and does not replace the invalid report.

The owner separately authorized a manual portfolio run as an infrastructure
baseline. That execution is independent of the invalid frontier review and is
not review-approved. At qualification time its outcome remained unreported;
the next section was added only after the terminal dispatcher receipt and
objective grades became available.

## Manual portfolio infrastructure baseline: incomplete transport

The separately owner-authorized portfolio run reached a terminal dispatcher
receipt. It used the immutable qualification checkout and the same manifest
described above. All 16 declared cells remain in the result, but three coding
requests reached their 180-second deadlines. The evaluator status is
**`incomplete_transport`**, the controller status is **`failed`**, and the
controller recorded no separate error. Its trusted receipt charged
**1,014.852476 seconds** against the 2,310-second reservation and released the
unused time. Preflight and postflight serving identities match, both queues
returned idle, the pinned bubblewrap/Python sandbox identity matched, and the
receipt validator reproduced the public objective grades without another
model call.

| Frozen result, failures included | A: xhigh | B: medium |
|---|---:|---:|
| Returned / timed out | 6 / 2 | 7 / 1 |
| Scientific/formal passes | 4/4 | 4/4 |
| Evidence passes | 2/2 | 2/2 |
| Coding passes | 0/2 | 1/2 |
| Total objective passes | 6/8 | 7/8 |
| Sum of cell wall time | 506.416325 s | 507.345490 s |
| Derived failure-inclusive correct-task throughput | 42.652653/hour | 49.670295/hour |

All twelve structured scientific/evidence cells returned and passed their
deterministic calculators, exact schemas and evidence-ID checks. The
delegation coding task timed out in both arms at 180.045027 and 180.116137
seconds. On the regret coding task, B returned in 161.322197 seconds and
passed all five fresh-process behavioral cases; A timed out at 180.115604
seconds. No returned completion hit its 6,144-token cap. The run-level
failure-inclusive elapsed time is 1,014.255880 seconds and its descriptive
aggregate Correct Task Throughput is 46.142202 completed tasks/hour.

A manual audit found no obvious false positive or false negative among the
thirteen returned cells: the twelve structured answers match independently
recomputed finite oracles, and B's returned code produced the expected parent-
checked values/exceptions in all five isolated cases. That finding has narrow
scope. The prompts, cases and oracles are public, the evidence packets are
synthetic and constrained, and there is only one seed. The three timeout cells
contain no gradeable answer, so their failures measure deadline-bounded task
completion rather than incorrect code. This deadline effect is also why B's
16.45% higher derived throughput cannot be interpreted as a capability gain.

The run is manual descriptive infrastructure evidence only. It did not pass a
review gate, does not supply a complete paired result, and supports no policy
or production change. Key durable hashes are:

| Artifact | SHA-256 |
|---|---|
| Manifest snapshot | `a268fbf8eb2535066d97f6e7e15327300f35f0d1df727fdd039059b772bb10cf` |
| Run | `c7ff223a81fd13d24699d3a7a05fe1cb65492648cd4fdfe39db52135c0be13c2` |
| Raw attempts | `48d6b157337db2d9c9ba79f1b35b84ccb9e3202a165808144c78c61581b9758c` |
| Objective outcomes | `c26bc2665689dc0a51789f8e87e7e8df315ef9e8c617986dc4c1e4eacdeba50b` |
| Durable calls | `1dda7b248867a34fbf9a4f5b805324e76056d0c1232979c4d03ad2764e813e3e` |
| Worker activity | `3ce2df81d8333f29a150527530476ac6dd8093db9f9ce4e9020b8796c24aa565` |
| Terminal trial result | `4355c85c6a766a7af7ff647de8f13b20716cee57fcad063f4affff3648d1e888` |

## Diversity plus selection canary: complete negative result

The manual public-development diversity canary ran from immutable commit
`f490c7ecce81a80a154b361e1869d4d08f6a65ac`. All **25/25** calls returned,
the runtime identity remained stable, and the trusted receipt replayed every
prompt, completion, parse and finite objective grade without another model
call. The controller charged **14.975764 seconds**; the evaluator recorded
13.675222 failure-inclusive seconds.

| Frozen objective result | Control | Diverse plus selection |
|---|---:|---:|
| Creditable task successes | 3/5 | 0/5 |
| Valid proposals | 6 | 5 |
| Valid unique proposals | 6 | 2 |
| Objective selection recoveries | 2 | 0 |

The primary unique-valid-proposal difference is therefore **-4** for the
diverse condition. All fifteen exploratory proposal calls parsed. The five
validator calls returned Markdown-fenced JSON despite the frozen strict-JSON
instruction; the control coalition response had the same formatting defect.
Every affected call stopped normally far below its output cap, so this was
schema compliance rather than timeout or truncation.

A post-hoc diagnostic inspected the fenced content without changing the
frozen grades. Two of five validator choices were objectively correct and
three were incorrect. Only the diverse coalition cell both contained a valid
candidate and chose one correctly, so accepting fenced JSON would move its
task-success total only from 0/5 to 1/5; control would remain 3/5 and the
primary -4 diversity result would not change. The ballot candidates were
invalid in both conditions; the diverse delegation and coordination
candidates were also invalid. The diverse pure-Nash candidates were valid but
duplicates and were not selected correctly. This result supports no
exploratory-policy promotion. A future trial requires a newly preregistered
structured-output validator and a fresh or held-out panel, rather than replay
of this run.

| Bound artifact | SHA-256 |
|---|---|
| Manifest snapshot | `0d1bb84609d7d7ea6f3c60a3ea4ae5a2670c727b47fe3400b906c1af68314ff4` |
| Replayed run | `02e08386436b2b57c535dda8b1ae36996a375b281f88eb934faf56cb1167bed5` |
| Terminal trial result | `4d0a46f31a42dde5213609edab5b90afb81e672abcd336654166c044113d49c6` |

## Resident long-context canary: complete with one Qwen schema failure

The context capability canary ran from immutable commit
`9d21f16b43d263a0df97de42c6104c7471dbcf01`. All **8/8** calls returned,
runtime identity was unchanged before and after the run, and the controller
charged **135.553790 seconds**. The result is descriptive because it compares
the resident defaults: deterministic non-thinking Gemma against deterministic
Qwen with its template-default `xhigh` thinking mode.

| Input band | Gemma | Qwen |
|---|---:|---:|
| Approximately 8K, two tasks | 2/2 | 1/2 |
| Approximately 14K, two tasks | 2/2 | 2/2 |
| Total | 4/4 | 3/4 |

Gemma used 14.239863 failure-inclusive seconds and Qwen used 120.107115.
Across both arms the run completed seven tasks in 134.347780 evaluator seconds,
or 187.572880 successful arm-tasks per wall-clock hour. These four public
synthetic tasks support no general capability or production claim.

The sole failure was Qwen's 8K grim-threshold task. It stopped normally after
528 of 1,024 allowed output tokens, so neither the reasoning cap nor timeout
caused the failure. Its content contained the correct answer code and all
three required evidence-role citations, with no factual error or citation
omission. A leaked thinking delimiter separated two copies of that correct
JSON object, causing the strict parser's extra-data failure. The original
failure remains authoritative; this diagnosis is not a regrade.

The pre-dispatch offline receipt bound the exact manifest, source generator,
execution dependencies, Transformers 5.8.1, Tokenizers 0.22.2, selected
tokenizer assets, template policies and rendered token-ID hashes. Frozen input
counts were Gemma **8,104 / 8,354 / 14,267 / 14,537** and Qwen
**8,138 / 8,383 / 14,286 / 14,573**. Live Qwen usage matched exactly. vLLM
reported one additional input token for every Gemma request; this uniform
host-versus-server accounting difference had no fit consequence under Gemma's
17,207-token minimum frozen margin. Qwen retained a 787-token frozen margin
after the full 1,024-token output reserve. The preregistration explicitly did
not claim an independent vLLM tokenizer implementation measurement. No 16K,
32K, or 64K input lane was measured by this run.

The immutable receipt validator replayed the complete artifact graph without
another model call and returned `execution_complete=true` and
`semantic_benefit_measured=false`. Before another context trial, a no-call
fixture should reproduce and repair Qwen's reasoning-channel separation; that
would require a newly preregistered run rather than regrading or replaying this
one.

| Bound artifact | SHA-256 |
|---|---|
| Manifest snapshot | `7a65db923631d01c296ba8e65e924e646c9134082bb2a600c099eeb66eb6f735` |
| Context tokenizer preflight | `aa1a48e787bdce8f0252530c2c81471618485cb6744a763ca6153ee76b8fe201` |
| Token measurement object | `16868ff8999336a82d8a20a4bf79ab2e44d80f6c7d922e113226e881894dd894` |
| Replayed run | `8af0b602b6adfc98e576cf03fb6099ee387b2f442943c0ca8dd2d2670c258229` |
| Terminal trial result | `bdfffa7ffdd5c83aed3ccb83f5e285cf4545d219ff0917fef119f6a7f5b7073a` |
