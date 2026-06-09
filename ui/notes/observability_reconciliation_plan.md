# Observability reconciliation — "the machine is busy but the dashboard says idle"

> Authored by the UI session, 2026-06-09 evening, from the human's screenshot review
> (`/home/decross1/projects/Capture*.PNG`) + a live-data investigation. A plan for
> **both** sessions: the main session owns the data/EMIT fixes, the UI session owns the
> render fixes. The human's direction: **Dashboard = high-level activity on the Spark
> system and specifically what a_bgt_rsi is doing; Activity / Coordinator / Experiments =
> deep dives into arms of the system; plus a HUMAN TODO surface — interactive, writing
> approvals/gates/journal verdicts back for the system to ingest.**

## What the screenshots show (the complaint, made precise)

| Evidence | Observation |
| --- | --- |
| Capture3 (dashboard) | GPU **96%**, gemma decoding **51.6 tok/s**, 1 running request, prefix-cache 66.8% — yet "ACTIVE: **idle** — type a topic" and hero "HEALTHY · all systems nominal". The system is working hard and the dashboard can't say what or why. |
| Capture / Capture4 (activity) | The live-calls banner *knows* there's activity ("4 calls in last 15s · novelty_classify · gemma") and *admits the gap*: "this run isn't dispatching through the orchestrator or the loop, so there are no per-task rows below." Active iteration idle / workers 0 / coordinator idle. |
| Capture4 (activity) | FAILED DISPATCHES = **12 visually identical** `noop · FASE · RuntimeError: boom` rows — noise that buries any real failure. |

## Root causes (live-data investigation, 2026-06-09 ~20:00)

1. **Attribution exists but is dropped on the floor.** `logs/calls.jsonl` rows DO carry
   `caller_tag` (last 200 calls: `nara.run_iteration` ×178, `novelty_classify` ×22) and a
   `run_id`. The UI uses this only for the thin live-banner; the Dashboard ignores it
   entirely. The data to say *"a real iteration is driving gemma right now"* already flows.
2. **The active_run mirror has drifted from the invocation paths.** A real iteration was
   running during the investigation (`nara.run_iteration` calls at 19:58) yet
   `run_state/active_run.json` and `active_iteration.json` were **absent**. Whatever
   entrypoint drives tonight's runs (battery / direct `run_iteration` / lit-pipe harness)
   bypasses — or prematurely clears — the mirror that the UI's "what is running" panels
   poll. (Related: the known lock-leak bug is the *opposite* failure of the same mirror.)
3. **Stale `run_id` stamping.** The last 30 calls tonight carry
   `run_id = iter-2026-06-05-001` — a June-5 id on June-9 calls. A `set_run_id` leak:
   per-call attribution is *wrong*, not just unsurfaced.
4. **Test pollution of live artifacts.** `coordinator_cycles.jsonl` grew 19 → **97** rows
   tonight; **32** are `topic="noisy PD"` cycles with `noop` actions and **16** carry
   `RuntimeError: boom` — test/dev cycles written to the production path (the writers
   take a path param; something ran with defaults). The UI faithfully renders the noise.
5. **The human's queue is invisible.** **13** iterations sit at `gate_status="pending"`;
   only 2 feedback rows exist → **11 await a human verdict** and no surface says so. The
   ingestion channel ALREADY EXISTS: `orchestrator/gate_cli.py:append_feedback` —
   schema-validated, append-only → `memory/loop_feedback.jsonl`. Findings review
   similarly exists (`finding_session` → `surfaced_findings.status.jsonl`). Bubbles are
   written but have no acknowledge channel.

---

## Workstream A — MAIN SESSION (data / EMIT fixes)

**A1. Every LLM-invoking entrypoint registers presence (fix the mirror drift).**
Any path that calls the wrapper beyond a one-off — `run_iteration` direct, the
lit-falsification battery, ml_intern sweeps, skeptic panels — must `write_active_run`
(kind + label + narration) on start and clear on exit, or explicitly opt out with a
documented reason. Acceptance: while ANY apparatus work runs, `active_run.json` exists
and names it; `/api/coordinator/active` never 204s mid-run. Add the missing
`update_active_run` calls to the entrypoints found bypassing it tonight.

**A2. Fix `set_run_id` lifecycle (stale-attribution bug).** Tonight's calls stamped with
a 4-day-old iteration id. Reset/scope the run_id around each entrypoint (context-manager
or set/clear pairing); regression test: two consecutive runs never share a run_id, and a
call made outside any run carries none/`ad_hoc`.

**A3. `task_type` on wrapper calls.** `task_type` is `None` on all recent rows. Stamp it
(worker name / phase) so the UI can aggregate "what kind of work" without parsing
caller_tags. Additive field; already in the row schema.

**A4. Test/dev hygiene for live artifacts.** Tests and dev harnesses must point
`cycles_path` / `loop_memory` / etc. at tmp paths (they're already parameters — enforce
via a conftest guard or env default). Decide disposition of the existing 32 noisy-PD /
16 boom rows: either prune them once (logged, append a tombstone note) or bless a
`synthetic: true` field the UI can filter. Acceptance: a fresh `pytest` run adds 0 rows
to any `run_state`/`memory` artifact.

**A5. Bless the human write-back contract (decision needed).** The UI backend is
read-only on `run_state`/`memory` by rule; the loop_v0 `/start` endpoint already
established the sanctioned pattern: **subprocess to a validating CLI**. Proposal — the
UI backend invokes, never writes files directly:
- Gate verdicts → `python -m orchestrator.gate_cli <iteration_id> <verdict> [--note]`
  (exists today; enum-validated, append-only).
- Finding review → the `finding_session` CLI surface (exists).
- Bubble acknowledge → small new `orchestrator/ack_cli.py` appending
  `{bubble_run_id, ack_by, ts, note}` → `memory/coordinator_acks.jsonl`; coordinator's
  `assess_state` treats acked bubbles as closed (new, small).
Main session confirms/amends this contract + the verdict enums; UI builds against it.

## Workstream B — UI SESSION (render fixes; B1–B3 buildable NOW from existing data)

**B1. Dashboard hero becomes activity-first (the headline fix).** Compose what already
flows: live wrapper-call aggregation (caller_tag × model × rate from the activity API),
GPU util, vllm running-requests, active_run/iteration when present. The hero must never
say "idle/nominal" while calls are flowing or GPU is loaded — instead:
*"BUSY — nara.run_iteration driving gemma (51 tok/s, 1 req), no registered run
[unattributed]"*. Idle ≠ busy-but-unregistered ≠ registered-run: three distinct states,
the middle one amber ("activity without provenance" — itself a legible finding).
Until A1/A2 land, "unattributed/stale-id" will show often — that's correct and useful.

**B2. Failed-dispatch grouping + synthetic filter.** Group identical (topic, action,
error) failures into one row with ×count and first/last timestamps; collapse the 12
boom rows to one line. Filter/badge synthetic rows when A4 blesses a marker (until then,
group-by makes the noise cheap).

**B3. HUMAN TODO panel — read-only first slice.** A first-class Dashboard panel (and
nav item) aggregating, from data that exists today:
- the 11+ `gate_status="pending"` iterations lacking a `loop_feedback` verdict
  (join `loop_memory` × `loop_feedback` — the backend already reads both),
- surfaced findings with status `surfaced`/`in_review` (when the file appears),
- unacked bubbles (when the file appears),
- stale `active_run` (the WF-A staleness hint's signal — "investigate/clear"),
- pending-gate entries from `run_state/week1.state.json` `human_gates_pending`.
Each item: what / since-when / the exact CLI command to resolve it (copy-pastable),
ordered oldest-first. Backend: new read-only `GET /api/human_todo` composing these.

**B4. HUMAN TODO write-back (gated on A5).** Buttons on B3's items — *valid / invalid /
needs_revision* on a pending gate, *ack* on a bubble — POSTing to new backend endpoints
that subprocess the blessed CLIs (the loop_v0 `/start` pattern: validate input, spawn,
return the CLI's verdict; the CLI's schema validation is the gate). Optimistic UI off
the appended row, never a direct file write. Full audit trail comes free (the CLIs are
append-only + validated).

**B5. Page-role sharpening (the human's IA direction).** Dashboard = high-level only
(hero + health + red-flags + TODO + compact recents). Activity = the live deep-dive
(per-call stream, workers, coordinator phases, failed dispatches). Coordinator =
decision audit (cycles → plan → outcomes → findings/bubbles). Experiments = research
arms. Move anything deep off the Dashboard behind its deep-dive link; add "drill into"
links from every dashboard tile to its deep-dive anchor.

## Sequencing

| Order | Item | Depends on |
| --- | --- | --- |
| now | B1 hero, B2 grouping, B3 TODO read-only | nothing — data exists |
| now | A1 mirror, A2 run_id, A3 task_type, A4 hygiene | main session |
| after A5 decision | B4 write-back | A5 (CLI contract blessing) |
| after A1–A3 land | B1 upgrades from "unattributed" to naming the registered run | A1–A3 |
| anytime | B5 IA sharpening | nothing |

**Verification:** re-take the four screenshots' scenarios after landing: (1) battery/
iteration running → dashboard hero names it (or shows amber "unattributed"), GPU 96%
never coexists with "idle/nominal"; (2) the 12 boom rows render as 1 grouped line;
(3) the TODO panel lists the 11 pending gates and a click writes a valid
`loop_feedback.jsonl` row the coordinator ingests; (4) fresh pytest adds 0 rows to live
artifacts.
