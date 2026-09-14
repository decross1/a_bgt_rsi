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
task and seed; keep the three runner summaries separate until a reviewed
task-clustered aggregation is available.
Until then, calculating RSR and the decision requires a reviewed manual
task-by-seed table. Do not pool the three summaries as independent tasks.

| Manifest | SHA-256 |
| --- | --- |
| `weekly_qwen_effort_pilot_2026-09-14/seed_17.json` | `88aacc3868dc116f30ba6c9769834886a1ec26071967f7cf8ae5d7413a5b71aa` |
| `weekly_qwen_effort_pilot_2026-09-14/seed_29.json` | `1a2a24131cf9a5047cb30ea6b1aee748964df4dab6d48c1c702af3dc6c62e02f` |
| `weekly_qwen_effort_pilot_2026-09-14/seed_43.json` | `b0e8c83c0662141880ad8c7af514b61827f1391f270a849efcbcb5483bbbb287` |

## Resource and abort rules

Reserve at most 2,250 wall seconds per repeat, 6,750 seconds (112.5 minutes)
for the three repeats. There are twelve per-repeat task deadlines of at most
180 seconds; the remaining allowance covers harness overhead. Do not run the
three repeats concurrently. These are bounds, not a forecast of actual use.

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

The runner's `--runtime-budget-s` is a per-run limit; it does not enforce the
shared weekly allowance and excludes external preflight. Record a manual
reservation/usage receipt for any supervised execution until shared accounting
exists. Scope correction now takes priority: the owner confirmed game theory,
so first test the upstream generated-topic mismatch without weakening R0.

Before calls verify both endpoints' queues, active workload and memory margin.
Target at least 20 GiB MemAvailable throughout. Do not stop production or load
a third server. Defer a run when production needs the same resource. The
current harness does not enforce a shared GPU lease or continuous memory
monitoring, so this pilot is operator-supervised until those mechanisms exist.

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

Validate the manifest without calls (this does not probe endpoints or resolve
the backend/profile combination):

```bash
.venv-chroma/bin/python -m bench.weekly_upgrade_eval.runner --plan \
  --manifest experiments/weekly_qwen_effort_pilot_2026-09-14/seed_17.json
```

Resolve the backend/profile configuration without contacting a model:

```bash
.venv-chroma/bin/python -c 'from bench.weekly_upgrade_eval.manifest import load_manifest; from bench.weekly_upgrade_eval.runner import validate_live_configuration; validate_live_configuration(load_manifest("experiments/weekly_qwen_effort_pilot_2026-09-14/seed_17.json"))'
```

Repeat both checks for all three manifests. Endpoint queues, active workload,
memory margin and output-directory isolation still require the separate
pre-call checks above; neither no-call command verifies them.

After the resource/isolation checks, use a fresh output directory for each
repeat. Unset profile overrides so the frozen arms remain the actual arms:

```bash
env -u MOCK_LLM -u WRAPPER_PROFILE_OVERRIDES \
  .venv-chroma/bin/python -m bench.weekly_upgrade_eval.runner --run \
  --manifest experiments/weekly_qwen_effort_pilot_2026-09-14/seed_17.json \
  --output-dir /tmp/weekly-qwen-effort-20260914-seed17 \
  --runtime-budget-s 2250
```

Repeat explicitly for seeds 29 and 43 with their corresponding manifests and
fresh directories. Archive results, provenance and decision together. A
scheduled dispatcher and repetition-aware summarizer are follow-on code;
these commands do not claim that either is already implemented.
