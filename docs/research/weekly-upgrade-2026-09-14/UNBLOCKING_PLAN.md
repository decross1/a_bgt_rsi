# Completing the weekly upgrade loop

Prepared 2026-09-14. This is an implementation tracker, not a completion claim
or a production change decision. The owner has authorized repository work.
Older handoff questions do not prevent code, tests, isolated diagnostics, or
Git/PR delivery within that scope.

**Owner decisions, 2026-09-14:** keep game theory and correct generated topics;
use subscription-only frontier sessions and design for at most **120 Spark
GPU-minutes per week**. Neither answer activates calls or scheduling. The
[implementation runbook](../../weekly_upgrade_implementation.md#owner-decisions-recorded-2026-09-14)
defines the shared accounting now implemented and tested in the delivery
worktree, along with the remaining activation limits.

## The immediate blocker begins in topic selection

The subsequent [topic-starvation audit](topic_starvation_audit.md) traced all
60 recent research dispatches to one stale machine-mined queue entry. That
entry's agenda copy had been consumed, but its duplicate follow-up remained
eligible. A fresh arXiv option was present throughout. Correct that queue
lifecycle before spending more calls replaying the same off-topic seed.

The [skeptic readiness audit](skeptic_readiness_audit.md) found that all 59
completed iterations in its seven-day snapshot were low-confidence and
off-domain. None passed the predicate that attempts an independent skeptic
call. The route exists. Optimizing Qwen alone cannot repair this eligibility
problem.

After the queue repair, a frozen, isolated replay of the R0 topicality gate
can distinguish bad retrieval, a bad
topicality judgment, and a mismatch between generated topics and the declared
research scope. All 89 recent primary topicality responses parsed as `off`;
the sampled recent topics concern collaborative ML while the gate expects
game theory. The owner has now confirmed game theory: correct upstream
topic selection/generation, including its mistaken assumption that suggested
paper titles have already been vetted. Retain the D-075 social-choice
extension, but do not expand the gate to general collaborative ML. A
counterfactual eligibility increase is not evidence that
the newly admitted claims are scientifically sound. Blindly demoting that gate
would trade an observed traffic problem for an unmeasured validity problem.

## Work sequence and completion evidence

| Work | Current state | Evidence required to close it |
| --- | --- | --- |
| Stable regression baseline | Public-artifact reconstructions and explicit-source path fixes added | Original scientific rows/aggregates and real hash-seed checks pass; no ignored raw stores are published; full integrated suite has no failures |
| Active Qwen builder label | Default corrected to registry Qwen3.8; explicit override retained | Canned endpoint verifies default and both override paths |
| Repeated machine-mined topic | Queue lifecycle and attribution fixes implemented; frozen replay removes all four handled entries | Consumed machine entries cannot recur; failed dispatches remain retryable; human follow-ups keep their semantics; observe the next deployed cycle |
| Generated-topic scope | Prompt corrections plus an immutable 80-call topic/planner/R0 diagnostic, blind export and local summary are implemented and tested; no live calls or annotations | Run the registered diagnostic; obtain complete independent blind annotations; summarize scope, usefulness/diversity, unchanged R0 and failure-inclusive time |
| Repeated frontier veto reviews | Opt-in cache implemented; production use remains off | Exact unchanged review reuses a complete veto; evidence, prompt, implementation, provider identity, TTL changes invalidate; outages stay uncached |
| Dormant skeptic diagnosis | R0 blockade located by recorded inputs | Reproducible read-only audit, then isolated paired replay with output/log paths checked before model calls |
| Role policy benefit | Profiles, paired runner and repeat-aware locked-pilot summarizer are implemented and tested; benefit unmeasured | Run all three registered repeats, validate every task/arm/seed cell, apply RSR/CTT rule, then confirm on broader independent tasks before role changes |
| Weekly research/review | Manual bounded Codex proposal and Claude adversary implemented | Validated report, literal source binding and receipts; rejected reports remain rejected |
| Weekly experiment execution | Fixed allowlist dispatcher, review binding, hard supervisor deadline, durable journal and no-replay recovery are implemented and tested; no live end-to-end execution | Exercise one manual registered trial and one newly admitted review path after canonical adoption; retain exact receipts and isolated artifacts |
| Weekly budget | Shared canonical 7,200-second ledger and cooperative execution/GPU/cron leases are implemented and tested; not adopted by the canonical checkout or loaded daemon | Adopt the reviewed code, verify the canonical ledger/lock inode, then prove accounting and resource coordination in a bounded live cycle |
| Broader benchmark coverage | Public development canaries exist | Independent repository coding tasks, scientific tasks and held-out evidence/context tasks with objective graders and provenance |
| Scheduled operation | New schedule not activated | Exact schedule, resource budget/coordination, stop control, trial-only runbook and successful manual end-to-end cycle |
| Challenger runtime | Unqualified | Exact weights/digest/launch configuration, reserved memory slot, same-policy comparison, both-model regressions and tested restore command |
| Production improvement | Not established | Repeatable project-level task benefit under reliability/memory constraints, plus recorded runtime/scientific decision when applicable |

## Next isolated experiments

**Queue repair first.** Verify the deterministic lifecycle and attribution
tests, then observe whether the next ordinary cycle chooses a different topic.
Do not hand-consume scientific agenda items or manufacture a successful cycle.
The owner scope answer preserves the scientific gate while this operational
fix removes stale machine topics from selection.

**Generated topics next.** Correct planner/generator instructions so raw paper
titles are not treated as scope-vetted or inherently human-authored. Favor
questions with real players, actions, incentives and testable strategic or
collective-choice outcomes. Mere use of “cooperation” or “equilibrium” is not a
pass. Freeze positive, negative and vocabulary-camouflage examples before any
paired call; compare semantic scope, usefulness/diversity and total time, not
only the fraction passing R0. A prompt correction is not measured evidence of
better science. Preserve the input titles and downstream rejection receipts.
The [40-minute diagnostic design](../../../experiments/PREREG_topic_scope_repair_2026-09-14.md)
defines eight development topics (including the observed failing seed) and four
planner-state cases. The immutable execution manifest is
`experiments/topic_scope_repair_2026-09-14.json`, SHA-256
`aab09640a9d377fc0a2a1c830223f5cd8b4e7e20299ac968d7bd01f2512b06a2`.
The registered dispatcher always includes the unchanged primary R0 arm: 32
hypothesis calls, 16 planner calls and 32 R0 calls, for at most 80 serial local
calls inside a 2,370-second evaluator payload and 2,400-second reservation.
Its model calls remain unexecuted; subjective scope grading still needs complete
independent annotations from the blinded package. Raw completions and the
private arm map stay in the isolated output and must not be published.

**R0 diagnostic if needed.** Follow the audit's frozen-record selection and compare
the current predicate with independent domain annotations. The existing advisory
counterfactual remains diagnostic only; the owner selected topic correction,
not demotion of R0. Add independent
review of whether each evidence packet actually fits its question. The
diagnostic may produce fewer or more eligible candidates; neither direction is
intrinsically a win. Keep the original evidence and critic outputs for paired
inspection. Do not accept or dismiss the existing scientific agenda to make its
acted-on rate look better.

**Qwen effort pilot after route diagnosis.** The executable manifests and explicit decision
rules are in
[the preregistration](../../../experiments/PREREG_weekly_qwen_effort_pilot_2026-09-14.md).
They compare only xhigh versus medium on the existing runtime, with equal
sampling, output caps, request deadlines and task inputs. These are six public
development templates repeated three times, not a replacement for the older
skeptic sentinel study or a hidden confirmation panel. The pilot can justify
a larger trial; it cannot promote a policy.
Its 112.5-minute reservation replaces that week's panel, leaving at most
7.5 minutes for other charged work. Defer it when that cannot cover overhead
and already-used time; do not quietly shorten only one arm or run it on top of
the regular panel. Keep this study behind the topic-scope diagnostic.

Each Qwen repeat reserves 2,250 seconds and gives the evaluator a fixed 2,220-
second payload; the 30-second envelope covers preflight and supervisor shutdown.
The three reservations total 6,750 seconds. An active 2,400-second topic
reservation leaves only 4,800 seconds and therefore cannot coexist with the
pilot. Even after a trusted topic terminal receipt releases unused time, the
pilot may start that same week only if the canonical ledger shows at least
6,750 seconds remaining, meaning every prior charge combined is at most 450
seconds. An interrupted topic run retains the full charge and pushes the pilot
to another week.

Run local calls in a known idle window. The delivery dispatcher now takes the
exclusive execution, coordinator-cron and GPU locks, checks a 30 GiB
`MemAvailable` floor plus both endpoint queues, and passes the exact GPU lock
descriptor to its independently supervised child. Ordinary Gemma/Qwen calls in
the delivery wrapper take the corresponding shared lock. This coordination is
cooperative: arbitrary processes can ignore it, and the already-running daemon
continues using older imported wrapper code until an explicit canonical
adoption and reload. The coordinator-cron lock does coordinate with the old
daemon cycle. Do not stop a production service merely to complete this pilot.

## Convert weekly advice into executed work

The typed registered-trial dispatcher now implements this boundary. An analyst
may identify a supported experiment, but repository code selects the module and
fixed caps from an allowlist; free-form analyst shell commands are never an
execution interface. Its current card catalog is:

| Registered trial | Reservation | Evaluator payload |
|---|---:|---:|
| Public 12-task objective canary | 1,800 s | 1,770 s |
| Qwen effort seed 17, 29 or 43 | 2,250 s each | 2,220 s each |
| Topic-scope diagnostic with R0 | 2,400 s | 2,370 s |

Inspect a complete offline plan without model calls, writes, ledger reservation,
locks or endpoint probes:

```bash
.venv-chroma/bin/python -m orchestrator.weekly_upgrade_trial --plan \
  --manifest experiments/topic_scope_repair_2026-09-14.json
```

Live execution has two explicit, mutually exclusive modes. `--manual` is an
operator's deliberate invocation of a registered preregistered trial:

```bash
env -u MOCK_LLM .venv-chroma/bin/python -m orchestrator.weekly_upgrade_trial \
  --run --manual \
  --manifest experiments/topic_scope_repair_2026-09-14.json \
  --output-dir /tmp/weekly-topic-scope-2026-W38
```

`--review-dir` instead requires and revalidates a completed two-provider review
with `CONTINUE_TRIAL`, exact receipts, snapshot, card and execution fingerprint:

```bash
env -u MOCK_LLM .venv-chroma/bin/python -m orchestrator.weekly_upgrade_trial \
  --run --review-dir /tmp/weekly-review-2026-W38 \
  --manifest experiments/topic_scope_repair_2026-09-14.json \
  --output-dir /tmp/weekly-topic-scope-reviewed-2026-W38
```

Both use an isolated fresh output outside the worktree and canonical checkout.
The canonical checkout owns the single 120-minute UTC ISO-week append-only
ledger and durable trial journal across all worktrees and output directories.
The dispatcher reserves before resource preflight, runs a fixed command under
cooperative locks and GNU `timeout`, then records terminal actual usage. Resume
uses the journal, artifacts and live process handles; a post-reservation run is
never replayed blindly. An uncertain orphan is interrupted and fully charged.
The requirement that the registered manifest and execution dependencies be
committed and clean binds evidence to executable code; it is an experiment
integrity check, not a new gate for authorized Git work.

The Qwen repeat summarizer and topic blind grading path are also implemented.
The former validates all planned task/arm/seed cells, produces RSR 2-of-3,
task-clustered paired bootstrap, family tables and failure-inclusive CTT, and
omits raw completions/tool payloads. The latter exports candidate text without
the private arm/source/prompt mapping and requires complete independent
annotations before summary. No raw private benchmark inputs belong in Git.

These mechanisms are implemented and tested without models. They have not yet
been adopted in the canonical checkout or exercised by a live manual trial or
newly admitted review. The running daemon imported older code and will continue
to do so until explicit activation/reload. No independent topic annotations or
scientific gain measurement exists yet.

A future first scheduled cycle should scan, review and execute an admitted
bounded trial, then produce a measured decision. No scheduler or new cron has
been activated. Ordinary code fixes can be prepared, tested and delivered under
standing maintenance authority. A proposed serving change needs a concrete
configuration, evidence and rollback before final activation. That boundary
comes from the deployed runtime contract and the handoff's exclusion of a
production cutover, not a new Git approval requirement.

## Reporting rule

Keep these states separate: implemented, tested without models, live protocol
verified, task benefit measured, merged, activated. Do not label the original
request complete while scheduled execution, benchmark coverage or demonstrated
benefit remains unfinished. No new runtime or weekly recurrence was activated
by this unblock tranche. There has been no live evaluation, independent
annotation, new review-to-trial integration, canonical adoption, service reload
or scheduler activation, and no scientific or performance gain is claimed.
