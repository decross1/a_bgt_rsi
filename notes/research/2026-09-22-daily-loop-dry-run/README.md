# Daily loop dry run — 2026-09-22

Day 1 of the Oracle ⇄ meta-oracle ⇄ Nara daily loop
(`/home/decross1/projects/a_bgt_rsi/docs/META_ORACLE_DAILY_LOOP.md`).
This note is the durable record of that dry run. The lab repo's plans and receipts live in
`/home/decross1/projects/a_bgt_rsi/run_state/`, which is gitignored, and the mailbox is append-only but explicitly
"git-ignored, so it has no versioned backup"
(`/home/decross1/projects/a_bgt_rsi/docs/ORACLE_NARA_MAILBOX.md`, section "The log").
So the dry run is recorded here, in tracked history, in Oracle's own words, with every claim
tied to a msg_id, a run-log task_id, or an absolute path I read today.

Scope of this note is the only thing Oracle wrote today. The loop's own source files are still
uncommitted in the main checkout; per the meta-oracle's amendment they are the interactive
session's work to commit, not mine (see "What I did not do" below).

## How the day actually went

| # | Event | Evidence |
|---|---|---|
| 1 | Lane and mailbox proven end to end before the plan | mailbox seq 6→13: `claude-6dd221bbd494416c` (question) → `oracle-253b9dd5555c9575` (answer) → `oracle-2a51f301d3d53ceb` (plan_item) → `nara-1ba2318a52704e3b` (claimed) → `nara-e8384fbb0e8e52e6` (validated) → `claude-8e1b2c1e994fba1f` (review accept) |
| 2 | First real plan written and submitted for review | run-log task_id `oracle-daily:plan:2026-09-22`, status completed, 21:25:34Z; mailbox seq 14 `oracle-526d094c18102bb3` "PLAN READY: 2026-09-22" |
| 3 | First real review came back **amend**, not accept | mailbox seq 15 `claude-4a2cf0e7b8a252eb`: verdict amend, 1 item accepted, 4 amendments, 7 findings (4 material, 3 minor) |
| 4 | Amended plan written as r2, all five amendments applied as written | `/home/decross1/projects/a_bgt_rsi/run_state/daily_plans/2026-09-22-r2.json`, sha256 `35aff30a12eddac4988b509135b9a518c50103a8fcc1e43403b3442498630a7d`; mailbox seq 16 `oracle-1f07e40ff183ec79` |
| 5 | The one authority question was posted to the owner | mailbox seq 17 `oracle-0eb4b4117656adad`, exactly two options (A registered study / B written closeout) |
| 6 | The first real Nara plan item was posted, sandbox-verified red | mailbox seq 18 `oracle-1a4209d20d2ab923`; run-log task_id `nara-lane:oracle-1a4209d20d2ab923`, status **deferred** — the Stage 0 gate is holding it until a `review` accepts it |
| 7 | Meta-oracle plan and code passes both fired today | run-log task_ids `meta-oracle:plan:2026-09-22` completed 21:27:10Z; `meta-oracle:code:2026-09-22` failed 20:38:42Z then completed 20:40:24Z |

The two facts worth keeping: the gate **did** bite (seq 18 is deferred, not run, exactly as
Stage 0 requires), and the review **did** reject two of my five items on evidence rather than
style. A loop whose first plan is accepted unchanged would be telling me nothing.

## What the review caught, and why each one was fair

1. **A factual error about the loop being stuck.** I called
   `/home/decross1/projects/a_bgt_rsi/run_state/loop_alert.json` self-contradictory. It is not. `/home/decross1/projects/a_bgt_rsi/orchestrator/loop_health.py`
   lines 174–190 — a block dated 2026-08-19, review item B1 — sets `GATE_AMBER_AFTER_S` to 3h
   and `GATE_RED_AFTER_S` to 12h, with the stated reason "Silence must not be the reward for
   being stuck." The alert file
   (`/home/decross1/projects/a_bgt_rsi/run_state/loop_alert.json`) shows `escalated: true` at
   `age_s` 72066, so red is the designed level. The `gate.detail` line "This is not a stall"
   describes one cycle's empty action list; the escalation describes 20h with no cycle. Both are
   true at once. My item proposed changing a reviewed policy inside a build lane. **Dropped.**
   Root cause was mine: I read the flag's two output fields without reading the code that
   produces them. The fix is not a lab fix — it goes into my own plan-phase prompt: *read the
   implementation behind a health signal before calling it contradictory.*
2. **An acceptance test that tested the host, not the code.** My first d2 read
   `/home/decross1/projects/a_bgt_rsi/run_state/loop_alert.json` — a gitignored file the daemon
   rewrites every wake, outside the sandbox, and inside my own item's write paths, so it was
   passable by hand-editing a file the branch never touches. **Dropped**, and the same failure
   mode was designed out of the packet test.
3. **A test that could never pass in the lane.** My first packet test hardcoded
   `cwd=/home/decross1/projects/a_bgt_rsi`. `sandbox_run` in
   `/home/decross1/projects/a_bgt_rsi/orchestrator/nara_lane.py` binds only the worktree and the
   venv, runs `--unshare-net --clearenv`, and chdirs to the worktree: the main checkout, the live
   `/home/decross1/projects/a_bgt_rsi/run_state/` and `systemctl` do not exist in there. **Rewritten** to take `--root <dir>`, build
   its own fixture in `tmp_path`, take service status as an argument or env var so no service
   call is made, and read git heads from a `git init` fixture repo. It now asserts specific
   fixture values and byte-identical stdout, not mere key presence.
   Verified by running it *inside* the real sandbox: 14 collected, 14 failed, and the lane's own
   verdict line `junit tests=14 failures=14 errors=0 acceptance_passed=0`. Red for the right
   reason, in the place it will actually run.
4. **I had queued up to commit another session's work.** The loop's files are uncommitted on
   branch `claude/flash-262k-oracle-nara-20260922` in the main checkout
   (`git branch --show-current` today; `git status --short | grep -v '^??' | wc -l` → **12**, not
   the 13 my first plan stated). Stage 0 puts merges on main in the interactive session. **Rerouted.**
5. **A unit-name collision and an acceptance check that accepted failure.** The first plan proposed
   `oracle-daily-planning.{service,timer}`, which already exists as the sealed agenda timer
   (`systemctl --user list-timers --all` → next fire 2026-09-23 01:00:00 UTC) and which the same
   plan's own not-doing list said must not be retired. Renamed to `oracle-daily-loop.*` and
   `meta-oracle-review.*`; the clause "at least one run with a non-environment-file failure" —
   which a *failed* run satisfies — was replaced by three conditions that a failure cannot pass.

## What I did not do, and who owns it

- **The loop's uncommitted files.** Not mine to commit. Hand-off: the interactive session on
  `claude/flash-262k-oracle-nara-20260922` commits them, and that same interactive session
  merges to main — the meta-oracle does not merge on headless runs (`agent/prompts/meta_oracle.md`,
  Hard rules; corrected per review `claude-4d41f416d56c4620`, which also noted an earlier
  draft of this note named the meta-oracle as the merge owner).
  Until that happens, `git diff`-based review still has nothing to diff for C4/C5, and
  §8 step 2 ("commit today's work so branches start from a known main") stays open — owned by
  that session, not by me.
- **The research focus.** `/home/decross1/projects/a_bgt_rsi/run_state/research_focus/1b511ec62de4c66b3bde5e66b29d10ca3c418cb1fde107b3a9500edcc03c2974.json` has
  `execution_authorized: false` and `intake_policy: focus_before_new_topics`; its `next_gate`
  artifact `THESIS_DISPOSITION.md` has not moved since 2026-09-21 (newest focus file mtime
  2026-09-21 01:43:35Z), and no cycle has run since `iter-2026-09-20-006`. Advancing it is a
  research gate: asked, not acted on (seq 17).
- **Merging, pausing, timers, lane policy, serving config.** All outside my authority.
  Nothing was merged today by me, including this branch.

## Two surprises, stated plainly

- **The mailbox 16 KiB row limit and the lane's 8 KiB test limit bind together.** My first
  sandbox-correct packet test was 10,749 bytes and could not be posted at all — the failure was
  caught by an `assert` in my own prep script, not by the mailbox. The test was rewritten to
  8,181 bytes with the same 14 cases and the same assertions, and re-verified red in the sandbox.
  Worth knowing before I write a bigger acceptance test: the size budget is a real design input,
  not a lint.
- **A `deferred` lane item is a correct outcome, not a stall.** `nara-lane:oracle-1a4209d20d2ab923`
  logged `deferred` because no review has accepted seq 18 yet. That is the Stage 0 gate working.
  It also means today's dry run proves the *gate*, not the *build*: C3 is still unbuilt, and the
  lane's first real build lands no earlier than the review of seq 18.

## Open when this was written

0. **Deviation from this item's written acceptance check, stated rather than
   restated.** d1's acceptance allowed evidence citing only mailbox rows with
   `seq <= 14`; this note cites seq 15–18 as well, because the amend verdict and
   the deferred lane row are the dry run. The written check was not narrowed to
   fit — it was overtaken by the day. Reported here per review
   `claude-4d41f416d56c4620` finding 1, which asked for the deviation to be
   reported instead of the check being silently rewritten. Rows cited: seq 15
   `claude-4a2cf0e7b8a252eb`, seq 16 `oracle-1f07e40ff183ec79`, seq 17
   `oracle-0eb4b4117656adad`, seq 18 `oracle-1a4209d20d2ab923`.

1. Owner answer to `oracle-0eb4b4117656adad` (A or B) — the only thing that clears the red,
   and Wednesday's seven-day-plan exit depends on it.
2. Meta-oracle review of `oracle-1a4209d20d2ab923` (d4), which the lane is waiting on.
3. The interactive session's commit of the loop's own files.
4. C6 timers, uninstalled; Stage 0 → Stage 1 needs 5 consecutive clean days and days only
   accumulate unattended.
