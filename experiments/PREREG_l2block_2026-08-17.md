# Pre-registration — L1→L2 synthetic experiments (block of 2026-08-17)

Status: exp010 and exp011 **LOCKED at commit time** after adversarial critique
(`wf_2f651b79`, 3 critics, all FIX-REQUIRED; every required fix applied below
and noted in each section's "Amendments from critique"). exp012 is a **v2
redesign** (the critic proved v1's positive outcome was manufacturable in
closed form from its own constants); v2 LOCKS only after a second critique
returns SOUND — its build starts then, never before. Decision rules are final
at lock — any later change is a new dated amendment section, never an edit
(inviolate rule 4).

Owner authorization: 2-hour autonomous block, 2026-08-17 02:41Z ("start the
block" + "do as much work as you can"). Design basis: grounding `wf_2c484eb9`.

Common commitments (all three experiments):
- Synthetic tier, algorithmic agents, pure-Python/numpy(/scipy.stats) — zero
  LLM calls per trial. The claims are classical game-theory claims; LLM-agent
  variants are the natural future L3 cross-tier comparison, not this rung.
- trials.jsonl one row per trial; errors/non-convergence recorded, never
  coerced; per-trial seeds derived from the base seed (exp009 pattern).
- analyze.py carries the decision rule as module constants copied verbatim
  from this document; `Verdict=YES/NO.` on summary line 1; machine-readable
  results/summary.json (exp004 pattern) plus summary.md.
- loop_bridge.py per exp003 contract: LOOP_V0_CALLS_LOG set at module load,
  `build_experiment_outcome()` returns {experiment_id, metric, value, summary,
  results_path, trials, effect_confirmed}; bridged via
  run_iteration(topic, source="human_cli", experiment_outcome=...).
- Ladder/ledger integration (wiring caveats from grounding): after each
  bridge lands its loop_memory row, the integrator appends `member_added`
  (new iteration id → the ORIGINAL cluster, before the next hourly
  consolidation founds a duplicate) and `evidence_level_changed` with the
  level `evidence_ladder.derive_level` actually returns — never hardcoded.
  On effect_confirmed=False the integrator appends `cluster_killed` with
  `kill_reason_from_experiment(outcome)` +
  `reopening_condition("experiment_rerun")`. A null result is a valid,
  publishable outcome of this block.
- The standing Qwen-panel refutations are named null hypotheses with LOCKED
  adjudication criteria inside each experiment's rules.

---

## exp010_audit_collusion — cl-iter-2026-07-13-001 — **LOCKED**

**Claim under test.** "Periodic audits increase collusion rates in
non-equilibrium markets because the predictability of the audit cadence
allows agents to synchronize deviations during high-probability oversight
gaps." (iter-2026-07-13-001, L1.) Operationalization scope: "non-equilibrium
markets" = learning dynamics not at stage-game equilibrium (Q-learning
transients + fined stage games), stated here so the L1-claim→L2-design
mapping is explicit.

**Environment.** Repeated 2-player pricing game, T=5000 rounds. Actions
{COLLUDE, DEFECT}; stage payoffs: (C,C)=(10,10); (D,C)=(15,2); (C,D)=(2,15);
(D,D)=(5,5). Auditor: on an audit round, EACH agent that played COLLUDE that
round is fined F=20 (own-action fine — symmetric across arms, so it cannot
confound the arm comparison). EV arithmetic on record: blind mutual collusion
earns 10 − 20/8 = 7.5/round > mutual defection 5; perfectly timed collusion
earns 9.375; COLLUDE on a known audit round is strictly dominated (−10..−18
vs +5..+15) — no arm is trivially dominated or dominant. Arms at equal
expected audit frequency 1/8:
- PERIODIC: audit every 8th round (deterministic, learnable phase);
- RANDOM: audit i.i.d. Bernoulli p=1/8;
- NONE: no audits (Q1-adjudication arm).

**Agents.** Independent tabular Q-learners (α=0.1, γ=0.95, ε-greedy,
ε: 0.20 → 0.01 with multiplicative decay 0.999 — floor reached by round
~2995, so the measurement window is a converged-ε window). State =
(rounds_since_last_audit capped at 7 — values ≥7 collapse to 7, giving BOTH
audit arms an identical 8×2×2 = 32-state space; PERIODIC loses nothing
because full phase information is counter 0–7, RANDOM loses nothing because
its hazard is memoryless — this removes the state-cardinality confound; ×
own last action × opponent last action). Counter convention (pinned): the
counter is rounds since the last audit, observed BEFORE action selection; it
is 0 on the round immediately after an audit, so in PERIODIC the audit falls
exactly on counter=7, and the fine enters that round's reward. Same agent
code in every arm; NONE uses counter ≡ 0.

**Metrics.** collusion_rate := fraction of the LAST 1000 rounds in which
BOTH agents played COLLUDE (grounding Qwen Q3: this is the operational
definition). timing_gap := mean(both-collude | non-audit round) −
mean(both-collude | audit round) over the last 1000 rounds, computed in the
PERIODIC arm AND identically in the RANDOM arm as a placebo control
(expected ≈ 0 there since audits are unpredictable at action time; a
materially positive RANDOM gap flags metric contamination — reported,
non-gating). Also reported, non-gating: per-arm means, fraction of seeds
with collusion_rate ≥ 0.5 (Q-learner bimodality visibility), and per-agent
collude-rate on audit vs non-audit rounds (distinguishes joint timing from
one-sided timing). Metric ceiling on record: a perfectly-timed PERIODIC pair
caps at collusion_rate ≈ 0.875 while blind RANDOM collusion can approach
1.0; rule 1 therefore effectively requires RANDOM ≤ ~0.825.

**Trials.** 40 seeds × 3 arms = 120 trial rows (trials=120 ≥ 30).

**Decision rule (LOCKED).** effect_confirmed = TRUE iff BOTH:
1. median collusion_rate(PERIODIC) − median collusion_rate(RANDOM) ≥ 0.05,
   AND one-sided Mann–Whitney U (PERIODIC > RANDOM, n=40 vs 40) p < 0.01;
2. mechanism gate: mean timing_gap over ALL 40 PERIODIC seeds (exact-zero
   gaps included) ≥ 0.10, AND one-sided Wilcoxon signed-rank p < 0.01.
Pre-committed phrasings: rule 1 without rule 2 → Verdict=NO, summary states
"level effect without the claimed timing mechanism". Rule 2 without rule 1 →
Verdict=NO, summary states "timing mechanism present without a level effect
— the claim as written (increase collusion RATES) is unsupported".
**Q1 adjudication (LOCKED, non-gating).** Q1 ("any monitoring reduces
collusion vs no-monitoring") is SUPPORTED iff median collusion_rate(NONE) −
median collusion_rate(arm) ≥ 0.05 with one-sided MWU p < 0.01 for BOTH
audited arms; REFUTED iff for NEITHER arm; otherwise MIXED — the label
written verbatim into the summary.

**metric/value.** metric="collusion_rate_gap_periodic_minus_random",
value=median gap.

**Amendments from critique** (`critic-exp010`, all applied): counter cap
12→7 (state-cardinality confound removal); counter timing convention pinned;
ε decay 0.9995→0.999 (floor now reached inside T); mechanism gate gains a
0.10 magnitude floor over all-40-seeds mean; Q1 adjudication got a locked
criterion; RANDOM-arm placebo timing_gap added; ceiling/bimodality/EV notes
put on record.

---

## exp011_matching_reconstruction — cl-iter-2026-07-15-001 — **LOCKED**

**Claim under test.** "An adversary can reconstruct the preference rankings
of a specific agent by observing the deviation in the resulting stable
matching when a small, targeted subset of agent preferences is perturbed."
(iter-2026-07-15-001, L1. The recorded DRIFT flag stands: novelty/critique
argued a different mechanism; this experiment targets the hypothesis text.)

**Environment.** Stable marriage, n=12 per side, uniform-random full
preference profiles, deterministic man-proposing Gale–Shapley. Target t = a
uniformly chosen receiving-side agent; t's true ranking hidden from the
adversary. Perturbation semantics (pinned): each query's perturbation is
applied to the ORIGINAL stated profile (perturbations never accumulate; at
most 2 proposer lists differ from baseline in any single mechanism run); a
perturbed list moves t to position 1 with the remainder in original order;
the unperturbed baseline matching is computed and shown to the adversary
once before query 1 — so observing the full perturbed matching is
informationally equivalent to the claim's "observing the deviation".

**Attack (pre-specified, two modes).**
- Mode 1, pairwise probes: to compare proposers (a,b) in t's ranking, set t
  at the top of both a's and b's lists (2 modified lists). If μ′(t) ∈ {a,b},
  the pairwise order is revealed (provably unbiased when it resolves: both a
  and b propose to t, and t keeps her best proposal). If μ′(t)=c ∉ {a,b},
  record the constraints c >_t a AND c >_t b (both provably proposed to t).
  A merge-sort schedule issues ≤ 33 comparisons at n=12.
- Mode 2, frontier-demotion probes (spends the otherwise-idle budget,
  ≥ 11 queries): promote candidate a (t to top of a's list) + demote the
  current known frontier man f (t to bottom of f's list) — still k=2 — on a
  fixed deterministic schedule targeting the largest constraint-unordered
  group. This attacks the structural ceiling (pairs below t's natural
  proposer frontier are unresolvable under Mode 1 alone).
Reconstruction = deterministic topological linear extension of ALL recorded
constraints; pairs left unordered by the constraint set are counted in
unresolved_pairs and scored as DISCORDANT-at-worst is NOT assumed — scoring
uses the expected tau over the uniform distribution of linear extensions,
computed exactly from the constraint DAG's unordered-pair count:
tau_scored = (concordant_known − discordant_known) / C(n,2), i.e. unordered
pairs contribute 0 (chance), never favorably.

**Trials.** 40 seeds (fresh profile + fresh target per seed); query budget
Q_max = 44 = ceil(n·log2 n); attack may terminate early (metrics computed at
attack termination, queries_used ≤ 44). Per-trial diagnostic recorded:
rank_t(best natural proposer) from the baseline run; tau reported stratified
by it (shows where the frontier ceiling bites).

**Metrics.** kendall_tau (scored as above); queries_used; unresolved_pairs;
bits_per_query := total pairwise constraints recorded (~1 bit each) /
queries_used, reported against the log2(12!) ≈ 28.9-bit requirement;
deviation_size := number of receiving-side agents whose partner differs from
baseline, recorded per query, median reported — this directly tests the
refutation's O(k)-bits-per-observation premise. info_yield retained as a
sanity check only (it sits near 1.0 by construction). Chance baseline:
100-permutation null tau draw per trial. Noted for the record: no
random-perturbation control arm tonight (the 2026-08-15 frontier methods
review asked for one); the summary must state its absence.

**Decision rule (LOCKED).** effect_confirmed = TRUE iff BOTH:
1. median kendall_tau ≥ 0.90 at attack termination within Q ≤ 44 and
   perturbations of ≤ 2 lists per query;
2. ≥ 90% of trials reach kendall_tau ≥ 0.80.
**Verdict=NO attribution (LOCKED).** The summary MUST attribute failure from
recorded diagnostics: (i) budget-limited — constraints still accruing in the
final 5 queries — consistent with the panel's query-complexity refutation;
or (ii) attack-limited — unresolved_pairs plateaued with idle budget
remaining — adjudicating NEITHER the claim nor the refutation. exp011 counts
as evidence FOR the refutation only in case (i).

**metric/value.** metric="median_kendall_tau_at_termination", value=median
tau.

**Amendments from critique** (`critic-exp011`, all applied): constraint
harvesting from non-{a,b} outcomes (c >_t a, c >_t b); Mode-2
frontier-demotion probes added (the one fix with real build cost — without
it the bottom ~2/3 of the ranking is structurally unreachable and NO is
predetermined); unresolved-pair scoring made implementable and
chance-neutral; baseline-vs-cumulative perturbation semantics pinned;
bits_per_query and deviation_size defined; dead adjudication branch replaced
with the two-case attribution rule; early-termination wording; frontier-rank
stratification.

---

## exp012_lqg_spectral — cl-iter-2026-08-15-002 — **v2, LOCKS ONLY ON A SOUND RE-CRITIQUE**

**Claim under test.** "Bounded rationality, modeled as a constraint on the
precision of belief updating, slows the convergence rate of
communication-control strategies in partially nested LQG games specifically
when the spectral radius of the information structure's adjacency matrix
exceeds a critical threshold." (iter-2026-08-15-002, L1.)

**Scope limit (binding on the summary and ledger events).** This environment
is a linear belief-best-response contraction surrogate — it is NOT an LQG
game (no state dynamics or cost matrices) and NOT partially nested (the
sweep requires cyclic digraphs; genuinely nested/acyclic structures have
adjacency spectral radius exactly 0, degenerating the claim's threshold
quantity — this degeneracy is itself recorded as a finding about the claim's
framing). Any Verdict binds to the surrogate; the evidence_level_changed /
cluster event must carry this scope limit verbatim.

**Why v2.** The v1 design (additive Gaussian belief noise + fixed ε-band
convergence) was refuted pre-lock: its "threshold" was computable in closed
form from ε/σ_b geometry (ρ_floor ≈ 0.09·(1/0.7), below the whole sweep —
every bounded cell would cap), and dithered additive noise cannot change a
linear map's transient rate at all, so any YES was an artifact by necessity.
v2 adopts the critic's quantization-only swap and replaces band-entry timing
with settling/fixation detection, which has no band geometry to fake.

**Environment (all constants pinned).** N=8 agents; b_i ~ U[−1,1] i.i.d.
per seed; θ_0,i ~ U[−1,1] i.i.d. per seed; directed Erdős–Rényi graph
p=0.35, no self-loops, drawn fresh per seed; if the drawn digraph's
pre-rescale spectral radius < 1e−6 (acyclic instance), redraw and log the
redraw count. Information matrix M = A · (ρ_eff / ρ(A)), with the REPORTED
sweep variable ρ_eff := ρ(M) ∈ {0.21, 0.32, 0.42, 0.53, 0.63, 0.74, 0.84}
(every value < 1: the classical instability boundary is outside the sweep by
construction). Synchronous update, no separate damping factor:
θ_{t+1} = b + M · belief(θ_t).
- FULL arm: belief = identity. Deterministic linear contraction; θ* =
  (I − M)^{-1} b by direct linear solve (never the empirical limit).
- BOUNDED arm (quantization-only, σ_b = 0): belief_j = Q_Δ(θ_j) with
  Δ = 0.05, Q_Δ(x) = np.round(x/Δ)·Δ (ties-to-even, deterministic). The
  precision constraint is the quantizer — deterministic quantized dynamics
  can exhibit genuine deadband/limit-cycle behavior with real structure
  dependence; nothing is dithered into linearity.

**Convergence/settling criterion (band-free).**
- T_full := first t with ‖θ_{t+1} − θ_t‖∞ < 1e−6 (pure geometric decay —
  deterministic and guaranteed).
- T_bounded := first t with θ_{t+1} EXACTLY equal to θ_t (fixation of the
  deterministic quantized map). Cycle detection: the trajectory of quantized
  belief vectors Q_Δ(θ_t) is tracked in a hash set; a revisit without
  fixation ⇒ limit cycle ⇒ T_bounded := t_max = 20000, row flagged
  cycling=true (recorded, never dropped). No ε-band exists in the bounded
  arm, so no noise/deadband-floor artifact can manufacture the threshold.

**Trials.** 30 seeds × 7 ρ_eff values × 2 arms = 420 trial rows.

**Closed-form null on record (H0_construction).** The naive deadband
prediction is T_pred_bounded(ρ) ≈ ln(e_0 / r_dead(ρ)) / (−ln ρ) with
r_dead(ρ) = ρ·(Δ/2)/(1−ρ) — SMOOTH in ρ, no breakpoint. analyze.py must
compute and report max_ρ |log R_observed(ρ) − log R_pred(ρ)| and plot both;
a genuine threshold is a departure from this smooth prediction. This is the
experiment's explicit adjudication of "the threshold is your construction's
geometry".

**Decision rule (v2 — final wording subject only to the re-critique gate).**
R(ρ) := median T_bounded(ρ) / median T_full(ρ). effect_confirmed = TRUE iff
ALL of:
1. a continuous two-segment piecewise-linear fit of the 7 (ρ_eff, log R)
   MEDIAN points (n=7 in BIC; k=4 vs k=2 parameters, penalty 2·ln 7) beats
   the single-line fit by ΔBIC ≥ 10;
2. fitted breakpoint interior: 0.32 ≤ ρ* ≤ 0.74, AND the two grid cells
   immediately above ρ* each have < 50% capped/cycling trials in the bounded
   arm (the decisive upper slope must come from uncensored cells);
3. slope above ρ* ≥ 2.0 (log R per unit ρ_eff) AND ≥ 3× max(slope below,
   0.25);
4. stability: seed-level bootstrap B=1000 (resample seeds within each
   (ρ, arm) cell, recompute medians, refit rules 1–3): rules 1–3 hold in
   ≥ 90% of resamples AND bootstrap IQR of ρ* ≤ 0.15.
Reported non-gating: median R over cells below ρ* (the claim's "specifically
when" implies ≈ 1 there); raw fitted ρ* and per-rule pass/fail in
summary.json regardless of verdict.

**metric/value.** metric="slowdown_breakpoint_rho_eff", value = fitted ρ*
(or −1.0 on Verdict=NO — never a fabricated threshold; raw fit still in
summary.json).

**Amendments from critique** (`critic-exp012` v1 critique, applied in this
redesign): quantization-only swap (their proposed alternative); fixed-band
criterion replaced by fixation/cycle detection; every free constant pinned
(no damping, θ_0, b, quantizer, θ* solve, per-seed graph, acyclic redraw);
BIC sample pinned to the 7 median points; interior window tightened
0.35–1.10 → 0.32–0.74 (ρ_eff) + uncensored-cells requirement; slope rule
gains absolute floor 2.0 and denominator floor 0.25; bootstrap stability
rule added; closed-form smooth-prediction null added; scope-limit note
binding the verdict to the surrogate; dead full-arm exclusion clause
removed (full arm converges deterministically).

---

## Execution plan after lock

1. Build exp010 + exp011 immediately (workflow build agents, disjoint dirs +
   own tests; done-condition = own tests green under MOCK_LLM=1); exp012 v2
   re-critique runs concurrently; exp012 builds only on SOUND.
2. Serial integration (primary session): tier_registry _TIER_MAP entries
   (synthetic), test_experiment_log_isolation HARNESSES additions, suite.
3. Real runs (numpy; minutes), analyze, verdicts.
4. Bridges --live (env -u MOCK_LLM, Gemma resident): one run_iteration per
   experiment; then ledger events per Common commitments.
5. Run-log rows throughout; session-note + commit at each milestone. Hard
   stop 04:42Z: whatever is unfinished is reported honestly, never rushed
   past a gate.
