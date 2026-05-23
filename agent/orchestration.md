# Agent orchestration — worktrees, launches, merges

> This file tells **you (the human researcher)** how to orchestrate
> Claude Code worktrees each day, and tells **each Claude session**
> what its file boundaries are.
>
> Canonical machine-readable plan: `plan.yaml`.
> Human's daily prose: [`../human/daily_plan.md`](../human/daily_plan.md).
> Autonomy framework (tiers, SLAs, alignment): [`autonomy.md`](autonomy.md).
> Ownership registry (which paths belong to which zone): [`ownership.yaml`](ownership.yaml).
> Claim/lock protocol (how concurrent agents avoid collisions): [`collision_protocol.md`](collision_protocol.md).
>
> Per-track launch prompts are extracted into [`prompts/`](prompts/) —
> one file per track. This file is the orchestration narrative; the
> prompts are the operational text you paste into each session.

---

## The four tracks

| Track | Worktree role | Owns | Launch prompt |
|---|---|---|---|
| **A — Main** | Critical-path Block 2 for the current day | `run_state/`, `logs/`, `bench/`, `chroma_db/`, `agent_wrapper/`, end-of-day commits | [`prompts/track_a.md`](prompts/track_a.md) |
| **B — Tests & schemas** | Next-day(s) test scaffolds and JSON schemas, drafted ahead | `tests/`, `schema/`, draft files in `notes/` | [`prompts/track_b.md`](prompts/track_b.md) |
| **C — Pipeline & ops** | Self-contained scripts: ingest, scraper, cron, inspect_run, strategy stubs, quicklook | `ingest/`, `pipeline/`, `cron/`, `scripts/`, `tools/`, `infra/`, specific experiment files | [`prompts/track_c.md`](prompts/track_c.md) |
| **D — UI** | Observability dashboard + call-chain inspector | `ui/`, `ui_plan.md` | [`prompts/track_d.md`](prompts/track_d.md) |

**Authoritative zone-by-zone ownership lives in
[`ownership.yaml`](ownership.yaml).** This table is a quick reference;
the YAML is the source of truth and what `tools/claims_check.py` reads.

---

## Hard rules that apply to every track

1. **Only Track A writes to `run_state/week1.state.json` and
   `run_state/week1.run.jsonl`.** Tracks B, C, D are read-only on
   those. Shared append-only JSONLs (`attestations.jsonl`,
   `escalations.jsonl`, `claims.jsonl`) accept appends from any agent.
2. **Only Track A calls `LOCAL_LLM_BASE_URL` (the vLLM endpoint).**
   Tracks B, C, D set `MOCK_LLM=1` in their environment and stub LLM
   responses. The GPU belongs to Track A.
3. **Tracks B, C, D never advance the day.** They draft work for
   future days; Track A consumes the draft when its day arrives,
   validates it, and runs the day's gates.
4. **Every agent that writes must claim first.** See
   [`collision_protocol.md`](collision_protocol.md). The exception is
   Track A on its primary (non-dispatchable) zones — Track A's
   primacy is unconditional there.
5. **`plan.yaml` is read-only for everyone except Track A.**

---

## One-time setup (do before Day 2)

```bash
# In the main checkout, repo root:
echo ".claude/worktrees/" >> .gitignore

cat > .worktreeinclude <<'EOF'
.env
run_state/week1.state.json
run_state/week1.run.jsonl
EOF

# Verify Claude Code is recent enough for --worktree (≥ 2.1.50).
claude --version

# Verify worktrees work on this machine.
claude --worktree smoke-test
# In the spawned session, just `exit`. The worktree should auto-clean.
```

Confirm `claude --version` is ≥ 2.1.50; older versions do not have the
`--worktree` flag. If too old, run `claude update` (or re-install)
before Day 2.

---

## How a day runs (template)

```
08:30  Block 1 starts. You only. No agents (per inviolate rule,
       though Block 2 no longer blocks on Block 1 — the agent can
       start whenever you're ready).
10:00  Block 1 ends.

10:30  ── Terminal 1 (Track A): env -u MOCK_LLM claude --worktree dayN-main
        Track A reads plan.yaml + run_state, resumes at first
        incomplete task for the day, begins Block 2.

10:30  ── (If Day 2+) Terminal 2 (Track B): claude --worktree dayN-tests
        Track B receives its prompt from prompts/track_b.md and
        drafts named scaffolds for day N+1 (and N+2 where listed).

10:30  ── (If Day 3+) Terminal 3 (Track C): claude --worktree dayN-ops
        Track C receives its prompt from prompts/track_c.md and
        drafts named pipeline / ops scripts for day N+1.

10:30  ── (Day 4+) Terminal 4 (Track D): claude --worktree dayN-ui
        Track D works on UI per ui_plan.md.

10:30–
12:30  Track A executes Block 2 with [GATE] pauses for you.
        Tracks B/C/D run independently. If any finishes early, merge
        it back (see "Merging side branches" below) and exit it.

12:30  Block 2 ends. All side worktrees that haven't merged remain
       paused. You go to lunch.

13:30  Block 3 — your reading and journal post. Track A is idle but
       open (it generates the journal stub on request).

14:30  Ambient listening (you only).

15:30  End-of-day. Track A commits, attests, and pre-stages tomorrow.
       Side worktrees: if any are unmerged and still useful, leave
       them; otherwise close them with `exit` and let cleanup happen.
```

**`env -u MOCK_LLM`** is required for Track A so the wrapper does not
silently stub embedders/inference (memory: `mock-llm-track-a-env`).
Tracks B, C, D can keep `MOCK_LLM=1` (and should).

---

## Per-track prompts

Each track's launch prompt lives in [`prompts/`](prompts/):

- [`prompts/track_a.md`](prompts/track_a.md) — Main session prompt
  (paste at start of every day for Track A).
- [`prompts/track_b.md`](prompts/track_b.md) — Tests & schemas
  prompt (paste when launching; per-day task list inside).
- [`prompts/track_c.md`](prompts/track_c.md) — Pipeline & ops
  prompt (paste when launching; per-day task list inside).
- [`prompts/track_d.md`](prompts/track_d.md) — UI prompt
  (paste when launching; refer to `ui_plan.md` for current revision).
- [`prompts/dispatched_task.md`](prompts/dispatched_task.md) — Template
  for orchestrator-dispatched coding agents (Week-2 deliverable).

---

## Merging side branches (procedure)

When a Track B / C / D session prints `TRACK <X> COMPLETE — ready to
merge`, in your main checkout:

```bash
# From the main checkout, on the main branch (or current dev branch):
git fetch
git merge --no-ff worktree-dayN-tests   # or worktree-dayN-ops, etc.
# Resolve any conflicts (there should be none if file boundaries were
# respected). Run the agent's validation for the day; the merged
# files are inputs to Track A's next task.

# After merge succeeds and Track A has confirmed it can use the files:
git worktree remove .claude/worktrees/dayN-tests
git branch -d worktree-dayN-tests
```

If a conflict appears, that means a file-boundary rule was violated —
do not auto-resolve. Open both versions in a diff viewer and decide by
hand. Most often the answer is: **Track A's version wins** (Main owns
the file), and the side track's edit was a mistake.

### Sentinel attestation

If a side track has finished but did not print the sentinel
(`TRACK <X> COMPLETE — ready to merge`), it is **advisory only**. The
auditor's MERGE decision based on the diff is the load-bearing signal
(memory: `sidetrack-sentinel-attestation`). Surface to the human and
accept verbal attestation when the auditor says MERGE.

---

## Per-day parallel schedule

| Day | Track A | Track B | Track C | Track D |
|---|---|---|---|---|
| **1** | (main checkout; no worktree) | — | — | — |
| **2** | day2-main | day2-tests | — | — |
| **3** | day3-main | day3-tests | day3-arxiv-pipeline | — |
| **4** | day4-main | (Day-3 B unmerged) | day4-pd-strategies | day4-ui |
| **5** | day5-main | (Day-3 B merged AM) | day5-inspect-run + (Day-3 C merged AM) | day5-ui-sync |
| **6** | day6-main | — | day6-quicklook + (Day-5 C merged AM) | — |
| **7** | day7-main | — | (Day-4, 6 C merged AM) | — |

For per-day task assignments to each track, see:
- Track A: `plan.yaml` `dayN_*` tasks for the current day.
- Track B: [`prompts/track_b.md`](prompts/track_b.md) "Per-day task
  table" section.
- Track C: [`prompts/track_c.md`](prompts/track_c.md) "Per-day task
  table" section.
- Track D: [`../ui_plan.md`](../ui_plan.md) "Build order" section.

---

## Beyond 4 tracks — orchestrator-dispatched coding agents

Starting Week 2 (Day 39 deliverable), the orchestrator can dispatch
additional Claude Code sessions on demand via
`agent_wrapper/dispatch_coding_agent.py`. Each dispatched agent:

- Runs in its own worktree (extends the `claude --worktree` pattern).
- Receives a scoped prompt assembled from
  [`prompts/dispatched_task.md`](prompts/dispatched_task.md) +
  the task spec.
- Must obey the claim protocol in [`collision_protocol.md`](collision_protocol.md)
  before any file write.
- May only write to **dispatchable** zones in [`ownership.yaml`](ownership.yaml).

Concurrency caps per phase boundary (see
[`autonomy.md`](autonomy.md) §3 and [`collision_protocol.md`](collision_protocol.md) §3):

| Phase | Concurrent agents (typical) | Who dispatches |
|---|---|---|
| Week 1 | 4 (A/B/C/D) | Human launches each manually |
| Week 2 unlock | 4–6 | Human + orchestrator (1/day cap) |
| Weeks 3–4 unlock | 6–8 | Orchestrator (≤3 concurrent) |
| Phase 2 entry | 8–12 | Orchestrator autonomously |
| Phase 2+ | unbounded | ~80% target |

The unlock is gated on the alignment evidence in
[`autonomy.md`](autonomy.md) §4 plus a claim-protocol-clean week.

---

## Failure modes specific to parallel execution

### State-file collision

**Symptom:** `run_state/week1.run.jsonl` has a corrupted line; verify
returns malformed > 0; some entries are missing fields.

**Cause:** Two tracks tried to append simultaneously. Should be
impossible if the file-boundary rules were followed.

**Fix:** Restore from the most recent commit (`git checkout HEAD --
run_state/week1.run.jsonl`), re-run the affected task from Track A,
and audit which side track violated the rule. Strengthen its prompt.

### vLLM queue contention

**Symptom:** Track A's tokens/sec micro-bench produces inconsistent
numbers; determinism check fails because two callers interleaved.

**Cause:** A side track hit `localhost:8000` despite the rule.

**Fix:** Stop the side track. Set `MOCK_LLM=1` explicitly in its
worktree shell (`export MOCK_LLM=1`). Re-run Track A's bench. Audit
the side track's code for un-stubbed LLM calls.

### Stale-context drift

**Symptom:** A side branch drafted on Day 3 evening can't import a
helper that Track A added to `agent_wrapper/wrapper.py` on Day 4.

**Cause:** Side branch hasn't rebased on main.

**Fix:** In the side worktree, `git fetch && git rebase origin/main`
(or whichever branch Track A merges into). Reinstall the venv if
`requirements.txt` changed.

### Merge conflict on a "shared" file

**Symptom:** `git merge` reports a conflict in a file Track A also
edited.

**Cause:** A file-boundary rule was violated.

**Fix:** Track A's version always wins. Discard the side track's edit
to that file (`git checkout --ours <path>`), accept the merge, then
audit the side track's prompt and tighten the forbidden list.

### Claim protocol violation

**Symptom:** `tools/claims_check.py --validate-ownership` exits non-zero;
two agents claimed overlapping paths.

**Cause:** Claim scan was skipped or two agents claimed simultaneously
(claim race).

**Fix:** Stop both side branches. Track A reviews their work in their
respective worktrees. Whichever has the more complete work wins; the
other re-runs after the first releases its claim. Log the violation
in the weekly retrospective; if it happens twice in a week, the
claim-protocol-clean check fails and the dispatch unlock does not
advance.

---

## What you gain, what you don't

**Gain:** Roughly 30–60 min/day on Days 3, 4, 5, and 6 by having the
next day's test scaffolds and prep scripts already drafted and waiting
for review at the start of Track A's Block 2. About 3 hours across the
week. Enough to absorb one bad day without losing the schedule.

**Don't gain:** Critical-path compression. Hard-gates and the single
GPU serialize Track A. Block 1 is sacred and human-only. Day 7's
experiment is sequential by nature.

**The discipline that makes this work:** file boundaries you actually
enforce. The moment a side track edits something it doesn't own, the
parallelism stops paying for itself and starts eating your evenings on
merge resolution. If you can't keep boundaries clean, drop back to
sequential (Track A only) — sequential single-track is faster than
parallel with conflicts.
