# Oracle ⇄ Nara build-out plan (2026-09-22)

Owner direction (DECISIONS.md D-082): Oracle sets the plan and develops the lab
itself, the UI, Nara's capabilities and its own long-term memory. Nara runs the
lab and implements Oracle's plan. This plan finishes three pieces of that split:

- **A.** Update Oracle's rules and charter to the new roles.
- **B.** Resize Oracle's planner and Pi session for 262K context and the 10 GiB reserve.
- **C.** Add a mailbox panel to the UI, with work cards and accomplishments built from
  Nara's receipts.

## 1. Who does what

| Party | Role in this plan |
|---|---|
| **Oracle (Pi session on local Flash)** | Orchestrator. Reads this plan, sequences work, edits `oracle_system`, `ui/` and Nara's capabilities in `orchestrator/` on branches, writes Nara's plan items (including their failing tests), reviews Nara's branches, posts progress to the mailbox. |
| **Nara (lane)** | Implements fenced plan items: pure modules, tools, tests and docs under `docs/ tests/ tools/ bench/ experiments/ workers/ notes/`. Builds on `nara/<id>`, never merges. See `docs/ORACLE_NARA_MAILBOX.md`. |
| **Owner (Derrick)** | Ratifies authority changes (charter, AGENTS rules, decisions), runs service changes, approves merges to `main` until A is ratified. |
| **Claude (primary session)** | Oversight at each milestone and the final review. Reads mailbox notes addressed to `claude` or `all`, replies in the mailbox. |

Tags used below: **[ORACLE]** Pi does it; **[NARA]** posted as a mailbox plan item;
**[OWNER]** only the owner can do it; **[REVIEW]** Claude checkpoint.

## 2. Operating rules for this plan

1. **The mailbox is the shared state.** Oracle posts a `note` to `all` when it starts
   and finishes each task (ID, branch, result), a `question` to `owner` for each
   [OWNER] step, and a `note` to `claude` titled `READY FOR REVIEW: <milestone>`.
   CLI: `python -m orchestrator.oracle_mailbox post --as oracle ...` from the lab checkout.
2. **Branches, not main.** Oracle works on `oracle/<task-id>` branches in its own
   worktree (`git worktree add ../a_bgt_rsi_worktrees/oracle-<task-id> -b oracle/<task-id>`).
   Nothing merges to `main` without the verification gate (§8) and, until A is
   ratified, the owner's go-ahead.
3. **Do not touch** without the owner: `flash-resident.service`, the frozen helpers
   under `sglang-fallback-prep/`, `config/model_deployment.json`, any `run_state/pause_*`
   file, `research_focus.select_focus` (stays operator-only), `DECISIONS.md` entries
   other than the new ones this plan names, `human/`, `journal/`.
4. **One Flash request at a time.** A 250K-token prompt blocks every other client for
   about two minutes. Before a prompt over 64K tokens, check that Nara's lane is idle
   (`python -m orchestrator.nara_lane status` shows nothing `claimed`).
5. **After any merge touching `orchestrator/`,** restart `nara-daemon` (owner or
   operator) so it does not run stale code.
6. **Logging.** Every executed step appends a row to `run_state/week1.run.jsonl` with
   `agent` `oracle`, `nara` or `claude-code-main`.
7. **Stop conditions.** Any test regression, a failed verification gate, a guard stop of
   Flash, or an unclear authority question: stop, post a `question` to `owner`, wait.

## 3. Phase 0 — prerequisites (before any workstream)

| ID | Tag | Step | Done when |
|---|---|---|---|
| P0.1 | [OWNER] | Commit today's work (262K deployment, supervisor evictor, eval driver, mailbox, lane, tests, docs) to `main` after Claude's review, so Nara's worktrees (cut from `HEAD`) include it. Decide separately about other sessions' uncommitted edits (`CLAUDE.md`, `DECISIONS.md` D-078..D-081, `LOOP_V1.md`, `START_HERE.md`, `docs/packet_sdlc.md`). | `git status` shows today's files committed; full suite green on `main`. |
| P0.1a | [OWNER] | The lane has been paused since 17:10 UTC on 2026-09-22 (`run_state/pause_nara_lane`) while a review-found sandbox escape was fixed (D-082 correction). Remove the pause after Claude's mailbox `note` says the fix is verified. | `python -m orchestrator.nara_lane status` runs and no `pause_*` file remains. |
| P0.2 | [OWNER] | Start a fresh Pi session in `oracle_system` and point it at this plan, D-082 and `docs/ORACLE_NARA_MAILBOX.md`. | Pi posts `note` "Oracle orchestrator started" to `all`. |
| P0.3 | [ORACLE]+[OWNER] | Resize the Pi client first (task B1 below): without it the session compacts above ~24.6K tokens and its 4,096-token summary cap fails. | Pi restarted on the new settings; `/context` shows a 262,144 window. |
| P0.4 | [ORACLE]+[OWNER] | Rebind Oracle's Pi mailbox (task B2 below) so the UI's "Ask or change the plan" stops returning 503. | `~/.local/state/oracle-pi-oversight/latest-status.json` is `active` for the new session. |
| P0.5 | [REVIEW] | Claude checks P0.1–P0.4. | Claude `note` "Phase 0 accepted". |

## 4. Workstream A — Oracle's rules and charter for the new roles

Why: four sources still say Oracle only observes the lab — `oracle_system/state/charter.json`
(`authority.a_bgt_rsi`: "observe directly; coordinate changes with Nara"),
`oracle_system/docs/ARCHITECTURE.md:34-38` and `:127-130`, lab D-067 (observer-only
steward), and `docs/daily_lab_workspace.md:5` / `ui/backend/daily_ops.py:488-489`
("Nara is observed state"). The charter is owner-ratified; the harness reserves
`human_confirmed` (`oracle_harness/integrity.py:402-404`), so Oracle can draft but not ratify.

| ID | Tag | Step | Files | Done when |
|---|---|---|---|---|
| A1 | [ORACLE] | Draft charter SCOPE v1.1: Oracle plans and develops the lab, the UI, Nara's capabilities and its own memory; Nara is the lab's implementor and only scheduler; Oracle's plans are an input queue, never a second scheduler (keeps oracle AGENTS.md rule 4). Submit with `oracle_harness propose`. | `oracle_system/state/charter.json` (proposal only) | Proposal recorded; `oracle_harness validate` passes. |
| A2 | [OWNER] | Ratify A1 in the harness. | charter | `oracle_harness validate` shows the new SCOPE as confirmed. |
| A3 | [ORACLE] | Amend `oracle_system/AGENTS.md`: grant the Pi-on-Flash Oracle branch-only write access to `oracle_system`, lab `ui/` (only when no `ui-session` worktree is live) and Nara-capability code in `orchestrator/`; require the §8 gate for merges; plan items via the mailbox only; research content generated on local weights (D-061). Amend `docs/ARCHITECTURE.md:34-38,127-130` to match. | `oracle_system/AGENTS.md`, `oracle_system/docs/ARCHITECTURE.md` | Owner approves the diff (A4). |
| A4 | [OWNER] | Approve A3's text. | — | Owner `answer` in the mailbox. |
| A5 | [ORACLE] | Lab decision **D-083 — writer and ownership matrix**, recorded without impersonating the owner: Oracle owns `ui/`, `orchestrator/` (Nara capabilities), `schema/`, `cron/`; Nara owns the lane fence paths; single integrator for the orchestrator core (`nara.py`, `tool_registry.py`, the iteration schema); supersedes in part D-067 (observer-only), D-040 ("merges to main remain human" becomes "Oracle-reviewed merges of Nara branches after the §8 gate"), D-079 (names Nara branches), D-046 (non-human actor stamps via blessed CLIs); supersedes `docs/daily_lab_workspace.md:5` and the "Nara is observed state" rationale. Update the operating-model section of `CLAUDE.md` to name Oracle, Nara and Claude-oversight. | `DECISIONS.md` (append only), `CLAUDE.md`, `docs/daily_lab_workspace.md` | Owner approves; no remaining doc says Oracle only observes (`grep -rn "observer-only\|Nara is observed" docs CLAUDE.md`). |
| A6 | [ORACLE] | Oracle memory: record the owner's 2026-09-22 direction **verbatim** as a `decide` event (subjects `owner_goal`, `lab_purpose`) with `oracle_harness decide`; add an owner-goals/purpose section to `scripts/oracle-brief` output and to the planner packet (B3). Build memory only from verbatim owner directives, DECISIONS quotes, the charter and events — never summaries of `human/` or `journal/` writing (inviolate rule 9). | `oracle_system/state/events.jsonl` (via CLI), `oracle_system/scripts/oracle-brief` | `oracle_harness validate` passes; `oracle-brief` shows the goal section. |
| A7 | [OWNER] | Decide Oracle memory durability (open item D1): `state/events.jsonl` has 241 lines in the working tree but 23 at `HEAD`. Commit it, or back it up on a schedule. | — | Decision recorded; ledger durable. |
| A8 | [REVIEW] | Claude reviews A1–A7 for consistency with D-082, D-061 and the inviolate rules. | — | Claude `note` "Workstream A accepted". |

Nara has no A task: every file here is outside its fence.

## 5. Workstream B — resize Oracle's planner and Pi session for 262K

Facts: Flash serves 262,144 tokens with a 10 GiB host reserve and ~22 GiB available
at idle (`docs/MODEL_TOPOLOGY_POLICY.md`, context amendment). The Pi client still
advertises 32,768 with `maxTokens` 4096 (`~/.pi/agent/models.json`, model
`spark-flash`); project compaction reserve 8192 / keepRecent 4096
(`oracle_system/.pi/settings.json`), so the summary cap is 4,096 and length-stops kill
compaction. The planner release `4f154d6` hard-codes 32,768 context and a 24,000-byte
packet (`personal_agent/daily_planning.py:44,259`), requires 20 GiB MemAvailable
(`:302-319`), and only allows owners "Oracle or Codex" (`:67`). The one-shot
`oracle-agent` still points at `:8001` with 16K context (installed
`personal_agent/contracts.py:12-14`).

| ID | Tag | Step | Files | Done when |
|---|---|---|---|---|
| B1 | [ORACLE]+[OWNER restart] | (Client files applied by Claude on 2026-09-22 with backups `*.bak-20260922T170118Z`, including `~/.pi/agent/settings.json` compaction 32768/16384; they take effect when Pi next starts. Oracle verifies.) Pi client: set `contextWindow` 262144 and `maxTokens` 16384 for `spark-flash`; set project `reserveTokens` 32768 and `keepRecentTokens` 16384. The summary cap becomes 16,384, and compaction fires near 229K. | `~/.pi/agent/models.json`, `oracle_system/.pi/settings.json` | New session shows the 262K window; one deliberate compaction completes without a length stop. |
| B2 | [ORACLE]+[OWNER service] | Pi mailbox rebind: replace the hard-coded `OWNER_SESSION_ID` (`.pi/extensions/oracle-mailbox.ts:25`) with a binding file the owner updates when starting a session; update `session_id` in `~/.config/oracle-lab/daily-ops.json`; archive the `processing_failed` block for envelope `codex-20260921T011740Z-seven-day-plan-review` (re-send it if still wanted). | `oracle_system/.pi/extensions/oracle-mailbox.ts`, binding file, `daily-ops.json` | Status `active`; a UI "Ask Oracle" request returns 200. |
| B3 | [ORACLE] | New planner release: read the served context from `/v1/models` (or `config/model_deployment.json`) instead of 32,768; raise the packet cap with an explicit token budget (for example 64K tokens); set the memory floor from the lab's `HOST_RESERVE_GIB` plus 2 GiB instead of 20; allow task owner `Nara`; add the mailbox fold (open plan items, recent receipts) and the A6 owner-goals section to the packet. Keep it proposal-only, zero tools, sealed. Add tests in `oracle_system/tests`. | `oracle_system/personal_agent/daily_planning.py`, tests | Tests pass; a dry run prints context 262144, floor 12 GiB, and a task owned by Nara. |
| B4 | [OWNER] | Install B3 as a new immutable release and repoint `~/.config/systemd/user/oracle-daily-planning.service`. | unit file | Next 08:00 or 18:00 PT run seals an agenda with `context_tokens` 262144. |
| B5 | [ORACLE] | `oracle-agent`: endpoint `:30080`, model `nvidia/Qwen3.8-Flash-Next-NVFP4`, context 262144; pass `allowed_write_paths` through `cli.py`/`service.py` (source `9619b88` already has the router support). Reinstall. | `oracle_system/personal_agent/{contracts,cli,service}.py` | `oracle-agent --help` and one read-only task hit `:30080`. |
| B6 | [NARA] | Lab tool `tools/flash_serving_info.py`: given the JSON of `/v1/models` and the text of `config/model_deployment.json`, return `{context_tokens, host_reserve_gib, model}`; pure, no network. Oracle's planner and Pi config can call it to stay in sync. Plan item template in §9. | `tools/flash_serving_info.py`, `tests/test_flash_serving_info.py` | Nara receipt `validated`; Oracle reviews and merges. |
| B7 | [REVIEW] | Claude reviews B1–B6, including one real planner dry run and a long Pi session. | — | Claude `note` "Workstream B accepted". |

## 6. Workstream C — UI mailbox panel, work cards and accomplishments

Target: "Today's research path" shows the Oracle ⇄ Nara thread; each Oracle plan item
appears as a work card whose status comes from Nara's receipts; an accomplishment
appears only when a validated Nara branch is merged into `main`. Nothing is inferred
from prose; nothing on the page can approve, dispatch or execute
(`ui/backend/daily_ops_work_plan.py:3-7`). Today cards come only from a hand-curated
file bound to a volatile agenda revision (`daily_ops_work_plan.py:157-171`), so they
vanish when the agenda reseals.

Split: Nara builds the pure projection logic inside its fence; Oracle wires it into
`ui/` (outside Nara's fence). Before any `ui/` edit, Oracle checks `git worktree list`
for a live `ui-session`; if one exists, it writes a spec into the session note's
"UI session work order" instead.

| ID | Tag | Step | Files | Done when |
|---|---|---|---|---|
| C1 | [NARA] | `tools/mailbox_projection.py`: pure functions over `oracle_mailbox.fold()` output — `work_cards(fold)` maps plan items to `{id, title, what, owner:"nara", status}` with status open→authorized, held/failed→blocked, claimed→in_progress, validated→done (`awaiting_integration: true`); `accomplishments(fold, merged)` returns items whose receipt `head_sha` is in the set `merged`. Full template in §9. | `tools/mailbox_projection.py`, `tests/test_mailbox_projection.py` | Nara receipt `validated`. |
| C2 | [ORACLE] | Merge C1 after the §8 gate. | — | On `main`. |
| C3 | [ORACLE] | Backend: `ui/backend/oracle_mailbox_view.py` serving `/api/mailbox` (thread rows with actor, kind, to, summary; plan items with state and receipts; bounded to the last 200 rows; cached by file size+mtime). Merged-branch detection: `git merge-base --is-ancestor <head_sha> main` per validated item, cached. Register in `ui/backend/app.py`. Add `nara`, `claude`, `codex` to the actor set shown (`daily_ops.py:70`) without giving them approval paths. | `ui/backend/*`, backend tests | Backend tests pass (host namespace; the restricted namespace cannot run TestClient). |
| C4 | [ORACLE] | Bridge: in `daily_ops_bridge.refresh`, append mailbox-derived cards (labelled `source: mailbox`, author shown) after reviewed cards, independent of the agenda binding; append accomplishments from C1 with the receipt link. Reviewed cards keep their current rules. | `ui/backend/daily_ops_bridge.py`, tests | Page shows mailbox cards even after the agenda reseals. |
| C5 | [ORACLE] | Frontend: `MailboxPanel.tsx` on the research page — thread (who → whom, kind, time), plan items with state badges and branch/SHA, and a clear "read-only: posting happens through the mailbox CLI" label. | `ui/frontend/src/components/MailboxPanel.tsx`, `DailyOpsPanel.tsx`, vitest | Frontend suite passes; screenshots at 1440 px and a narrow width. |
| C6 | [ORACLE]+[NARA] | End-to-end: Oracle posts one small plan item; Nara validates; Oracle merges; the page shows the card move authorized → in progress → done → accomplishment. | — | Screenshots of each state attached to the mailbox note. |
| C7 | [REVIEW] | Claude reviews C1–C6. | — | Claude `note` "Workstream C accepted". |

## 7. Order and milestones

1. **M0** Phase 0 (P0.1–P0.5).
2. **M1** A1, A3, A5, A6 drafted in parallel by Oracle; A2, A4, A7 by the owner; A8 review.
3. **M2** B1–B2 were done in Phase 0; B3, B5 by Oracle and B6 by Nara in parallel; B4 owner; B7 review.
4. **M3** C1 by Nara first; then C2–C5 by Oracle; C6 together; C7 review.
5. **M4** Claude's final review (§8), then the owner's go-ahead to close the plan.

Workstreams B and C may start before A is ratified, but nothing from B or C merges to
`main` until A2 and A4 are done, because the authority for Oracle's edits comes from A.

## 8. Verification gate (every merge) and Claude's final review

For each branch before merge:

1. The framework code-review skill (`.agents/skills/code-review/`) over
   `git diff <merge-base>..<branch>`, with findings resolved.
2. Full suite green: lab `pytest` over git-tracked tests (see
   `human/sessions/2026-09-21.md` for the exact command); `oracle_system` tests; UI
   backend and frontend suites when `ui/` changed.
3. One real smoke with `env -u MOCK_LLM` for anything that calls Flash.
4. Branch author ≠ merger. Nara's branches are merged by Oracle; Oracle's by the
   owner until A is ratified, then by Oracle with Claude's review note.

Claude's final review (M4) checks: every task's "done when"; the full lab suite, the
`oracle_system` suite and the UI suites; that `run_state/oracle_nara_mailbox.jsonl`
verifies (`python -m orchestrator.oracle_mailbox fold` runs without a chain error);
that no invariant from §2 was broken (grep for edits to forbidden paths in the merged
range); one live loop (plan item → Nara → merge → accomplishment on the page); and
Flash health (262K, reserve 10 GiB, no guard stop during the work). The result is a
mailbox `note` to `all` and a written report under `notes/research/`.

## 9. Nara plan item templates

Oracle posts these with
`python -m orchestrator.oracle_mailbox post --as oracle --kind plan_item --to nara --body-file <file>`.
Oracle writes the test; it must fail before Nara's change.

**C1 — mailbox projection**

```json
{
  "title": "Project mailbox plan items into work cards and accomplishments",
  "objective": "Create tools/mailbox_projection.py with work_cards(fold) and accomplishments(fold, merged). fold is the dict returned by orchestrator.oracle_mailbox.fold(): msg_id -> {item, state, receipts}. work_cards returns a list ordered by item seq of {id, title, what, owner: 'nara', status, awaiting_integration}; status maps open->authorized, held->blocked, failed->blocked, claimed->in_progress, validated->done, withdrawn->withdrawn, expired->blocked; awaiting_integration is true only for validated. accomplishments returns [{id, title, branch, head_sha}] for validated items whose last receipt head_sha is in the set merged. Standard library only.",
  "task_class": "tooling",
  "allowed_write_paths": ["tools/mailbox_projection.py"],
  "acceptance": {
    "test_path": "tests/test_mailbox_projection.py",
    "test_content": "<Oracle writes: a fold fixture with one item per state, assertions on every status mapping, ordering, awaiting_integration, and an accomplishment only when head_sha is merged>",
    "test_argv": ["python", "-m", "pytest", "-q", "tests/test_mailbox_projection.py"]
  },
  "budget": {"attempts": 3, "wall_clock_minutes": 20}
}
```

**B6 — serving info**

```json
{
  "title": "Read Flash context and host reserve for clients",
  "objective": "Create tools/flash_serving_info.py with serving_info(models_json: dict, deployment_text: str) -> {context_tokens, host_reserve_gib, model}. context_tokens is data[0].max_model_len from the /v1/models JSON; host_reserve_gib and model come from the deployment JSON text. Raise ValueError when the two models differ or a field is missing. Standard library only; no network.",
  "task_class": "tooling",
  "allowed_write_paths": ["tools/flash_serving_info.py"],
  "acceptance": {
    "test_path": "tests/test_flash_serving_info.py",
    "test_content": "<Oracle writes: a matching pair returns 262144/10/model; mismatched model raises; missing field raises>",
    "test_argv": ["python", "-m", "pytest", "-q", "tests/test_flash_serving_info.py"]
  },
  "budget": {"attempts": 3, "wall_clock_minutes": 20}
}
```

## 10. Risks

- **Pi has no permission layer.** Its read/bash/edit/write tools run with full user
  access. Rules §2.2–§2.3 and the branch-only practice are the guard; Claude's
  checkpoints look for edits to forbidden paths.
- **Same-weights review.** Oracle reviewing Nara's code runs on the same model; the
  tests and the §8 gate carry the weight, and Claude's review is the independent check.
- **Contention.** Oracle's long prompts and Nara's builds share one request slot.
- **Attribution is unauthenticated.** Any local process can post as any actor; the
  hash chain shows tampering, not identity.
- **Research gates stay closed.** Nothing here changes the research focus, registers a
  study or promotes a finding.
