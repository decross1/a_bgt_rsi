> Imported from ~/.claude/plans/idempotent-spinning-sonnet.md on 2026-06-14; scratch original; reference-only.

# Plan — Part 1: install framework + Runtime abstraction + Nara hello-world + UI

## Context

Today is "Part 1" of LOOP_V0: lay the substrate so Part 2 (the 5
workers and real iterations) is a clean build on top. By end of day:

- `agent_system` framework symlinked into `a_bgt_rsi`, Nara has
  access to all 17 skills.
- Runtime abstraction in place so Nara is substrate-agnostic
  (PyRuntime today; NemoClawRuntime today if 90-min install works,
  stubbed if it doesn't).
- Tool registry exposing existing capabilities (wrapper, two existing
  workers, Chroma query) as tools Nara can call.
- "Hello-world" Nara: human types a topic in the UI dashboard, Nara
  runs, picks one tool, emits brief narration between calls, writes
  a stub iteration_record and journal entry. The full 5-step LOOP_V0
  chain is **not** built today — Part 2.

The five LOOP_V0 workers (`hypothesize`, `retrieve_literature`,
`novelty_classify`, `critic_loop_v0`, `journal_writer`) slip to Part
2 next session. Architecture today makes Part 2 a mechanical extension.

### Decisions baked into this plan

- **NemoClaw**: 90-min capped install attempt. If it works,
  build `NemoClawRuntime`. If not, `PyRuntime` only and the swap
  point is documented for a later session.
- **Framework install**: full skill set (17 skills + 4 agent profiles),
  symlinked. Diverges from `agent_system/BOUNDARY.md` — log a
  `DECISIONS.md` entry recording the divergence.
- **UI trigger**: `POST /api/loop_v0/start` shells out to the CLI.
  Submit button works today.
- **Nara narration**: brief sentence between tool calls; the UI
  renders it as a live activity log.

### What's already in the substrate

- `agent_wrapper/wrapper.py` — `call_sync`, `call_async`,
  `call_with_tools(messages, tools, *, max_depth=3)`. Auto-logs to
  `logs/calls.jsonl`.
- `workers/summarize_paper.py`, `workers/play_pd_match.py` — two
  existing single-function workers. Both follow the same shape.
- `tests/test_papers_retrieval.py` lines 110-154 — exact Chroma
  query pattern.
- `pipeline/embed_and_store.py` and `ingest/chunking.py` — Chroma
  collection metadata.
- `ui/backend/critic.py`, `ui/backend/meta_review.py` — endpoint
  shape reference (Day-9 salvage).
- `ui/frontend/src/components/CriticPanel.tsx` and friends —
  component shape reference.
- `/home/decross1/projects/agent_system/install.sh` —
  `--target-path PATH --filter all` installs all 17 skills as
  symlinks.

## Architecture (Nara v0, hello-world)

```
CLI / UI POST /api/loop_v0/start --topic "..."
   │
   ▼
orchestrator.nara.run_iteration(topic, runtime=PyRuntime())
   ├─ iteration_id = "iter-2026-05-26-001"
   ├─ writes run_state/active_iteration.json {iteration_id, current_step: "starting"}
   ├─ wrapper.call_with_tools(
   │     messages=[
   │       {"role":"system","content": NARA_PROMPT_V0_HELLO},
   │       {"role":"user","content": f"Evaluate topic: {topic}"}
   │     ],
   │     tools=tool_registry.all_specs()
   │  )
   ├─ Each tool call:
   │    1. update active_iteration.json {current_step, started_at, narration}
   │    2. runtime.dispatch_tool(name, args) → result
   │    3. log to run_state/week1.run.jsonl
   │    4. feed result back to Nara
   │    5. Nara emits short narration before next call
   ├─ Nara emits final summary
   ├─ writes run_state/loop_memory.jsonl row (stub iteration_record)
   ├─ writes journal/iterations/NNN.md (stub)
   ├─ deletes run_state/active_iteration.json
   ▼
journal entry + loop_memory row
```

`NARA_PROMPT_V0_HELLO` (for today's hello-world):

> You are Nara, the research orchestrator for a_bgt_rsi. Today is a
> substrate-validation run. Given a topic, call **one** of the
> available tools (your choice based on the topic), emit a brief
> one-sentence narration before each tool call describing what
> you're about to do, then call the journal_writer_stub tool to
> finalize. Available tools: summarize_paper, play_pd_match,
> query_chroma, journal_writer_stub.

The full 5-step `NARA_PROMPT_V0` lands in Part 2 when the LOOP_V0
workers exist.

### The Runtime interface

```python
# orchestrator/runtime.py
from typing import Protocol

class Runtime(Protocol):
    def dispatch_tool(self, name: str, args: dict, *, parent_request_id: str) -> dict: ...
    def log_event(self, event: dict) -> None: ...
    def read_state(self, path: str) -> dict | None: ...
    def write_state(self, path: str, value: dict) -> None: ...
    def delete_state(self, path: str) -> None: ...

class PyRuntime:
    """In-process Python dispatch. Reads/writes state files directly."""
    def dispatch_tool(self, name, args, *, parent_request_id):
        fn = TOOL_REGISTRY[name]  # imported from orchestrator.tool_registry
        return fn(**args, parent_request_id=parent_request_id)
    # ... log_event, read_state, write_state, delete_state via standard file I/O

class NemoClawRuntime:
    """Stub — raises NotImplementedError. Today's job: document the
    swap point so a future session can fill it in mechanically."""
    def dispatch_tool(self, name, args, *, parent_request_id):
        raise NotImplementedError("Activate when NemoClaw is installed; see DECISIONS.md D-031")
```

If today's 90-min NemoClaw investigation succeeds, `NemoClawRuntime`
becomes a real implementation. If not, the stub stays — Nara still
runs via PyRuntime, and a future session swaps.

### The tool registry

```python
# orchestrator/tool_registry.py
from workers.summarize_paper import summarize as _summarize
from workers.play_pd_match import play_match as _play_match
from agent_wrapper.wrapper import call_sync as _call_sync
# Chroma query helper — extract from tests/test_papers_retrieval.py pattern
from orchestrator.chroma_query import query_top_k as _query_chroma

TOOL_REGISTRY: dict[str, Callable] = {
    "summarize_paper":      _summarize,
    "play_pd_match":        _play_match,
    "query_chroma":         _query_chroma,
    "journal_writer_stub":  _journal_writer_stub,
}

TOOL_SPECS = [
    {
      "type": "function",
      "function": {
        "name": "summarize_paper",
        "description": "Summarize an arXiv paper by its ID.",
        "parameters": {
          "type": "object",
          "properties": {"arxiv_id": {"type": "string"}},
          "required": ["arxiv_id"]
        }
      }
    },
    # ... and similar for the others
]

def all_specs() -> list:
    return TOOL_SPECS
```

`query_chroma` is a small new helper extracting the existing test
pattern into a reusable function. It does the BGE-M3 embedding +
Chroma query + content_hash on the result. ~80 LOC.

## Files to create / modify (primary session)

| Path | Action | Approx LOC | What |
| --- | --- | --- | --- |
| `.agents/` | created by install.sh | — | Symlinks back to `/home/decross1/projects/agent_system/.agents/{skills,agents}` |
| `CLAUDE.md` | check | — | install.sh tries to symlink AGENTS.md → CLAUDE.md; current CLAUDE.md is our operating contract, so we must use `--target-path` mode (not `install_local`) to avoid clobbering. Plan flow: `cd /home/decross1/projects/agent_system && ./install.sh --target-path /home/decross1/projects/a_bgt_rsi/.agents --filter all` |
| `orchestrator/runtime.py` | new | ~150 | Runtime Protocol + PyRuntime + NemoClawRuntime stub |
| `orchestrator/tool_registry.py` | new | ~120 | TOOL_REGISTRY dict + TOOL_SPECS list + small helpers |
| `orchestrator/chroma_query.py` | new | ~80 | `query_top_k(text, k=10, collections=...)` reusable Chroma helper |
| `orchestrator/nara.py` | new | ~180 | `run_iteration(topic, runtime)`; uses `wrapper.call_with_tools`; writes active_iteration.json + loop_memory.jsonl + journal stub |
| `orchestrator/journal_stub.py` | new | ~60 | `journal_writer_stub` tool — minimal write of iteration record + markdown stub |
| `orchestrator/loop_v0_cli.py` | new | ~60 | `python -m orchestrator.loop_v0_cli --topic "..."` |
| `schema/iteration_record.schema.json` | new | n/a | Schema for one loop_memory.jsonl row (full Part-2 shape; Part-1 hello-world fills required fields with placeholders) |
| `schema/active_iteration.schema.json` | new | n/a | Schema for the live-state file |
| `run_state/loop_memory.jsonl` | touch | 0 | Empty file |
| `journal/iterations/` | mkdir | — | New directory |
| `tests/test_runtime_interface.py` | new | ~80 | PyRuntime contract tests; NemoClawRuntime raises NotImplementedError |
| `tests/test_tool_registry.py` | new | ~60 | Validates each tool spec against OpenAI tool-call schema; smoke-tests dispatch for the 4 tools |
| `tests/test_nara_hello_world.py` | new | ~100 | End-to-end: PyRuntime + Nara + topic → loop_memory row + journal stub. Asserts narration is non-empty |
| `DECISIONS.md` | append | — | D-031 (NemoClaw outcome from today's investigation) + D-032 (BOUNDARY.md divergence for full-skill install) |
| `human/sessions/2026-05-26.md` | update | — | What actually happened + Part 2 proposal |

### NemoClaw investigation (90-min cap)

Before the build steps. Document outcome in `DECISIONS.md` D-031.

Steps:
1. Read NVIDIA OpenShell / NemoClaw current docs (`bookmarks.txt` in `infra/` may have URLs; otherwise web-fetch).
2. Try `nemoclaw onboard` per ARCHITECTURE.md §5.2.
3. If install succeeds: smoke test a sandbox spawn; if that works, plan a 30-min `NemoClawRuntime.dispatch_tool` implementation; if not, stop and document.
4. If 90 min elapsed without success: stop, document the blockers in D-031, continue with PyRuntime only.

Outcome paths:
- **Succeeded with smoke test passing**: build `NemoClawRuntime`; both runtimes available; Nara hello-world runs on PyRuntime today, NemoClawRuntime is built but unexercised by Nara today.
- **Installed but smoke test failed**: stub remains; document specific failure in D-031.
- **Install failed**: stub remains; document install failure mode in D-031; Day-1's D-008 stays the active record.

## Files to create / modify (UI session, parallel)

| Path | Action | Approx LOC | What |
| --- | --- | --- | --- |
| `ui/backend/loop_v0.py` | new | ~150 | Endpoints: `POST /api/loop_v0/start` (subprocess to CLI), `GET /api/loop_v0/active`, `GET /api/loop_v0/iterations`, `GET /api/loop_v0/journal/{id}` |
| `ui/backend/tests/test_loop_v0.py` | new | ~100 | Endpoint tests with fixtures + a real subprocess test with `MOCK_LLM=1` |
| `ui/frontend/src/components/NaraPromptForm.tsx` | new | ~80 | Topic textarea + submit button; POSTs to `/api/loop_v0/start` |
| `ui/frontend/src/components/ActiveIterationPanel.tsx` | new | ~140 | Polls `/api/loop_v0/active` 1×/sec; renders narration log + current tool indicator + elapsed time |
| `ui/frontend/src/components/ResolvedIterationsList.tsx` | new | ~100 | Polls `/api/loop_v0/iterations` 5×/sec; lists past iterations |
| `ui/frontend/src/components/JournalScroll.tsx` | new | ~100 | Polls `/api/loop_v0/iterations`; renders latest journal markdown |
| `ui/frontend/tests/*.tsx` | new | ~250 | Component tests with fixture data |
| `ui/frontend/src/routes/Dashboard.tsx` | modify | — | Mount the 4 new components; comment out UnlockPanel + Day-9 CriticPanel/MetaReviewPanel (don't delete) |
| `ui/frontend/src/types/schemas.ts` | modify | — | Add `IterationRecord`, `ActiveIteration` types |
| `ui/frontend/src/fixtures/loop_v0/` | new | — | Hand-rolled fixtures the UI builds against until real iterations exist |
| `ui_plan.md` | modify | — | Replace stale-framing header note with the actual LOOP_V0 layout |

UI session reads `LOOP_V0.md` + `agent/prompts/ui_session.md` + this
plan. Communicates with the primary session via the two state files
(`active_iteration.json`, `loop_memory.jsonl`).

## Build order — primary session

Each numbered step ends with a commit. The 90-min NemoClaw block runs
early (in parallel mentally with framework install, but on the same
session — single Claude can context-switch).

0. **Read `call_with_tools` source** in `agent_wrapper/wrapper.py` to confirm tool-dispatch contract. Decide whether to register Python callbacks with the wrapper or wrap our own dispatch loop in Nara. Allocate the ~40 LOC into `nara.py` or `runtime.py` accordingly.

1. **Install agent_system framework.** `cd /home/decross1/projects/agent_system && ./install.sh --target-path /home/decross1/projects/a_bgt_rsi/.agents --filter all`. Verify symlinks created. Update `agent/README.md` to mention `.agents/`. Commit.

2. **NemoClaw 90-min investigation.** Time-capped. Outcome → DECISIONS.md D-031 entry. Commit (D-031 + whatever new files if any).

3. **Runtime + tool_registry skeletons.** `orchestrator/runtime.py` (Protocol + PyRuntime + NemoClawRuntime stub). `orchestrator/tool_registry.py` (skeleton with TOOL_REGISTRY = {} initially). `tests/test_runtime_interface.py`. Commit.

4. **`chroma_query.py`** — extract the query pattern from `tests/test_papers_retrieval.py` into a reusable function. Quick smoke test: `python -c "from orchestrator.chroma_query import query_top_k; print(query_top_k('Tit-for-Tat in repeated PD', k=5))"` (with `env -u MOCK_LLM`). Commit.

5. **Tool registry populated.** Add `summarize_paper`, `play_pd_match`, `query_chroma`, `journal_writer_stub` to TOOL_REGISTRY + TOOL_SPECS. `tests/test_tool_registry.py` validates each spec is well-formed and dispatch works. Commit.

6. **Schemas.** `schema/iteration_record.schema.json` + `schema/active_iteration.schema.json`. Skeleton/stub-friendly: required fields are minimal so hello-world's record validates. Commit.

7. **`nara.py` orchestrator.** `run_iteration(topic, runtime)`. Uses `wrapper.call_with_tools`. Writes active_iteration.json on each tool call. Emits brief narration (the system prompt tells Nara to). Writes loop_memory.jsonl row + journal stub at end. Deletes active_iteration on completion. Commit.

8. **`loop_v0_cli.py`.** Argparse on `--topic`. Instantiates PyRuntime. Calls `nara.run_iteration`. Prints the journal entry path. Commit.

9. **End-to-end smoke.** `env -u MOCK_LLM python -m orchestrator.loop_v0_cli --topic "Tit-for-Tat dominance in repeated PD"`. Verify: one row in loop_memory.jsonl (schema-valid), one file in journal/iterations/, narration captured in active_iteration log history. Commit.

10. **DECISIONS.md D-032** for the BOUNDARY.md divergence (full skill set into runtime project). Commit.

11. **Update `human/sessions/2026-05-26.md`** — Part 1 outcomes + Part 2 proposal.

## Build order — UI session (parallel)

1. Read prompt + LOOP_V0.md + this plan. Survey current `ui/` layout. Confirm where to mount the 4 new components.
2. Hide / comment-out UnlockPanel + Day-9 CriticPanel/MetaReviewPanel from `Dashboard.tsx` (don't delete).
3. Add `IterationRecord`, `ActiveIteration` types to `schemas.ts`.
4. Create `ui/frontend/src/fixtures/loop_v0/` with example active_iteration.json + 2-3 loop_memory.jsonl rows + 2 journal markdown files.
5. Build `NaraPromptForm.tsx` (POSTs to `/api/loop_v0/start` — endpoint doesn't exist yet, so this returns 404 until step 7).
6. Build `ActiveIterationPanel.tsx`, `ResolvedIterationsList.tsx`, `JournalScroll.tsx` against the fixtures. Frontend tests.
7. Backend `ui/backend/loop_v0.py`: 4 endpoints. The `POST /start` shells out: `subprocess.Popen(["env", "-u", "MOCK_LLM", "python", "-m", "orchestrator.loop_v0_cli", "--topic", topic], cwd="/home/decross1/projects/a_bgt_rsi")` and returns 202.
8. Wire frontend to backend endpoints. Remove fixture coupling.
9. Update `ui_plan.md` with the new layout, replacing the stale-framing header note.
10. End-to-end: human types topic in the form, watches Nara hello-world run, sees the journal entry.
11. Print `UI READY TO MERGE`.

## Verification (end-of-session acceptance)

Pass criteria (all must hold):

1. `.agents/skills/` and `.agents/agents/` are symlinks pointing into `agent_system/`.
2. DECISIONS.md has D-031 (NemoClaw outcome) and D-032 (BOUNDARY divergence rationale).
3. `python -c "from orchestrator.runtime import PyRuntime, NemoClawRuntime; r=PyRuntime(); print(r)"` runs. `NemoClawRuntime` either works (if today's investigation succeeded) or raises NotImplementedError with a pointer to D-031.
4. `env -u MOCK_LLM python -m orchestrator.loop_v0_cli --topic "..."` runs end-to-end; exit code 0.
5. After (4), exactly one new row in `run_state/loop_memory.jsonl` schema-valid against `schema/iteration_record.schema.json`. One new `journal/iterations/NNN.md` file. `logs/calls.jsonl` has wrapper-call rows linked by `parent_request_id`.
6. UI: open dashboard, type topic in NaraPromptForm, click submit. The ActiveIterationPanel updates 1×/sec showing Nara's tool calls + narration. When done, the iteration appears in ResolvedIterationsList and the journal in JournalScroll.
7. Tests pass: `pytest tests/test_runtime_interface.py tests/test_tool_registry.py tests/test_nara_hello_world.py` (primary). `pytest ui/backend/tests/test_loop_v0.py` + `npm test` (UI).
8. `human/sessions/2026-05-26.md` updated with outcomes.

If (3) fails, root-cause and fix. If (5) hits schema mismatch, narrow the iteration_record required fields. If (6) hits subprocess permission or path issues, fix the subprocess invocation.

## Out of scope today

- The five LOOP_V0 workers (`hypothesize`, `retrieve_literature`, `novelty_classify`, `critic_loop_v0`, `journal_writer`). Part 2.
- Real LOOP_V0 chain (today is hello-world: Nara picks one tool, narrates, journals).
- Renaming `run_state/week1.*`.
- Reconciling salvaged `workers/critic.py` (Phase-2) vs. eventual `workers/critic_loop_v0.py`.
- Backend auth on `/api/loop_v0/start`.
- Cancel / abort an in-flight iteration.
- Loop-memory synthesis / meta-review.
- Step 1 literature-scan-before-hypothesize.
- Continuous-running Nara. Single forward pass per submission.

## Files referenced (read-only context)

- `agent_wrapper/wrapper.py` — `call_with_tools` signature + auto-logging.
- `workers/summarize_paper.py`, `workers/play_pd_match.py` — worker shape.
- `workers/critic.py` (Day-9 salvage) — DO NOT import. Reference only.
- `tests/test_papers_retrieval.py` lines 110-154 — Chroma query pattern.
- `pipeline/embed_and_store.py` lines 184-193 — `papers_recent` metadata.
- `ingest/chunking.py` lines 148-155 — `osborne_rubinstein` metadata.
- `ui/backend/critic.py`, `meta_review.py` — endpoint shape.
- `ui/frontend/src/components/CriticPanel.tsx` — component shape.
- `agent_system/install.sh` — install flow + filter modes.
- `agent_system/BOUNDARY.md` — dev-time vs runtime line. Today's install diverges (full skill set into runtime project); rationale in D-032.
- `ARCHITECTURE.md` §5.1, §5.2 — NemoClaw alpha discipline + footguns.
- `DECISIONS.md` D-008, D-021 — Day-1 NemoClaw fallback record.

## Operational notes (inviolate)

- All real runs and the UI subprocess invocation prefix `env -u MOCK_LLM`.
- Every wrapper call auto-logs to `logs/calls.jsonl`.
- Every tool dispatch through `runtime.dispatch_tool` appends to `run_state/week1.run.jsonl`.
- `iteration_id` = `iter-YYYY-MM-DD-NNN`, sequential by counting today's rows in `loop_memory.jsonl`.
- "Nara" is a string in CLI banners, journal headers, dashboard labels, and Nara's own narration. No `class Nara` — the orchestrator is `run_iteration(topic, runtime)`.
