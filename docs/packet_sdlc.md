# Packet-execution SDLC — how coding work ships in this repo (LOOP_V1 P4)

This document codifies the software-delivery path that LOOP_V1 work already
follows in practice, so the packet dispatcher, the premerge gate, and every
future workflow run enforce the same path mechanically instead of by memory.
It is **self-contained**: it cites only this repo's own rules (CLAUDE.md
§Inviolate rules, §Dynamic Workflow discipline) and names the enforcing
artifacts by path. It does not replace CLAUDE.md; it makes its rules
executable for packet-shaped work.

## The pipeline

Every change larger than a trivial fix moves through the same six stages, in
order. No stage is skippable; each has a named enforcing artifact.

### 1. Slice

The primary session cuts the work into units with **disjoint NEW files only**
(CLAUDE.md workflow rule 2). Two unit shapes exist:

- **Workflow build agent** — an ephemeral Dynamic Workflow subagent under a
  spawn contract hand-appended to `run_state/spawn.jsonl` (a discipline, not a
  launch gate — workflow rule 3). Contract carries task statement,
  done-condition, `skill_subset`, authority cap, budget, reporting format.
- **Task packet** — a `tasks/packets/PKT-*.json` file validating against
  `schema/task_packet.schema.json`, dispatched by
  `orchestrator/packet_dispatcher.py` and ledgered in `run_state/packets.jsonl`
  (machine-enforced two-line open/close; `spawn.jsonl` stays a discipline —
  the two ledgers' semantics are deliberately not mixed).

Either way the unit names its files-in-scope up front; the **shared spine**
(`orchestrator/nara.py`, `orchestrator/tool_registry.py`,
`schema/iteration_record.schema.json`), `run_state/`, and `ui/` (when a
ui-session worktree is live) are never in a build agent's scope. Spine edits
belong to the single serial integrator only.

### 2. Build

Agents build in parallel — each produces its worker + its test, hermetic
under `MOCK_LLM=1` (tmp_path ledgers, no network, no real CLI or model
calls). Bounded codegen (inviolate rule 8) applies: match neighboring files'
norms; the ~100-line figure is the *wrapper* budget, not a per-worker cap.
Packet-dispatched work additionally runs **red-first**: the dispatcher
verifies the acceptance test FAILS before the agent starts
(`acceptance_criteria.must_fail_before: true` — a test that already passes
proves nothing, rule 4).

### 3. Review — the framework `code-review` skill on the local range

The verification gate is the **framework `code-review` skill**
(`.agents/skills/code-review/`, symlinked from
`/home/decross1/projects/agent_system/.agents/skills/code-review/`) run over
the local commit range:

```
git diff <merge-base>..HEAD
```

This is explicitly **NOT** the Claude Code `/code-review` GitHub-PR builtin.
That builtin reviews an open PR; with no PR open it no-ops and yields a
falsely-clean gate (workflow rule 4 records this trap). If the review tool
reports nothing, first confirm it actually saw the diff.

Before review, `tools/premerge_check.sh` runs as the zero-LLM mechanical
pre-gate: it FAILS on protected-path touches (spine files, `schema/`,
`run_state/`, CLAUDE.md, DECISIONS.md, `cron/serve-models.sh`, `agent/`,
`ui/` when a ui-session worktree is live, version-pin strings), deleted or
skipped tests, banned patterns, and diffs over the packet's
`max_diff_lines` budget. For packets the **dispatcher, never the agent**,
runs the acceptance test and `premerge_check.sh`.

### 4. Verify

Two runs, both mandatory, neither substitutes for the other:

1. Full suite green: `MOCK_LLM=1 .venv-chroma/bin/python -m pytest tests/ -q`
   (report the count — a shrinking count is a finding, not noise).
2. **One real smoke** with the mock stripped: `env -u MOCK_LLM <smoke cmd>`.
   `MOCK_LLM=1` silently stubs embedders and CLIs (inviolate rule 10); a
   suite that never leaves mock has never exercised the real seam.

Validation results are never coerced (rule 4): below-band is a failure, and
a near-miss is reported as the failure it is.

### 5. Merge — primary session only

The **primary session is the single merge/commit authority** (workflow
rule 4). Workflows and dispatched agents return reports and branches
(`pkt/<id>` for packets); they never merge, never commit to main, never
push. The primary self-merges only after stage 3 + stage 4 pass, subject to
the entrenchment tiers below.

### 6. Record

- Run-log entries to `run_state/week1.run.jsonl` for phase/agent start+finish
  (inviolate rule 6; `agent` as `workflow:<wf_id>/<role>` or the packet
  dispatcher's identity).
- Spawn-ledger close lines (`status: completed|escalated` with the
  done-condition check) / packet-ledger close lines.
- A DECISIONS.md entry when the work embodies a decision; the `narrate`
  skill at workflow synthesize; `propose` only when a durable lesson
  warrants it (both dev-time only — the runtime never touches the brain,
  D-014).
- Human overrides of any gate land in `run_state/overrides.jsonl` as
  `{timestamp, actor, packet_id, action, rationale}` via
  `orchestrator/override_log.py` — an override is logged, never silent
  (rule 7).

## Entrenchment tiers

> **Status: DRAFT — pending G4 human ratification.** Until the human
> ratifies (logged in `run_state/overrides.jsonl` or DECISIONS.md), this
> table is the working norm the premerge gate encodes, not settled law.

| Tier | Paths / artifacts | Merge bar |
|---|---|---|
| **P — Periphery** | `workers/`, `tools/`, `tests/`, `docs/`, `bench/`, `experiments/` | Green suite + framework code-review on the local range. Primary self-merges. |
| **S — Spine / settled** | `orchestrator/nara.py`, `orchestrator/tool_registry.py`, `schema/`, version pins (ARCHITECTURE.md §2), promotion-bar constants, CLAUDE.md, DECISIONS.md, `cron/serve-models.sh`, `run_state` semantics | Everything Tier P requires, **plus explicit human ratification**, logged in `run_state/overrides.jsonl` or as a DECISIONS.md entry. No agent — workflow, packet, or primary acting alone — entrenches Tier S. |

The tier of a change is decided by the *most* entrenched path it touches: a
diff spanning `workers/` and `schema/` is Tier S. `tools/premerge_check.sh`
enforces the Tier S path list mechanically by failing any packet diff that
touches it; the human-ratification route is the only way through, and it is
logged.

## Why this shape

The pipeline is the inviolate rules made concurrency-safe: disjoint files
keep parallel limbs from racing the spine; red-first keeps acceptance tests
honest; the local-range review closes the no-PR-no-review hole; the real
smoke closes the mock-only hole; single merge authority keeps the commit
history one narrative; and the ledgers (`spawn.jsonl`, `packets.jsonl`,
`overrides.jsonl`, the run log) make every step — including every human
override — auditable after the fact.
