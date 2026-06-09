# Validation session plan (2–3h, Dynamic Workflow)
**Goal:** validate, end-to-end, two things on real infrastructure —
1. the **UI autonomy-observability render** works against live data, and
2. **NemoClaw can run an autonomous research idea/thesis** — Nara, as an OpenClaw
   agent *inside* nara-sandbox, autonomously forms a research thesis and drives a
   host-side research iteration through the tool plane.

This is a **validate + finish-the-last-mile** session, not a greenfield build. Run
it as one Dynamic Workflow (build/probe limbs → serial integrator validates,
runs the demos, commits). Single human-triggered demonstration — **not** continuous
autonomy (the D-040 always-on switch stays human-gated).

## Where things stand (grounding)
- **UI render half is merged** (commit `07b6729`): `/coordinator` route + CoordinatorCycleCard
  (failed dispatch = explicit red row), Surfaced Findings + Bubbles panels, agent badges,
  low-evidence flag, red-flags strip, health panel; backend `/api/coordinator/{cycles,active,
  findings,bubbles,health_signals}`. Tests green (152 backend + 200 frontend). **But the running
  UI backend predates the merge → its `/api/coordinator/*` routes 404; it needs a restart.**
- **EMIT half (host) is live**: `run_state/coordinator_cycles.jsonl` (13 rows), `health_signals.jsonl`,
  `active_run kind="coordinator"`, `retrieval.relevance` + `low_confidence` on iteration records.
- **β seam PROVEN**: sandbox → host tool plane (`orchestrator/tool_plane.py`, `get_apparatus_state`)
  works end-to-end via `host.openshell.internal:8077` + the applied egress preset
  (`agent/nemoclaw_nara/host_tool_plane_egress.yaml`, policy version 15). The tool plane process may
  still be running (pid from the 2026-06-09 session) — treat as "restart to be safe".
- **OpenClaw agent bundle is a DRAFT** (`agent/nemoclaw_nara/`: manifest + system prompt) — it is
  NOT yet a verified-running in-sandbox agent. That last mile is the heart of Track B.
- **Host autonomous loop works** (`coordinator --execute --once`); critic-honesty (relevance gate)
  + ml-intern query fix are in.

## Pre-flight (primary session, before launching the workflow)
- `git worktree list` → note the live `ui-session` worktree (no workflow agent writes `ui/`).
- Restart the UI stack so the merged endpoints serve: `ui/scripts/ui-services.sh` (restart) — then
  `curl -s localhost:8700/api/coordinator/cycles` should return the 13 cycles (currently 404).
- Confirm/restart the tool plane: `env -u MOCK_LLM .venv-chroma/bin/python -m orchestrator.tool_plane --port 8077`;
  gateway `curl localhost:18789/health` live; egress policy present (`nemoclaw nara-sandbox policy-list | grep nara-host-tool-plane`).
- Free-memory check (the guard): gemma+qwen+tool-plane+an iteration share the 121 GiB unified pool.

## Phase 1 — Build/probe (parallel limbs; NEW files + DRAFT spine edits only)
**L1 — Tool plane → research-cycle capability (host build).** Add the tool the sandbox agent needs
to *act on* a thesis: `POST /tools/run_loop_iteration {topic}` in `orchestrator/tool_plane.py`,
wrapping `orchestrator.nara.run_iteration(topic, source="nemoclaw_agent")` (bounded: one iteration).
This is the tool plane's first NON-read-only tool — gate it (validate the topic; one-at-a-time;
log it) and document the security framing (sandbox agent can now trigger host compute — the egress
preset + this server-side validation are the boundary). Add `tests/test_tool_plane.py` cases. DRAFT
the `schema/iteration_record.schema.json` `seed.source` enum add for `"nemoclaw_agent"` (integrator
applies — like the `"coordinator"` add already landed).

**L2 — OpenClaw agent bundle → runnable (the last mile).** Turn `agent/nemoclaw_nara/` into a
*verified-running* OpenClaw agent: a system prompt (Nara research persona — *assess apparatus state →
form ONE research thesis grounded in a gap/newest-paper → run it via the tool → report the verdict*),
the tool manifest pointing at `host.openshell.internal:8077` (`get_apparatus_state` + `run_loop_iteration`),
and the **local-Gemma harness wiring (NOT the default `claude-cli` — D-013/D-014)**. Probe the OpenClaw
agent-run mechanics read-only (`nemoclaw nara-sandbox exec`, `openclaw agent --help`, how a custom
agent + custom tool + the `inference` provider are invoked). Produce the EXACT commands to run the
agent in the sandbox + a checklist of what's confirmed vs unknown. (Config/runbook only; the actual
in-sandbox run is an integrator step.)

**L3 — UI validation harness (read-only).** A scripted checklist: restart the backend, `curl` each
`/api/coordinator/*` endpoint and confirm it serves the live `coordinator_cycles.jsonl`/health data;
the expected frontend render (CoordinatorCycleCard shows the 13 cycles incl. the `promote_findings`
cycle and the FASE iteration with its **low-evidence flag**; Surfaced Findings + Bubbles + health
panels; agent badges); run the e2e (`152 backend + 200 frontend` + a live endpoint smoke). Report
PASS/FAIL per surface + any render bug (→ the UI session via `docs/ui_validation_handoff.md`).

**L4 — Autonomous-thesis scenario + success criteria + fallback.** Design the exact demonstration:
seed state, the kind of thesis the agent should autonomously form (a real game-theory gap, or the
newest *on-domain* `papers_recent` paper — note the off-domain-picker caveat from 2026-06-09), the
tool-call sequence (`get_apparatus_state` → reason → `run_loop_iteration`), and the explicit success
criteria. **Fallback ladder (rule 7, time-capped):** if the in-sandbox OpenClaw agent can't be made
to run in the budget, drive the same tool-call sequence from a host script that *simulates the agent's
calls* (proving the tool plane supports the full thesis→iteration→result cycle), and land the agent
bundle as far as it got — logged, explicit, not masqueraded as the full demo.

## Phase 2 — Integrate + validate (serial integrator = primary session)
1. Apply L1 (tool plane `run_loop_iteration` + the `nemoclaw_agent` schema enum); restart the tool plane.
2. **UI validation** (L3): restart the UI backend; confirm `/api/coordinator/*` serves the 13 cycles +
   panels + the low-evidence flag render live; e2e green. File any render bug to the UI handoff (don't
   fix `ui/` from the primary session).
3. **NemoClaw autonomous thesis** (L2+L4): run the Nara OpenClaw agent in the sandbox → it calls
   `get_apparatus_state`, forms a thesis, calls `run_loop_iteration(topic)` → the host runs ONE real
   iteration (`seed.source="nemoclaw_agent"`) → the agent reports the thesis + verdict. If blocked, the
   L4 fallback (scripted tool-call sequence) proves the seam + tool plane; the agent bundle is the
   carryover. Either way the iteration shows up in the UI as a `nemoclaw_agent`-sourced cycle.
4. **Verify gate**: framework `code-review` skill + full suite green (excl. the pre-existing
   `test_dispatch_coding_agent.py` debt) + the two real smokes (UI live + the thesis run). Commit
   (single merge authority); log phase/agent rows with the `agent` field (rule 6); spawn-ledger the
   workflow limbs (rule 3); `narrate` at synthesize (rule 5).

## Success criteria
- **UI ✓**: the live dashboard (restarted backend) shows the coordinator cycles, the Surfaced-Findings
  + Bubbles panels, agent badges, and at least one **low-evidence-flagged** verdict — served from real
  data, e2e green.
- **NemoClaw ✓**: a research thesis was **autonomously formed and run via the sandbox→host tool plane**,
  end-to-end, and the result is surfaced (or, fallback: the tool plane is proven to support the full
  cycle via the simulated sequence, with the in-sandbox agent as the named carryover).

## Risks / fallbacks / guardrails
- **Biggest unknown = the in-sandbox OpenClaw agent** (custom persona + custom tool + local-Gemma
  harness). L4's fallback keeps the session bounded; do NOT let a scripted simulation masquerade as a
  full agent run (rule 4).
- **First non-read-only host tool** (`run_loop_iteration`): the sandbox agent can now trigger host GPU
  compute. Bounded (one iteration), server-side-validated, human-triggered. NOT continuous (D-040 stays
  gated). Memory: watch the unified pool (gemma + qwen + tool plane + an iteration) — the pre-flight guard.
- **Off-domain picker** (2026-06-09): if the agent's thesis lands off-domain, the relevance gate should
  fire (`low_confidence`) — that's a *passing* observation, not a failure.
- **UI isolation**: render fixes go to the UI session via the handoff; the primary session never writes `ui/`.
