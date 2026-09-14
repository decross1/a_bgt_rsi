# Raw Claude adversarial reviews

**Status:** Unedited model outputs retained for audit. These contain retracted errors and stale assumptions, including the claim that the existing agenda cron is inactive. They are not implementation instructions. Read [REVIEW_RECORD.md](REVIEW_RECORD.md) for dispositions and the [canonical handoff](CODEX_RESEARCH_HANDOFF.md) for the final design.

## Round 1 — independent critique

# Independent Critique — Weekly Inference/Runtime Upgrade Loop

Reviewer: Claude (independent pass, no tools, no external verification). All model-version, throughput, and dataset-size numbers in the proposal are treated as *unverified claims*, not facts. Statements about the local checkout (`frontier_cli.py`, `frontier_review.py`, `frontier_agenda.py`, weekly shell, sentinels, subscription-only auth stripping) are treated as *reported project facts* per the handoff; I have not read the files myself.

---

## 1. Verdict and top 10 flaws

**Verdict:** The proposal is a plausible skeleton for a *research-agenda* loop, but as an *infrastructure upgrade loop* it is not yet a scientifically valid instrument. The core failure mode is category confusion: it conflates (a) generating hypotheses about better runtimes/weights, (b) measuring them under conditions that would justify a swap, and (c) actually swapping. Adopting it as written would produce weekly motion, weekly PRs, and weekly-looking "improvements" whose statistical basis is too weak to distinguish real gains from selection/peeking noise. Ship a much smaller v0 that lets *NO_CHANGE* be the honest default and that keeps candidate weights, quantization, runtime, and sampling on strictly separated axes.

**Top 10 flaws that would invalidate conclusions or stall delivery:**

1. **Unverified capability claims treated as design inputs.** Gemma4-26B-A4B NVFP4/MARLIN/MTP4 in vLLM 0.21, Qwen3.8-27B NVFP4+FP8-KV at 0.30 mem-util each, and 64–78 tok/s SGLang/DFlash2 through 65K are asserted, not measured on the local Spark. Any policy built on them (co-residency, 64K tier, best-of-3 budgets) inherits their falsehood risk.
2. **Best-of-3 accounting is under-charged.** If candidate generation, selector overhead, retries, judge calls, and serialization aren't all charged to `tasks/device_wall_clock`, best-of-N will spuriously beat single-shot at 2–3× the true cost. The metric must be end-to-end wall-clock including failed candidates and validator time.
3. **RSR (repeat-success rate) 2/3 hides production 3/3 risk.** RSR@k=2/3 is a *lower* bar than deployment reality; you want RSR@k as a *distribution*, plus a distinct "reliable" cut requiring k/k. Report both, and never let 2/3 satisfy a promotion gate meant to protect production.
4. **20–40 private bug tasks cannot support a tight noninferiority claim.** With p≈0.5, the 95% CI half-width is ~15–22 pp. Any "≤2 pp regression" gate on n=20 is theatre. Either widen the margin, pool across weeks with pre-registered pooling rules, or restrict the claim to "we did not observe a large regression."
5. **Repeated weekly profile selection = uncontrolled multiple comparisons.** Choosing among many profiles every week without alpha-spending or a holdout budget guarantees false "winners." No mention of pre-registration alpha, family-wise error control, or a sequential design (e.g., group-sequential / always-valid CIs).
6. **Correlated seeds on the same task are counted as independent.** Bootstrap or cluster-robust SEs at the *task-family* level are required; treating N seeds × M tasks as N·M i.i.d. trials overstates power dramatically.
7. **Failure censoring biases "time-to-success."** Only successful runs contribute latency; slow-successes and censored-failures both bias upward. Report a Kaplan–Meier-style estimator or a joint success×latency metric (e.g., expected time-to-first-success with failures assigned a penalty cap).
8. **Cross-provider judges are not independent.** OpenAI ↔ Claude judges share training corpora, RLHF conventions, and stylistic priors; agreement is not evidence of correctness on scientific content. Ground truth or human adjudication is required at least on a rotating sub-sample, and judge disagreement should trigger abstention, not majority vote.
9. **Changing the evaluation suite weekly destroys comparability.** ScienceAgentBench / CORE / ResearchBench / PaperBench rotation guarantees that week-over-week deltas mix suite change with system change. A *frozen* core suite must anchor all cross-week comparisons; rotating suites are exploratory only and cannot gate promotion.
10. **Delivery preflight is fragile and already broken locally.** The `npm`-installed `claude` shim failing on a missing native binary while `/usr/bin/claude` works, plus a Codex home whose model/effort pin may be stale, means the loop can silently execute against the *wrong* subscription runtime. Without a preflight that pins resolved binary path + version + auth mode + model id and refuses to run otherwise, all weekly evidence is untrustworthy at the source.

Honorable mentions: 64K context is a tokenizer-dependent tier (Gemma vs Qwen tokenizers differ, so "32K" and "16K" caps are not directly comparable); "temp=0 for determinism" is false across kernels/hardware and for tool-argument JSON stability; "fails open per unavailable vendor" is dangerous if it means silently degrading — NO_CHANGE must be *explicit* and *typed*, not a fall-through.

---

## 2. Minimum useful one/two-session scope

**In scope for v0 (one working session, maybe a second for tests):**

- **Preflight & provenance module.** A single `preflight()` that records: resolved CLI path, `--version`, auth mode (subscription vs API), model id, quantization tag, runtime version, git SHA of the harness, dataset SHAs, and a hash of the resolved sampling profile. Refuses to run if any field is missing. Writes an immutable JSON to `runs/<utc>/manifest.json`.
- **Named sampling profiles as data.** `profiles.yaml` with `deterministic`, `coding`, `scientist`, `explore`, `critic`. Loader validates against a schema *per model adapter*; unknown fields for a given model fail closed. Every call logs the *fully resolved* profile actually used, not the requested one.
- **Frozen core benchmark v0.** ~30 items total: 10 tool-use cases, 10 private-repo bug tasks, 10 game-theory synthetic-truth items (see §3). Fixtures pinned by SHA. Hidden graders and reference solutions live behind a directory the optimizer cannot read; enforced by a filesystem gate, not a convention.
- **Controller with explicit `NO_CHANGE` typing.** Enum: `NO_CHANGE_INTENTIONAL`, `NO_CHANGE_NO_PROVIDER`, `NO_CHANGE_NO_BUDGET`, `NO_CHANGE_INVALID_EVAL`, `NO_CHANGE_INSUFFICIENT_EVIDENCE`. The default outcome is `NO_CHANGE_INSUFFICIENT_EVIDENCE`.
- **Subscription-only mode wired end-to-end.** API mode is *stubbed and disabled* by a feature flag defaulting off; no code path can invoke a billed API without an explicit `--allow-api-billing` argument and a printed cost estimate.
- **Two-tier separation.** Candidate *evaluation* is authorized; candidate *promotion to the live agenda runtime* requires a separate `promote` command with a distinct gate. Research work continues on the incumbent regardless of eval status.

**Explicitly out of scope for v0 (must be later, in writing):**

- New weights (Gemma4/Qwen3.8) evaluation.
- Co-resident memory experiments and MTP tuning.
- SGLang / DFlash2 runtime comparison.
- 64K context tier evaluation.
- Best-of-N and multi-judge panels.
- ScienceAgentBench / CORE / ResearchBench / PaperBench integrations.
- Any cron scheduler activation. The weekly shell stays dark.
- Any code path that could produce a paid API call.

The v0 goal is *not* to pick a winner. It is to make future picks credible.

---

## 3. Concrete game-theory / research function tests (8)

Each test lists: input spec, objective grader, failure/trap, acceptance, example fixture. All are deterministic-graded; no human coursework.

**T1. Nash equilibrium enumeration on a 3×3 bimatrix.**
- Input: two 3×3 payoff matrices as JSON.
- Grader: exact-match on the set of NE (mixed strategies to 1e-3) against Lemke–Howson reference.
- Trap: fixture includes a game with a *unique* mixed NE and no pure NE; models that only report pure fail.
- Acceptance: exact set match; abstention allowed with penalty 0.5.
- Fixture: `matching_pennies_3x3.json` with computed NE `[(1/3,1/3,1/3),(1/3,1/3,1/3)]`.

**T2. Iterated elimination of strictly dominated strategies (IESDS).**
- Input: n×m payoff matrix + player index.
- Grader: reduced game must equal reference reduction; order-independence must hold.
- Trap: a *weakly* dominated strategy included; wrongly eliminating it is a fail (tests knowledge of the strict/weak distinction).
- Acceptance: reduced-matrix hash match.
- Fixture: 4×4 with one strictly and one weakly dominated row.

**T3. Behavioral-game-theory fit: QRE λ recovery.**
- Input: choice-frequency data from a 2×2 game.
- Grader: recovered λ within ±10% of the value used to generate the synthetic data; log-likelihood within ±0.05 of oracle.
- Trap: dataset generated with λ=0 (uniform); model must not report a large λ from noise.
- Acceptance: numeric tolerance + correct qualitative statement ("cannot distinguish from uniform").
- Fixture: 500 synthetic trials, `lambda_true=1.2`.

**T4. Falsification of a flawed hypothesis.**
- Input: a hypothesis + a small dataset that *superficially* supports it but is confounded (e.g., Simpson's paradox on cooperation rate by group size).
- Grader: model must (a) identify the confound, (b) propose a stratified re-analysis, (c) state the flipped conclusion.
- Trap: dataset also includes a *valid* hypothesis in a parallel item; a critic that rejects everything scores 0 on the valid item.
- Acceptance: structured rubric with three boolean sub-scores; ≥2/3 required.
- Fixture: `simpson_cooperation.csv` with pre-computed stratified means.

**T5. Repeated-game strategy identification.**
- Input: a transcript of 50 rounds of iterated PD play by two anonymized strategies.
- Grader: classify each as one of {AllC, AllD, TFT, GTFT, WSLS, Grim, Random} using a fixed decision rule on transition frequencies; graded by confusion-matrix diagonal match.
- Trap: one player is *noisy TFT* (5% error); must not be labeled Random.
- Acceptance: ≥6/7 correct across fixture set.
- Fixture: `ipd_transcripts_v1/` with ground-truth labels.

**T6. Citation faithfulness / abstention.**
- Input: a claim + a set of 5 short passages, only 2 of which support it, 1 of which contradicts it, 2 irrelevant.
- Grader: precision/recall of cited passage ids; contradicting passage must be acknowledged; abstention if support is weak.
- Trap: one supporting passage is a paraphrase whose *conclusion* is opposite (surface similarity, semantic mismatch).
- Acceptance: F1 ≥ 0.8 on citations *and* contradiction flagged.
- Fixture: 20 items, hand-labeled.

**T7. Reproducibility check on a small simulation.**
- Input: a Python snippet claiming a result (e.g., mean cooperation rate under moran dynamics).
- Grader: model must run/inspect, report the observed number, and flag mismatch with the claim; oracle number is fixed.
- Trap: snippet has an off-by-one in the update loop that shifts the mean by ~7%.
- Acceptance: numeric report within tolerance of true value + bug identified.
- Fixture: `moran_offbyone.py` + `oracle.json`.

**T8. Experiment design under a budget.**
- Input: a research question ("does communication increase cooperation in n-player PD?"), a budget (e.g., 200 subject-rounds), and a menu of design knobs.
- Grader: rubric on (a) identified confounds, (b) power estimate present and roughly correct given effect-size assumption, (c) preregistered primary outcome, (d) stopping rule.
- Trap: obvious cheap design has zero power at stated effect size; models that pick it fail (a) and (b).
- Acceptance: ≥3/4 rubric points, machine-graded by structured JSON output schema.
- Fixture: `comm_pd_design_v1.json` with expected fields.

Two optional add-ons if time permits: **T9** minimax regret vs Bayes-optimal action on a decision under ambiguity; **T10** identification of a data-leakage flaw in a described ML-in-games pipeline.

---

## 4. Smallest credible weekly experiment

**Design:** Paired task families, pre-registered, incumbent vs a *single* candidate change on *one* axis (weights XOR quantization XOR runtime XOR sampling XOR scaffold). No multi-axis weeks in v0.

**Sample:** From the frozen core suite, use 30 items. Each item is run k=5 times per system with a *fixed seed schedule* pre-committed before candidate selection. Pairing is by item; the unit of analysis is the item-level mean success.

**Primary metric:** Δ = mean(item_success_candidate) − mean(item_success_incumbent), where item_success is `(#successes)/k` including failures and timeouts. Failures charged; no censoring.

**Secondary metrics:** RSR@5 distribution (report full histogram, not just ≥2/3); tasks-per-device-hour including all overhead; abstention rate; citation F1 on T6-class items.

**Statistical test:** Paired bootstrap (10k resamples) over items, cluster-resampling at *task family* (T1–T8 groupings), reporting a 90% CI on Δ. No p-value gates.

**Honest thresholds:**
- Promote only if the 90% CI lower bound on Δ ≥ +0.05 *and* the RSR@5 5th-percentile does not drop by >0.10 vs incumbent *and* tasks/device-hour is within 0.8× incumbent.
- Otherwise: `NO_CHANGE_INSUFFICIENT_EVIDENCE`.

**Power reality check:** With n=30 items paired and per-item SD ≈ 0.2, minimum detectable effect at 80% power is roughly ΔMDE ≈ 0.10. Anything below that will be under-powered; we accept this and *do not* pretend to detect small gains. The loop's honest job is to catch *large* wins and *large* regressions.

**Multiple-comparisons control:** A weekly alpha budget is spent only when the CI-based gate triggers a promotion decision; exploratory metrics are labeled and not eligible for promotion. Pre-register the candidate axis and the exact profile *before* seeing this week's runs.

**Compute budget:** Cap at 2 Spark device-hours + 0 USD API by default. If a week's plan exceeds cap, the controller returns `NO_CHANGE_NO_BUDGET` and archives the plan for a later week.

---

## 5. Bounded weekly controller state machine

States (each writes an immutable event to `runs/<utc>/events.jsonl`):

1. **SNAPSHOT** — Freeze git SHA of harness, dataset SHAs, incumbent config hash. Preflight all runtimes; if preflight fails → `HALT(reason=preflight)`.
2. **SCAN** — Passive scan of local `CHANGELOG`/notes only. No network. Emits a candidate list of *at most one axis change*.
3. **PROPOSE** — For each of {OpenAI-cli-subscription, Claude-cli-subscription}, request a written proposal *and* a written falsification of the other side's proposal. Both are stored verbatim.
4. **SYNTHESIZE** — Deterministic rule: keep only claims where both proposers *disagree in falsifiable ways*. If none, → `NO_CHANGE_INSUFFICIENT_EVIDENCE`.
5. **PREREGISTER** — Emit a signed JSON with candidate axis, profile, metric definitions, seeds, gate thresholds. Once written, immutable.
6. **CANARY** — Run 3 cheap items on both systems; if candidate errors on ≥1 or exceeds latency cap → `NO_CHANGE_INVALID_EVAL`.
7. **EVALUATE** — Full paired run per §4. Enforce compute cap; overrun → `NO_CHANGE_NO_BUDGET`.
8. **DECIDE** — Apply gates from §4 to produce `PROMOTE_RECOMMEND` or one of the typed `NO_CHANGE_*` outcomes. This is a *recommendation*, not an execution.
9. **DELIVER** — Under standing authorization, open a PR containing: manifest, preregistration, results, and (if `PROMOTE_RECOMMEND`) a config diff on a *shadow* branch. The main runtime is untouched.
10. **SHADOW** — Candidate runs in parallel on live research traffic in read-only mode for a fixed window (e.g., next N tasks or 24h device-time). Metrics diff'd against incumbent.
11. **PROMOTE (separately gated)** — Requires an explicit human `promote` command. On promotion, incumbent config is archived and rollback command is generated and printed.
12. **ROLLBACK** — Single command reverts to the archived incumbent config; controller refuses to propose changes on the same axis for one cycle.

**Actual execution vs recommendation:** Steps 1–9 execute autonomously under standing authorization. Step 11 requires an explicit human action. Step 12 executes autonomously when triggered by either a human command or automated regression detection on shadow.

**Fail-closed promotion, research continues:** Any failure in steps 1–8 halts *promotion* only; the research-agenda runtime keeps serving on incumbent config. The controller must never block the researcher's day-to-day work to run its own evaluations — evaluation runs are scheduled against the 2-device-hour cap in a window that does not preempt user tasks.

**Integration points:**
- `agent_wrapper/frontier_cli.py` — controller calls it for subscription CLI invocations; env stripping preserved.
- `workers/frontier_review.py` — its methods/novelty falsifiers reused for T4/T6-class grading; not modified in v0.
- `orchestrator/frontier_agenda.py` — remains inert; controller does *not* consume its proposed topics as inputs to promotion decisions.
- `cron/weekly-frontier-agenda.sh` — stays dark. Controller is invoked manually in v0. Sentinels `frontier_tos_ratified` and `pause_frontier` are honored.

---

## 6. Disagreements with the proposal and what would resolve them

**D1. Best-of-3 as default.** Disagree that best-of-N is a scientific improvement rather than a budget reshuffle. *Resolution:* a fixed-budget experiment where single-shot at 3× tokens is compared head-to-head with best-of-3 on the same items; if single-shot wins or ties, drop best-of-N from defaults.

**D2. Co-residency at mem-util 0.30 each as a starting point.** Disagree with committing to co-residency before measuring KV-cache pressure at 32K/16K under realistic concurrency-1 tool-call traffic. *Resolution:* a memory/latency probe that plots p50/p95 latency and OOM incidence across mem-util grids {0.25, 0.30, 0.35, 0.40} at both single and dual residency.

**D3. 64K as a "capability tier."** Disagree that 64K is meaningful without tokenizer-normalized context packs. *Resolution:* generate matched context packs measured in *characters* and *both* tokenizers, and report success vs effective context in bytes, not tokens.

**D4. Temp 0 as a tool-calling default.** Disagree that temp 0 is universally best for tool arguments; some models produce more schema-valid JSON at small non-zero temps due to sampling-vs-argmax degeneracies. *Resolution:* per-model ablation on T-tool cases across {0, 0.1, 0.3}, choose per adapter.

**D5. Cross-provider judges as validators.** Disagree that OpenAI/Claude judge agreement is sufficient. *Resolution:* on a 20-item rotating sub-sample, add human adjudication and compute judge-vs-human κ; only use judges on categories where κ ≥ 0.6.

**D6. Rotating science suites gating promotion.** Disagree. *Resolution:* freeze the core; rotate only in an *exploratory* lane whose results cannot promote.

**D7. Weekly cadence.** Disagree that weekly is the right period given n=30 and MDE≈0.10. *Resolution:* run bi-weekly or pool two weekly runs before applying the promotion gate; use always-valid CIs if truly weekly.

**D8. "Fails open" on unavailable vendor.** Disagree strongly. *Resolution:* replace with typed `NO_CHANGE_NO_PROVIDER`; never let missing vendor produce a silent single-provider decision.

**D9. Codex model/effort pin drift.** Not a disagreement so much as a gap: without a pinned, preflighted Codex model id, every weekly run is on an implicitly changing system. *Resolution:* record and gate on the pin; refuse to run if pin is unset or older than a declared floor.

**D10. Treating the research-agenda mechanism as an infra loop.** Agree with the handoff's own warning and want it emphasized: `frontier_agenda.py` proposes *research topics*, not runtime upgrades. The upgrade controller must be a separate module with its own manifest, gates, and events log, sharing only the preflight and CLI-wrapper primitives.

---

**Bottom line.** Ship v0 as: preflight + provenance, named profiles as validated data, a 30-item frozen core suite, a paired bootstrap gate with an honest MDE, and a controller whose default output is a typed `NO_CHANGE`. Keep weights/quantization/runtime/context/scaffold on strictly separated axes; change at most one per cycle. Do not turn on the cron. Do not enable API billing paths. Everything else in the proposal is a legitimate research lead, not a v0 requirement.

---

## Round 2 — response to team cross-critique

# Second-Pass Revision — Adversarial Self-Review

Reviewer: same independent Claude pass, no tools, no external verification. All source-findings in the research-team evidence block are **reported verified by the research team**, not personally verified by me. I read them as claims I now build on, not facts I confirmed.

Below I separate what I got wrong in the first pass (RETRACT), what still holds (RETAIN), and what only an experiment can settle (RESOLVE_BY_EXPERIMENT). I then give a corrected minimum experiment and an honest read on how much of this belongs on automation.

---

## RETRACT

**R1. T1 as written — "Lemke–Howson enumeration on a 3×3 bimatrix" with an asserted unique-mixed-NE matching-pennies fixture.** A single Lemke–Howson pivot is not an enumeration of all NE, and I asserted uniqueness of a mixed NE on an unspecified 3×3 game. Retracted. Correct form: **grade feasibility and best-response regret against exact supplied matrices; use LP for zero-sum games (e.g., A = [[3,0],[1,2]] → row (0.25,0.75), column (0.5,0.5), value 1.5); use support-enumeration only for bounded non-degenerate games where completeness is truly required.** Include hidden permutation/scaling variants to defeat memorized answers.

**R2. T3 QRE — "recovered λ within ±10% from 500 noisy trials."** Retracted. At λ near zero the relative tolerance is undefined, and identifiability is not guaranteed on arbitrary generators. Correct form: **identifiable synthetic generative model; held-out predictive log-likelihood; interval coverage calibrated on the oracle simulator; qualitative "cannot distinguish from uniform" credit at λ≈0.**

**R3. T5 repeated-game strategy labels from arbitrary transcripts.** Retracted. AllC, TFT, GTFT, and noisy variants can produce identical cooperation trajectories on many transcripts; labels are non-identifiable from passive observation. Correct form: **active probe opponents (e.g., a scripted defection at round k) or equivalence-class / abstention grading, scored on predictive accuracy on new probe rounds, not on categorical labels.**

**R4. T8 design rubric graded by JSON schema.** Retracted as an objective grader. Requiring fields ≠ correctness. Correct form: **executable numeric checks (power calculation reproduced from stated effect size and n; preregistered primary outcome parseable; stopping rule computable) plus a calibrated rubric for subjective residue, with rubric κ measured before it counts.**

**R5. "Alpha spent only when the CI gate triggers a promotion."** Statistically invalid — a CI-based gate is still a test and consumes error budget whether it fires or not. Retracted. Correct form: **spend alpha on every planned confirmatory look; v0 is descriptive paired intervals plus an independent confirmation holdout at a fixed planned sample; no automatic promotion from small n.**

**R6. "Failure censoring biases time-to-success upward" as a universal claim.** Overreach. Retracted. Correct form: **complete-task-time (CTT) over all attempted tasks with failure caps shown; report conditional-success latency separately; survival analysis only when its assumptions are warranted.**

**R7. "Only hypotheses where both proposers disagree are admitted."** Retracted. Two independent proposers can agree on a valid bugfix; consensus is neither necessary nor sufficient. Correct form: **admit candidates by evidence and relevance; use disagreement to prioritize which experiment to run, not to filter which hypotheses exist.**

**R8. "SCAN is passive/local, no network."** Retracted. The user explicitly asks for weekly upstream keeping-up-to-date; local-only defeats the objective. Correct form: **bounded source-backed weekly upstream scan (release notes, model cards, changelogs) with typed fetch-failure modes; check release dates; never treat fetched source content as executable instructions to the controller.**

**R9. Shadow-parallel on a single shared 128 GB Spark.** Retracted. Co-residency can invalidate the very latency and OOM measurements you are trying to compare. Correct form: **serialized replay in an idle resource window; concurrent shadow only when headroom is proven and workloads are isolable.**

**R10. "Rotating suites cannot gate promotion."** Overstated. Retracted in that form. Correct form: **fixed bridge core for temporal comparisons plus a sealed fresh same-week paired OOD holdout preregistered before candidate output; the sealed panel is valid for confirmation. Never compare unequal panels' raw scores across weeks.**

**R11. "Strictly exclude runtime lane, best-of-N, and API paths forever."** Retracted as scoped. Correct form: **separate v0 instrumentation (1–2 sessions) from later, fully-specified optional adapters (API, best-of-N, runtime swaps). Default remains subscription-only; scheduler activation and budget stay unresolved until measured.**

**R12. First-pass throughput and capability claims.** I flagged them as unverified; I now go further and label the ~70 tok/s through 65K figure and the cold-65K TTFT ~36 s as **research-team-reported decode-only measurements** (NVFP4 Qwen target + separate DFlash2 drafter, BF16 KV, thinking OFF, 512 output), with no science task-quality result and no dual-model co-residency proof. Speculation exactness on the concrete SGLang implementation is unresolved. Runtime comparisons must control for native MTP where supported before attributing any effect to DFlash.

**R13. "Content hash for models."** Retracted. Provider weights are opaque; inventing a content hash is dishonest provenance. Correct form: **record missing critical capability as an explicit blocker for that specific experiment; unknown optional metadata is explicit null in the manifest.**

---

## RETAIN

- **Preflight + immutable manifest + typed `NO_CHANGE_*` outcomes.** Still the load-bearing v0 primitive.
- **Named profiles as data with per-adapter validation and UNSET override semantics.** Reinforced by the research-team-reported Qwen3.8-27B and Gemma4 cards: thinking T1/top_p 0.95/top_k 20/min_p 0/presence 0 (Qwen think), T0.7/top_p 0.8/top_k 20/presence 1.5 (Qwen non-think), xhigh default with medium/low effort tiers, preserve_thinking=true; Gemma T1/top_p 0.95/top_k 64, think on/off, no Qwen-style effort tiers, prior thought content removed. **Profiles are role-intent-plus-capability-mapped adapters, never generic effort strings.**
- **Best-of-N cost must be charged end-to-end** including selector, retries, and judge time.
- **RSR@k as a distribution**, not a single ≥2/3 threshold.
- **30 items ≈ MDE 0.10; no tight 1 pp CI gates.** No promotion from underpowered weeks.
- **Family-stratified bootstrap over genuinely independent generated instances**, not seed pseudoreplication. Eight family clusters is too few for reassuring bootstrap; report family separately.
- **Cross-provider judge non-independence** is real; κ-vs-human gating on a rotating sub-sample remains required before judges count.
- **Cron stays dark; no auto cutover; documents-not-activation this cycle.**
- **Standing authorization covers authorized maintenance, code, and PRs**, not production service cutover.

---

## RESOLVE_BY_EXPERIMENT

- **Co-residency at mem-util 0.30 each.** Grid {0.25, 0.30, 0.35} × {single, dual}, KV-cache pressure at 16K/32K under concurrency-1 tool traffic. Serialize; do not co-run the very benchmarks that measure interference.
- **Best-of-3 vs single-shot at matched compute.** Fixed-budget head-to-head; single-shot at ~3× tokens against best-of-3 selector, all compute charged.
- **Native MTP vs DFlash2 speculation** on identical prompts, thinking OFF, 512 output, before attributing throughput effects.
- **Judge-human κ on 20 rotating items.** Only enable judge scoring in categories where κ ≥ 0.6.
- **Tokenizer-normalized context tiers.** Report success vs effective bytes, not raw tokens, for Gemma and Qwen.
- **Fresh sealed same-week paired holdout** to test whether it materially changes decisions versus fixed-core-only.

---

## Corrected minimum credible experiment

**Design.** Paired incumbent vs one candidate change on one axis. Frozen 30-item core (10 tool, 8 game-theory/learning-in-games numeric, 6 balanced-critic, 6 code-seed). Pre-registered seed schedule, k = 5 per item. Add a sealed fresh 10-item OOD panel drawn from the same generators, sealed before candidate output, opened same week.

**Metrics.** Item-level success mean; RSR@5 distribution; CTT (all attempted tasks, failure caps shown); conditional success latency separately; abstention rate; citation F1 where relevant.

**Analysis.** Family-stratified paired bootstrap (10k) over items; 90% CI on Δ; report per-family Δ separately. Descriptive only in v0. No promotion decision from a single 30-item run.

**Honest limits.** MDE ≈ 0.10 on success rate; no claim of small-effect detection; no ≤2 pp non-inferiority language on n=30. Confirmatory promotion requires **incumbent vs candidate paired on the sealed OOD panel replicated across two cycles**, or a preregistered larger n.

**Compute cap.** 2 Spark device-hours per cycle. Overrun → `NO_CHANGE_NO_BUDGET`.

---

## Remaining fatal risks

1. **Silent runtime substitution.** Two `claude` binaries on the local box (research-team-reported: npm 2.1.270 broken on missing ARM native binary; /usr/bin/claude 2.1.143 works authenticated on Max subscription). Preflight must pin resolved path + version + auth + model id and refuse otherwise. This is what actually resolves claude-opus-4-7 for the current pass.
2. **Category confusion between agenda and upgrade.** Keep the upgrade controller a distinct module; agenda topics are not upgrade candidates.
3. **Overreading research-team-reported numbers as measured on our Spark.** They are third-party reproducible decode-only figures, not our system's behavior.

---

## How much should be automated near-term

**Automate now, under standing authorization:** preflight/provenance, source-validation table generation, weekly bounded upstream scan with typed failures, independent proposal + cross-falsification capture, preregistration writing, off-production eval runs, PR/patch preparation. These reduce, rather than consume, research time.

**Do not automate yet:** promotion, cron activation, API billing paths, co-residency changes, runtime swaps, dataset rotation gates. Each requires either a measured prerequisite above or explicit human action.

**Rule of thumb:** the loop should return a Markdown handoff and a draft PR most weeks and `NO_CHANGE_INSUFFICIENT_EVIDENCE` on the rest. If it ever returns a promotion recommendation on 30 items alone, the loop is wrong, not the world.