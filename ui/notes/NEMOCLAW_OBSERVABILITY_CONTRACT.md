# Nemoclaw observability contract (UI <- primary session)

**From:** the UI session, 2026-06-08. **For:** the primary session activating the
nemoclaw path (`NemoClawRuntime`, OpenShell sandbox dispatch via `nemoclaw exec`).
**Status:** proposal — please bake in as you build, like the
[`INSTRUMENTATION_ASKS.md`](INSTRUMENTATION_ASKS.md) round (which you delivered in full
— thank you).

## Why this exists

The UI surfaces apparatus activity by reading on-disk artifacts **read-only**
(`logs/orchestrator.jsonl`, `run_state/active_run.json`, `logs/worker_activity.jsonl`,
`logs/calls.jsonl`, `ui/logs/telemetry.jsonl`). Today those are written by the
**host** process, and the local sampler sees the **host's** psutil processes. When
`NemoClawRuntime` lands and a tool/sub-agent body runs **inside an OpenShell sandbox**:

- the host can still log the dispatch/receipt, but **nothing tells the UI it ran in a
  sandbox** (vs in-process) — it cannot label or group sandbox work;
- the per-call internals (`worker_activity.jsonl`) and any per-run state are produced
  **inside the sandbox** unless explicitly bridged to the host paths — so the UI goes
  **blind** to sandbox runs (the same failure mode as exp005, whose calls routed to the
  in-memory `MEMORY_LOG` instead of `logs/calls.jsonl`);
- host telemetry (`psutil` on host PIDs) **cannot see** a sandbox's CPU/RSS.

Three small, additive contract points keep the UI sighted. All are **additive** (don't
break the 4700+ existing rows / current schemas), **atomic** where they are state files,
and should land with a `DATA_SHAPES.md` changelog entry in the same commit.

---

## 1. [HIGH] A `runtime` tag (and `sandbox_id` when sandboxed) on the observability records

Add two optional fields wherever the apparatus already emits observability:

- `runtime`: `"py"` | `"nemoclaw"` — which Runtime executed the tool/sub-agent.
- `sandbox_id`: the OpenShell sandbox id (e.g. `763df558-...`) when `runtime=="nemoclaw"`,
  else absent/null.

Put them on:
- **`logs/orchestrator.jsonl`** rows (the `orchestrator_dispatch` / `worker_invocation` /
  `orchestrator_receipt` stages) — the UI's `/activity` worker table + causal graph read
  these; with `runtime`/`sandbox_id` it can badge a row "nemoclaw · sandbox 763d…".
- **`run_state/active_run.json`** — so the active-run hero reads "running in sandbox 763d…".
- **`logs/worker_activity.jsonl`** — so per-call internals are attributable to a sandbox.
- (optional) **`logs/calls.jsonl`** alongside the existing `run_id`.

The UI keys colour/badges off `runtime`; absent `runtime` is treated as `"py"` (legacy
rows unaffected).

## 2. [HIGH] Bridge sandbox-produced logs to the HOST shared paths

Even when the tool body runs in a sandbox, the host-side runtime must ensure these end up
in the **host** dirs the UI reads — not inside the sandbox filesystem:

- the orchestrator dispatch/invocation/receipt rows (already host-side — keep it that way);
- **`logs/worker_activity.jsonl`** per-call internals, carrying `run_id` **and**
  `sandbox_id` (collect them out of the sandbox after each call, or have the sandbox call
  the same wrapper that appends to the host path);
- `run_state/active_run.json` updates (host-side, atomic `os.replace`).

If a sandbox writes its own copy internally, the host runtime is responsible for the
bridge. The UI never reads inside a sandbox.

## 3. [MED] A host-readable sandbox status the UI can poll

Host `psutil` can't see sandbox CPU/RSS, so the UI can't fill the worker table's
cpu/rss for sandboxed work. Give it one read-only source, whichever is authoritative:

- **(preferred)** a small `run_state/sandboxes.json` the runtime maintains:
  `{ sandboxes: [{ sandbox_id, state, run_id?, started_at, cpu_pct?, rss_mb? }] }`,
  atomically rewritten; or
- point the UI at the NemoClaw dashboard's read API on `:18789` / `~/.nemoclaw/sandboxes.json`
  (tell us the exact field shape and we'll read it; note `~/.nemoclaw/*` is `0700` — a
  `run_state/sandboxes.json` mirror is easier for the UI to consume than a private dir).

With this the UI can show "N sandboxes active" and per-sandbox state; without it, the UI
will honestly render sandbox cpu/rss as "n/a (sandboxed)" rather than guess zeros.

## 4. [LOW] `active_run.json` kind/label for a nemoclaw run

If a nemoclaw dispatch is its own run mode (not just a sub-step of an existing run), ensure
`active_run.json` carries `kind` (e.g. `"nemoclaw"`/`"subagent"`), a human `label`, the
`sandbox_id`, and `current_step`/`progress` as for other run modes — so the active-run hero
reads "running: <label> in sandbox 763d… · step X".

---

## What the UI builds on its side (so you know the consumer)

In parallel (the "catch-up" the UI owes the instrumentation you already shipped):
- `/activity` **active-run hero** reading `run_state/active_run.json` (what + progress).
- `/activity` **real inference internals** from `logs/worker_activity.jsonl` (`synthetic:false`)
  — this drops the UI's synthetic marker the moment real data flows.
- a **runtime/sandbox badge** on the worker rows + a "N sandboxes active" line once §1–§3 land.

## Contract reminders
- Additive only (validate new fields against existing rows, as you did for `run_id`).
- Atomic writes for state files (`os.replace`), as `active_run.json` already does.
- A `DATA_SHAPES.md` changelog entry in the same commit that ships any new field/shape.
- The UI is strictly read-only over all of these.
