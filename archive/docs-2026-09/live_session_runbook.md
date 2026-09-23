# Live reactive session runbook — first post-overhaul live hour (2026-06-10)

> The 1–2 h human-present session that follows the 2026-06-10 UI-overhaul
> build. Goal: load the merged code into the long-lived servers, kick **one**
> real thing (an iteration, or one pending gate verdict), watch both surfaces
> move, and capture friction — without sliding back into a build session.
>
> A **no-live-iterations embargo** was in force during the build because the
> long-lived `:8077` / `:8700` processes hold pre-session code (started
> 2026-06-09). The §0 restarts are what lift the embargo — do them **before**
> kicking anything.

All commands run on the Spark; repo root `/home/decross1/projects/a_bgt_rsi`
unless stated. Every command was verified against the live host at
runbook-write time (2026-06-10); live numbers (queue counts, PIDs, uptimes)
were correct then and will move.

---

## 0. Preflight

### 0.1 Model servers — verify only, do NOT restart

Both vLLMs are root-owned docker containers (`vllm-gemma4` Up 2 weeks,
`vllm-qwen` Up ~30 h, image `vllm/vllm-openai:v0.21.0`). Nothing in this
session's diff touches them.

```bash
curl -fsS http://127.0.0.1:8000/v1/models | head -c 200   # expect "id":"gemma-4-26b-a4b"
curl -fsS http://127.0.0.1:8001/v1/models | head -c 200   # expect "id":"qwen3.6-27b-nvfp4-mtp"
docker logs vllm-gemma4 2>&1 | grep -m1 "Using 'MARLIN'"
# expect: ... Using 'MARLIN' NvFp4 MoE backend out of potential backends: [...]
```

The MARLIN line is the D-003 / D-024 serving-stack pin (startup-log
confirmation that the NVFP4 MoE path is the benchmarked one). If it is
absent, the container is on a wrong config — stop and investigate before any
iteration; do not "run anyway".

### 0.2 No run in flight

```bash
ls run_state/active_run.json    # expect: No such file or directory
ls run_state/active_runs/       # expect: empty (D-047 registry; absent dir is also fine)
```

If `active_run.json` exists and its freshest timestamp is >30 min old, that
is a lock-leak (it surfaces as a `stale_active_run` inbox item): process
autopsy first — `pgrep -af loop_v0_cli` — and do **not** kick a new
iteration on top of it.

### 0.3 RESTART the tool plane :8077 (holds pre-session code)

Relaunch exactly as it runs today: cwd = repo root, `MOCK_LLM` unset,
`NARA_SKEPTIC=1`, stdout → `run_state/tool_plane.out` (gitignored).

```bash
cd /home/decross1/projects/a_bgt_rsi
pkill -f "orchestrator.tool_plane"
env -u MOCK_LLM NARA_SKEPTIC=1 nohup .venv-chroma/bin/python \
  -m orchestrator.tool_plane --port 8077 \
  > run_state/tool_plane.out 2>&1 & disown
sleep 2 && curl -fsS http://127.0.0.1:8077/health
# expect: {"ok":true,"tools":["get_apparatus_state","run_loop_iteration"]}
```

- `env -u MOCK_LLM` is **mandatory** — `MOCK_LLM=1` sits in the default
  shell and silently stubs the BGE-M3 embedder + workers (the nemoclaw
  runbook's H1 rule).
- `NARA_SKEPTIC=1` per the 2026-06-09 ops rule 3 (`iter-008` ran on a stale
  no-skeptic in-memory pipe; never again).
- No `--host` flag needed: `tool_plane.py` has `DEFAULT_HOST = "0.0.0.0"`,
  so the sandbox alias `host.openshell.internal:8077` keeps working.
- The first `POST /tools/*` after a restart can hang ~30 s — the one-time
  BGE-M3 load. Wait it out.

### 0.4 RESTART the UI backend :8700 (holds pre-session code)

Exact live launch shape: cwd = `ui/`, interpreter `ui/.venv/bin/python`,
stdout → `run_state/ui_backend.out`. (`ui/backend/run.sh` exists but is NOT
the live shape — it is foreground, system python, and does not unset
`MOCK_LLM`.)

```bash
cd /home/decross1/projects/a_bgt_rsi/ui
pkill -f "uvicorn backend.app:app"   # may also reap the lingering launcher shell — fine
env -u MOCK_LLM nohup .venv/bin/python -m uvicorn backend.app:app \
  --host 0.0.0.0 --port 8700 \
  > ../run_state/ui_backend.out 2>&1 & disown
sleep 3 && curl -fsS http://127.0.0.1:8700/api/health
```

**Restart-took check** — T1.5 made `version` mean *the running binary* (sha
snapshotted at import), so:

```bash
curl -fsS http://127.0.0.1:8700/api/health | grep -o '"version":"[^"]*"'
git -C /home/decross1/projects/a_bgt_rsi rev-parse --short HEAD
# the two values must match; a pre-session sha means an old process survived the pkill
```

### 0.5 vite :5173 — only if wedged

The dev server hot-reloads frontend source; restart only if HMR is wedged.
Live shape: `npm run dev` (→ `vite`, port pinned 5173 + `host: true` in
`ui/frontend/vite.config.ts`), cwd `ui/frontend`, log →
`ui/logs/services/vite.log`.

```bash
# ONLY if wedged:
pkill -f "node .*ui/frontend/node_modules/.bin/vite"
cd /home/decross1/projects/a_bgt_rsi/ui/frontend
nohup npm run dev > ../logs/services/vite.log 2>&1 & disown
```

### 0.6 agent_system side — restart the brain watcher; check the static server

The watcher daemon runs the ingest → project → render pipeline on every
apparatus JSONL change, but holds its pipeline step list in memory — restart
it so the overhaul's new steps (map/summary emitters) run in-session:

```bash
/home/decross1/projects/agent_system/scripts/watch_brain.sh restart
/home/decross1/projects/agent_system/scripts/watch_brain.sh status   # expect: running (pid …)
```

The wrapper manages the daemon via `run_state/brain-watch.pid` (verified:
`status` reports the live pid 606862, up since May 26), so `restart` is the
whole move; wrapper defaults match the live flags
(`--interval 1.0 --debounce 1.5`), log →
`agent_system/run_state/brain-watch.log`. Only if the pidfile ever goes
stale while the process lives:

```bash
pkill -f "scripts/watch_brain.py"
/home/decross1/projects/agent_system/scripts/watch_brain.sh start
```

The static brain server :5174 serves files fresh per request — nothing to
reload. Verify, start only if down:

```bash
/home/decross1/projects/agent_system/scripts/serve_brain.sh status   # or: start
# live shape: python3 -m http.server 5174 --bind 0.0.0.0 \
#   --directory /home/decross1/projects/agent_system/memory/brain/view
# log: agent_system/run_state/brain-http.log
```

### 0.7 Probe table — all green before kicking anything

| Port | Probe (from the Spark) | Expect |
| --- | --- | --- |
| :8000 | `curl -fsS http://127.0.0.1:8000/v1/models` | 200, `"id":"gemma-4-26b-a4b"` |
| :8001 | `curl -fsS http://127.0.0.1:8001/v1/models` | 200, `"id":"qwen3.6-27b-nvfp4-mtp"` |
| :8077 | `curl -fsS http://127.0.0.1:8077/health` | `{"ok":true,"tools":["get_apparatus_state","run_loop_iteration"]}` |
| :8700 | `curl -fsS http://127.0.0.1:8700/api/health` | `{"ok":true,…,"version":"<current HEAD sha>"}` |
| :8700 | `curl -fsS http://127.0.0.1:8700/api/human_todo \| head -c 120` | 200, the `{items, counts}` wrapper |
| :5173 | `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5173/` | `200` |
| :5174 | `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5174/dashboard.html` | `200` |

---

## 1. Kick ONE live thing

Pick **A**, **B**, or **C** — one at a time. The loop and the tool plane
enforce a one-at-a-time guard, and a skeptic-on iteration takes ~90 s–3 min.

### A. NARA topic from the dashboard prompt box

On `http://<spark>:5173/`, use the prompt box (NaraPromptForm: topic →
start iteration). That is `POST /api/loop_v0/start`; curl equivalent:

```bash
curl -fsS -X POST http://127.0.0.1:8700/api/loop_v0/start \
  -H 'content-type: application/json' \
  -d '{"topic":"<ONE in-domain (cs.GT / econ.TH) research sentence>"}'
# expect: 202 {"pid": …, "topic": …}; empty/oversize topic → 400
```

The backend spawns `env -u MOCK_LLM .venv-chroma/bin/python -m
orchestrator.loop_v0_cli --topic …` with cwd = repo root, so the iteration
is real (no mock) regardless of the backend's own environment.

### B. Same iteration from the CLI

```bash
cd /home/decross1/projects/a_bgt_rsi
env -u MOCK_LLM .venv-chroma/bin/python -m orchestrator.loop_v0_cli \
  --topic "<ONE in-domain research sentence>"
# --source defaults to human_cli (recorded in iteration_record.seed.source)
```

### C. Clear ONE pending gate instead (16 pending at write time)

Open the inbox (dashboard hero on :5173, or the `/todo` route), pick a
`gate_verdict` item, copy its `resolve_command`, run it from the repo root:

```bash
.venv-chroma/bin/python -m orchestrator.gate_cli \
  --iteration-id <iter-…> --verdict <valid|invalid|needs_revision> --note '<why>'
# appends to memory/loop_feedback.jsonl (gated_by "human"); never edit the ledger by hand
```

Then watch the inbox count decrement on the panel's next poll — the queue,
not the CLI echo, is the durable confirmation (D-046 principle 5) — and the
brain's needs-you count follow after the watcher's regen pass. If this
build's in-UI attestation landed in the running binary
(`curl -fsS http://127.0.0.1:8700/api/attest/available` → 200,
`available: true`), the inbox form is the same write through the same CLI
(stamped `human:ui`); the copied-CLI path above is the always-works fallback.

---

## 2. What to watch, per surface

**:5173 apparatus**

- **Inbox count** — gate_verdict was 16 at write time; a §1-C clear must
  decrement it on the next poll.
- **ActiveRunCard / active-iteration phases** while in flight: kind + label,
  `current_step` walking the loop chain (`hypothesize →
  retrieve_literature → novelty_classify → critic_loop_v0 →
  journal_writer`), the narration line ticking; the `steps[]` board renders
  per-step status if the 2026-06-10 EMIT is in the running producer.
- **The resolved row** when it lands: verdict + novelty + gate badges;
  **agent/source badge on new rows** — `nemoclaw_agent` = violet
  (tool-plane-driven), human CLI/UI = quiet zinc, coordinator = sky; a
  low-evidence flag only if retrieval was genuinely thin (a well-aimed
  in-domain topic should not trip it).
- A failed dispatch must appear as an **explicit red row** — never a silent
  gap. Absence of a row where you expected one is itself a finding.

**:5174 brain**

- **Status strip**: loop state + needs-you counts move after the watcher's
  regen pass (`watch_brain.sh tail` to watch ingest → project → render fire
  on the ~1.5 s debounce).
- **NEEDS-YOU inbox** mirrors the apparatus queue — the gate clear from §1-C
  shows up as a decrement here too.
- **Cluster map**: **solid** edges (explicit `skill_used` attribution)
  appearing as attributed rows land — the D-043 payoff made visible; a
  tool-plane-driven iteration draws violet `nemoclaw_agent` edges. Dashed
  edges stay inferred-only.

---

## 3. Friction-capture loop (the actual point of the hour)

1. Keep a **scratch list** — one line per friction; do not fix
   mid-observation.
2. Triage each item at a natural pause:
   - **fix-now** iff ≤10 min **and** view-layer-only (`ui/` or
     `agent_system/memory/brain/view/` — no spine edits while the servers
     are running that code);
   - otherwise **file a `propose` entry** (framework skill; appends to
     `agent_system/memory/brain/proposals.jsonl`) so it gets review, not
     amnesia.
3. **One `run-log` row per kicked iteration / cleared gate** — observed,
   not intended; the a_bgt_rsi run ledger is `run_state/week1.run.jsonl`.
4. At session end, run **`harvest`** once (framework skill; consumer-trace
   findings → `agent_system/memory/feedback.jsonl`).

---

## 4. Teardown

- **Ledger commits** — commit only what the session itself touched:
  a_bgt_rsi session note (+ any `DECISIONS.md` entry, append-only,
  date-stamped); agent_system brain-ledger appends with regen artifacts in
  their own isolated commit, per the build-session convention. Append-only
  files are never rewritten.
- **`narrate`** the session (framework skill): intent, observed deltas,
  corrections honored, what to do differently.
- **Update `human/sessions/2026-06-10.md`** with the live-session outcome:
  what ran, gates cleared, frictions fixed vs filed.
- Leave all six services **up** — they are long-lived. The build-time
  embargo ended with §0's restarts; nothing to re-arm.

---

## Failure notes

- **202 from `/api/loop_v0/start` but nothing moves**: check
  `run_state/active_iteration.json` appeared (and its `active_run.json`
  mirror) + `pgrep -af loop_v0_cli`. The backend's in-memory process map
  forgets children across its own restarts — by design; the producer's
  writes still land.
- **Second kick refused**: the one-at-a-time guard. Wait out the active
  iteration; do not delete state files to force it.
- **:8700 `version` still pre-session after §0.4**: an old uvicorn
  survived — `pgrep -af "uvicorn backend.app:app"`, kill stragglers, probe
  again.
- **Brain pages stale while the apparatus moves**: watcher dead or on the
  old pipeline — `watch_brain.sh status` / `tail`. The regen pipeline must
  run from the agent_system **main checkout** (generators resolve the
  consumer path relative to the repo; worktrees break it).
- **Gate clear didn't decrement the inbox**: confirm gate_cli exited 0 and
  the row landed (`tail -1 memory/loop_feedback.jsonl`). The queue is the
  truth; the POST/CLI echo is not.
- **Tool-plane call 403/refused from the sandbox** (stretch path only):
  re-check the egress preset + alias per
  [`nemoclaw_agent_run_runbook.md`](nemoclaw_agent_run_runbook.md) S1–S2;
  the gRPC/h2 issue is out of scope for this hour.
