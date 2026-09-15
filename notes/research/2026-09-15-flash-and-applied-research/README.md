# Overnight model decision and applied research handoff

Prepared during the owner-authorized 2026-09-15 07:08:57–15:08:57 UTC window.
Final model decision; measurements below distinguish closed experiments from
the prospective market observation scheduled for later today.

## Decision

**RETAIN-INCUMBENT:** keep Gemma 4 26B-A4B (generation/coding, 32K) and
Qwen3.8-27B (secondary reasoning/criticism, 16K) on the current vLLM 0.21
production runtime. Both exact original containers and Nara are running.
Keep the optimized Mia Flash checkpoint as an isolated research challenger. Flash has demonstrated useful
science reasoning and fits one Spark, but the tested configuration does not yet
justify replacing both resident models for every lab task.

The owner permits a single primary model and up to a 12 GiB reserve when needed.
Neither is the reason for retaining the incumbent: Mia C0 passed qualification
with 36.31 GiB minimum available memory under the preferred 20 GiB reserve. The
constraint is completed useful work and reliability.

## Completed measurements

The full preregistered development panel ran 126 cells per system. Both windows
closed, restored the exact original services, and passed their evidence gates.
Flash took 4,958 seconds of task-harness time versus 630 seconds for the resident
bundle. Startup and restoration are separate from those times.

| Task family | Resident passes | Flash passes |
|---|---:|---:|
| Context controls | 4/4 | 4/4 |
| Diversity/selection | 2/10 | 2/10 |
| Historical coding repairs | 0/6 | 0/6 |
| Objective science/tools | 2/24 | 12/24 |
| Science/coding portfolio | 5/16 | 12/16 |
| Role/effort | 17/18 | 11/18 |
| Topic protocol | 47/48 | 13/48 |

Flash completed all 12 portfolio science/evidence cases, but its four coding
cases and six historical repairs timed out. Its native omitted-effort template
uses xhigh thinking, so this first comparison is a model/runtime/policy bundle
comparison, not a pure weights estimate. Changing the frozen answers or dropping
timeouts would invalidate the result.

A second, explicitly controlled development panel tested thinking off, low,
medium, xhigh and adaptive escalation. Flash passed 15/30 and resident Qwen
18/30. These six reused tasks do not establish a general policy ranking. A
separate diagnostic found ten Flash final answers exactly echoed the requested
JSON Schema instead of returning an instance. This is more substantial than
fenced JSON and remains a model/contract failure in the primary grades.

On 12 fresh, objectively graded game-theory/market-research scenarios, both
models passed 12/12 with medium reasoning. Flash took 351.84 seconds and Qwen
314.01 seconds. With thinking off, Flash passed 9/12 in 36.36 seconds and Qwen
7/12 in 25.05 seconds. Reasoning improves this panel at a large latency cost;
that supports role-specific evaluation, not globally raising or lowering effort.
These are reasoning problems, not evidence of profitable trading.

Both systems passed 12/12 supported context tasks at approximately 2K and 8K.
Flash's three ungraded 512-token timing requests completed 1,536 tokens in
106.11 summed request seconds, about 14.5 tokens/sec, with mean first-token
latency 0.186 seconds. Short-prompt timing is not long-context quality.

## What the research pipeline needs

The audit found a missing transition from a plausible topic to an executable
empirical application. The current campaign's one linked iteration was a
rediscovery and subsequently killed for an existing paper prior. Most recent
campaign cycles were no-ops. Older negative experiments are useful constraints,
but the repository has no demonstrated trading edge.

Known game-theory mechanisms can motivate application tests without being
claimed as new theory. The implemented application sidecar therefore preserves
the scientific novelty ladder while separately connecting a mechanism, frozen
data, a declared forecast, an outcome horizon and a measured result.

The first application is a BTCUSDT spot research lane: test whether lagged signed
taker flow adds out-of-sample predictive information beyond return, volatility
and volume baselines; separately collect prospective public quote/trade evidence
for a flow/visible-liquidity reference diagnostic. REST snapshots do not identify
actual cancellations, trader inventory or causal strategic behavior. The
historical baseline is a forecast test and the prospective adapter is explicitly
nonexecutable reference evidence, not fill-aware paper trading.

The evaluation infrastructure also exposed an architectural problem: an older
runtime qualification contains its original evaluator source bundle. Adding a
new task runner in a different checkout caused the worker to compare that old
qualification with the new evaluator's files and reject the launch before any
model mutation. The bounded correction validates the exact historical runtime
record through its unchanged original reader, while independently validating
the current evaluator. The next harness refactor should make those two
identities explicit: a runtime certificate for model/image/launch/canaries and
an experiment manifest for tasks/policies/graders. That would reduce brittle
checkout-specific adapters without weakening either provenance check. The
historical records and frozen source trees were retained in this round.

## Changes to prioritize next in the lab

Retaining the resident setup is an operational choice, not a clean bill of
health: both systems failed the original historical repair panel. The current
measurement now distinguishes formatting, reasoning/output-budget exhaustion,
and task correctness, so those failures can drive concrete improvements.

1. Version response contracts by task and model. Keep the exact raw grading
   boundary, give explicit raw-JSON or raw-diff framing, and use a separate
   presentation diagnostic rather than silently rescuing benchmark answers.
   Test fresh numeric/repair instances after prompt development.
2. Keep Gemma thinking off in its current production contract until thinking
   text and final content are separated reliably. Use the resident Qwen
   reasoning parser for bounded science/criticism trials, with explicit effort
   and adequate output budgets. The existing 12/12 medium science panel is a
   useful starting point, not a universal profile optimum.
3. Treat executable calculation, source checks and regression tests as the
   scientific instrument's ground truth. A critic's fluent approval or a valid
   JSON action cannot replace the payoff oracle, working patch, or future
   outcome. The quote control specifically exposed this distinction.
4. Keep one strategic-liquidity application record connected across literature,
   mechanism, as-of data, frozen prediction, validation and disposition. The
   canonical package is [bench/applied_trading](../../../bench/applied_trading/README.md);
   its [30-day execution plan](../../../bench/applied_trading/30_DAY_EXECUTION.md)
   separates the known-prior application from the novelty ladder.
5. Before another large model window, address the contract failures and rerun
   fresh bounded coding/science cases on both setups. Flash promotion needs
   reliable completed work across required roles and a replayable advantage;
   a faster fixed token stream alone does not satisfy that condition. Native
   64K quality and exact DFlash/alternative-quant qualification remain optional
   follow-up experiments with explicit unresolved status.

## Why Flash starts slowly

The measured Mia C0 container needed 610.46 seconds to become ready. Its logs
attribute 486.02 seconds to model loading and another 72.19 seconds to engine
initialization. The checkpoint is approximately 106 GB, with a separate 28.8 GB
packed PLE table attached through disk-backed memory mapping. MoE reduces the
parameters used by a token; it does not eliminate the need to initialize all
resident experts and the serving machinery.

The qualification workflow adds its own full artifact verification and quiet
observation periods. Those checks are not an intrinsic model generation cost.
Likewise, the roughly 6–7 minutes spent restoring the two original servers is
recovery time, not Flash decode time. Host I/O observations showed that readiness
was not continuously saturating NVMe; a faster disk alone is not established as
the fix. GPU and kernel-level timing would be needed to allocate the remaining
startup cost causally.

## Configuration coverage and remaining uncertainty

| Configuration or lever | What was actually established |
|---|---|
| Mia one-Spark NVFP4 with disk-backed packed PLE, MTP off | Qualified; complete original paired panel and controlled thinking/context follow-ons |
| Mia reduced 47,149-token draft vocabulary, MTP3, explicit V2 worker, compilation mode 0 and FULL_DECODE_ONLY capture [4] | Qualified with 12/12 canaries and 34.51 GiB minimum available memory; completed selected repair panel and the final recommended-sampling coding diagnostic (0/4); fixed completion-token rate approximately 43 tokens/sec including request overhead |
| Full-vocabulary MTP3 with PIECEWISE graphs | Startup failure during CUDA graph replay; no answer-quality score |
| NVIDIA NVFP4 checkpoint | Weights downloaded; an earlier launch produced probe output but its recorder failed. No admitted comparison and no quality claim |
| DFlash artifacts | Downloaded and researched; exact one-Spark/Mia/PLE compatibility was not locally qualified |
| Context | Approximately 2K and 8K quality controls passed in both systems; the qualified Flash profile is configured for 32K. Native 69,632-token configuration is prepared but unrun; 32K/64K task-quality superiority is unmeasured |
| Thinking | Explicit off, low, medium, xhigh and adaptive arms tested on reused development tasks; fresh market reasoning cases tested off versus recommended-sampling medium |

The reduced MTP3 profile changes several serving levers together. Its success
does not identify which individual change fixed the full-vocabulary startup
failure. The decoded parity controls also do not establish bit-for-bit lossless
speculation. This is the best locally qualified Flash profile from this round,
not an exhaustive optimum across every quant and runtime.

The exact user-referenced [Mia single-Spark recipe](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark)
was included. The local model revision is `925d7be6c14c6c9442ef83e8f05b5a3c39304f69`;
the optimized image is `sha256:29eab5a29b765eef8b6405bbe0f2d385fc1e7b5e3c7ae18ae70382a68a0a2201`.
The launch contract and qualification receipts retain the exact flags and
artifact hashes. Both downloaded checkpoints and the qualified challenger
remain available for subsequent experiments.

## Closed follow-on results and operational changes

- Optimized reduced47k/MTP3 qualification passed: all three fixed probes and 12/12 repeated canaries, minimum available memory 34.51 GiB, exact original restoration. A full-vocabulary PIECEWISE variant failed during CUDA graph replay before probes; it remains a startup failure, not a model-quality score.
- Selected repair completed and exactly restored at 13:22 UTC: resident Gemma 15/22, zero timeouts, 126.37 seconds of harness time; Flash off 14/22 and medium 0/22. All 22 resident and 44 Flash grades were independently reproduced from recorded responses. Flash off passed all 12 topic cases and two of four portfolio coding cases; historical repairs remained 0/6. Medium's 12 topic calls exhausted the 512-token output cap; all four portfolio coding calls streamed reasoning until the 180-second timeout, with no final patch; four of six historical calls reached their 4,096-token cap. This diagnoses a budget/contract problem and does not establish the checkpoint's best attainable coding quality.
- A separately frozen final diagnostic uses four repeated coding tasks with temperature 1, top-p .95, top-k 20, medium thinking, 8,192 output tokens and a 360-second per-call limit. Sampling, cap and timeout change together; reasoning effort also differs from the original omitted-effort/xhigh panel. This is a targeted configuration diagnostic, not a temperature-only causal estimate or a held-out confirmation. Its first controller attempt failed before model/service mutation because of an old-versus-new source-registration mismatch; the exact failed source and receipts were archived before correction.
- The final diagnostic closed and exactly restored production at 14:20:57 UTC. All four calls returned, but **0/4 passed**, and an independent replay reproduced all four grades. Three calls exhausted 8,192 tokens with no final content. The other historical-repair response had two leading blank lines and no terminal newline; raw SSE and the adapter input agree, so the transport did not strip the newline. Correcting that framing hypothetically passes the syntax parser, but no patch correctness or repaired grade is claimed. This is evidence of output-budget and response-contract failure, not a clean measurement of every task's underlying reasoning ability.
- In the same closed optimized window, three fixed 512-token decode calls returned 1,536 tokens in 35.74 summed request seconds: **42.98 completion tokens/sec over summed request elapsed time (including first-token latency)**, compared with 14.48 in the earlier MTP0 window. Mean latency was 11.91 versus 35.37 seconds, a 2.97× ratio; first-token latency was 0.193 versus 0.186 seconds. MTP, reduced vocabulary, worker and graph settings changed together across separate epochs. This is a useful bundle-level speed result, not lossless speculation, long-context speed or improved task success.
- Nominal-greedy MTP0 repeated controls were not completely stable: one exact arithmetic request gave two wrong answers and one correct answer. The optimized MTP3 repeats were correct, but this is not proof of lossless speculation or a causal explanation of the change.
- Native long-context and DFlash qualification were deferred; no further candidate launch is scheduled.
- All 60 historical days were acquired, verified, scored and independently replayed by the publication gate; the immutable result was admitted at 14:25:42 UTC.
- Public capture was bootstrapped after exact model restoration at 14:21:29 UTC. The first five-minute lineage hit the eight-page backlog limit at 14:35. The failed branch and its exact state were retained; PR 37 raised continuation capacity to the collector's existing 32-page ceiling and the feature-event ceiling to 500,000. The 90-second capture wall limit, five-minute cadence, 96-batch feature cap, and due-service 1 GiB/240-second limits are unchanged. A new lineage was bootstrapped at 14:48 and the new H1 timer is active.
- Dashboard: original A/B, C0 follow-ons, selected repairs and the final coding/decode report are published. Selected-repair UI and verified capture transport-gap recovery were merged in PR 36 and integrated into the canonical checkout; live backend/frontend health and report readers passed. Eight pre-existing dirty tracked files remained byte-identical. PR 37 adds the final 0/4 coding diagnostic with its four reproduced grades, keeps the older windows visible, and integrates the bounded applied-capacity correction.

No real orders, asset transactions, paid frontier calls or destructive history
changes are part of this work. All eight pre-existing canonical dirty files have
been preserved byte for byte through the completed integrations.

## First empirical market result

The sealed BTCUSDT trade-only archive covers **2026-07-17 through 2026-09-14**:
60 complete days, 1,440 hourly rows, 40 development days and 20 chronological
validation days. Fixed ridge regularization and train-only standardization
compare return/volatility/volume with the same features plus signed taker flow.
A four-hour split embargo and horizon exclusions leave 476 one-hour and 473
four-hour validation predictions. The publication gate rehashed all daily
sources and independently reproduced scores and all 949 private predictions.

| Horizon | Baseline MSE (bps²) | With flow MSE (bps²) | Baseline direction | With flow direction |
|---|---:|---:|---:|---:|
| 1 hour, primary | 1,242.423 | 1,243.208 | 49.37% | 50.00% |
| 4 hours, secondary | 5,120.070 | 5,120.179 | 52.85% | 52.85% |

**No supported incremental forecast gain.** The primary MSE improvement is
−0.785 bps², with the recorded day-bootstrap interval [−4.986, +3.151]. The
small direction change has an interval spanning zero. At the declared 30/60 bps
round-trip reference costs, the one-hour rules abstain; four-hour rules have
−1.508 bps per eligible hour at the base cost and abstain at double cost. These
are last-trade reference calculations, not an executable portfolio backtest.
The equal-day bootstrap and hour-weighted headline have different estimands;
overlapping four-hour labels also cross day clusters. See
[the statistical limits](HISTORICAL_SCORE_LIMITS.md) before reusing the intervals.

This deprioritizes the simple hourly flow proxy for trading-model development.
The next justified work is collecting prospective quote/trade evidence and
checking the controlled incentive experiment, not tuning repeatedly on these
same validation days until a positive number appears.

The replacement **H1 REST observation pilot is frozen for 17:05–19:05 UTC on September 15**.
It becomes due at 20:15 UTC after its one-hour outcome horizon and ten-minute
exit allowance; the five-minute timer's first eligible tick is 20:18:30 UTC.
Study ID: `h1-btcusdt-rest-20260915-144919`. Capture is active before the start.
The earlier three-hour plan remains archived and its due timer is disabled.
A 16:30 replacement attempt was rejected before publication because the
registered grid requires HH:05; that preflight failure is also retained.
The accepted two-hour plan binds the new capture and feature source hashes.
The preset is unfitted engineering calibration, not the historical ridge model;
it does not include all historical control features. It has local exclusive-write
freeze evidence only, no external timestamp attestation. Its future outcome is
pending, `paper_supported=false`, `sequence_valid=false`, and no orders are placed.
The due job will either publish qualified reference evidence or retain explicit
missing/invalid status; it cannot promote the scientific ladder or trade.

## The next month: turn a mechanism into a falsifiable application

Use two connected evidence tracks. The scientific track asks whether an agent
responds to incentives and observability as the game predicts. The application
track asks whether a specific as-of signal predicts a future market quantity
beyond simple controls and whether any improvement survives realistic costs.
A successful transport or model benchmark is evidence about the lab's instrument,
not evidence for either scientific or trading claim.

| Period | Concrete deliverable | Decision it enables |
|---|---|---|
| Days 1–3 | Source-complete public trade/quote capture; sealed historical baseline; completed two-hour forward plumbing pilot | Is there enough valid, timestamped evidence to test a hypothesis? |
| Days 4–10 | One frozen flow hypothesis; a matched return/volatility/volume control; sign/time placebo; controlled quote/abstain game against scripted best responses | Is there an incremental forecast or incentive effect worth prospectively testing? |
| Days 11–20 | Untuned forward observations under the frozen hypothesis, all abstentions and data gaps retained | Does the result survive data that was unavailable at design time? |
| Days 21–30 | Cost sensitivity, day-clustered uncertainty, independent-period or venue check, negative/unknown/pass report | Continue research, reject the hypothesis, or justify a separately reviewed fill-aware paper trial. |

The implemented REST reference pilot is an engineering calibration with fixed,
unfitted coefficients. It cannot estimate cancellations, latent trader inventory,
or a causal strategic response from five-minute snapshots. Its result must not
be promoted to executable paper trading. A subsequent fill-aware study needs
sequence-validated book updates, decision-before-quote evidence and explicit
latency, depth and cost assumptions.

For the scientific track, prioritize a bounded quote-versus-abstain game with
known spread reward, adverse-selection loss and inventory penalty. Compare the
model's decisions with the analytical or scripted best response under exactly
the same observations. A model that fails the controlled payoff test should not
be used to explain real-market strategic behavior. Three 32-cell Gemma development arms were completed and replayed.
The original JSON-only prompt yielded 0/32 strictly valid actions; explicit
raw-JSON wording yielded 32/32 valid actions but only 17/32 optimal choices.
Enabling thinking with a larger cap yielded 0/32 valid actions and substantial
text in the content channel, with 23 calls at the cap. See
[the controlled-game results](CONTROLLED_GAME_RESULTS.md). Formatting, arithmetic,
and incentive response need separate validation before explaining trader behavior.

## Where to follow progress

Use **Now** (`/`) for the active model cards and the supervised research-window
status. Use **Operations → Benchmark progress** (`/benchmarks`) for weekly
maintenance, the one-time local-model A/B, admitted follow-on studies, and the
market-research collection/reference stages. **Research** (`/ladder`) remains
the separate scientific evidence ladder; **Calls** (`/model-io`) is request
history. Refresh records to re-read admitted artifacts. A pending or absent
result is not a zero score.

The one-time model R&D does not consume the recurring weekly maintenance
allowance. The historical baseline and the forthcoming REST pilot are also
separate from week-to-week model-regression scores. This keeps infrastructure
health, apparatus quality, scientific claims and market reference outcomes
legible as different kinds of progress.

## Evidence and implementation entry points

- [Original paired aggregate](/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/evaluation/aggregate-summaries/qfn-ab-mia-c0-20260915-a.json).
- [Final optimized coding/decode report](/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/evaluation/followon-reports/qfn-followon-coding-temp1-20260915-b.flash/report.md); its index binds raw results, immutable source, independent replay and restoration.
- [Historical baseline publication](/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/applied-trading-public-data/publications/fixed60-BTCUSDT-v1.json) and [future H1 plan publication](/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/applied-trading-public-data/publications/h1-rest-h1-btcusdt-rest-20260915-144919.plan.json).
- [Research pipeline audit](PIPELINE_AUDIT.md), [cited trading-research strategy](TRADING_RESEARCH_PLAN.md), [statistical limitations](HISTORICAL_SCORE_LIMITS.md), and [controlled-game protocol](NEXT_AGENT_GAME.md). The audit is explicitly a 07:15 snapshot; later operational evidence in this report supersedes its execution status.
- [EVIDENCE.json](EVIDENCE.json) inventories exact receipt paths and SHA-256 values. Private raw model streams and prediction rows stay in the local artifacts tree; this note publishes no model reasoning.

The frozen original-pair, 39-source follow-on and 42-source final diagnostic
worktrees remain evidence dependencies. They are not candidates for ordinary
dead-code cleanup until their source inventories have a verified portable
archive and the readers no longer need their original locations. Public
changes use the isolated follow-on branch; the canonical checkout's private
history is not pushed.

## Validation and current operational boundary

The final UI projection passed 23 backend and six frontend tests plus
TypeScript/Vite build. Capture/continuation/collector checks passed 28 tests;
feature/lifecycle/reference-driver checks passed 18. Ruff and diff checks
passed. An independent agent reviewed the cap/source-pin changes. A CPU-only
500,000-event synthetic feature derivation took 1.46 seconds and approximately
234 MiB peak RSS with mocked source validation/compact payloads; it is a
capacity estimate, not full due-service performance proof.

The 32-page and 500,000-event limits still permit an honest incomplete/unknown
outcome under heavier traffic. No failed cursor is reused. The old capture
state was archived by exact SHA acknowledgement, and the new lineage makes
no continuity claim across the interruption. Future study outcomes are not
known tonight. Source-bound final integration and restart receipts are under
`a_bgt_rsi_v2_artifacts/2026-09-15/overnight-final-results-integration/`.
