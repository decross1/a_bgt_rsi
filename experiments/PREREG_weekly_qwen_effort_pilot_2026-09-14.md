# Qwen effort pilot: equal-budget completed tasks

**Status:** preregistered, not executed. No production policy change authorized
by this pilot. Lock this document and its JSON manifests in Git before calls.

## Question and estimand

Does the existing Qwen model finish more objectively correct development tasks
within an interactive request budget when effort is medium instead of xhigh?
This estimates a bounded task-completion tradeoff, not unrestricted reasoning
quality, production skeptic effectiveness, or a model/runtime effect.

## Fixed arms and controls

| Setting | A | B |
| --- | --- | --- |
| Backend / model | `vllm-qwen` / `qwen3.8-27b-nvfp4-mtp` | same |
| Profile / effort | `critic_current` / xhigh | `critic_medium` / medium |
| Temperature / top-p | 0.2 / 0.95 | same |
| Output cap | 6,144 tokens | same |
| Whole request/tool-loop deadline | 180 seconds | same |
| Seeds | 17, 29, 43 | matched per task |

Keep checkpoint, MTP, KV type, parser, context limit and serving configuration
fixed. Do not disable speculation in this policy comparison. Record the
observed model and runtime provenance. Different speculative acceptance under
the two policies is a possible mechanism for a system-level policy effect;
it does not establish that the runtime itself changed.

The deadline can bind before the token cap, especially at xhigh. Timeouts stay
in the denominator. Any result is conditional on this budget. A later
unrestricted-quality question needs a separate preregistration with suitable
budgets; do not extend only the losing arm after seeing results.

## Tasks, repetitions and order

Six public, previously inspected development templates from
`bench/weekly_upgrade_eval/fixtures.json`: two fatal and two proceed critic
cases, one attrition/evidence case, and one semantic experiment-lookup case.
These are not the project's historical six skeptic sentinels. They do not
exercise repository patching, full literature retrieval, or long-horizon
scientific discovery.

Run both arms on all six tasks for each seed: **36 task attempts**, potentially
more HTTP requests when a tool loop needs additional turns. Each manifest uses
AB/BA task pairing. Task order reverses in repeat 2 and rotates in repeat 3 to
reduce persistent arm-order bias. Cache state and speculative nondeterminism
remain possible confounders; matching a seed does not guarantee identical
randomness across policies.

The six templates are the independent task units. Three repetitions do not
turn them into eighteen independent scientific problems. Report outcomes by
task and seed. The repeat-aware summarizer now validates the complete
task/arm/seed matrix and matching task inputs, graders, harness and fixed
configuration, then computes RSR 2-of-3, a task-clustered paired bootstrap and
the locked decision rule. It does not pool the 18 task-by-seed observations as
independent tasks or copy raw completions/tool payloads into its summary.

| Manifest | SHA-256 |
| --- | --- |
| `weekly_qwen_effort_pilot_2026-09-14/seed_17.json` | `88aacc3868dc116f30ba6c9769834886a1ec26071967f7cf8ae5d7413a5b71aa` |
| `weekly_qwen_effort_pilot_2026-09-14/seed_29.json` | `1a2a24131cf9a5047cb30ea6b1aee748964df4dab6d48c1c702af3dc6c62e02f` |
| `weekly_qwen_effort_pilot_2026-09-14/seed_43.json` | `b0e8c83c0662141880ad8c7af514b61827f1391f270a849efcbcb5483bbbb287` |

## Resource and abort rules

Reserve at most 2,250 wall seconds per repeat, 6,750 seconds (112.5 minutes)
for the three repeats. The registered dispatcher fixes the evaluator payload at
2,220 seconds per repeat inside the unchanged 2,250-second upper envelope. The
30-second difference covers resource preflight and independently supervised
shutdown; it is the same for every repeat and changes no arm, task deadline,
output cap or manifest hash. There are twelve per-repeat task deadlines of at
most 180 seconds. Do not run the three repeats concurrently. These are bounds,
not a forecast of actual use.

**Budget annotation, 2026-09-14 (no changes to arms or manifest hashes):** the
owner chose subscription-only frontier sessions and a design ceiling of
120 Spark GPU-minutes per week. This pilot replaces that week's regular panel;
112.5 minutes leaves at most **7.5 minutes** for GPU-using preflight, warmups,
recovery and any other upgrade work. All three repeats draw from one weekly
balance. Do not start unless the full remaining pilot reservation plus required
overhead fits the available balance. Defer the pilot if it does not fit; do not
shorten an arm, drop a seed or pool partial weeks after seeing outcomes.
No metered frontier call is part of this pilot. The budget answer does not
start the experiment or a schedule.

The dispatcher now enforces one canonical 7,200-second UTC ISO-week ledger
across worktrees and output directories. An active 2,400-second topic-scope
reservation leaves only 4,800 seconds and therefore cannot coexist with this
6,750-second pilot. After a trusted topic terminal receipt releases unused
time, the pilot may start in the same week only if the ledger shows at least
6,750 seconds remaining; all prior charges combined must be no more than 450
seconds. An interrupted topic run remains fully charged, so defer this pilot to
another week. Scope correction still takes priority: first test the upstream
generated-topic mismatch without weakening R0.

Before calls verify both endpoints' queues, active workload and memory margin.
Require at least 30 GiB MemAvailable at dispatcher preflight. Do not stop
production or load a third server. Defer a run when production needs the same
resource. The delivery dispatcher holds exclusive execution,
coordinator-cron and GPU locks, and its child inherits the exact GPU-lock
descriptor. Ordinary Gemma/Qwen calls in the delivery wrapper use the matching
shared lock. This is cooperative: the running daemon imported older code and
will not use the new wrapper lock until explicit canonical adoption and reload,
although the coordinator-cron lock coordinates its old cycle. There is no claim
of continuous memory monitoring.

Abort on model/runtime drift, evidence of production contention, memory margin
violation, isolation failure or broken transport. A schema/grader failure is
a scored outcome; repeated transport errors are an operational abort. Preserve
partial artifacts. Any missing declared attempts count as missing/failure in
the failure-inclusive view; they are never silently removed. An aborted run
cannot support a gain claim.

## Metrics and decision rules

Report exact correct/attempted counts by task, family and seed; empty-at-cap,
parse/tool failures, request timeouts, observed output/reasoning tokens when
available, and wall time including unsuccessful attempts. Correct-task
throughput uses all arm wall time. A parseable-only comparison is secondary.

For repeatability, report how many of the six tasks each arm solves in at least
two of three attempts (`RSR_2of3`). Report paired task deltas; bootstrap the six
task clusters if an aggregate interval is computed. Intervals are descriptive.
Do not claim significance or general superiority from this selected tiny set.

Decision after all planned attempts:

- **INVALID / INCOMPLETE:** drift, isolation failure, or aborted/missing work;
  diagnose the protocol, retain all receipts and make no superiority claim.
- **RETAIN-INCUMBENT for this pilot:** B has fewer successful attempts, lower
  RSR, or more semantic tool failures than A. Record any speed tradeoff without
  hiding the regression.
- **EVALUATE-LARGER:** B is no worse on those three counts, has at least one
  success, and either succeeds on at least two more attempts or improves
  correct-task throughput by at least 15% when A's throughput is positive.
  If A has zero throughput, use the absolute success-count rule. Confirm on
  new independent tasks before considering a role-policy change.
- **NO-MATERIAL-SIGNAL:** all other completed outcomes, including zero success
  for both arms. Reconsider tasks, reasoning budget or the upstream funnel.

These are screening thresholds, not statistically powered promotion bars.
No pilot outcome authorizes a production change.

## Execution

Inspect each registered card without calls, output writes, ledger reservation,
locks or endpoint probes:

```bash
.venv-chroma/bin/python -m orchestrator.weekly_upgrade_trial --plan \
  --manifest experiments/weekly_qwen_effort_pilot_2026-09-14/seed_17.json
```

The plan records the exact manifest/configuration hashes, fixtures, seed,
expected attempts, execution fingerprint, 2,250-second reservation and fixed
2,220-second payload. Repeat for seed 29 and seed 43. Resolve the backend/profile
configuration without contacting a model if separately auditing the manifest:

```bash
.venv-chroma/bin/python -c 'from bench.weekly_upgrade_eval.manifest import load_manifest; from bench.weekly_upgrade_eval.runner import validate_live_configuration; validate_live_configuration(load_manifest("experiments/weekly_qwen_effort_pilot_2026-09-14/seed_17.json"))'
```

Repeat the checks for all three manifests. Neither offline command proves live
endpoint identity, idle resources or memory margin.

Live dispatcher admission has two mutually exclusive modes. `--manual` is an
explicit operator invocation of this already preregistered trial. Use a fresh
output directory outside both the canonical checkout and worktree:

```bash
env -u MOCK_LLM .venv-chroma/bin/python -m orchestrator.weekly_upgrade_trial \
  --run --manual \
  --manifest experiments/weekly_qwen_effort_pilot_2026-09-14/seed_17.json \
  --output-dir /tmp/weekly-qwen-effort-2026-W38-seed17
```

`--review-dir` is the separate path for an exact card admitted by a newly
completed two-provider review; do not combine it with `--manual`:

```bash
env -u MOCK_LLM .venv-chroma/bin/python -m orchestrator.weekly_upgrade_trial \
  --run --review-dir /tmp/weekly-review-2026-W38 \
  --manifest experiments/weekly_qwen_effort_pilot_2026-09-14/seed_17.json \
  --output-dir /tmp/weekly-qwen-effort-reviewed-2026-W38-seed17
```

The registered manifest and execution dependencies must be committed and clean
before calls so artifacts bind to the executable code. This is an evaluation
integrity check, not a new gate for authorized Git work. The dispatcher removes
`MOCK_LLM` and profile overrides from the child, performs live queue/memory
preflight inside the reservation, and supervises the fixed evaluator command.

Repeat explicitly for seeds 29 and 43 with their corresponding manifests and
fresh directories only if the canonical ledger can reserve each full envelope.
A run ID is single-use. After a reservation, rerunning cannot blindly replay;
recovery inspects the durable canonical journal, ledger, exact artifacts and
live process handles, then finishes a prepared receipt or records uncertain
work as interrupted and fully charged.

After all three repeats have terminal artifacts, create a fresh raw-free
aggregate:

```bash
.venv-chroma/bin/python -m bench.weekly_upgrade_eval.repeats \
  --runs \
    /tmp/weekly-qwen-effort-2026-W38-seed17/evaluation/run.json \
    /tmp/weekly-qwen-effort-2026-W38-seed29/evaluation/run.json \
    /tmp/weekly-qwen-effort-2026-W38-seed43/evaluation/run.json \
  --output /tmp/weekly-qwen-effort-2026-W38-summary.json
```

Archive the summary and provenance without publishing raw completions, tool
payloads or private benchmark inputs. This delivery has not run the pilot,
integrated a new review, adopted the code in the canonical checkout, reloaded
the daemon or activated a scheduler. It establishes no scientific or policy
gain.
