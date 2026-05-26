# Current day — day_7: first synthetic-tier experiment + retrospective

_Active-day tracker. Authoritative plan: `plan.yaml`. State:
`run_state/week1.state.json`. Run log: `run_state/week1.run.jsonl`._

> **TRANSITION (2026-05-24).** Day 7 is fully closed. `state.current_day`
> has advanced to `day_8`; `human_gates_pending` is empty. The
> publication-review gate cleared under **D-028** (no-publish-standalone
> disposition — the Day-7 result aggregates into a broader future
> publication). The next Track A session opens Day 8 against
> `notes/day8_agenda.md` and `PHASE_1_ROADMAP.md` §5.1.

> **Slip banner.** Day 7 bled into Day 7.1 → 7.2 → 7.3 (three
> declared slips on a hard-gate validation failure that turned out
> to be a genuine finding). All slips resolved at 7.3;
> `state.current_subday` cleared on slip_resolved. Slip mechanism:
> [`PHASE_1_ROADMAP.md`](PHASE_1_ROADMAP.md) §2.

**Day goal:** Run the first synthetic-tier experiment — 100 rounds
of repeated PD against each of {TFT, grim trigger, all-C, all-D,
mirror-LLM}. Capture full per-round logs, summarize cooperation
rates, compare to fixed strategies. Result requires human review
before publication (graduated-autonomy gate).

**Status as of 2026-05-24: ✅ Day 7 FULLY CLOSED.** Baseline
experiment + 3-rerun diagnostic completed; cooperation lock-in
confirmed as Gemma 4 model prior (not sampling/framing artifact);
publication-review gate **CLEARED** under D-028 no-publish-standalone
disposition (Day-7 result aggregating into broader future publication);
journal updated to reflect disposition; `experiment.lock` +
`week2_plan_seed.md` written; Day-7 task IDs backfilled into
`state.completed_tasks`; `current_day` advanced to `day_8`. Track A
merged Track B (54 new tests) and Track C (2 cron wrappers) at EOD;
Track D merged at EOD (16 files, +785/-24, 82/82 UI tests).

## Headline outcomes

- **OpenSpiel + GRA up — 2/2 checks.** `open_spiel-1.6.15` and
  `game_reasoning_arena-0.1` installed into `.venv-chroma`;
  `pyspiel.load_game("matrix_pd")` loads cleanly (action 0=C, 1=D;
  payoff matrix CC=5/5, CD=0/10, DC=10/0, DD=1/1). Authored
  `tests/test_gra_random_vs_random.py`: random-vs-random over 5
  episodes returns 0.600 cooperation, inside [0.3, 0.7] band.
- **LLM agent + dry-run — 3/3 checks.** Prompt-contamination grep on
  `experiments/exp001_repeated_pd/llm_agent.py` returned 0 matches
  for plan-prescribed forbidden pattern and a broader case-
  insensitive sweep. Parser retry-once + log-as-observation policy
  implemented (`_log_parse_failure` to `logs/day7_dryrun.jsonl`).
  Dry-run LLM-vs-`constant_d`, 10 rounds, T=0.0: LLM switched to D
  by round 3 (last-5 `D C D D D` → 4/5 D); 0 parse failures.
- **500-round experiment — partial_pass (baseline).** 5 opponents ×
  100 rounds = 500 rounds completed in 114.2s through the Day-6
  orchestrator (its first non-`summarize_paper` use). Per-opponent
  cooperation rates: `tft 1.000`, `grim_trigger 1.000`, `all_c
  1.000`, **`all_d 0.120`**, `mirror_llm 1.000`. The 1.000 vs TFT
  fell OUTSIDE the human's pre-computed range [0.60, 0.95] —
  precompute-range safeguard fired correctly.
- **Slip ladder 7.1/7.2/7.3 — all PARTIAL_PASS at validation 2; all
  diagnostic.** T=0.2 (7.1) and T=0.7 (7.2) reproduced the same
  1.000 vs cooperators → rule out sampling artifact. T=0.0 +
  `exploitation_hint` prompt variant (7.3) drove `all_d` rate to
  0.020 (more aggressive defection) but kept cooperator-rate at
  1.000 → rule out framing artifact. Conclusion: cooperation
  lock-in is Gemma 4's prior; the model IS responsive to incentives
  vs defectors but does not defect first.
- **Range amended; slip resolved.** `notes/day7_expected_range.md`
  updated to `[0.60, 1.00]` with the 4-run diagnostic table as
  justification. `current_subday` cleared on `slip_resolved` event.
- **Quicklook — 2/2 checks.** Installed `pandas==2.2.3` +
  `matplotlib==3.9.2` into `.venv-chroma` (closes Day-7 carry-over
  item 4). 5 cumulative-payoff PNGs in
  `experiments/exp001_repeated_pd/plots/` + per-opponent
  cooperation rate + mean payoff + switch points in
  `experiments/exp001_repeated_pd/analysis/quicklook.md`. Per-round
  JSONL → per-opponent CSV adapter; `cooperation_rates.csv` moved
  to `results/_aggregate/` to avoid glob collision.
- **Publication review gate — ARMED.**
  `state.human_gates_pending = ["day7_publication_review"]`. Per
  CLAUDE.md inviolate rule 3 this is the **most important gate of
  Week 1** and never auto-clears. The Day-7 weekly synthesis
  journal stub mentions results with explicit ⚠️ PRELIMINARY
  caveat banner; results-announcement is a follow-up post.

## Block 1 — Foundations (human-only, NO AI)

> HALT. Reading: Camerer Ch. 4 §4.3 (cognitive hierarchy + level-k
> for repeated games) + Fudenberg & Levine Ch. 1 §1.1–1.2 (learning-
> in-games framing). Problem set: finish MW proof from Day 6 if not
> complete; otherwise Camerer 4.1, 4.2.

| Task | Type | Status |
|------|------|--------|
| `day7_block1_reading` | human-only, blocking | ✅ pending — Block 1 decoupled from Block 2 per CLAUDE.md inviolate rule 1; agent proceeded on Block 2 in parallel; awaiting end-of-day attestation if not already given |
| `day7_block1_problemset` | human-only | ✅ — same |

## Block 2 — Build + slip ladder

| Task | Status |
|------|--------|
| `day7_block2_openspiel_up` (hard, hard_checkpoint) | ✅ 2/2 checks |
| `day7_block2_strategies_and_llm_agent` (hard, hard_checkpoint) | ✅ 3/3 checks |
| `day7_block2_precompute_expected_range` (human-only, blocking) | ✅ pre-run range [0.60, 0.95]; amended to [0.60, 1.00] post-diagnostic |
| `day7_block2_run_experiment` (hard, hard_checkpoint) | ⚠️ partial → slip 7.1 |
| `day7_1_block2_run_experiment` (T=0.2) | ⚠️ partial → slip 7.2 |
| `day7_2_block2_run_experiment` (T=0.7) | ⚠️ partial → slip 7.3 |
| `day7_3_block2_run_experiment` (exploitation_hint, T=0.0) | ✅ slip resolved; range amended |
| `day7_block2_quicklook` | ✅ 2/2 checks |
| `day7_publication_review_gate` | ✅ **CLEARED 2026-05-24 (D-028)** — no-publish-standalone disposition |

## Block 3 / end of day

| Task | Type | Status |
|------|------|--------|
| `day7_block3_reading` | human-only, blocking | ✅ passed — human attestation (decross1) 2026-05-23 |
| `day7_block3_journal_weekly_synthesis` | human-assisted | ✅ stub at `journal/day7.md` (996 words; prose to write by human, target 600–1000) |
| `day7_ambient` | human-only, non-blocking | ✅ passed — human attestation 2026-05-23 |
| `day7_end_of_day_artifacts` | agent-executable | ⏳ this commit |
| `day7_retrospective` | human-driven | ⏳ 6 questions surfaced; human writes prose in `human/retrospectives/week1.md` |

## Side-track merges this day

- **Track B `day7-tools-tests`** — merged at EOD (commit appended
  by EOD command). 5 files (+1028): `tests/test_claims_check.py`
  (442 lines, 25 tests), `tests/test_gate_sla_check.py` (310 lines,
  16 tests), `tests/test_mock_payoffs.py` (174 lines, 13 tests),
  `notes/track-b-day7-tools.md`, +2 lines on `run_state/claims.jsonl`
  (clean claim+release lifecycle). 54/54 tests passing post-merge.
- **Track C `day7-cron-sla`** — merged at EOD. 3 files (+112):
  `cron/sla-sweep.sh` (every-15-min SLA + GC sweeper),
  `cron/claims-weekly.sh` (Sunday 04:00 weekly summary),
  `notes/track-c-day7-cron.md` (install playbook). Scripts NOT yet
  installed in crontab — human-step per Track-C install playbook.
- **Track D `day7-ui`** — NOT merged today. Track D is waiting on
  Day-7 experimental data; see Day-7 retrospective for hand-off
  list. Surfaced below.

## Decisions / findings

- **Cooperation lock-in is a model prior (Gemma 4).** Robust across
  T ∈ {0.0, 0.2, 0.7} AND across baseline vs. exploitation_hint
  prompt. The same model defects 88–98% against `all_d`, so it IS
  responsive to data — it just does not defect first against a non-
  defecting opponent. Candidate D-NNN entry for the next decisions
  pass: "Day-7 cooperation lock-in is a Gemma 4 property, not a
  measurement bug."
- **Orchestrator surgically extended.** Added `play_pd_match` to
  `KNOWN_TASK_TYPES` + branching dispatch in `_worker_entry` +
  payload validation in `_validate_input` + task-type-aware receipt
  detail. Backward-compatible: `summarize_paper` code path bitwise
  identical (Day-6 malformed-input test still 5/5; Day-6 5-sequential
  test deferred to a separate validation pass since it's expensive
  but tested at zero-modification on the day6_block2_robustness_mini
  task). Week 2 should generalize this to a registry pattern (#10
  in `week2_plan_seed.md`).

## Carried into Day 8 / Week 2

- `day7_publication_review_gate` ✅ CLEARED 2026-05-24 (D-028). No
  results-announcement post is coming for Day-7 standalone; the Day-7
  result aggregates into a broader future publication. A new
  publication-review gate will be defined when the aggregate paper is
  drafted (Week 2+ scope).
- `week2_plan_seed.md` written with 10 bullets — input to Day-38
  planning; the Week-2 plan execution itself is a separate task
  (per CLAUDE.md / not-in-scope-for-Week-1 rules).
- Track D is waiting for the Day-7 experiment data. Day-7 baseline
  results + 4-run diagnostic + experiment.lock + journal stub are
  all in this commit; Track D can consume them post-publication-gate
  (the data is not gated for *consumption* — only for *publication*).
