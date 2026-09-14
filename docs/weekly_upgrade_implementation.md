# Weekly upgrade tooling: implementation and operation

Prepared 2026-09-14. Entry point for the implementation built from the
[Claude handoff](weekly_upgrade_loop_handoff.md) and the separately reviewed
[Codex research](research/weekly-upgrade-2026-09-14/CODEX_RESEARCH_HANDOFF.md).
The owner directed Codex to proceed and use both reviews as evidence.

## Owner decisions recorded 2026-09-14

**Research scope:** “Keep game theory; correct the generated topics.” Retain
game theory, behavioral game theory and learning in games, including the
already-ratified D-075 delegation, liquid-democracy, social-choice and sortition
extension. Collaborative ML is relevant only when the actual question concerns
strategic behavior, incentives or collective choice. Adding game vocabulary to
an infrastructure/performance claim does not make it in-domain. Correct the
upstream topic/planning instructions; keep R0 and its scientific criteria.

**Budget:** “Subscription-only frontier sessions, with up to 2 Spark GPU-hours
per week.” This sets the design limits; it starts no paid calls or jobs.
Use authenticated subscription CLI sessions; no metered API fallback. The
current review permits at most two attempts (Codex proposal, then Claude
adversary), with no retries; an early failure can prevent the second call. The
existing agenda also permits up to two. When explicitly enabled, the new
weekly hook replaces that agenda branch, so the scheduled invocation remains
bounded to two subscription attempts. It does not run both workflows. Separate
manual diagnostic annotation calls have their own finite receipts; the owner
decision does not set a numeric subscription-session cap or activate cron.

The earlier public dispatcher/budget tranche now enforces the **shared 120
Spark GPU-minute weekly ceiling** through one canonical ledger and has been
adopted by the canonical checkout. The weekly cycle, corrected review inputs,
and completed measurement panels are the subject of
[public PR 19](https://github.com/decross1/a_bgt_rsi/pull/19). Because this file
is part of that delivery, it does not predict its own final commit. The exact
public merge SHA, private adoption SHA, and dirty-state preservation hashes are
recorded afterward in the canonical external completion receipt. The
already-loaded daemon still imports older code:

- One ISO week, Monday 00:00 UTC through the next Monday, with no carryover.
  Charge the one physical Spark's reserved elapsed time once, including both
  resident models; do not grant separate allowances to each model, arm or run.
- Count all upgrade-triggered GPU work: preflight generations, warmups, trials,
  failed/time-out requests, retries, challenger loading and recovery. Frontier
  subscription analysis and CPU-only planning use zero Spark GPU minutes.
- Treat this as a separate upgrade allowance from D-063's daily coordinator
  activity-unit ledger. Both still require physical-resource coordination;
  a separate accounting allowance does not create an idle resource window.
- Reserve against the remaining weekly balance before dispatch. All checkouts,
  output directories and resumed sessions resolve the canonical checkout and use
  `run_state/weekly_upgrade_budget.jsonl`. Its sidecar lock serializes processes;
  its fsynced append-only records carry sequence and hash-chain checks. An empty,
  partial, corrupt or inconsistent journal fails closed.
- Active reservations charge their full maximum. A trustworthy
  `completed`/`failed`/`cancelled` receipt charges measured elapsed time and
  releases the unused reservation; `interrupted`/`unknown` retains at least the
  full reservation. An honest overrun or imported prior-use debit is recorded
  even when it takes the week over 7,200 seconds, preventing another same-week
  dispatch. Run IDs are single-use across output directories and week rollover.
- Defer any run whose maximum duration could cross the next Monday 00:00 UTC;
  do not borrow from the next week. The registered dispatcher starts accounting
  before its resource preflight, so that preflight and recovery consume the same
  reservation rather than creating an unmetered prefix.
- A normal design allocation is 15 minutes of canaries, 90 minutes for one
  admitted trial and 15 minutes for GPU-using preflight/recovery. This is an
  allocation, not a measured runtime promise. A larger preregistered panel
  replaces that allocation; it never adds another allowance.

The review controller's `--max-gpu-minutes` still validates only one proposed
experiment card. It does not grant or reserve GPU time. The separate registered
trial dispatcher now performs the cumulative reservation, cooperative resource
lease, bounded child execution and terminal accounting. Monthly, deeper and
runtime campaigns share the same ledger unless the owner explicitly changes
the budget contract.

The [Qwen pilot](../experiments/PREREG_weekly_qwen_effort_pilot_2026-09-14.md)
reserved 112.5 minutes across three 37.5-minute registered repeats. All 36
cells ran. Trusted terminal receipts released unused reservations and charged
1,833.744028 seconds for those repeats. Including the conservative prior-use
debit and topic v1, the canonical ledger then showed **2,150.711097 seconds
(35.845185 minutes) consumed**. The locked result is `INCOMPLETE` and supports
no gain: xhigh passed 13/18 versus medium 12/18, with one xhigh timeout. The
post-hoc grader audit found ambiguities but does not alter the frozen result.

After all authorized manual panels, the canonical ledger recorded
**3,455.296794 seconds (57.588280 minutes) consumed** and **3,744.703206
seconds remaining** in the 7,200-second UTC-week allowance. The ledger is
authoritative; displayed per-panel values are rounded independently. No GPU
trial remains active.

## Delivered scope

- Model-aware generation profiles on sync, async, wrapper tool loops, Nara,
  and bounded subagent calls. Existing callers keep their sampling defaults.
- Optional, additive call telemetry for resolved policy and response termination.
- Correct vLLM provenance for Qwen's existing endpoint.
- Persistent default subagent call logging, with the actual legacy temperature
  0.2 recorded; explicit `log_path=None` retains in-memory logging.
- Twelve objective task templates with paired AB/BA execution, immutable run
  manifests, exact graders, recorded errors/timeouts, and descriptive uncertainty.
- An explicit weekly maintenance review: source collection, local snapshot,
  Codex proposal, Claude adversarial review, validated experiment card and journal.
- A bounded subscription CLI transport separate from the scientific frontier
  transport, with receipt reservation, time limits, output limits, and no tools.
- Frozen reconstruction inputs for the older calibration studies, a builder
  model-default drift fix, a read-only skeptic-readiness audit, and an opt-in
  cache for exact completed frontier vetoes.
- Suppression of already-handled machine follow-up topics using existing
  consumption/dispatch receipts, plus correct planned-topic source attribution.
- Planner/hypothesis prompt corrections: suggested paper titles are unvetted;
  prioritize substantive game-theory/collective-choice questions and preserve
  verbatim specificity only within scope. The evaluate-as-stated bypass remains.
- A fixed 7,200-second UTC ISO-week ledger shared through the canonical checkout,
  with cross-process reservations, fail-closed recovery and exact terminal usage.
- A cooperative inference lease: ordinary Gemma/Qwen backend calls take the same
  shared lock, while a weekly trial takes exclusive execution, coordinator-cron
  and GPU locks. The supervised child inherits the exact GPU-lock descriptor, so
  a new descriptor or wrong inode cannot bypass an exclusive trial.
- An allowlisted trial dispatcher for the public objective panel, the three
  preregistered Qwen repeats and the topic-scope diagnostic. It binds a committed
  manifest and execution fingerprint to canonical state, isolated artifacts,
  endpoint/memory checks and an independent GNU `timeout` process-group deadline.
- Before, during and after execution, the dispatcher checks resident container
  IDs, image IDs, process/start identity and a hash of launch arguments. A
  restart or serving change invalidates the experiment even if its answers pass.
  `preflight.json` and `postflight.json` retain these observations; backend
  version labels alone are insufficient runtime evidence. This is periodic
  monitoring, not a claim that every transient resource change is observed.
- The topic-scope harness, its immutable public development manifest, optional
  unchanged R0 replay, blind export, independent annotation contract and local
  summary. The registered 40-minute form includes all 48 generation/planner
  attempts plus 32 primary-R0 attempts: 80 serial local calls at most.
- A repeat-aware objective summarizer that checks all task/arm/seed cells and
  configuration hashes, reports RSR 2-of-3, task-clustered bootstrap intervals,
  family metrics and failure-inclusive correct-task throughput, without copying
  raw completions or tool payloads.
- A default-off weekly cycle integrated into the existing Sunday owner. When
  enabled it replaces, rather than adds to, the legacy agenda firing; it refreshes
  bounded sources, incorporates sanitized prior outcomes, performs at most one
  Codex proposal and one Claude adversary attempt, and can dispatch only an exact
  registered card. Pause, week-boundary, durable no-replay and finite child-kill
  behavior are covered by focused tests.
- An eight-task public synthetic game/science/evidence/executed-code portfolio
  with deterministic parent-side grading and sandbox receipts. Its authorized
  manual baseline completed all 16 cells in 1,014.852476 charged seconds: arm A
  passed 6/8 and arm B 7/8. Both passed science 4/4 and evidence 2/2; executed
  code was 0/2 versus 1/2. Three timeouts remained in the denominator and no
  separate error outcome occurred.
- A four-task public synthetic long-context panel using the existing objective
  runner. Review of its first revision exposed ambiguous citation grading and
  missing dispatch-time token validation. The corrected manifest
  `7a65db923631d01c296ba8e65e924e646c9134082bb2a600c099eeb66eb6f735`
  binds full tokenizer preflight and explicitly records Qwen's default xhigh
  thinking versus Gemma thinking off. Its largest Qwen request is 15,597 total
  tokens, 787 below the current 16,384 limit. All eight cells completed in
  135.553790 seconds: Gemma passed 4/4 and Qwen 3/4; at ~8K the split was 2/2
  versus 1/2 and at ~14K both passed 2/2. This is a cross-model capability
  observation, not a causal context- or policy-gain claim.
- A registered five-task Gemma diversity-plus-objective-selection panel with 25
  bounded calls and finite feasibility graders. All 25 calls completed in
  14.975764 seconds. The control passed 3/5 tasks with six valid unique
  proposals; diversity plus selection passed 0/5 with two. It supports no gain.
- Six authentic public historical repairs with exact base-fail, fix-pass and
  reverted-file mutation receipts. This proves task/grader curation only; no
  agent repair runner is registered and no agent coding performance is measured.

The [topic-scope diagnostic](../experiments/PREREG_topic_scope_repair_2026-09-14.md)
has run twice. Its locked v1 result is `INVALID/INCOMPLETE`: all eight candidate
planner responses used the wrong action key, one R0 call was correctly omitted,
and independent blind annotation found only one of six grounded repairs plus
three candidate/R0 disagreements. V2 completed 80/80 protocol-valid calls in
139.203669 seconds and both planner arms passed 8/8. A 173.377-second independent
Claude pass covered 93 annotations. Its conclusion is
**`NO-MATERIAL-SIGNAL`**:
grounded adjacent-topic repair stayed 0/6 versus 1/6, valid on-domain choices
were 7/10 versus 6/10, and R0 disagreements were 0 versus 2. The original
annotation envelope used the wrong kind; a recorded local normalization retained
byte-equivalent judgment items and made no call retry. Neither run establishes
better generated topics or R0 accuracy.

The [completion tracker](research/weekly-upgrade-2026-09-14/UNBLOCKING_PLAN.md)
separates the completed initial evaluation set from Git-delivery and activation
closure. Topic v2 found no material signal, the Qwen pilot remained incomplete,
and no production-policy change follows from either result.

The [live evaluation record](research/weekly-upgrade-2026-09-14/LIVE_EVALUATION_RECORD.md)
records canonical adoption, both topic diagnostics and blind annotations, the
complete three-repeat Qwen pilot, resume-without-replay, and the first manual
weekly cycle. That cycle refreshed eight sources and completed both subscription
attempts, but correctly ended `REVISION_REQUIRED`: the card omitted actual arm
settings and proposed imprecise semantic metrics, so no trial was admitted and
no Spark time was charged. A separately preregistered corrected-input
qualification produced a valid Codex card, but Claude returned fenced JSON that
the strict parser rejected; the report is `INVALID_REPORT` and admitted no
trial. Its diagnostic content also recommended revision. No provider call was
retried. Scheduling and runtime qualification remain separate from code
adoption. No schedule, serving restart, model-role swap, context increase or
production promotion has been activated.

## Corrections established during implementation

1. Qwen is reachable through `run_loop_iteration` → Nara → `critic_loop_v0` →
   `_maybe_run_skeptic`. Absence of a standalone coordinator skeptic action does
   not establish an unreachable seat. Retrieval confidence and critic verdicts
   gate that route. Sparse traffic is still an operational investigation;
   repairing telemetry does not prove the scientific funnel is repaired.
2. The installed Qwen template accepts `low`, `medium`, and `xhigh`; its default
   thinking effort is `xhigh`. It also accepts `enable_thinking=false`. A live
   profile smoke returned `{"sum":2}` at the existing endpoint with thinking off.
   `high`, `none_or_low`, and `medium_or_high` are not valid effort values here.
3. Many workers already override temperature. Profiles make these choices
   explicit and measurable; temperature changes alone do not establish a gain.
4. The existing subagent request used temperature 0.2 while its record said 0.0.
   Default logs also went to memory. Both telemetry defects are corrected.
5. The 64K lane and SGLang/DFlash2 remain qualification experiments. Existing
   production context limits remain 32K Gemma and 16K Qwen. The measured
   8K/~14K capability panel fits both contracts and completed 8/8 responses; it
   compares different resident models and disclosed reasoning defaults. A 32K
   comparison remains Gemma-only and 64K remains inadmissible under the resident
   launchers. No broader context or policy claim follows from this small panel.

## Profile use

```python
from agent_wrapper.wrapper import call_sync

record = call_sync(
    [{"role": "user", "content": "Explain this experiment's confounders."}],
    backend="vllm-qwen",
    profile="critic_medium",
    max_tokens=2048,
    request_timeout_s=120,
    log_path="/tmp/my-evaluation/calls.jsonl",
    caller_tag="my_evaluation",
)
```

Profiles are experimental configurations, not an automatic role router. An
explicit caller temperature/top-p/seed overrides the profile. Unsupported
backend/model/effort combinations raise instead of silently dropping controls.
`WRAPPER_PROFILE_OVERRIDES` optionally maps exact caller tags to profile names
as JSON; leave it unset in production until the candidate policy is qualified.

| Profile family | Purpose |
|---|---|
| `deterministic`, `planner`, `precise`, `dialog` | Explicit control policies |
| `coding_precise`, `scientist`, `explore`, `critic` | Role experiments |
| `critic_current`, `critic_medium`, `critic_low` | Qwen effort comparisons |
| `qwen_card_thinking`, `qwen_card_coding`, `qwen_card_instruct` | Qwen sampling/template experiments |
| `gemma_card`, `gemma_card_thinking` | Gemma sampling/template experiments |

Gemma thinking and Qwen effort use different request controls. Server-supplied
reasoning is retained in profiled tool history when required by the template.
Unavailable reasoning-token counts are not invented: response telemetry records
available reasoning characters and nullable finish metadata. No-profile call
records remain valid under the additive schema.

`request_timeout_s` bounds the wrapper request/tool-loop transport and disables
SDK retries for budgeted requests. Arbitrary Python tool functions still need
their own bounded execution. Existing Nara/subagent direct-call wall budgets
remain checks between turns; this change does not claim to fix that older
whole-call deadline gap. The weekly canary uses the bounded wrapper path and
only fixture-owned simple tools.

## Evaluation

Use the project's Python environment (for example `.venv-chroma/bin/python`).
The fixed catalog and its current evidence are:

| Manifest | Trial | Reservation | Payload | Calls | Evidence state |
|---|---|---:|---:|---:|---|
| `bench/weekly_upgrade_eval/fixtures.json` | objective canary | 1,800 s | 1,770 s | 24 | registered development canary |
| each Qwen seed manifest (`17`, `29`, `43`) | objective repeat | 2,250 s | 2,220 s | 12 | all three measured; locked `INCOMPLETE` |
| `experiments/topic_scope_repair_2026-09-14.json` | topic scope + primary R0 | 2,400 s | 2,370 s | 80 | v1 measured `INVALID/INCOMPLETE` |
| `experiments/topic_scope_repair_v2_2026-09-14.json` | planner protocol repair + unchanged R0 | 2,400 s | 2,370 s | 80 | measured; `NO-MATERIAL-SIGNAL` |
| `experiments/weekly_upgrade_game_science_dev_v0_2026-09-14.json` | eight-task public game/science/evidence/code panel | 2,310 s | 2,280 s | 16 | manual descriptive baseline complete; A 6/8, B 7/8 |
| `experiments/weekly_context_capability_v1_2026-09-14.json` | four-task resident 8K/~14K capability panel | 1,230 s | 1,200 s | 8 | corrected panel complete; Gemma 4/4, Qwen 3/4 |
| `experiments/diversity_selection_dev_v0_2026-09-14.json` | Gemma diversity plus objective selection | 880 s | 850 s | 25 | complete; control 3/5, diverse-selection 0/5; no gain |

The fixed 30-second difference between each reservation and payload covers
resource preflight plus supervisor shutdown. The payload cap is identical for
both arms and every task in a registered repeat. It does not alter any
per-request deadline in the immutable manifest.

The topic manifest is immutable public development input with SHA-256
`aab09640a9d377fc0a2a1c830223f5cd8b4e7e20299ac968d7bd01f2512b06a2`.
Its registered form always enables unchanged primary R0 and therefore contains
32 hypothesis calls, 16 planner calls and 32 R0 calls: at most 80 serial local
calls inside the 2,370-second payload.

Planning performs no generation, output writes, ledger reservation, resource
lock or endpoint probe. Use the registered dispatcher to inspect the complete
card, including exact manifest/configuration hashes, fixture IDs, seeds,
dependency fingerprint, reservation, payload and expected attempts:

```bash
.venv-chroma/bin/python -m orchestrator.weekly_upgrade_trial --plan \
  --manifest experiments/topic_scope_repair_2026-09-14.json
```

For the underlying topic harness plan, include R0 explicitly so its offline
count matches the registered card:

```bash
.venv-chroma/bin/python -m bench.weekly_upgrade_eval.topic_scope --plan \
  --manifest experiments/topic_scope_repair_2026-09-14.json --include-r0
```

The dispatcher has two explicit, mutually exclusive live admission modes.
`--manual` means an operator deliberately invokes an already registered,
preregistered trial. `--review-dir` revalidates a completed two-provider review
whose status is `CONTINUE_TRIAL` and binds its exact experiment card, snapshot,
receipts and execution dependencies. It is not a free-form command interface.
Neither mode creates a schedule or authorizes production promotion.

Manual topic diagnostic, when an owner/operator elects to spend the reservation:

```bash
env -u MOCK_LLM .venv-chroma/bin/python -m orchestrator.weekly_upgrade_trial \
  --run --manual \
  --manifest experiments/topic_scope_repair_2026-09-14.json \
  --output-dir /tmp/weekly-topic-scope-2026-W38
```

Reviewed execution of a card admitted by the weekly review:

```bash
env -u MOCK_LLM .venv-chroma/bin/python -m orchestrator.weekly_upgrade_trial \
  --run --review-dir /tmp/weekly-review-2026-W38 \
  --manifest experiments/topic_scope_repair_2026-09-14.json \
  --output-dir /tmp/weekly-topic-scope-reviewed-2026-W38
```

Use a fresh output directory outside both the canonical checkout and this
worktree. The registered manifest and execution dependencies must be committed
and clean so the receipt describes the code actually run. That integrity check
is not a new approval gate for ordinary authorized Git maintenance.

The bundled 384-token Qwen arms diagnose liveness and empty-at-cap behavior.
They are deliberately too small to establish scientific superiority under
xhigh reasoning. A quality experiment must preregister appropriate output caps,
repeat counts, resource windows and thresholds before generating results.

The original objective panel covers exact mixed equilibrium, external regret,
repeated-game traces, balanced fatal/proceed critique, evidence attribution and
semantic tool use. The newer eight-task portfolio adds D-075 collective-choice,
mutually exclusive evidence contracts, and two parent-graded executed-code
tasks. The frozen context panel adds exact fact/contradiction/source-ID checks at
approximately 8K and 14K. All remain public synthetic development material.
They are not a hidden confirmation set, a repository patch benchmark, or an
end-to-end science suite. Six public historical repair contracts have separate
curation proofs; an agent runner and scored repair execution are outside this
delivery.
A separate five-task Gemma diversity-plus-objective-selection panel is frozen
and registered with 25 bounded calls and finite feasibility graders. Its live
run completed with control 3/5 and diversity plus selection 0/5. It measures
valid unique proposals and selection recovery, not scientific novelty, and the
result supports no gain.

Failures, timeouts and budget-skipped work stay in the declared denominator.
Correct-task throughput includes unsuccessful wall time. Bootstrap intervals
are descriptive across task templates; this small panel never authorizes
promotion or supports a significance claim from repeated weekly selection.
The runner records manifest, grader, harness, configuration and observed runtime
provenance hashes. Server labels are observations, not independently verified
weight-file hashes or immutable runtime image attestations.

Registered trials run serially under an exclusive cooperative GPU lease plus
the execution and coordinator-cron locks. Ordinary Gemma/Qwen wrapper calls in
this delivery code take the matching shared GPU lock. The child receives the
exact exclusive descriptor and GNU `timeout` independently supervises its
process group. Preflight requires at least 30 GiB `MemAvailable`, both resident
endpoint metrics and no competing requests. This does not lock arbitrary
processes that ignore the protocol.
The already-running daemon imported older wrapper code and will keep doing so
until an explicit canonical adoption and reload. The coordinator-cron lock still
coordinates the dispatcher with the old daemon's cycle. Do not run another
runtime alongside the resident pair.

The canonical checkout owns both the append-only budget ledger and the durable
trial journal, regardless of which linked worktree or output directory launches
the command. A run ID is single-use. Resume inspects the journal, ledger,
artifacts and live `/proc` handles. It may finish a prepared terminal receipt or
mark an uncertain orphan interrupted and fully charged; it never replays a
post-reservation run blindly. A new output directory cannot reset either state.

After a completed topic run, export only the blinded grading package to an
independent human or subscription frontier reviewer. Keep the private arm map
and raw completions in the isolated evaluation directory:

```bash
.venv-chroma/bin/python -m bench.weekly_upgrade_eval.topic_scope \
  --export-grading-package \
  --manifest experiments/topic_scope_repair_2026-09-14.json \
  --artifact-dir /tmp/weekly-topic-scope-2026-W38/evaluation \
  --grading-package /tmp/topic-scope-blind-2026-W38.json

.venv-chroma/bin/python -m bench.weekly_upgrade_eval.topic_scope \
  --summarize \
  --manifest experiments/topic_scope_repair_2026-09-14.json \
  --artifact-dir /tmp/weekly-topic-scope-2026-W38/evaluation \
  --annotations /tmp/topic-scope-annotations-2026-W38.json
```

Complete independent annotations were collected separately for topic v1 and
topic v2 and are bound in the live record. They do not repair v1's invalid
planner outputs or turn v2's one-case grounded-repair difference into a material
gain. V2's original annotation envelope had the wrong kind; the recorded local
normalization retained all 93 judgment items byte-for-byte and made no provider
retry. Each blind package contains candidate text and an annotation template,
but no arm/source/prompt mapping. Do not publish the raw private evaluation
directory or add private benchmark inputs to Git.

The three Qwen repeats have completed. Their `run.json` artifacts can be
re-aggregated without generation using:

```bash
.venv-chroma/bin/python -m bench.weekly_upgrade_eval.repeats \
  --runs \
    /tmp/weekly-qwen-effort-2026-W38-seed17/evaluation/run.json \
    /tmp/weekly-qwen-effort-2026-W38-seed29/evaluation/run.json \
    /tmp/weekly-qwen-effort-2026-W38-seed43/evaluation/run.json \
  --output /tmp/weekly-qwen-effort-2026-W38-summary.json
```

The summarizer validates the full task/arm/seed matrix and provenance, keeps
timeouts and partial runs failure-inclusive, computes exact-three-repeat RSR
2-of-3, task-clustered paired bootstrap intervals, family tables and CTT from
all arm wall time, and applies the locked pilot threshold. Its output contains
metrics/status/hashes, not raw completions or tool payloads. `INVALID` and
`INCOMPLETE` cannot support a gain.

## Weekly manual procedure

1. Inspect the previous report and failures; select at most one bounded change.
2. Fetch a small explicit list of official sources, adding release-specific URLs
   when relevant. Fetched text remains unverified until its claim is checked.
3. Build a snapshot and run the two-provider review with explicit budgets.
4. Select a card from the fixed registered catalog, inspect its offline plan,
   and use either the explicit `--manual` path or a bound `--review-dir` path in
   an idle window. The canonical ledger decides whether the reservation fits.
5. Complete objective aggregation or blind independent annotation, as required,
   before interpreting an evaluation.
6. Record NO_CHANGE, a follow-up trial, or a reviewed code change. Runtime
   promotion additionally requires exact artifact provenance, regression gates
   and rollback. Most weekly reviews should require no production change.

Example source collection (the supplied list is a starter, not exhaustive
release discovery):

```bash
.venv-chroma/bin/python -m orchestrator.weekly_upgrade \
  --fetch-sources bench/weekly_upgrade_eval/sources.json \
  > /tmp/weekly-source-fetch.json
.venv-chroma/bin/python -c \
  'import json; print(json.dumps(json.load(open("/tmp/weekly-source-fetch.json"))["source_packet"]))' \
  > /tmp/weekly-source-packet.json
```

Inspect `receipts` for failed fetches and content limits. Unknown publication
dates stay null. A fetch timestamp is not a release date. Never label a claim
verified solely because its URL was retrieved successfully.

```bash
.venv-chroma/bin/python -m orchestrator.weekly_upgrade --plan \
  --repo-root . --source-packet /tmp/weekly-source-packet.json

env -u MOCK_LLM .venv-chroma/bin/python -m orchestrator.weekly_upgrade --run \
  --repo-root . --source-packet /tmp/weekly-source-packet.json \
  --output-dir /tmp/weekly-review-2026-W38 \
  --frontier-call-budget 2 --total-deadline-s 600 \
  --call-timeout-s 300 --max-gpu-minutes 40
```

This first implementation uses Codex proposal → Claude falsification. It does
not claim two independent proposals or a four-pass debate. Actual vendor/model
metadata is retained when the CLI exposes it; absent resolved model IDs remain
unknown. CLI subscriptions are used, with API-key routes removed. The configured
model is recorded; the controller does not claim an alias is the newest model.
For the September 14 maintenance review, the current selection is
`FRONTIER_CODEX_MODEL=gpt-6-astra`, `FRONTIER_CODEX_EFFORT=xhigh`, and
`FRONTIER_CLAUDE_MODEL=claude-opus-5`, supplied only to the maintenance process.
The [official Codex model guide](https://learn.chatgpt.com/docs/models)
recommends Astra for demanding research/coding workflows, and this host's
fresh subscription model catalog lists it. The completed blind annotation's
Claude receipt reports Opus 5. Anthropic's
[current model overview](https://platform.claude.com/docs/en/models/overview)
recommends Opus 5 for most workloads and Fable 5.1 for demanding reasoning when
Opus at higher effort falls short. Opus has a successful local subscription
grading receipt here; Fable is a future analyst candidate, with subscription
availability and bounded response behavior still to verify. This selection
does not alter the separate
scientific frontier seam's defaults. Check actual access and receipts each
week; documented model availability depends on account and rollout, and a
stale hard-coded model name does not establish current suitability.
The example's 40-minute card ceiling is a per-trial proposal bound, not another
40 minutes granted outside the weekly 120-minute total. A fresh review output
directory does not reset the weekly balance.

Only the declared output directory receives review artifacts. Completed runs
can be reopened without repeating provider calls. Interrupted call reservations
are charged and not retried blindly. Mock mode and provider failures cannot
be recorded as completed frontier analysis. `NO_CHANGE`, `REVISION_REQUIRED`,
or `CONTINUE_TRIAL` is an advisory result, not a deployment instruction or
statistical promotion decision.

Canonical adoption, a real registered diagnostic and independent topic
annotation are recorded in the
[live evaluation record](research/weekly-upgrade-2026-09-14/LIVE_EVALUATION_RECORD.md).
The full Qwen pilot attempted all 36 cells. Its frozen result is 13/18 for
xhigh versus 12/18 for medium; one timeout leaves the locked decision
`INCOMPLETE` and no gain supported. A separate grader audit preserves the
identified false negatives without changing the recorded scores. The first
manual scheduled-style review completed both providers and ended
`REVISION_REQUIRED`, so its card did not dispatch. Corrected-input qualification
also ended without admission because Claude's fenced response was strict-parser
`INVALID_REPORT`; topic v2 ended `NO-MATERIAL-SIGNAL`. The remaining live panels
then completed as descriptive measurements: portfolio A 6/8 versus B 7/8,
context Gemma 4/4 versus Qwen 3/4, and diversity control 3/5 versus candidate
0/5. Service reload and scheduler activation remain separately tracked. Neither
protocol completion nor these small negative/mixed results establish a
scientific, coding or performance gain.

## Validation and delivery

See [implementation validation](research/weekly-upgrade-2026-09-14/IMPLEMENTATION_VALIDATION.md)
for committed test evidence and the
[live evaluation record](research/weekly-upgrade-2026-09-14/LIVE_EVALUATION_RECORD.md)
for terminal measurements. The initial bounded evaluation set is complete.
The final integrated suite passed 2,955 tests with one skipped, two xpassed, 23
warnings, and no failures; 68 subtests also passed in 66.76 seconds. Scoped Ruff
checks for the new implementation also passed, followed by 91 focused
context/trial/review tests after the style-only correction. PR 19 delivery,
private canonical adoption, and the owner's explicit activation decision are
the remaining closure steps; none authorizes a model, runtime, context, or
production-policy promotion.
