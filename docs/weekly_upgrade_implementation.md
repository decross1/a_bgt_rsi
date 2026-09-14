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
existing agenda also permits up to two, so running both workflows can use up to
four subscription attempts. Both must be visible in the weekly usage report;
this decision does not set a numeric subscription-session cap or activate cron.

Proposed accounting for the **shared 120 Spark GPU-minute weekly ceiling**:

- One ISO week, Monday 00:00 UTC through the next Monday, with no carryover.
  Charge the one physical Spark's reserved elapsed time once, including both
  resident models; do not grant separate allowances to each model, arm or run.
- Count all upgrade-triggered GPU work: preflight generations, warmups, trials,
  failed/time-out requests, retries, challenger loading and recovery. Frontier
  subscription analysis and CPU-only planning use zero Spark GPU minutes.
- Treat this as a separate upgrade allowance from D-063's daily coordinator
  activity-unit ledger. Both still require physical-resource coordination;
  a separate accounting allowance does not create an idle resource window.
- Reserve against the remaining weekly balance before dispatch. Record reserved,
  consumed and released time; charge uncertain interrupted work conservatively
  before any retry. For the initial design, defer any run whose maximum reserved
  duration could cross the UTC week boundary; do not borrow from next week. Multiple
  output directories and resumed sessions must share the same accounting.
- A normal design allocation is 15 minutes of canaries, 90 minutes for one
  admitted trial and 15 minutes for GPU-using preflight/recovery. This is an
  allocation, not a measured runtime promise. A larger preregistered panel
  replaces that allocation; it never adds another allowance.

The controller's `--max-gpu-minutes` validates one proposed experiment card.
It does **not** reserve time, execute a trial, enforce a cumulative weekly
ceiling or coordinate a GPU lease. The evaluator's per-run deadline also
excludes external preflight. Shared accounting/dispatch remains implementation
work; until then, any authorized supervised run needs a recorded manual
reservation and remaining balance. Monthly/deeper/runtime campaigns share
this ceiling unless an additional budget is explicitly authorized.

The [Qwen pilot](../experiments/PREREG_weekly_qwen_effort_pilot_2026-09-14.md)
reserves 112.5 minutes and leaves only 7.5 minutes for all other charged work.
It replaces that week's panel and must be deferred if the full reservation plus
required overhead cannot fit. The next scientific diagnostic instead targets
the upstream game-theory topic mismatch before optimizing Qwen effort.

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

The [topic-scope diagnostic](../experiments/PREREG_topic_scope_repair_2026-09-14.md)
defines the paired measurement still needed for that prompt change. Code
compatibility checks do not establish better generated topics or R0 accuracy.

The [completion tracker](research/weekly-upgrade-2026-09-14/UNBLOCKING_PLAN.md)
separates delivered code from remaining experiments and activation. Its first
priority is the stale topic queue feeding the observed R0 blockade upstream of Qwen;
the paired effort pilot remains a separate, preregistered development test.

The implementation does not activate a schedule, execute an analyst's proposed
commands, change the scientific frontier policy, restart serving, swap a role,
raise context limits, or promote a candidate. The existing agenda cron remains
unchanged. The weekly controller produces a review artifact; the evaluator is a
separate explicit command. Scheduling and runtime qualification are follow-on
work with the deployed contracts applied at that point.

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
   production context limits remain 32K Gemma and 16K Qwen. No new throughput or
   science-quality claim follows from this implementation's smoke checks.

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
Planning performs no generation and creates no output files:

```bash
.venv-chroma/bin/python -m bench.weekly_upgrade_eval.runner --plan \
  --manifest bench/weekly_upgrade_eval/fixtures.json
```

For an actual run, first freeze the two arms, caps and task set in a separate
manifest and reserve its complete cost within the shared weekly allowance
above. Give each run a fresh output directory outside live ledgers:

```bash
env -u MOCK_LLM .venv-chroma/bin/python -m bench.weekly_upgrade_eval.runner \
  --run --manifest /tmp/my-preregistered-panel.json \
  --output-dir /tmp/my-weekly-evaluation --runtime-budget-s 1800
```

The bundled 384-token Qwen arms diagnose liveness and empty-at-cap behavior.
They are deliberately too small to establish scientific superiority under
xhigh reasoning. A quality experiment must preregister appropriate output caps,
repeat counts, resource windows and thresholds before generating results.

The panel covers exact mixed equilibrium, external regret, repeated-game traces,
balanced fatal/proceed critique, evidence attribution and semantic tool use.
It is public development material in this repository. It is not a hidden
confirmation set, a repository patch benchmark, or an end-to-end science suite.
Independent coding tasks, held-out scientific tasks, long context and runtime
qualification remain separate panels to add when those hypotheses are tested.

Failures, timeouts and budget-skipped work stay in the declared denominator.
Correct-task throughput includes unsuccessful wall time. Bootstrap intervals
are descriptive across task templates; this small panel never authorizes
promotion or supports a significance claim from repeated weekly selection.
The runner records manifest, grader, harness, configuration and observed runtime
provenance hashes. Server labels are observations, not independently verified
weight-file hashes or immutable runtime image attestations.

Run local evaluations serially during an idle resource window. A request cap
is not a GPU lease: do not run a competing runtime alongside the resident pair.

## Weekly manual procedure

1. Inspect the previous report and failures; select at most one bounded change.
2. Fetch a small explicit list of official sources, adding release-specific URLs
   when relevant. Fetched text remains unverified until its claim is checked.
3. Build a snapshot and run the two-provider review with explicit budgets.
4. Freeze a concrete evaluation manifest for an admitted experiment, run it in
   an idle window, and compare the full success/reliability/time vector.
5. Record NO_CHANGE, a follow-up trial, or a reviewed code change. Runtime
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
  --call-timeout-s 300 --max-gpu-minutes 30
```

This first implementation uses Codex proposal → Claude falsification. It does
not claim two independent proposals or a four-pass debate. Actual vendor/model
metadata is retained when the CLI exposes it; absent resolved model IDs remain
unknown. CLI subscriptions are used, with API-key routes removed. The configured
model is recorded; the controller does not claim an alias is the newest model.
The example's 30-minute card ceiling is a per-trial proposal bound, not another
30 minutes granted outside the weekly 120-minute total. A fresh review output
directory does not reset the weekly balance.

Only the declared output directory receives review artifacts. Completed runs
can be reopened without repeating provider calls. Interrupted call reservations
are charged and not retried blindly. Mock mode and provider failures cannot
be recorded as completed frontier analysis. NO_CHANGE, REVISION_REQUIRED, or CONTINUE_TRIAL is an
advisory result, not a deployment instruction or statistical promotion decision.

## Validation and delivery

See [implementation validation](research/weekly-upgrade-2026-09-14/IMPLEMENTATION_VALIDATION.md)
for test counts, live smoke evidence, review findings and outstanding limits.
