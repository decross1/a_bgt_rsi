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

## Current state — 2026-09-14

- One DGX Spark hosts two resident local endpoints: Gemma on `:8000` and
  Qwen3.8 on `:8001`.
- Nara runs as an event-driven user service. Its coordinator is bounded by a
  lock, ratification sentinel, human pause file, unified-memory preflight, and
  daily action budget. Hourly cron uses the same lock and gate ladder.
- Research claims move through the L0-L5 evidence ladder. Only L4+ can surface;
  only an explicit human verdict earns L5.
- The weekly upgrade controller runs Sunday at 05:30 UTC in review-only mode.
  It may use two subscription frontier sessions to propose and challenge one
  bounded hypothesis. It cannot promote production automatically.
- Named generation profiles exist as explicit evaluation arms. Legacy calls
  that do not select a profile retain their existing deterministic behavior.
- The v2 foundation adds immutable campaign identity, explicit lifecycle receipts,
  legacy isolation, and a measured research funnel. Runtime activation is an
  exact hash-bound pointer; consult `/benchmarks` and
  `run_state/v2_preparation/deployment_receipt.json` for adoption evidence.
- The prepared first campaign is `v2-agentic-game-theory-20260914`. It asks how
  individual versus shared payoff objectives and access to player-identified
  interaction history affect cooperation and utility-consistent behavior in
  repeated public-goods games among model agents. Its 324 CPU records are 81
  scripted-policy assignments under four objective/observation invariance
  conditions, not 324 independent behavior samples. They made no model calls;
  the narrower one-model-seat study remains gated.

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
curl -fsS http://127.0.0.1:8700/api/health
curl -fsS http://127.0.0.1:8000/v1/models
curl -fsS http://127.0.0.1:8001/v1/models
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
