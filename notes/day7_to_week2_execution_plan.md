# Day 7 → Week 2 execution plan — concurrent-agent optimized

> How to execute Day 7 (the experiment day) and the first week of
> concurrent-agent ramp-up (Days 38–44) in the way that maximizes
> parallelism without violating the constraints. Honors
> [`agent/autonomy.md`](../agent/autonomy.md) §3 (phase-aware tier
> unlocks), [`agent/collision_protocol.md`](../agent/collision_protocol.md)
> (claim/lock discipline), [`agent/ownership.yaml`](../agent/ownership.yaml)
> (which paths each track owns), and
> [`PHASE_1_ROADMAP.md`](../PHASE_1_ROADMAP.md) §5 (the Week-2
> sequenced plan).
>
> The single most important rule: **alignment evidence drives unlock
> cadence, not the calendar.** If alignment doesn't clear by Day 44, the
> Week-2 tier shifts don't apply and Week 3 stays at Week-1 tiers.

---

## Day 7 — sequential by design (the experiment day)

Day 7 is **Track A only** during Block 2. The reason isn't tradition;
it's that the experiment uses the GPU for 20–40 minutes, side worktrees
would queue on inference, and the publication review gate halts
everything. Concurrent agents during the experiment would add zero
throughput and introduce noise.

The **window after Block 2** (12:30+) is where you can prep Week 2
without breaking Day 7's discipline.

### 07:00–08:30 — pre-flight (you, 15 min)

```bash
cd /home/decross1/projects/a_bgt_rsi
git pull
git status                         # should be clean on main at 46e20e0
git worktree list                  # should show only main
env | grep MOCK_LLM                # if "MOCK_LLM=1" appears, plan to launch with `env -u MOCK_LLM`
```

If anything looks off, stop and resolve before launching agents.

### 08:30–10:00 — Block 1 (you, no AI, KEYSTONE for Day 7)

Reading (per [`human/learning_track.md`](../human/learning_track.md)):
- Camerer Ch. 4 §4.3 (cognitive hierarchy + level-k for repeated games)
- Fudenberg & Levine Ch. 1 §1.1–1.2 (learning-in-games framing)

Problem set: finish the **Multiplicative Weights proof from Day 6** if
not complete; otherwise Camerer 4.1, 4.2. The MW proof matters because
the Week-2 critic + meta-review architecture leans on no-regret
intuition.

Block 1 does NOT gate Block 2 in `plan.yaml` (decoupled). The agent
launch below can happen any time after 08:30 — don't wait until 10:00 if
you're done early.

### 10:00–10:30 — launch Track A

```bash
# Single terminal. No side tracks.
env -u MOCK_LLM claude --worktree day7-main
```

Paste [`agent/prompts/track_a.md`](../agent/prompts/track_a.md) into the
session. Track A reads the day-7 section of `plan.yaml`, picks up at
`day7_block2_openspiel_up`, walks through Block 2 sequentially.

### 10:30–12:30 — Block 2 (Track A, you supervise the gates)

Five sequential tasks. Don't try to parallelize anything here.

| Time | Task | Your role |
|---|---|---|
| 10:30–10:50 | `day7_block2_openspiel_up` (hard-gate) | Attest random-vs-random looks ~50%. |
| 10:50–11:20 | `day7_block2_strategies_and_llm_agent` (hard-gate, prompt-contamination grep) | **Read the actual prompt yourself.** No "tit-for-tat" / "grim trigger" / "all-C" / "all-D" strings. |
| 11:20–11:30 | `day7_block2_precompute_expected_range` (`requires_human_understanding: true`) | On paper, write the LLM-vs-TFT expected cooperation rate range (Horton-style: ~60–95% over 100 rounds). Save the paper. |
| 11:30–12:10 | `day7_block2_run_experiment` (the big one) | Sit on hands. 20–40 min of GPU. |
| 12:10–12:30 | `day7_block2_result_sanity_check` (hard-gate) | Compare actual vs your pre-written range. If OUTSIDE, **do not declare success** — investigate (MARLIN backend, parse-failure events, prompt drift). |

If a hard-gate fails: Track A writes `day_aborted` to the run log and
halts. Declare a slip (Day 7.1) per [`PHASE_1_ROADMAP.md`](../PHASE_1_ROADMAP.md)
§2.

### 12:30–13:30 — buffer / lunch

Track A is idle but holding state. Don't close the terminal yet — the
journal stub task comes after.

### 13:30–14:30 — Block 3 (you, journal post)

Track A produces the data-filled stub via `agent_assisted` task. You
write the **600–1000 word weekly synthesis** (longer than usual): what
worked, what didn't, 7 specific over-budget things, what the first PD
run produced (with explicit PRELIMINARY caveat banner).

**The publication review gate** (`day7_publication_review_gate`) lands in
`human_gates_pending` after this. It never auto-clears. Don't tell
Track A to publish — do not let it use the "just publish now" reasoning.

### 14:30–15:30 — ambient (you, no AI)

A keynote on game theory + LLMs from a recent venue (Simons, NeurIPS
workshop, AAMAS). Sets frame for Week 2.

### 15:30–16:30 — retrospective + Week-1 attestation (you, KEYSTONE)

This is the load-bearing handoff into Week 2. Two parts.

**Retrospective (the human's).** Track A prints the 6 questions; you
write answers in pen + notebook; Track A appends to the run log
(does NOT write, summarize, or interpret).

**Week-1 attestation.** Open
[`human/retrospectives/week1.md`](../human/retrospectives/week1.md)
(the stub I shipped in the restructure). Fill in:
- Sections 1–6 (your retrospective answers, transferred from notebook).
- Section 7 — the four-bullet **alignment evidence** check.
- Section 8 — tier-shift inventory (read but don't act yet — needs Week 2
  attestation as the second pass).
- Section 10 — sign + commit.

If sections 7's four boxes all check, this is the **first** of two
weekly attestations needed for Week-2 tier shifts to apply. If any box
fails, Week 2 still runs but the tier shifts wait until alignment
recovers.

```bash
# When the retrospective is committed:
git add human/retrospectives/week1.md
git commit -m "retrospective: week1 attestation"
git push origin main
```

### 16:30+ — optional Week-2 prep window (Track D can run)

If you have energy, you can launch Track D in parallel to start UI v1
groundwork — this saves 1–2 hours on Day 38 and is the only safe
parallel work for Day 7 (Track D doesn't touch the GPU; MOCK_LLM=1 is
fine for UI sampler work).

```bash
# Optional second terminal:
claude --worktree day7-ui-v1-prep
```

Paste [`agent/prompts/track_d.md`](../agent/prompts/track_d.md). Task:
draft the UI v1 scaffolding — sampler entry point, dashboard skeleton,
alignment-evidence panel placeholders. Do NOT consume any logs from
today's experiment in the prep — the experiment data is gated by the
publication review.

---

## Day 38 — the Week-2 linchpin (3–4 concurrent agents)

Day 38 is the **single most important day for Week-2 success.** Three
things have to land cleanly, in order:

1. **UI v1 deployment** (Track D ships; you attest end-to-end).
2. **Dispatch plumbing** (Track A lands `agent/ownership.yaml`,
   `agent/collision_protocol.md`, `run_state/claims.jsonl` exercises —
   most of this already exists in the repo; today you *use* them).
3. **Week-2 unlock attestation** (you write in
   `human/retrospectives/week2.md` after UI v1 verified).

### 08:30–10:00 — Block 1 (you, no AI)

C-B & L Ch. 2 §2.4–2.8 (MW variants, regret bounds). Reading load is
moderate; if you're light, get ahead on Camerer Ch. 5.

### 10:00 — launch ALL FOUR tracks in parallel

```bash
# Terminal 1 — Track A (main)
env -u MOCK_LLM claude --worktree day38-main

# Terminal 2 — Track B (schema amendments scaffolding)
claude --worktree day38-tests

# Terminal 3 — Track C (hypothesis fixture set + cron/snapshot tweaks)
claude --worktree day38-ops

# Terminal 4 — Track D (UI v1 final ship + alignment panel)
claude --worktree day38-ui
```

Paste the per-track prompt from [`agent/prompts/`](../agent/prompts/) at
each session start. **Each track must read `agent/ownership.yaml` and
`agent/collision_protocol.md` before any file write.**

### 10:30–12:30 — Block 2 (4 tracks in parallel)

**Track A** (you supervise; the only one calling the GPU):
- Verify yesterday's experiment results (Day-7 publication gate
  still open — do NOT publish; just review).
- Prep `plan.yaml` for the Week-2 tasks — when Track B's schema
  amendments merge, validate and adopt the new fields
  (`human_intervention`, `retrieval_context`, `calibration_entry`).
- Coordinate with Track D: as the UI panels light up, attest each one
  works correctly.

**Track B** (drafts; no GPU; MOCK_LLM=1):
- Author `schema/human_intervention.schema.json`,
  `schema/retrieval_context.schema.json`,
  `schema/calibration_entry.schema.json`.
- Write regression tests for each.
- Sentinel: `TRACK B COMPLETE — ready to merge`.

**Track C** (drafts; no GPU; MOCK_LLM=1):
- Build the 20-known-flawed-hypotheses fixture set in
  `experiments/critic_calibration/fixtures.py` (zone:
  `experiments` — claim before writing).
- Tweak `cron/snapshot-chroma.sh` for the off-host destination
  (per memory `chroma-backup-status` — decision due ~2026-06-05).
- Sentinel: `TRACK C COMPLETE — ready to merge`.

**Track D** (UI; no GPU; MOCK_LLM=1):
- Ship UI v1: sampler reading `run_state/week1.run.jsonl`, dashboard
  rendering run-log integrity + recent task statuses + pending
  soft-gate attestations + hard-gate pending list.
- Render `state.fallbacks_taken` in the sidebar.
- Render today's `metric_log` values vs prior runs (the metric-drift
  evidence).
- Sentinel: `TRACK D COMPLETE — ready to merge`.

**Claim discipline** (every track, before any file write):
```bash
# Append a claim to run_state/claims.jsonl
# (see agent/collision_protocol.md §1 for the schema)
```
Tooling check: `python3 tools/claims_check.py --dry-run` from any
terminal will show active claims. `--check <path>` confirms a path is
free. `--validate-ownership` confirms `ownership.yaml` covers what's
being written.

### 12:30–13:30 — first merge window (you)

By 12:30, at least 2 of the 3 side tracks should have printed the
sentinel. Merge in this order:

```bash
# Always merge Track D last — its commits touch ui_plan.md which
# Track A also reads for alignment-evidence verification.
git merge --no-ff worktree-day38-tests
git merge --no-ff worktree-day38-ops
git merge --no-ff worktree-day38-ui

# After each merge, verify file boundaries:
git diff --name-only HEAD~1 HEAD   # should only show files in that track's zone

# Run validation:
python3 tools/claims_check.py --validate-ownership
python3 -m pytest tests/  # or per-test-file invocations
```

Merge conflicts → Track A's version wins; discard side-track edits to
conflicting files (`git checkout --ours <path>`); audit the side
track's prompt and tighten the forbidden list.

### 13:30–14:30 — Block 3 (you, journal)

Public post (200–400 words): "Week 2, Day 1 — the apparatus learned to
build itself in parallel." Include the 4-track concurrency story and
the alignment-evidence-first framing for autonomy.

### 14:30–15:30 — ambient

### 15:30–16:30 — Week-2 unlock attestation (you, load-bearing)

Open `human/retrospectives/week2.md` (you'll create this — copy the
template from `week1.md`). Fill in:
- Sections 1–6: this week's narrative (just one day so far; this
  retrospective will grow through Day 44).
- Section 7: alignment evidence. The four-bullet check **using the
  shipped UI v1**.

If section 7 all-clear AND `week1.md` is also all-clear:
**Week-2 tier shifts apply.** Track A applies them per
[`agent/autonomy.md`](../agent/autonomy.md) §4.2: swap
`autonomy_tier` → `autonomy_tier_after_unlock` on every task that
has one, append a single `tier_shift` event to the run log.

If section 7 fails: Week 2 continues but at Week-1 tiers. Iterate the
UI on Day 39 to address whatever was missing.

```bash
git add human/retrospectives/week2.md plan.yaml run_state/week1.run.jsonl
git commit -m "week2 day38: UI v1 shipped; Week-2 unlock attestation"
git push origin main
```

---

## Days 39–44 — Week 2 sequenced (4–6 concurrent agents)

Days 39–44 use the same morning-launch / Block-2-parallel /
afternoon-merge / EOD-retrospective rhythm. Concrete daily
assignments per [`PHASE_1_ROADMAP.md`](../PHASE_1_ROADMAP.md) §5:

### Day 39 — critic agent + dispatcher plumbing

Track A: `agent_wrapper/dispatch_coding_agent.py` lands (the
plumbing — see [`agent/collision_protocol.md`](../agent/collision_protocol.md) §5).
Once it lands, you have your **first orchestrator-dispatchable
agent**. Also: W2-01 Critic agent (`workers/critic.py`).

Tracks B + C + D: continue drafting Day-40 scaffolds.

**First dispatch experiment** (15-min budget): late afternoon, dispatch
ONE tiny task to a non-critical path (e.g., draft a docstring for a
helper function). Confirm:
1. The worktree spawns.
2. The dispatched agent claims correctly.
3. It prints the soft-gate sentinel.
4. The dispatched commit appears.
5. You can merge it.

If any step fails, fix before Day 40's real dispatch.

### Day 40 — meta-review + first real dispatched task

Track A: W2-02 meta-review synthesis (`workers/meta_review.py`).

**First real orchestrator-dispatched task lands.** Candidate: drafting
Day-41 test scaffolds for a deterministic module (clear success
criteria, soft-gate tier). Track A reviews the merge candidate; the
4-hour soft-gate SLA gives you breathing room.

Concurrency reaches **5 agents** (4 manual + 1 dispatched).

### Day 41 — auto-evaluator calibration

W2-05. The first task that produces a numeric threshold (κ + Spearman)
that the autonomy framework will rely on for novelty evaluation
later. Track A only on the calibration itself; B + D can continue
drafts.

### Day 42 — schema amendments lock + `plan.yaml` field population

This is the day to populate the remaining `autonomy_tier:` /
`dispatchable:` / `target_zone:` fields on every `plan.yaml` task.
Track A handles. Use the **dispatcher** here: dispatch a coding agent
to do the bulk annotation per a clear spec (zone: `docs-root`; success
criterion: every task has all three fields). Soft-gate.

Concurrency: 4 manual tracks + up to 2 dispatched.

### Day 43 — PD experiment re-run with critic in the loop

First end-to-end Phase-2-architecture exercise. Track A only on the
experiment; Tracks B and D in parallel for prep. Hard-gate on the
publication side; soft-gate on the run itself.

### Day 44 — retrospective + alignment scoring

Week-2 retrospective. **Second consecutive weekly attestation** —
this is what unlocks Weeks-3-4 tier shifts. Includes a *concurrency*
attestation: was the claim log clean? Any overlapping claims? Any
expired-claim writes?

```bash
python3 tools/claims_check.py --weekly-summary
```

If the answer is "0 overlaps, 0 expired writes, 0 ownership violations"
AND the four alignment-evidence boxes check, **Weeks-3-4 tier shifts
apply on Day 45.**

---

## The daily template (apply Days 38 → 44 and beyond)

```
07:00  Pre-flight (you, 15 min): pull, status, worktree-list, env check.
08:30  Block 1 (you, no AI). Reading + problems per learning_track.md.
10:00  Launch all N tracks in parallel terminals.
       Each track: paste prompt, confirm it reads CLAUDE.md →
       agent/autonomy.md → agent/ownership.yaml →
       agent/collision_protocol.md → plan.yaml (today).
10:30  Block 2 — Track A on critical path; B/C/D on next-day drafts.
       Claim discipline mandatory before any write.
       Hard-gates pause Track A. Soft-gates flag and continue.
       Dispatched agents (Day 39+) run in their own auto-worktrees.
12:30  Merge window (you). Sentinels checked; ownership validated;
       per-track merges in dependency order; tests on merged set.
13:30  Block 3 — journal post. Agent stubs; you write prose.
14:30  Ambient. No agents needed.
15:30  EOD wrap. Track A:
         - commits and pushes the day's work
         - updates current_day.md
         - pre-stages tomorrow
         - updates state file (current_day, completed_tasks)
         - if hard-gates pending: confirms human_gates_pending honored
16:00  Optional Track D run (UI iteration) until you're done for the day.
```

---

## Concurrency caps by phase (compact reference)

| Phase | Manual tracks | Orchestrator-dispatched | Total max | What unlocks the next tier |
|---|---|---|---|---|
| Week 1 (Day 7) | 1 (A only) | 0 | 1 | n/a — Week 7 is sequential by design |
| **Week 2 unlock** (Day 38+) | 4 (A/B/C/D) | 1/day | 5 | week1.md alignment evidence clean (Day 7 EOD) |
| **Weeks-3-4 unlock** (Day 45+) | 4 | up to 3 concurrent | 7 | week1.md + week2.md alignment evidence clean (Day 44 EOD) |
| **Phase 2 entry** (Day ~91) | 4 | autonomous, weekly attest | 8–12 | 4 consecutive weekly attestations + UI v2 + critic + meta-review live |
| **Phase 2+** | 4 | unbounded | unbounded | Maintained alignment — ~80% target |

---

## The four things that will trip you up

1. **Skipping the claim scan before writing.** First time a dispatched
   agent does this, you'll see an unexpected merge conflict. Fix:
   re-read [`agent/collision_protocol.md`](../agent/collision_protocol.md) §2.1
   with the offending agent; tighten its prompt; re-run.

2. **The UI doesn't render alignment evidence end-to-end on Day 38.**
   Likely cause: Track D's data-contract assumptions diverged from
   Track A's actual log shapes (this happened on Days 4 and 5 already
   — see `ui_plan.md` r6 and r7). Fix: pair Track A's attestation with
   a UI walk-through; iterate on Day 39.

3. **MOCK_LLM=1 in Track A's shell.** Per memory
   `mock-llm-track-a-env`, MOCK_LLM=1 is set in the shell env. ALWAYS
   launch Track A with `env -u MOCK_LLM claude --worktree …` or the
   wrapper silently stubs embedders/inference. There's no in-session
   warning louder than a `Mock` log line; easy to miss.

4. **Trying to "just publish" Day 7's PD results from a Day-8 session
   to clear the publication gate.** Don't. The gate stays open until
   the human (you, after retrospection) explicitly attests. Even when
   Week-2 work is calling for Day-7 numbers, the gate stays. Publish
   only after the result sanity check + the prompt-contamination
   review + the JSONL integrity check are all attested in
   `week1.md` §7.

---

## Where to look if something goes wrong

- **Hard-gate failure**: [`agent/autonomy.md`](../agent/autonomy.md) §2.2;
  the gate stays halted; declare a slip per
  [`PHASE_1_ROADMAP.md`](../PHASE_1_ROADMAP.md) §2.
- **Soft-gate rejection**: [`agent/autonomy.md`](../agent/autonomy.md)
  §2.1; rollback within the 4h window.
- **Claim conflict**: [`agent/collision_protocol.md`](../agent/collision_protocol.md) §7;
  Track A's version wins on conflicting paths.
- **Ownership-zone violation**: `tools/claims_check.py --validate-ownership`;
  if multi-assigned, fix `ownership.yaml`; if unassigned, decide if
  the file needs a zone.
- **Stale memory entry**: this file's own MEMORY.md cleanup pattern —
  remove the index line and the linked file (or update both).

---

## What this plan optimizes for

- **Critical-path compression**: Track A is the bottleneck on GPU work
  (inference for the wrapper, embeddings for ChromaDB). Concurrent
  agents on Tracks B/C/D/dispatched do not compress Track A's
  critical path; they compress the *drafting* path for tomorrow's
  Track A work. Roughly 30–60 min/day savings on Days 38–44.

- **Alignment-evidence accumulation**: every week of clean evidence
  unlocks the next tier shift. Trying to unlock Weeks-3-4 by skipping
  the Day-44 retrospective fails — the system stays at Week-1 tiers
  forever if attestations aren't written.

- **Dispatcher confidence**: the first 5–6 dispatched tasks are the
  ones that prove the protocol works. Pick clear-success-criterion
  tasks; soft-gate them all; review every merge. Once the success
  rate is 95%+ over 10+ tasks, expand the concurrency cap.

- **Boundary discipline**: file ownership zones + claim protocol +
  Track-A merge primacy. The moment a side track edits something it
  doesn't own, parallelism stops paying for itself and starts eating
  your evenings on merge resolution. If discipline slips, fall back
  to fewer concurrent tracks for the day; sequential single-track is
  faster than parallel with conflicts.

---

## After Day 44

[`PHASE_1_ROADMAP.md`](../PHASE_1_ROADMAP.md) §5.4 (Days 45–51) and §5.5
(Days 52–58) carry the plan forward. The pattern stays the same: morning
launch all tracks; Block 2 parallel; afternoon merge; EOD attestation.
Concurrency expands as alignment evidence accumulates. The Phase-2
entry milestone at Day 91 is the next major boundary.

This file can be deleted once Day 44 retrospective is committed — its
content is then absorbed into the run-log history and the weekly
retrospective record.
