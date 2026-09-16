# Stable Benchmark v1

The stable benchmark is one versioned program with a generic projection, not a new UI panel for every experiment. The current release is `1.1.0`, published and preregistered on September 16. Release `1.0.0` remains a commissioning archive with its original outcomes; no historical score is converted into the corrected series. It is a small regression canary, not evidence of broad scientific intelligence or a sufficient model-selection instrument. The frozen definition contains 18 model-capability units and three actor–tool–critic harness micro-workflows. The latter measure a narrow two-role scaffold; they do not establish whole-orchestrator, scheduler, research-funnel, or production success.

## Measurement layers

| Layer | Release v1 evidence | Scored with model capability? |
|---|---|---|
| MODEL | Science/evidence 4, functional repair 4, deterministic tool use 4, strategic behavior 6 | Reported by construct; no omnibus score |
| SYSTEM harness | Three actor–tool–critic micro-workflows with schema-validated CPU tools and objective artifact checks | Separate panel |
| RUNTIME | Endpoint identity, policy, call ceilings, resource guard, monitor completion, and restoration | Gate only |
| Applied study | Market capture, prediction-market pilots, or later empirical work | Separate research record |

The strategic rows include two public-goods instances, two Vickrey instances, one discrete Cournot instance, and one ex ante Brier proper-scoring report. The trusted grader derives own utility, joint or social utility, and best-response regret from the selected action. The prompt explicitly asks the agent to maximize its own payoff. Joint Brier utility is descriptive only, and no metric is averaged across mechanisms.

Public summaries may show binary objective-completion counts for science/evidence (4), functional repair (4), deterministic tool use (4), and harness micro-workflows (3). Strategic behavior is shown only as public goods (2), Vickrey auction (2), Cournot (1), and proper-scoring reporting (1). These are descriptive canary denominators. The API does not publish one cross-domain credited total, and strategic utility or regret is aggregated only within a mechanism.

## Fixed resource envelope

The 21 units have a derived ceiling of 29 model calls per arm, 58 calls for a matched two-arm comparison, 25,088 output tokens per arm, and 1,575 seconds of summed episode ceilings per arm. A supervised lifecycle may reserve at most 7,200 seconds including setup, readiness, evaluation, monitoring, and restoration. The expected path can use fewer than 29 calls because a correct no-call task ends after one response; the ceiling also covers the bounded follow-up when a model incorrectly calls its distractor tool. Each system-role call has a 1,536-token ceiling so the resident `critic_current` xhigh route is not evaluated under the unrelated 768-token truncation confound.

Every transport failure charges a known attempt count when the adapter supplies one. If the lower-level transport cannot prove the exact number, the receipt charges that task's full call ceiling and labels the summary `conservative_upper_bound_where_transport_failed`. No failed or partial request disappears from resource accounting.

For each 120-second SYSTEM mission, the actor call is capped at 60 seconds.
The critic receives the remaining episode budget after a fixed five-second
allowance for trusted local grading; it does not have a second undocumented
60-second cap. The outer episode deadline and supervised-window deadline still
terminate the path if either role or grading runs late.

## Definition, arm, and harness binding

`make_draft()` constructs a side-effect-free definition. A runner rejects it until `publish_definition()` receives an external Git-commit or preregistration-receipt witness. The intended review boundary is `2026-10-14T00:00:00Z`; reaching it sets `review_required` and never extends the release implicitly.

An execution arm is a model stack:

```json
{
  "id": "resident-stack",
  "label": "Gemma actor with Qwen critic",
  "seed": 17,
  "routes": {
    "gemma": {"backend": "...", "model": "...", "profile": "...", "expected_policy": {}, "runtime_identity": {}},
    "qwen": {"backend": "...", "model": "...", "profile": "...", "expected_policy": {}, "runtime_identity": {}}
  },
  "role_map": {
    "capability": "gemma",
    "system_actor": "gemma",
    "system_critic": "qwen"
  }
}
```

The resident manifest uses the actual wrapper profiles: `precise` for Gemma capability/actor work and `critic_current` for the Qwen critic, unless a later manifest explicitly declares another release-specific stack. There is no `generator_current` profile. The candidate may map all three roles to one separately admitted Flash transport and policy. A comparison between these arms is a stack comparison. It cannot isolate weight quality from routing, policy, or scaffold effects. Each route freezes backend, served model, named profile, temperature, top-p, reasoning effort, sampling extras, artifact digest, runtime digest, and context ceiling.

`bind_run_manifest()` also freezes `harness_identity`: scaffold ID, injected-supervised-endpoint transport contract, and the hashes of every package source plus the imported bubblewrap sandbox. A Flash controller must use an injected, source-bound transport after lifecycle admission. It must not label the Flash endpoint as the existing resident Qwen wrapper backend.

## Execution boundary

The runner signature is:

```python
run_arm(
    definition,
    run_manifest,
    *,
    output_dir,
    execution_gate,
    absolute_deadline_monotonic,
    cancel_event,
    invoke=invoke_via_wrapper,
    monotonic=time.monotonic,
)
```

The runner never starts, stops, swaps, or discovers a model. A supervisor passes a gate after readiness and resource-monitor arming. That gate binds the exact definition and run-manifest bytes, route runtime identities, endpoint-binding receipt, supervision-ready receipt, and resource-guard receipt. The supervisor's injected transport checks its monitor before and after every request.

The output directory must be new and outside live `logs`, `memory`, and `run_state` roots. Public `run.json` contains bounded outcomes without raw completions. Mode-0700 `private/` contains raw attempts, wrapper call records, and worker activity. The runner performs no retry, records every planned unit, marks remaining work `skipped_budget` after cancellation or deadline, and emits a terminal `complete`, `aborted`, or `unissued` state.

## Outcome and admission states

Cell states are `passed`, `failed`, `abstained`, `timeout`, `transport_error`, `invalid_output`, `invalid`, `skipped_budget`, and `unissued`. A correct evidence-insufficiency response remains visibly `abstained` and can receive score credit. Model malformed output is `invalid_output` and counts against the planned denominator. Harness, grader, source, or policy drift is `invalid` and withholds admission.

Run execution never self-admits. `replay_run()` rereads private raw evidence, checks source and content hashes, reruns objective graders and code sandboxes, and writes `replay.json`. `admit_replay()` then requires that verified replay plus a separate supervisor-final receipt proving monitor completion, no guard breach, and exact restoration. Only `admission.json` may set `admitted=true`, and it never authorizes promotion.

## Comparisons and uncertainty

`compare_admitted()` accepts only two replay/admission chains bound to the same comparison cohort and release. It reports matched task deltas, discordant counts, and fixed-seed clustered bootstrap intervals per construct. Repeated public-goods and Vickrey parameterizations share a mechanism cluster. A construct with fewer than four uncertainty clusters gets no interval; larger fixed-panel intervals remain descriptive. An inconclusive interval cannot automatically promote a stack.

Strategic own-regret stays in its mechanism-specific row. Science, code, tool, and harness constructs also remain separate. The comparison receipt has `omnibus_score=null` and `promotion_authorized=false`.

## Registry and future releases

The source-controlled [program catalog](program_catalog.json) contains at most eight release entries and one active pointer. Each entry binds a version, suite ID, fixed artifact root, published-definition SHA-256, label, and `measurement_review_sha256` (a required digest or explicit `null`). Missing or invalid catalog data withholds current-release claims. A required measurement notice that disappears or changes cannot restore comparative quality claims.

The generic API uses `?release=1.0.0` for the commissioning archive and defaults to active release `1.1.0`. Different releases have separate run histories. Global model-state reporting checks unresolved windows across all registered releases, so changing the active measurement pointer cannot hide an unfinished older runtime window.

Release 1.1 was preregistered in [commit c840466](https://github.com/decross1/a_bgt_rsi/commit/c840466), after frozen causal source [979f961](https://github.com/decross1/a_bgt_rsi/commit/979f961), with definition SHA-256 `d2eb69d9c0fefc7b377cec6cb550f491979a5f137d38346dc99a607be5890006`. The two evidence contracts and shared code sandbox disclosure were corrected prospectively. The same 21 task lineages, strict response contract, policies, caps, and October 14 review boundary are retained. This is a fresh comparison series, not a new holdout.

Weekly comparisons append under the selected release root at `runs/<comparison_id>/<arm_id>/`; they do not create endpoints or frontend components. At review, an explicit release entry either extends unchanged bytes with a new witness or activates a new semantic version. Task, grader, independent-unit, or metric changes start a new comparison series. A score-preserving metadata correction may use a patch version only when byte-level replay proves unchanged outcomes.

Before inference, each comparison also receives a checked-in
`docs/benchmarks/registrations/<comparison_id>.json`. It orders the reference
then candidate arm and freezes the definition and manifest bytes, each arm's
execution/replay/admission source maps, fixed run receipt directory, and the
lifecycle window-plan, worker-argv, controller-source, and receipt-directory
bindings. An unissued candidate has `lifecycle: null`. The read-only verifier
uses the recorded historical maps rather than recomputing hashes from the
current checkout. For an executed arm it also verifies the plan, process,
terminal state, both copies of the three gate receipts, supervisor result,
replay, and admission chain. It never reads private responses or grades during
an HTTP request.

External ScienceAgentBench, BFCL, Terminal-Bench, or TextArena subsets are not part of the synthetic v1 score. A future rotation must first record its upstream version, license, selected IDs, oracle replay, architecture/resource pilot, and separation from the optimizer. An adapted subset must be labeled as the project rotation and must not be reported as the upstream benchmark's public score.

## Cadence and extended tier

Run the fixed canary at most weekly for the resident stack and once for a materially changed candidate stack. Every run receives runtime admission and restoration checks. Run the extended tier monthly, at release review, or after a preregistered trigger: a stable-core regression, a scaffold/runtime change, a promotion candidate, or two consecutive descriptive canary improvements. Register the trigger, task IDs, versions, denominators, and stopping rule before inference; a result cannot expand its own panel.

The first extended tier should use fresh real-repository repair snapshots and a licensed, oracle-validated scientific-replication subset. Later rotations may add a pinned non-live BFCL subset, an ARM-qualified Terminal-Bench edition, or fixed game environments with scripted opponents. ScienceAgentBench, CORE-Bench, PaperBench, Terminal-Bench, BFCL, TextArena, GTBench, KantBench/OpenEnv, and tau-bench remain separate benchmark lineages. No adapted rotation inherits an upstream leaderboard name or score.

## Initial resident-only window

The September 16 initial window records a fresh resident baseline only. The Flash candidate failed the unchanged host pageout startup gate before any stable-suite model request, after the final permitted startup attempt. Its arm is written as `unissued` with all 21 units and zero model calls; it receives no score, replay admission, comparison delta, loss, or imputed value. A later Flash run requires a separately reviewed runtime qualification and remains bound to this release only while the definition is active.

Historical 126-cell, supplement, context, diversity, payoff-tool, calibration, and applied-market records remain in their original lineages. They inform diagnostics and future task design, but they neither establish the v1 baseline nor get rescored under this definition. The existing 384-versus-1,536 Flash cap closure is a reused-fixture `diagnostic_development` study and stays outside the stable canary.

The resident receipt chain is admitted with 21/21 units accounted, 27 model
calls, and 139.951927 seconds of evaluator wall time. Here, `admitted` means the
source-controlled registration, run, replay, supervision, resource, and
restoration receipts verified. It does not by itself establish that every task
contract was valid or authorize a promotion. A post-run measurement audit found
four v1.0 task-design defects in the two evidence oracles and two code tasks with
undisclosed sandbox constraints. The other channel-format and output-cap
failures remain observed end-to-end failures under the declared contract. Keep
the original receipts and grader outputs immutable; use the
[source-controlled measurement review](measurement_reviews/75de9dc0dc324a4559332f88ae6e5ae861ba0d6f683334d85395d082bbaf04df.json)
for interpretation. Correcting a task or oracle
starts a new release and never silently rescales v1.0.

## Sunday report and next-run recipe

The existing Sunday 05:30 UTC review owner adds a bounded `stable_benchmark`
section to `cycle_report.json`. New provider-review receipts also copy the same
section into `review/weekly_report.json`. This distinction matters for the first
follow-up: September 20 is still ISO week `2026-W38`, whose provider review was
already completed on September 14. The immutable provider report is not
rewritten. The Sunday cycle report refreshes the stable benchmark observation
without repeating either provider call.

The section contains the release/version/definition hash, publication and review
times, the latest comparison cohort, receipt-admission states, construct or
mechanism result rows, the bounded measurement-review notice, and a manual
preregistration recipe. It omits model
policies, private responses, grader inputs, and lifecycle payloads. It reads the
generic verified projection with active-runtime inspection disabled. Reading or
writing this report makes zero model or paid-API calls and never schedules an
evaluation.

For v1.0, `next_run_preregistration.eligibility` is
`corrected_release_required`: its commissioning review forbids a comparative
quality claim, so rerunning unchanged v1.0 would not repair the four task
contracts. A later active release that passes its measurement review may be
prepared as a new comparison cohort only through this recipe:

1. Resolve the versioned measurement review. If the intended measurement needs
   a prompt, oracle, grader, task, metric, or independent-unit change, publish a
   new semantic release. Do not edit release 1.0.0 or its receipts.
2. Choose fresh comparison, run, and lifecycle window IDs. Build role-specific
   manifests with `bind_run_manifest()` from the published definition and the
   exact frozen source checkout. Preserve the reference/candidate order. An arm
   that will not run remains explicitly `unissued`; it is not a loss.
3. Generate the prospective lifecycle plan without inference:

   ```bash
   python -m bench.stable_benchmark.supervised_window \
     --plan \
     --window-id '<new-window-id>' \
     --run-manifest '<new-run-manifest.json>'
   ```

4. Before any model request, commit
   `docs/benchmarks/registrations/<comparison_id>.json`. Bind the exact
   definition and manifest bytes, historical execution/replay/admission source
   maps, fixed receipt directories, lifecycle plan hash, worker argv hash, and
   controller source map. Validate it with `load_registration()` from the
   frozen checkout.
5. Review runtime qualification, the 120-Spark-minute weekly budget, the
   unchanged 30 GiB admission threshold, and restoration ownership. A candidate
   needs its own qualified transport. The Sunday job does not perform this
   review or launch the supervisor.
6. If manually authorized after preregistration, run the supervisor once. Retain
   terminal run, replay, supervision, admission, and unissued receipts in the
   registered cohort. Inspect `/api/benchmark_program`; the next Sunday report
   will read that same verified history.

At or after the review boundary, the recipe changes to
`explicit_release_review_required`. Record an unchanged-definition extension
with a new witness or publish a new release before inference. The small canary
remains separate from monthly or triggered public rotations; those rotations
still require their own version, license, oracle, ARM/resource pilot, and result
lineage.

## Public API projection

`program_projection()` exposes definition hash, release/freeze state, panel and task IDs, constructs, resource ceilings, and bounded run status. It omits prompts, grader inputs, functional cases, raw responses, and arbitrary receipt payloads. Scores and task outcomes appear only when a supplied admission receipt cryptographically binds the same verified replay and definition. HTTP handlers read this projection; they never trigger replay, grading, inference, publication, or lifecycle work.
