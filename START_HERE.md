# Start here

This is the shortest reliable orientation to `a_bgt_rsi`. It separates what is
deployed, what is being prepared for v2, and what remains a historical record.

## Read in this order

1. Read the user's current request and your assigned scope.
2. Read checkout-local `AGENTS.md` for Codex repository authority or
   [`CLAUDE.md`](CLAUDE.md) for Claude's operating contract.
3. Read this file and the newest relevant note under
   [`human/sessions/`](human/sessions/).
4. Read [`LOOP_V2.md`](LOOP_V2.md) for the v2 foundation and subsequent study work.
5. Read [`ARCHITECTURE.md`](ARCHITECTURE.md) for the deployed system and data
   boundaries.
6. Consult [`DECISIONS.md`](DECISIONS.md) when a choice or apparent conflict
   matters. The most recent accepted decision wins over the older decision it
   supersedes.

`LOOP_V1.md`, `LOOP_V0.md`, `PROJECT_CONTEXT.md`, and the v5 diagrams are
valuable historical inputs. They contain dated implementation claims and are
not a substitute for current code, validated receipts, or a live health check.

## Current state — 2026-09-23

- One DGX Spark hosts one resident local model, Flash
  (`nvidia/Qwen3.8-Flash-Next-NVFP4` on SGLang, `127.0.0.1:30080`, 262,144-token
  context, one running request; two-request serving is prepared, see
  `docs/FLASH_C2_CUTOVER.md` on branch `claude/flash-c2-prep-20260923`). The prior
  Gemma/Qwen vLLM pair (`:8000`/`:8001`) stopped 2026-09-19 and is a rollback only.
  See `docs/FLASH_RESIDENT.md` and `docs/MODEL_TOPOLOGY_POLICY.md`.
- Three actors coordinate the lab: **Oracle** (Pi on Flash) plans the day and
  develops architecture, UI, contracts and its own system; **Nara** runs research
  continuously (`nara-daemon` plus the hourly cron; no daily cap since D-085) and
  builds lab tools through the lane (`orchestrator/nara_lane.py`, a bwrap sandbox,
  `nara/<id>` branches); the **meta-oracle** (Claude Opus 5.5,
  `tools/meta_oracle_run.sh`) reviews every plan, plan item and branch and merges
  accepted work. They coordinate through the lab mailbox
  (`run_state/oracle_nara_mailbox.jsonl`, `docs/ORACLE_NARA_MAILBOX.md`); the daily
  loop is `docs/META_ORACLE_DAILY_LOOP.md`. See D-082 and D-084 to D-087.
- Nara's coordinator is bounded by a lock, ratification sentinel, human pause file
  and unified-memory preflight; the hourly cron uses the same lock and gate ladder.
- Research claims move through the L0-L5 evidence ladder. Only L4+ can surface;
  only an explicit human verdict earns L5. A thesis separately climbs T (theory,
  OpenSpiel), then S (semi-synthetic), then A (applied proposal, paper trade)
  per D-084. The owner's only required gate is live trading.
- The goal plan is `docs/v2/ALIGNMENT_AND_GOALS.md` (G0-G7); the research direction
  (information and beliefs), the refinement protocol and conviction scoring are in
  D-086, D-087 and `docs/v2/THESIS_BRIEF_2026-09-23.md`.
- The active campaign is `v2-daily-agentic-game-theory-20260917` (registered
  exploratory arXiv intake). No research focus is selected: the payoff-assistance
  line was killed on 2026-09-22 (closure receipt under
  `run_state/research_focus/closures/`), and successor theses (G1.1) are in progress.
- The weekly upgrade controller runs Sunday at 05:30 UTC in review-only mode. It
  may use two subscription frontier sessions to propose and challenge one bounded
  hypothesis. It cannot promote production automatically.
## Truth hierarchy

Use evidence in this order for the question it can answer:

1. **Explicit human instruction** sets task, research, publication, and runtime
   authority.
2. **Operating contracts** (`AGENTS.md`, `CLAUDE.md`) define session and
   maintenance boundaries.
3. **Latest accepted decision** in `DECISIONS.md` defines design intent.
4. **Current code plus validated immutable receipts** defines what was built or
   recorded.
5. **Live read-only checks** define what is running now.
6. **Architecture and loop documents** explain the system; dated historical
   plans do not override evidence above them.

Do not convert missing evidence into zero, a timeout into a failed scientific
claim, an operator summary into ground truth, or an L4 finding into a human
validation.

## Session start checklist

```bash
cd /home/decross1/projects/a_bgt_rsi
git status --short
git branch --show-current
git log -1 --oneline
ui/scripts/ui-services.sh status
systemctl --user show nara-daemon.service \
  -p ActiveState -p SubState -p MainPID -p ExecMainStartTimestamp
systemctl --user status flash-resident.service --no-pager
curl -fsS http://127.0.0.1:8700/api/health
curl -fsS http://127.0.0.1:30080/v1/models
```

Then inspect the files and receipts relevant to the task. Preserve all unrelated
working-tree changes. Do not restart services merely to establish status.

For a new Codex worktree, carry forward the canonical checkout's `.codex`
configuration, `AGENTS.md`, trust entry, and current rules before launching the
session. Standing Git authority covers ordinary repository delivery; it does
not grant a research verdict, unrelated deployment, scientific publication, model cutover, live
trading, or removal of a human pause.

## Where to look

| Need | Start here |
| --- | --- |
| Current research and next evidence rung | Local UI `/ladder` |
| A full finding or iteration record | Local UI `/dossier` or `/experiments` |
| Weekly benchmark and pipeline progression | Local UI `/benchmarks` |
| Current operational state | Local UI `/` and `/development` |
| Model calls and execution trace | Local UI `/model-io` and `/cycles` |
| Pause, restart, or recovery | [`docs/v2/OPERATOR_GUIDE.md`](docs/v2/OPERATOR_GUIDE.md) |
| Deployed components and data contracts | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Current v2 goal and activation bar | [`LOOP_V2.md`](LOOP_V2.md) |
| Current implementation envelope | [`docs/v2/IMPLEMENTATION_PLAN.md`](docs/v2/IMPLEMENTATION_PLAN.md) |
| Prior research and documents | [`docs/v2/RESEARCH_ARCHIVE.md`](docs/v2/RESEARCH_ARCHIVE.md) |
| Why an architecture choice exists | [`DECISIONS.md`](DECISIONS.md) |

## What to do next

Work the smallest evidence-backed unit that advances the assigned objective.
Keep model, runtime, inference-policy, scaffold, and data-model changes
separable so a measured gain can be attributed. Run the checks appropriate to
the change and write a durable receipt when the change affects runtime or
scientific evidence.

Distinguish source implementation, campaign runtime activation, controlled
model-study execution, and validated scientific outcomes. For an ordinary
campaign iteration verify the active campaign hash and existing research gates.
For a controlled model study additionally verify its own frozen execution
manifest, literature/novelty checks, analysis plan, and resource reservation.
