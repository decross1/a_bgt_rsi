# Stable Benchmark Architecture and Consolidation Research

## Decision

The benchmark program is one versioned measurement system with four separately reported layers: MODEL capability, SYSTEM harness behavior, RUNTIME qualification, and applied empirical research. The weekly fixed core is the new 18-task capability canary plus three actor–tool–critic micro-workflows. Runtime checks gate admission and never add quality credit; market studies and public-benchmark rotations remain separate records. Release 1.0.0 is published and preregistered, while its baseline remains null until a fresh resident run passes replay and lifecycle admission.

Historical results remain useful evidence in their original lineages, but none is a baseline for release 1.0.0. The old conditions differ in tasks, prompts, graders, model routes, policy, context, tool contracts, and runtime supervision. Converting the resident 87/126 or Flash 101/126 result into a new-suite score would manufacture comparability that does not exist.[^1]

Release 1.0.0 records `published_at=2026-09-16T05:22:36.754311Z`. Commit `e95073dc5ae6ec266b196ec9c5bba6cab91aba46` witnesses the reviewed causal source and draft bytes; public commit [`1fa863cef3dbd288d8408838e3138e00ece20aba`](https://github.com/decross1/a_bgt_rsi/commit/1fa863cef3dbd288d8408838e3138e00ece20aba) records the published definition, two manifests, window plan, and ordered comparison registration before inference. The fixed review boundary is `2026-10-14T00:00:00Z`; reaching it requires an explicit review, extension witness, or new semantic version. The program must not extend itself silently, add result-dependent tasks, or create another endpoint and UI card for each study.

The initial execution window is resident-only. The final permitted Flash startup stopped at the unchanged five-second host pageout guard before readiness, canaries, or evaluator admission, with zero issued model calls and verified resident restoration. The Flash arm is therefore `unissued`, not a loss, while the resident arm may establish the first fresh baseline after replay and lifecycle admission.[^2]

## What the repository contains

The canonical `bench/` tree contains 19 directories, including one test-support directory, four standalone data assets, and 216 files after excluding bytecode caches. This is not 19 independent benchmarks. Several directories are aggregators, calibration stores, runtime investigations, or applied-data systems; `bench/flash_next_ab` alone contains 61 files spanning qualification, lifecycle, primary, supplement, context, diversity, and follow-on work.

The machine-readable companion inventory lists every file, package, endpoint, UI surface, overlap lineage, recommended role, and public candidate pin. It is designed as the migration ledger rather than a replacement for immutable historical artifacts. Any future package or UI surface should be added to that ledger as part of a release review.

| Canonical source family | What it actually measures | Recommended disposition |
|---|---|---|
| `weekly_upgrade_eval`, `portfolio`, `historical`, `effort`, `diversity` | Development capability, role, repair, and proposal-selection batteries | Diagnostic/development; preserve original denominators and receipts |
| `weekly_upgrade_context` plus Flash context modules | Context-capacity and runtime behavior on controlled packs | Runtime diagnostic; do not convert capacity passes into capability credit |
| `flash_next_ab` | Runtime qualification and multiple local-model evaluation windows | Historical diagnostic lineage; retain the registered gate verdict |
| `fp8_ab`, `mtp.csv`, `day1.csv`, `control_baseline.csv` | Quantization, MTP, tool-probe, and early runtime records | Runtime/archive |
| `qwen_ab_3bcd`, `critic_*`, `judge_cal`, `readjudication`, `redteam_cal`, `debate_eval` | Role, prompt, judge, critic, and red-team calibration | Calibration/archive; do not pool with model capability |
| `agentic_game_theory` | Known-opponent finite-game behavior and best-response controls | Applied strategic diagnostic, by mechanism and episode |
| `payoff_tool_study` | Native arithmetic/tool intervention | Applied diagnostic; prior window remains zero-call unissued |
| `applied_trading` | Public/paper market data capture and trial contracts | Applied empirical lane; no model score and no trading authority |
| `stable_benchmark` | Published 18+3 fixed public regression canary | Stable core; fresh baseline still pending admission |

The existing 126-cell primary laboratory run is a condition matrix rather than 126 independent scientific claims. Topic, role, portfolio, repeated-condition, and scaffold variants reuse underlying tasks and graders. The two decisive Flash portfolio failures, for example, are two conditions from one delegation task lineage; this is why the original preregistered portfolio gate can fail while a population-style claim about 126 independent tasks would be invalid.[^1]

The same rule applies to context cells and diversity calls. The Gemma 36, Qwen 24, and Mia 36 context cells repeat four controlled tasks across evidence positions and capacity bands. The Flash cap closure reuses five development task lineages in two token-cap conditions, so its correct role is `diagnostic_development`, not holdout.[^1]

## Existing API and UI surface

Eight existing read-only benchmark-facing endpoints expose weekly history, primary lab evaluation, supplements, context cross-plan evidence, the diversity-cap study, payoff-tool status, applied data, and research operations. Some additional projections—local model research, follow-on results, research-pipeline state, and applied-market research—are embedded in `/api/weekly_upgrade/progress` rather than owning another route. The new `/api/benchmark_program` is the single generic release and run-history endpoint.

The Benchmarks page currently renders a weekly timeline/family view plus nine historical or research panels: Local Model Research, Lab Model Evaluation, Lab Model Supplement, Lab Context Cross-plan, Lab Diversity Cap, Payoff Tool Study, Follow-on Results, an inline Research Pipeline panel, and Applied Market Research. These surfaces are valuable provenance views, but their proliferation mirrors study history rather than a stable measurement taxonomy. The new Benchmark Program view should become the compact current-release surface while the older panels remain available as historical detail.

The generic projection should show the active release, publication/review status, panel and task IDs, fixed denominators, resource ceilings, run terminal state, replay state, and admission state. It should never return task prompts, hidden cases, grader inputs, raw completions, arbitrary receipt dictionaries, or private filesystem paths. Scores appear only for a complete receipt chain that binds the published definition, run manifest, arm, cohort, replay, and external lifecycle admission.

## Overlap and lineage rules

The weekly-upgrade family is one broad development lineage. `weekly_upgrade_eval` supplied general fixtures and topic/role tests; portfolio added delegation, sortition, social-choice, coordination, evidence, Simpson, and code tasks; historical added repository repair; effort varied reasoning policy; diversity varied generation and selection. Similar vocabulary does not make these tasks exchangeable because objective functions, parser contracts, policies, and independent units differ.

The Flash laboratory family is another broad lineage. Qualification and lifecycle modules establish whether a runtime may execute; primary and supplement windows measure quality; context modules measure supported bands; diversity modules study proposal generation and output caps; follow-on modules prepare later interventions. File count, call count, and condition count must never be displayed as independent benchmark count.

The strategic-utility lineage crosses `agentic_game_theory`, weekly game-science tasks, portfolio tasks, diversity tasks, and payoff-tool work. It contains different mechanisms, focal seats, opponent rules, own-versus-joint objectives, and arithmetic assistance. Report action validity and own-utility regret against a trusted oracle within each mechanism; report joint utility as a separate descriptive outcome. Do not average public goods, auctions, Cournot, coordination, and proper scoring into one “game theory” score.

The resident-calibration lineage crosses model versions and evaluator prompts. Critic, judge, red-team, readjudication, two-voice, vote, and restatement batteries answer whether a role or grading contract behaves acceptably. They do not establish scientific-task performance and should not receive a MODEL layer score.

The applied-market lineage records data availability, paper forecasts, reference captures, and trial contracts. It should prioritize mechanism questions—auctions, information aggregation, inventory, adverse selection, or prediction-market scoring—when a causal question justifies them. Cryptocurrency is a possible data source, not the default subject, and Bitcoin price prediction is not a standing benchmark objective.

## Integrity scale

A stable program needs one visible integrity scale because “completed” currently spans everything from a CSV to a replayed, restored model window. The scale below is monotone: a record can claim only the highest level whose requirements are all met. It describes evidence integrity, not task difficulty or model quality.

| Level | Name | Required evidence |
|---|---|---|
| I0 | Recorded only | A result artifact exists; denominator, task bytes, or runtime identity may be incomplete |
| I1 | Registered | Question, arms, denominator, metric, and stopping rule were fixed before inference |
| I2 | Source-bound complete | Manifest, task/grader/scaffold sources, runtime identity, raw evidence, attempt ledger, and terminal state are bound |
| I3 | Independently replayed and admitted | Objective replay passes; a separate supervisor proves monitor completion, no guard breach, and exact restoration; no partial or invalid cell is scored |
| I4 | Repeated comparable | The same published definition is repeated across eligible windows without task, grader, arm-policy, or harness drift |

The older standalone CSVs are I0 archives. Older calibration and A/B packages are mixed I1–I2. The admitted primary, supplement, and context windows reach I3 for their own frozen definitions, while the aborted cap and unissued payoff study are honest I2 terminal records with no quality score. No current lineage should be called I4 until the same release has been repeated prospectively.

Release 1.0.0 should require I3 before any public task result appears. A run with all inference calls returned may still be withheld if a grader is unavailable, a source hash changes, a transport failure requires conservative full-ceiling accounting instead of an exact attempt ledger, a monitor breaches, or restoration fails. I4 is the program’s eventual progress measure: a comparable time series within one frozen version.

## Fixed regression canary

The fixed core contains 18 one-arm capability units and three harness micro-workflows. It is intentionally small enough for one Spark and a weekly cadence. It is a regression canary for known contracts, not a comprehensive measure of scientific intelligence, autonomous research, general coding ability, or model selection.

| Layer and family | Units | Objective |
|---|---:|---|
| MODEL: science/evidence | 4 | Markov stationary calculation, randomized-arm effect, exact evidence attribution, and warranted abstention |
| MODEL: functional repair | 4 | Fresh isolated Python repairs for interval merging, weighted median, maximum drawdown, and waterfall payments |
| MODEL: deterministic tools | 4 | Single, parallel, relevant-no-call, and dependent two-tool use with exact transcripts |
| MODEL: strategic behavior | 6 | Public goods ×2, Vickrey ×2, Cournot ×1, and ex ante proper-scoring report ×1 |
| SYSTEM harness | 3 | Actor selects a schema-bound tool, trusted CPU code executes it, and a separately routed critic emits an objectively checked artifact |

Public summaries may report binary objective-completion counts for science/evidence `n=4`, functional repair `n=4`, deterministic tools `n=4`, and harness micro-workflows `n=3`. Strategic summaries remain split into public goods `n=2`, Vickrey `n=2`, Cournot `n=1`, and proper-scoring reporting `n=1`. There is no cross-domain credited total and no overall score.

The strategic prompts explicitly instruct the agent to maximize its own expected payoff. Trusted code derives own utility, joint or social utility, the finite-action best response, and exact own-utility regret after the action is returned. The Brier task supplies a private Bernoulli belief of 0.65 before any outcome and grades expected proper-score utility; it is a reporting-incentive construct, not forecast accuracy after seeing an outcome.

The two public-goods rows and two Vickrey rows are repeated parameter instances of their mechanisms. Their uncertainty cluster is the mechanism, not the row. Cournot and Brier each have one instance, so their result is a task-level canary observation and cannot support a population claim.

The four code repairs are genuine functional checks executed in an isolated bubblewrap boundary with mutation, return, and exception requirements. They are narrower than the repository’s historical repair panel and do not replace real-repository repair. The extended tier must provide fresh source snapshots and repository-level regression suites before a candidate promotion claim uses coding evidence.

The tool tasks use actual model–tool loops with exact selection, arguments, results, and grounded final answers. The dependent task consumes up to three model calls, while correct no-call behavior can finish in one. The call ceiling is therefore a maximum, not a requirement to issue filler calls.

## SYSTEM and orchestrator attribution

The three SYSTEM units are actor–tool–critic harness micro-workflows. The actor receives a goal plus two tool schemas, one of which is a distractor; it chooses the tool and supplies schema-valid arguments and a draft. Trusted CPU implementations calculate public-goods utility, evaluate a Vickrey bid, or check whether evidence supports a rate claim, and the critic receives the actual transcript before producing the final artifact.

These missions test a narrow scaffold boundary: role routing, schema adherence, actual tool execution, transcript propagation, and critic revision. They do not execute the whole production coordinator, research queue, literature ingestion, debate, journal, human gate, scheduler, or service lifecycle. The claim scope is therefore “actor–tool–critic micro-workflow,” never “orchestrator success.”

Whole-orchestrator progress belongs in a separate production funnel. Useful denominators include scheduled cycles, admitted iterations, empirical outcomes attached, critic/debate outcomes, science-gate dispositions, and terminal failures. Those outcomes can be linked to a benchmark release and runtime identity, but they must not be added to the 21-unit canary score.

The resident arm is a routed stack rather than one model. Capability and actor calls use the Gemma resident route with its exact `precise` profile; harness critic calls use the Qwen resident route with `critic_current` and xhigh reasoning. A later Flash arm may route all roles to Flash only after a reviewed transport and runtime admission. Any comparison is a SYSTEM-configuration comparison and cannot causally attribute the difference to weights alone.

## Resource and runtime contract

The task-level ceilings derive to 29 model calls per arm: 23 capability calls and six harness-role calls. A matched two-arm window therefore has a 58-call ceiling. The maximum output allocation is 25,088 tokens per arm, the sum of each task’s call ceiling times its per-call token cap; summed episode ceilings are 1,575 seconds per arm, within a 7,200-second supervised lifecycle envelope.

A successful path may use fewer calls. Every attempted transport request is still charged: an adapter reports the exact issued-attempt count, or the runner conservatively charges that task’s full ceiling and marks the count inexact. The latter receipt preserves resource evidence but is withheld from scored admission until an exact ledger exists; over-ceiling counts and missing partial records are likewise non-admissible.

RUNTIME admission binds the definition, run manifest, role-to-route mapping, served models, artifacts, runtime digests, contexts, generation profiles, temperature, top-p, reasoning effort, sampling extras, wrapper/policy/scaffold sources, endpoint-binding receipt, supervisor-ready receipt, and resource-guard receipt. The runner accepts an already admitted injected transport and never starts, swaps, discovers, or stops a model itself.

Per-cell states are `passed`, `failed`, `abstained`, `timeout`, `transport_error`, `invalid_output`, `invalid`, `skipped_budget`, and `unissued`. A warranted evidence abstention is visible and may earn objective credit. Malformed model output stays in the denominator; harness/grader drift is `invalid`; cancellation leaves `skipped_budget`; an arm that never passed runtime admission is `unissued`. Partial cells are never scored as if complete.

A run receipt cannot admit itself. Offline replay rereads private raw attempts, call records, tool transcripts, source hashes, and code-sandbox results. A separate supervisor-final receipt proves the end monitor, unchanged guards, and restoration before `admission.json` may set `admitted=true`; admission still sets `promotion_authorized=false`.

## Metrics and uncertainty

The primary denominator is the fixed task or episode lineage, not calls, conditions, files, outputs, or judge votes. Each public family row shows planned, accounted, credited, invalid, aborted, and unissued counts. Calls, output tokens, wall time, and memory are resource measurements rather than quality denominators.

Pairwise comparisons use matched task deltas and left-only/right-only discordant counts within each construct. A fixed-seed cluster bootstrap may describe constructs with at least four uncertainty clusters using an equal-weighted cluster estimand. With fewer than four clusters the interval is omitted, which avoids presenting a degenerate tiny-panel interval as inferential evidence.

Strategic reporting includes action validity, own utility, joint utility, best-response utility, and own-utility regret. Utility scales remain mechanism-specific. Brier joint utility is explicitly descriptive, and lower own regret in one mechanism cannot offset a regression in another.

The canary can trigger investigation, block a regression, or justify a larger preregistered panel. It cannot automatically promote a stack, even if every binary row improves. Promotion needs the relevant extended evidence, continued runtime qualification, resource acceptability, and a stated decision rule appropriate to the proposed production change.

## Freeze, registry, and cadence

The active registry should contain one bounded release entry and one active pointer. Weekly runs append under the same release and comparison namespace; they do not create new components. Definition, task, grader, independent-unit, or metric changes start a new series and normally require a minor or major version.

The release begins only when the actual bytes receive an external witness. A timestamp embedded while drafting is not publication. The intended review date is October 14 at 00:00 UTC; at that time the owner either witnesses an unchanged extension, publishes a revised version, or marks the release inactive.

Run the core at most weekly for the resident and once for a materially changed candidate configuration. Run an extended panel monthly, at release review, or after a preregistered trigger: a stable-core regression, a scaffold/runtime change, a promotion candidate, or two consecutive descriptive canary improvements. The trigger, IDs, versions, denominator, and stop rule are fixed before inference.

Stable public fixtures are expected to be visible and eventually contaminated. Their value is contract regression against a fixed public panel. Holdout and rotation tasks must live in distinct manifests and provenance roots, selected without result-dependent substitution, with answers and private grader material excluded from optimizer and agent context. A holdout result never silently replaces the stable-core denominator.

## Historical evidence boundary

The admitted primary pair recorded Flash 101/126 and the resident 87/126. The registered portfolio gate still failed because Flash scored 14/16 against the resident 16/16, with both failures arising from one delegation lineage. Fresh science was resident 6/6 and Flash 5/6; strict fresh repair was 0/6 for both, while a separately declared framing diagnostic passed 6/6 for both.[^1]

Those findings justify retaining the historical production decision and targeted follow-up. They do not say that the resident is generally better, that Flash lost the new stable suite, or that the repaired framing contract retrospectively changes the strict repair score. The stable release starts with `baseline_status=not_started` until a fresh resident run is replayed and admitted.

Context evidence is also preserved without conversion. Gemma and Mia passed their controlled 8K, 16K, and 32K cells; Qwen passed 8K and 16K, with no Qwen 32K result. These are supported capacity bands on one controlled panel rather than universal optimal context allocations.[^1]

The earlier 384-token observation found many reasoning-only completions without visible final answers. The final 384-versus-1,536 closure attempted exactly one new window with the same frozen plan, but the host paging guard stopped it during load at 562,221,056 bytes over five seconds against a 536,870,912-byte threshold. Candidate swap and OOM counters remained zero, so the terminal claim is a host-startup paging abort rather than candidate OOM or cap quality result.[^2]

The payoff-tool study’s earlier final window was `closed_unissued` with zero requests. It remains evidence that the instrument was not run, not a null arithmetic result. Any later execution uses a new window identifier and its own runtime admission.[^1]

## Public benchmark research

External suites should strengthen the monthly or triggered tier, not inflate the weekly core. Each adoption record needs an upstream version or commit, selected IDs, license review, task-content redistribution rule, local oracle result, ARM/runtime pilot, model and scaffold configuration, full denominator, and a declaration that the resulting number is a project rotation rather than an upstream leaderboard score.

| Candidate | Verified scope, version, and cost | Recommendation |
|---|---|---|
| ScienceAgentBench | 102 tasks from 44 papers in four disciplines, reviewed by nine experts; verified split announced 2026-04-30. Official README says a 102-task containerized pass can run in about 30 minutes with eight threads. Code is MIT; most tasks are CC BY 4.0, while IDs 3, 32, 46, 53, 54, and 84 retain upstream licenses.[^3] | Best scientific-workflow extended candidate. Select only license-cleared tasks, pin verified artifacts and commit `c26e151…`, replay oracles, and pilot ARM. |
| CORE-Bench | 270 tasks from 90 papers. The official repository says its harness is no longer actively maintained and recommends HAL; local medium tasks require privileged Docker-in-Docker, while documented Azure types include E2as_v5 and T4 instances.[^4] | Rare reproducibility diagnostic, not weekly. Pin capsules and verify their content licenses and local sandbox behavior. |
| PaperBench | Replication of 20 ICML 2024 papers with 8,316 rubric nodes. Official experiments give each rollout 12 hours with one A10; the paper estimates $400 API cost per paper plus $66 grading, about $9,320 for a full 20-paper run before compute.[^5] | Outside the one-Spark/no-paid-API envelope. Use only as occasional research design reference or separately funded audit. |
| Terminal-Bench | Current v4.0.0 release is pinned at `452bf305…` and changed or removed tasks relative to v3. Official guidance requires five oracle runs in the target sandbox; repository license is Apache-2.0.[^6] | Strong triggered terminal-agent rotation after selected-task license review, five-oracle qualification, and ARM pilot. Never track `latest`. |
| SWE-bench Verified / Pro | OpenAI’s 2026 audit of Verified found material flaws in 59.4% of an audited 27.6% subset and contamination evidence. A later Pro audit flagged 27.4% broken by the pipeline and 34.1% by humans, leading to an approximately 30% broken estimate.[^7] [^8] | Do not use either as stable core. A future coding rotation needs an independently audited/repaired task set and fresh snapshots. |
| BFCL V4 | Official leaderboard pin `f7cf735`, package `bfcl-eval==2025.12.17`, last updated 2026-04-12. V4 includes multi-turn and agentic categories, while live data is deliberately mutable.[^9] | Use a fixed non-live subset for tool-contract rotation after local oracle validation. Do not report the adapted subset as BFCL overall. |
| tau-bench | MIT; tags include v1.0.1 and current HEAD `2174a603…`. Results depend on task version, domain, user simulator, trial count, policies, and agent scaffold; official submission guidance prefers at least four trials.[^10] | Separate agent/tool rotation. Pin simulator and domain bytes, and avoid interpreting one domain as general tool ability. |
| TextArena | MIT framework with 100+ games; README announces v0.6.9, while no matching git tag was observed, so use a commit such as audited HEAD `6dfb577…` rather than the textual version alone.[^11] | Fixed game/config subset with scripted opponents, exact seeds, parsers, and payoff replay. Keep self-play and model-opponent effects separate. |
| GTBench | NeurIPS 2024 benchmark with 10 games spanning information, dynamics, and stochasticity; audited repository HEAD `b75e1d7…`.[^12] | Useful strategic extended candidate after exact opponent, prompt, parser, and utility audit. |
| KantBench/OpenEnv | BSD-3-Clause, audited HEAD `5d9419f…`, with 99+ configurable games across auctions, markets, signaling, and cooperative games.[^13] | Promising mechanism sandbox, but too new for a gate until payoff/oracle correctness, version stability, and local runtime are independently audited. |

ScienceAgentBench is the best first science rotation because it targets data-driven scientific workflow and now distinguishes a verified split. Even then, the full upstream score should not be claimed from a small local subset, and the six tasks with retained upstream licenses require individual treatment. A local subset should be named, for example, `sab-verified-project-rotation-<version>`.

Terminal-Bench is the strongest terminal-agent candidate after local qualification. Its v4 release demonstrates why edition pinning matters: tasks were removed and modified, so an unversioned time series would mix instruments. The official five-oracle instruction should be treated as an adoption prerequisite rather than optional cleanup.

SWE-bench provides the clearest reason to avoid prestige-driven adoption. A public name and large denominator do not repair flawed tests, underspecified prompts, or contamination. The repository’s fresh real-repair tier should use smaller source snapshots with manually reviewed issue/test alignment before considering a larger public set.

BFCL, tau-bench, TextArena, GTBench, and KantBench cover different agentic constructs. BFCL primarily measures tool invocation and state transitions; tau-bench adds a simulated user and policy environment; TextArena and GTBench add game/opponent dynamics; KantBench emphasizes configurable economic mechanisms. Their numbers should remain distinct because scaffold and opponent behavior contribute materially to outcomes.

## Hardware and cost fit

The audited host is ARM64 with 20 logical CPUs, about 121 GiB host RAM, 15 GiB swap, roughly 2.6 TiB free project storage, and one NVIDIA GB10. The weekly budget is 120 Spark minutes and the benchmark policy permits no paid frontier API. These constraints favor deterministic CPU graders, serial local inference, and a small fixed panel.

The 29-call resident canary is compatible with the available envelope, subject to normal runtime admission and restoration. A paired 58-call window also fits the definition’s 7,200-second supervised ceiling, but the current Flash runtime did not pass startup. Running ScienceAgentBench, CORE-Bench, PaperBench, or full Terminal-Bench in the weekly path would conflate benchmark work with environment builds and exceed the intended operational budget.

Public rotations therefore need separate reservations and cached, licensed artifacts. No large suite should be downloaded merely to claim coverage. First perform a metadata/license review, select a bounded edition, run the official oracle or equivalent on ARM, measure storage and wall time, and only then preregister a model run.

## UI presentation

The main Benchmark Program view should answer five questions in order: what release is active, whether its freeze is valid, which MODEL/SYSTEM/RUNTIME/applied layers have evidence, whether each run was replayed/admitted, and what changed within comparable families. One compact task-family table is enough for the current canary; mechanism rows expand to task receipts when needed.

Use explicit labels for `draft`, `published`, `review_required`, `complete`, `aborted`, `unissued`, `verified`, `admitted`, and `withheld`. An unissued Flash row should show zero calls and the startup-gate reason with no score cell. A resident-only baseline should not render a synthetic pairwise delta.

Historical panels remain accessible below or through lineage links. Their headings should identify `diagnostic_development`, `runtime`, `calibration`, or `applied empirical` rather than suggesting every panel is another core benchmark. The cap closure is shown beside its predecessor as one lineage, not a new benchmark family.

Resource charts should show actual calls, tokens, wall time, and guard outcome against fixed ceilings. Quality tables should show planned and credited units with the exact denominator. A small-N warning and `promotion_authorized=false` belong next to comparisons rather than in a distant footnote.

## Operating recommendation

The immutable release definition, two run manifests, resident lifecycle plan, and ordered comparison registration are now published in commit `1fa863c…`, after causal source commit `e95073d…` and before inference. The next action is to execute and admit the resident arm and write the Flash arm's 21-row `unissued` receipt with the runtime-gate reason and zero calls.

Keep release 1.0.0 unchanged through October 14 unless a correctness fault requires withdrawal. Append eligible weekly resident runs under the same registry entry. A later Flash attempt requires a reviewed runtime qualification; if it executes under identical release bytes and arm policy, it can join the cohort, while a route, policy, task, or harness change starts a new manifest or version as appropriate.

Use the fixed canary for regression detection and resource observability. Use fresh repository repair and a small ScienceAgentBench verified rotation as the first stronger monthly tier, followed by a fixed non-live BFCL or selected strategic-game rotation only after oracle and ARM qualification. Keep production-orchestrator outcomes and market studies visible as separate layers.

This structure stops one-off panel accretion without discarding evidence. Every old result remains traceable, every new result has a fixed denominator and terminal state, and future benchmark additions enter through a versioned rotation or release review rather than another bespoke endpoint.

## Dated follow-up — September 16, 2026

The analysis above records the architecture and publication state before the
first release 1.0.0 resident execution. That execution later completed with a
receipt-admitted lifecycle, replay, resource guard, and restoration chain. A
post-run prompt–grader audit then found four task-design defects: the two
evidence citation oracles did not match their visible minimal-evidence
contracts, and two otherwise ordinary code answers encountered sandbox
restrictions that the prompts had not disclosed. The remaining observed
serialization, token-cap, actor-output, and strategic-regret failures remain
declared end-to-end observations of the frozen stack. The exact disposition is
recorded in the [resident prompt–grader audit](../stable-benchmark/RESIDENT_PROMPT_GRADER_AUDIT.md)
and the source-controlled [release 1.0.0 measurement review](../../../../docs/benchmarks/measurement_reviews/75de9dc0dc324a4559332f88ae6e5ae861ba0d6f683334d85395d082bbaf04df.json).

Release 1.0.0 and its recorded numbers remain immutable commissioning
evidence. They are not retrospectively rescored, converted into a corrected
baseline, or used for comparative quality claims. Receipt admission establishes
the integrity of the recorded execution chain; it does not repair a defective
measurement contract.

Prospective release 1.1.0 keeps the same ordered 21 task IDs, family
denominators, role policies, strict JSON parser, tool transport, token ceilings,
and October 14 review boundary. It binds every task to the same-ID 1.0.0
predecessor while declaring the two releases non-comparable. Its bounded
contract changes require DOC-A/B/C for the full randomized 30-day evidence
claim, require DOC-E alone for the missing-denominator abstention, define
citations as arrays of bare document IDs, and disclose the unchanged sandbox
contract on all four code tasks, including banned syntax, allowed calls, all
attribute access, isolation, resource limits, and non-mutation. A model-free
preflight covers gold contracts for all 21 tasks and valid alternatives.

The reviewed prospective draft is
[`bench/stable_benchmark/definition.draft.json`](../../../../bench/stable_benchmark/definition.draft.json),
with raw-file SHA-256
`026cedcc23894600f95e542908bb6c19453f950eb63e62b9e6948f277662a9ed`.
Its distinct artifact root is
`ui-benchmark-eight-hour/stable-benchmark-v1_1`. At the time of this addendum,
release 1.1.0 was still unexecuted. Publication and preregistration subsequently
landed in [c840466](https://github.com/decross1/a_bgt_rsi/commit/c840466) at
06:34 UTC, following frozen source 979f961. The published definition SHA-256 is
`d2eb69d9c0fefc7b377cec6cb550f491979a5f137d38346dc99a607be5890006`.
Supervised runtime admission must precede any model call. Any later 1.1.0 result
begins a prospective series and cannot be matched against the 1.0.0
commissioning outcomes.

## Sources

[^1]: a_bgt_rsi project, [`notes/research/2026-09-15-lab-eight-hour/EIGHT_HOUR_RESULTS.md`](/home/decross1/projects/a_bgt_rsi/notes/research/2026-09-15-lab-eight-hour/EIGHT_HOUR_RESULTS.md), [`FINAL_INTEGRITY_AUDIT.md`](/home/decross1/projects/a_bgt_rsi/notes/research/2026-09-15-lab-eight-hour/FINAL_INTEGRITY_AUDIT.md), and [`NEXT_RUNS.md`](/home/decross1/projects/a_bgt_rsi/notes/research/2026-09-15-lab-eight-hour/NEXT_RUNS.md), September 15–16, 2026.
[^2]: a_bgt_rsi project, [`flash-cap-closure-result.public.json`](/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-16/ui-benchmark-eight-hour/flash-closure/flash-cap-closure-result.public.json), September 16, 2026.
[^3]: Ohio State NLP Group, “[ScienceAgentBench](https://github.com/OSU-NLP-Group/ScienceAgentBench),” repository and licensing notes, verified split update April 30, 2026; audited HEAD `c26e151ed601ba109dc4d35e057ff8e73fec469d`.
[^4]: Siegel et al., “[CORE-Bench](https://github.com/siegelz/core-bench),” official repository, accessed September 16, 2026; audited HEAD `e32a2980e72fe6eb04ee04eb749458f570625663`.
[^5]: OpenAI, “[PaperBench: Evaluating AI’s Ability to Replicate AI Research](https://cdn.openai.com/papers/22265bac-3191-44e5-b057-7aaacd8e90cd/paperbench.pdf),” 2025; [official frontier-evals repository](https://github.com/openai/frontier-evals), audited HEAD `51052cede8cc608f95bb00346635e03759013e5a`.
[^6]: Harbor Framework, “[Terminal-Bench releases](https://github.com/harbor-framework/terminal-bench/releases)” and [official repository](https://github.com/harbor-framework/terminal-bench), v4.0.0, August 26, 2026, tag commit `452bf305c6daa62fc59061d22133a7cbc7c1572e`.
[^7]: OpenAI, “[Why SWE-bench Verified no longer measures frontier coding capabilities](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/),” February 23, 2026.
[^8]: OpenAI, “[Separating signal from noise in coding evaluations](https://openai.com/index/separating-signal-from-noise-coding-evaluations/),” July 8, 2026.
[^9]: UC Berkeley Gorilla, “[Berkeley Function Calling Leaderboard V4](https://gorilla.cs.berkeley.edu/leaderboard)” and “[BFCL V4: Web Search](https://gorilla.cs.berkeley.edu/blogs/15_bfcl_v4_web_search.html),” leaderboard updated April 12, 2026.
[^10]: Sierra Research, “[tau-bench](https://github.com/sierra-research/tau2-bench)” and [release history](https://github.com/sierra-research/tau2-bench/releases), audited September 16, 2026.
[^11]: TextArena, “[TextArena](https://github.com/TextArena/TextArena),” official repository, README v0.6.9 announcement, audited HEAD `6dfb577c01d0337fe03b05adce84c5ae1878eca1`.
[^12]: Duan et al., “[GTBench: Uncovering the Strategic Reasoning Capabilities of LLMs via Game-Theoretic Evaluations](https://papers.nips.cc/paper_files/paper/2024/hash/3191170938b6102e5c203b036b7c16dd-Abstract-Conference.html),” NeurIPS 2024; audited repository HEAD `b75e1d7068d6935208810affa78b436072d08051`.
[^13]: Wisent AI, “[KantBench/OpenEnv](https://github.com/wisent-ai/OpenEnv),” BSD-3-Clause repository, audited HEAD `5d9419f194c282de3082e1850d150b77b062f8fb`.
