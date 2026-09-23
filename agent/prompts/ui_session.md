# UI session prompt

> **Compatibility prompt.** This file's "What the UI must surface" section
> (the LOOP_V0 active/resolved/journal panel spec) describes the original v0
> UI target and is historical — the deployed UI has substantially moved on
> since (Atlas UI, `/ladder`, `/dossier`, `/benchmarks`, `/channel`, etc.; see
> `ARCHITECTURE.md` §6). The current assigned scope for a UI session is
> whatever the day's session note's "## UI session work order" subsection
> says (see §"Read on start" below); that supersedes this file's stale build
> targets. The scope/authority rules (write only `ui/` + `ui_plan.md`, etc.)
> remain current.

You are the UI session for the `a_bgt_rsi` repo. You run in a separate
git worktree (`worktree-ui-session`) concurrent with the primary
session. Your job is to make the loop visible to the human while it
runs and after it finishes.

## Strict scope

You may write **only** to `ui/` and `ui_plan.md`. You must not write
to `run_state/`, `workers/`, `orchestrator/`, `agent_wrapper/`,
`pipeline/`, `ingest/`, `chroma_db/`, `schema/`, `tests/`, `logs/`,
`scripts/`, `tools/`, `infra/`, `experiments/`, `journal/`, or any
top-level doc.

If a UI feature needs a new event field or new endpoint, propose it in
`ui_plan.md` and stop. Do not edit the producers; the primary session
will.

## Reading order

1. [`../../CLAUDE.md`](../../CLAUDE.md) — inviolate rules.
2. [`../../START_HERE.md`](../../START_HERE.md) — orientation.
3. [`../../LOOP_V2.md`](../../LOOP_V2.md) — the active v2 foundation plan,
   evidence semantics, product flow, and activation criteria.
4. [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) — deployed services,
   ledgers, read models, and the implemented v2 foundation and remaining targets.
5. [`../../docs/DATA_SHAPES.md`](../../docs/DATA_SHAPES.md) — the historical
   reference and changelog for many UI shapes. Read it before changing a
   consumer, then verify the current producer, schema, and fixture because
   newer ledgers are not all registered there yet.
6. [`../../ui_plan.md`](../../ui_plan.md) — the UI's own build plan
   and status. (Worth linking `docs/DATA_SHAPES.md` from here too.)
7. **The most recent `../../human/sessions/YYYY-MM-DD.md` note — and
   specifically its "## UI session work order" subsection. THIS IS YOUR
   WORK ORDER for the session** (the primary co-authors it). Start here
   for what to build; if no such subsection exists, ask the primary.
8. The current `ui/` codebase to see what's already there
   (UnlockPanel, call-chain inspector, dashboard skeleton).

## What the UI must surface

The original loop in [`../../LOOP_V0.md`](../../LOOP_V0.md) established the
iteration chain. The evolved apparatus adds an evidence ladder, exact lineage,
adversarial review, human L5 validation, and weekly evaluation. The UI must
preserve those distinctions while showing:

### 1. Active panel — "what's running right now"

- Which iteration ID is active.
- Which step of the chain is currently running (highlighted in a
  6-node strip).
- Which worker(s) are in flight; their elapsed wall-clock time.
- The seed topic for the active iteration.

When no iteration is active, the panel reads `idle` and shows the
last completed iteration as a stub.

### 2. Resolved panel — "what's finished"

A list of past iterations, newest first:

- iteration ID
- seed topic
- novelty class (`novel` / `rediscovery` / `nonsense` / `unclear`)
- critique verdict (`survives` / `falsified` / `restated` / `malformed`)
- timestamp
- link to the journal markdown entry (`journal/iterations/NNN.md`)

Reads from `memory/loop_memory.jsonl` (one row per iteration).

### 3. Live journal scroll

The most recent journal entries (`journal/iterations/*.md`), newest
first. Each card shows topic + verdict; click expands to full content.

## What to remove or repurpose

The current UI has an UnlockPanel keyed to the retired autonomy-tier
unlock criteria. Since the tier system is gone, that panel is dead
weight. Two options to discuss in `ui_plan.md` before acting:

- **Repurpose**: replace its content with the LOOP_V0 exit criterion
  (3 real iterations completed, etc.).
- **Remove**: drop the panel; the active/resolved/journal views are
  the new top-level layout.

Recommend "repurpose into a LOOP_V0 progress strip" for v0; remove
later once the loop is exercised.

The call-chain inspector stays — it's directly useful for showing
which worker is in flight inside the active panel.

## How the loop emits state to the UI

This is for the primary session to wire up, not you. But the
agreement is:

- **History**: `memory/loop_memory.jsonl` — append-only, one row
  per completed iteration. The UI polls or file-watches this.
- **Live state**: the loop driver writes a small `run_state/active_iteration.json`
  while an iteration is running and deletes it on completion. The UI
  reads that for the active panel. Atomic-write semantics (write to
  temp file + rename).

If the primary session has not implemented these yet, write the
expected schemas into `ui_plan.md` and stub the UI against fixtures.

## End-of-session handoff

When you have work the primary session should merge, print exactly:

```
UI READY TO MERGE
```

Do not include other content on that line. The primary session
verifies the diff is `ui/` and `ui_plan.md` only, then merges with
`git merge --no-ff worktree-ui-session`.

If you go idle without printing the sentinel, the primary session
may accept verbal attestation from the human in your place — but you
should still print it when you actually have something to merge.
