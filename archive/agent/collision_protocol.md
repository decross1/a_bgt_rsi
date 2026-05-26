# Agent collision protocol

> How concurrent agents claim files before writing, so that N
> simultaneous agents (Phase-2 target: ~80% of new code via
> orchestrator-dispatched agents) can build the system without
> stepping on each other.
>
> Companion to [`agent/ownership.yaml`](ownership.yaml) (which paths
> belong to which zone) and [`agent/autonomy.md`](autonomy.md) (the
> autonomy framework).

---

## 1. The claim/lock log

File: `run_state/claims.jsonl` — append-only, owned by no one, written
by every agent that intends to write a file.

### 1.1 Claim entry shape

```json
{
  "timestamp": "2026-05-23T14:12:03Z",
  "agent_id": "claude-track-c-day6-quicklook",
  "zone": "experiments",
  "paths": [
    "experiments/exp001_repeated_pd/quicklook.py",
    "tests/test_quicklook.py"
  ],
  "intent": "write",
  "expires_at": "2026-05-23T16:12:03Z"
}
```

Required fields: `timestamp`, `agent_id`, `zone`, `paths`, `intent`,
`expires_at`. The `agent_id` follows the convention
`claude-track-<X>-<short-task-slug>` for manually-launched sessions,
or `claude-dispatched-<task-id>` for orchestrator-dispatched agents.

### 1.2 Release entry shape

```json
{
  "timestamp": "2026-05-23T15:42:11Z",
  "agent_id": "claude-track-c-day6-quicklook",
  "intent": "release",
  "claim_timestamp": "2026-05-23T14:12:03Z"
}
```

A release references the original claim by its `timestamp`. Releasing
is mandatory on commit. If an agent crashes without releasing, the
claim's `expires_at` eventually clears it.

### 1.3 Defaults

- **Default expiry:** 2 hours from claim time.
- **Maximum expiry:** 8 hours. A longer-running task must re-claim
  on a renewed timestamp.
- **Renewals:** append a new claim referencing the same `agent_id` +
  `paths`; the old claim implicitly closes when the new one lands.

---

## 2. The protocol — what every agent must do

### 2.1 Before writing any file

1. **Read** `agent/ownership.yaml` and resolve the file's zone.
2. **Verify dispatchability**: if you are a dispatched agent (not
   Track A in a primary zone), confirm the zone has
   `dispatchable: true`. If not, abort and escalate.
3. **Scan** `run_state/claims.jsonl` for the most recent non-released,
   non-expired claim covering any of the paths you want.
   - If a claim by a *different* agent exists, **wait or escalate**
     (do not write). Acceptable waits are short (≤ 5 min); past that,
     escalate to the human via the soft-gate path.
   - If no overlapping claim exists, proceed.
4. **Append your claim** to `run_state/claims.jsonl`. Use a 2-hour
   expiry unless you have reason to extend.
5. **Write the file(s).** Stay within the claimed paths — claim
   discipline only holds if no agent writes outside its declared
   `paths`.
6. **Commit the work.** Use the conventional commit message format
   for your track (`track-<X> day<N>: <summary>` or
   `dispatched task-<id>: <summary>`).
7. **Release** by appending a `release` entry to `claims.jsonl`.

### 2.2 What "scan claims.jsonl" means concretely

```bash
# Last 50 lines is almost always enough — old claims are released or expired.
tail -n 50 run_state/claims.jsonl | jq -c '
  select(.intent == "write")
  | select(.expires_at > now | tostring)
  | select(.paths | any(. == "<file-i-want-to-write>"))
'
```

In practice, agents call a helper: `tools/claims_check.py
--check <path>` exits 0 if the path is claim-free, 1 if held, 2 if
held-but-expired (safe to claim).

### 2.3 What Track A does differently

Track A has unconditional primacy on its primary zones (see
`ownership.yaml` `dispatchable: false`). It does **not** need to claim
when writing to those zones. It still:

- Appends a claim before writing to **shared** zones (docs, schemas,
  tests it doesn't author module-tests for).
- Acts as the rectifier: if `claims.jsonl` has a malformed line or a
  protocol violation, Track A fixes it and logs the fix in
  `run_state/week1.run.jsonl`.

---

## 3. Phase-aware concurrency unlocks

Parallels [`agent/autonomy.md`](autonomy.md) §3 but for *who can
dispatch*, not for *what's autonomous*. Same alignment evidence
(`autonomy.md` §4) gates both axes; they advance independently.

| Phase | Concurrent agents (typical) | Who dispatches |
|---|---|---|
| **Week 1** | 4 (A/B/C/D) | Human launches each manually via `claude --worktree dayN-<track>` |
| **Week 2 unlock** | 4–6 | Human still launches; orchestrator can dispatch *one* coding agent per day to a dispatchable zone |
| **Weeks 3–4 unlock** | 6–8 | Orchestrator can dispatch up to 3 concurrent coding agents; human attests the queue weekly |
| **Phase 2 entry** | 8–12 | Orchestrator dispatches autonomously; human attests weekly via UI |
| **Phase 2+** | unbounded | Orchestrator dispatches; human spot-checks; ~80% target |

The dispatch unlock at each phase requires, in addition to the
alignment evidence from `autonomy.md` §4, **a claim-protocol-clean
week**:
- Zero overlapping claims across the window.
- Zero expired-claim writes (writing past `expires_at` without renewal).
- Zero merge conflicts caused by ownership-zone violations.

`tools/claims_check.py --weekly-summary` produces the figures the
weekly retrospective consumes.

---

## 4. Collision-avoidance disciplines (beyond the claim log)

Three additional rules, enforced by convention and merge-time review:

1. **Worktree-per-task.** Every dispatched agent gets its own git
   worktree (extends the existing `claude --worktree <name>` pattern).
   No two agents share a working tree. Merge conflicts surface at
   integration time, not at edit time.

2. **Append-only state files.** `run_state/*.jsonl` files are
   append-only by every agent except Track A. Track A is the
   rectifier — it can rewrite if a malformed line appears. Other
   agents that need to log progress write to `notes/<agent-id>.log`.

3. **`plan.yaml` is read-only for dispatched agents.** Only Track A
   modifies `plan.yaml`. Dispatched agents read it to understand task
   specs. This prevents two agents both editing the canonical plan.

---

## 5. Orchestrator-dispatched agents (Phase 2 plumbing, Week 2 deliverable)

The Week 2 deliverable that makes ~80% of dev driven by orchestrator
dispatches possible is `agent_wrapper/dispatch_coding_agent.py`
(scheduled for Day 39 — see
[`PHASE_1_ROADMAP.md`](../PHASE_1_ROADMAP.md) §2.3). Signature:

```python
def dispatch_coding_agent(
    task_spec: dict,           # zone, paths, work description, success criteria
    worktree_prefix: str,      # "auto-task-NNN-{zone}"
    timeout_minutes: int = 120,
    autonomy_tier: str = "soft_gate",
) -> DispatchResult: ...
```

The dispatcher:

1. Resolves `task_spec.target_zone` to a path glob via `ownership.yaml`.
2. Spawns a Claude Code session in a fresh worktree (`claude --worktree
   <worktree_prefix>-<short-task-id>`).
3. Hands the session a prompt assembled from
   `agent/prompts/dispatched_task.md` + the task spec.
4. Appends a `dispatch` event to `run_state/week1.run.jsonl` (Track A
   is the writer, on behalf of the orchestrator).
5. Monitors the worktree for sentinel completion (the dispatched
   agent prints `DISPATCHED TASK <task-id> COMPLETE — ready to merge`).
6. Returns a `DispatchResult` describing the merge candidate.

The dispatcher does NOT auto-merge. Track A merges, after running
that day's validations on the merged files.

---

## 6. What this protocol is NOT

- **Not** a substitute for human review on hard-gates. The claim
  protocol prevents collisions; the autonomy framework prevents
  unwarranted advancement. They are orthogonal.
- **Not** a CAP-theorem-style distributed consensus. There is a single
  shared `claims.jsonl` on a single filesystem; the protocol is
  optimistic and informational, not transactionally enforced.
- **Not** a way for a side track to escape ownership-zone discipline.
  If a side track claims a path in a zone it doesn't own,
  `tools/claims_check.py --validate-ownership` flags it; Track A
  rejects the merge.

---

## 7. Failure modes (specific to concurrent agents)

| Symptom | Likely cause | Fix |
|---|---|---|
| Two agents wrote to the same file; merge conflict | One agent skipped the scan-claims step, or both claimed simultaneously and neither saw the other | Track A's version wins. Audit the offending agent's logs. Tighten its prompt to include the scan-and-claim sequence. |
| `claims.jsonl` has a malformed line | Agent crashed mid-write | Track A rectifies (replace the line with a `# corrupted at <ts>` comment); the affected work is re-done. Log a `claim_log_rectify` entry. |
| A claim's `expires_at` passed but the file was still being written | Long-running task didn't renew | The agent should have renewed at the 50% point. After the fact: log the violation in the weekly retrospective; if it happens twice in a week, the claim-protocol-clean check fails and the dispatch unlock doesn't advance. |
| Stale claim sitting at expiry past 24h | Agent crashed without releasing | `tools/claims_check.py --gc` removes claims whose `expires_at` is > 24h in the past. Run on the same cron as `gate_sla_check.py`. |
| A dispatched agent claimed a non-dispatchable zone | Protocol violation | `tools/claims_check.py --validate-ownership` flags. Track A rejects any commit from that worktree. The dispatcher logs the rejection. |
