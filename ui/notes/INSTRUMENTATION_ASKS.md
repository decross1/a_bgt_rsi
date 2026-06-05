# Apparatus-side instrumentation asks (for the primary session)

**From:** the UI session, 2026-06-05. **Status:** proposal / next block of work.

The UI reads on-disk artifacts **read-only**; it never writes apparatus state.
During polish we found `/activity` was blind to a live `exp005/run.py` run: it
bypassed the orchestrator (`logs/orchestrator.jsonl` stale) and the loop
(`run_state/active_iteration.json` absent), writing only wrapper calls to
`logs/calls.jsonl`. The UI now surfaces a run-mode-agnostic **"live calls"**
signal (rate + `caller_tag` + `model` + last-call time), but that can only show
*that* the apparatus is working — not *what* the run is doing or *how far along*
it is. To capture more, the apparatus needs to emit a few state/log artifacts.
Each ask below lists a concrete shape and what the UI will do with it.

Two cross-cutting contract reminders:
- **Atomic writes** for any "active" state file (write-temp-then-rename), so the
  UI never reads a half-written file. The loop's `active_iteration.json` already
  does this — generalize the pattern.
- **Add a `docs/DATA_SHAPES.md` changelog entry in the same commit** that ships
  any new shape (the rule already in that doc).

---

## 1. [HIGH] Generalized "active run" state — `run_state/active_run.json`

Today only the LOOP_V0 path writes `run_state/active_iteration.json`
(`current_step`, `latest_narration`, `tool_calls_so_far`). Autoresearch, raw
experiment drivers (`experiments/expNNN/run.py`), and direct `nara.run_iteration`
calls write nothing — so `/activity`'s iteration panel and worker table stay
empty even while work is running.

**Ask:** every run mode that drives the apparatus writes one small,
atomically-updated file while in flight (absent when idle):

```json
{
  "run_id": "exp005-2026-06-05T22-45-00",
  "kind": "experiment | autoresearch | loop_v0 | ad_hoc",
  "label": "exp005 mechanism-aware bidder (n=50, bidders=4)",
  "started_at": "2026-06-05T22:45:00Z",
  "current_step": "scoring trial 37",
  "step_started_at": "2026-06-05T22:56:20Z",
  "progress": { "done": 37, "total": 50, "unit": "trials" },
  "narration": "last human-readable line the run emitted",
  "model": "gemma-4-26b-a4b"
}
```

`progress`/`narration` are optional. **UI consumes:** a new
`GET /api/activity/active_run` endpoint + a hero card ("● running: exp005 ·
trial 37/50 · 12s on current step"). **This is the single biggest win** — it
turns "● live (calls flowing)" into "what + how far". If you'd rather, extend
`active_iteration.json` to a superset rather than add a new file; the UI can read
either.

## 2. [HIGH] Per-worker inference internals — `logs/worker_activity.jsonl`

The `/activity` "inference internals" block is **synthetic today** (decode-step /
tokens-generated / target / ETA / tok-per-s come from a fixture, flagged
`synthetic: true` with `needs: worker_activity.jsonl`). Real data requires the
apparatus to emit, per in-flight task/run, lines like:

```json
{ "timestamp": "...", "run_id": "...", "task_id": "...",
  "decode_step": 312, "tokens_generated": 312, "tokens_target": 512,
  "tok_per_s": 42.0, "eta_s": 4.7 }
```

appended (or an atomically-rewritten latest-per-task snapshot) as work
progresses. **UI consumes:** `activity.py`'s `SYNTHETIC_INFERENCE` constant
becomes a reader of this file and the amber "synthetic — not measured" marker
drops automatically once `synthetic:false`. (Already flagged in
`ui_plan.md` §ACTIVITY + EXPERIMENTS.)

## 3. [MED] Route experiment runs through the orchestrator (or emit its rows)

Experiment drivers don't dispatch through the orchestrator, so
`logs/orchestrator.jsonl` is stale and the `/activity` worker table + causal
graph stay empty during exp runs. Either **(a)** route experiment sub-tasks
through the orchestrator so it emits the existing
`orchestrator_dispatch → worker_invocation → orchestrator_receipt` rows, or
**(b)** have experiment drivers write minimal orchestrator-shaped rows for their
sub-tasks. Then the existing worker table + graph light up for experiments with
**zero UI change** (the UI already reads `orchestrator.jsonl`).

## 4. [MED] A stable `run_id` on wrapper call records

The live-calls signal groups by `caller_tag` (e.g. `nara.run_iteration`). If each
`calls.jsonl` record also carried the active run's `run_id` (from ask #1), the UI
could attribute live calls to a specific run and show per-run call rate, not just
a global tag. Small wrapper-record addition.

## 5. [LOW] Keep `DATA_SHAPES.md` current for experiment summaries

The experiments deep-dive renders exp001 (`per_opponent`) + exp003 (markdown).
exp004/005/006 have `per_mechanism` / flat shapes (already documented in
`DATA_SHAPES.md`). Rendering those is a **UI-side** follow-up (queued); the
apparatus just needs to keep the `DATA_SHAPES.md` changelog updated as summary
shapes change — the rule that doc already states.

---

### Priority summary
1. `run_state/active_run.json` (what + progress for any run mode) — **biggest win**
2. `logs/worker_activity.jsonl` (real inference internals; drops the synthetic marker)
3. experiment runs emit orchestrator rows (lights the existing worker table + graph)
4. `run_id` on wrapper calls (attribute live calls to a run)
5. keep `DATA_SHAPES.md` current (UI renders the new exp shapes on its side)
