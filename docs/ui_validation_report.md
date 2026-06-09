# UI validation report — autonomy-observability render against LIVE data (L3)

> **Authored by workflow limb L3 (read-only) on 2026-06-09.** A scripted
> checklist the **serial integrator fills after the UI-backend restart**. L3 does
> NOT write `ui/` (a UI session owns it) and does NOT restart services — the live
> render validation + any render-bug fix are the integrator's / the UI session's
> (render bugs route via [`docs/ui_validation_handoff.md`](ui_validation_handoff.md),
> which L3 does not edit).
>
> **Scope cross-check:** validation plan [`docs/validation_session_plan.md`](validation_session_plan.md)
> §"L3" + §"Success criteria"; design [`docs/ui_autonomy_observability_plan.md`](ui_autonomy_observability_plan.md);
> data contracts [`docs/ui_validation_handoff.md`](ui_validation_handoff.md).

---

## 0. What L3 verified, and three preconditions the integrator must satisfy FIRST

L3 ran the pre-restart baseline (§1), the backend suite (§4), and read the merged
backend + frontend on disk to build §2/§3. In doing so it found **three places
where the data ON DISK does not yet match the acceptance criteria** — flagged
honestly per inviolate rule 4 (a near-miss is NOT recoded into a pass). These are
**preconditions for the render checklist, not L3 failures**; the integrator's L1/L4
work is expected to produce them. They are called out inline below and gathered here:

| # | Precondition the render checklist depends on | Current on-disk state | Who closes it |
|---|---|---|---|
| **P1** | FASE `iter-2026-06-09-001` must carry `retrieval.relevance.low_confidence = true` for the low-evidence badge to render. | `iter-2026-06-09-001`: `retrieval.relevance = null`, `neighbors` present (count 10) → `isLowEvidence()` returns **FALSE**. The badge will **NOT** render on the current row. (`iter-...-002` correctly = `low_confidence:false`, on-domain — does not show it.) | Integrator L1/L4 must **re-run** the off-domain FASE iteration so `workers/retrieval_relevance.py` populates `low_confidence=true`. Until then this checklist row CANNOT pass. |
| **P2** | A `seed.source = "nemoclaw_agent"` iteration must exist AND the frontend must render a distinct (violet) provenance badge for it. | **Zero** `nemoclaw_agent` rows on disk. Frontend has **no** `nemoclaw_agent` tone — `AgentBadge.tsx` TONE = {coordinator, nara, workflow, human}; `CoordinatorCycleCard.tsx sourceTone()` = sky-for-coordinator-else-zinc; **no `violet` anywhere in `ui/frontend/src`.** | The demo iteration (L2+L4) produces the row; the **`nemoclaw_agent` badge is the UI session's Task-2 additive work** (handoff §Task 2) — **not in the merged 07b6729 code.** Route the badge to the UI session; do not expect it to pass on current `ui/`. |
| **P3** | The findings / bubbles / health-signals / active-run EMIT artifacts must exist for those panels to show real data (else they show the clean empty state, which is acceptable per the handoff, but is NOT "populated"). | **ABSENT on disk:** `run_state/health_signals.jsonl`, `memory/surfaced_findings.jsonl`, `memory/coordinator_bubbles.jsonl`, `run_state/active_run.json`. Present: `run_state/coordinator_cycles.jsonl` (13 rows), `memory/loop_memory.jsonl` (49 rows). | Integrator's coordinator run produces them. Endpoints already tolerate absence (return `{...:[]}` / 204). |

**DRAFT spine edit the integrator must apply (L1) — NOT applied by L3:**
`schema/iteration_record.schema.json` `seed.properties.source.enum` does NOT include
`"nemoclaw_agent"` yet (currently `["human_cli","human_ui","arxiv_pick","loop_memory_probe","coordinator"]`).
A `nemoclaw_agent`-sourced iteration would fail schema validation until this enum is
extended (mirrors the `"coordinator"` add already landed; `schema/active_run.schema.json`
already has `kind:"coordinator"`). See the workflow's L1 `spine_drafts`.

---

## 1. PRE-RESTART BASELINE (captured 2026-06-09 — the "before") ✓ DONE by L3

Running backend on `:8700` is ALIVE (`/api/health` → 200) but its
`/api/coordinator/*` routes **404** — confirming the running process is **stale**
(started before the autonomy-observability router landed on disk). Verbatim:

```
$ curl -s -w "[HTTP %{http_code}]" localhost:8700/api/coordinator/cycles
{"detail":"Not Found"}[HTTP 404]

$ curl -s -w "[HTTP %{http_code}]" localhost:8700/api/coordinator/active
{"detail":"Not Found"}[HTTP 404]

$ curl -s -w "[HTTP %{http_code}]" localhost:8700/api/coordinator/findings
{"detail":"Not Found"}[HTTP 404]

$ curl -s -w "[HTTP %{http_code}]" localhost:8700/api/coordinator/bubbles
{"detail":"Not Found"}[HTTP 404]

$ curl -s -w "[HTTP %{http_code}]" localhost:8700/api/coordinator/health_signals
{"detail":"Not Found"}[HTTP 404]

$ curl -s -w "[HTTP %{http_code}]" localhost:8700/api/health
{"ok":true,"hostname":"spark-7eeb","telemetry_last_seen":"2026-06-09T17:05:22.513+00:00","version":"65ba344"}[HTTP 200]
```

**Diagnostic (root cause of the 404 — and why a plain restart fixes it):** the
served `version` is `65ba344` (current `main` HEAD), and the code on disk IS correct
— `ui/backend/app.py` registers the router (`from .coordinator import register as
register_coordinator`; `register_coordinator(... run_state_dir=..., memory_dir=...)`)
and `ui/backend/coordinator.py` exists in the main checkout. The router last changed
in `0fdb671`/`55fd24f`, both ancestors of HEAD. So the **running uvicorn process is
simply older than the on-disk merge** — a `start`/restart that re-imports `app.py`
picks the router up. No code fix is needed for the 404.

---

## 2. EXACT POST-RESTART VALIDATION STEPS (integrator fills the OBSERVED column)

**Restart** (idempotent — frees the port, kills the old proc, relaunches detached):
```
ui/scripts/ui-services.sh start      # backend uvicorn -> :8700 (env -u MOCK_LLM), frontend vite -> :5173
ui/scripts/ui-services.sh status     # confirm "backend :8700 up" + version
```
> **Serve from the MAIN checkout** (`/home/decross1/projects/a_bgt_rsi`), not a
> worktree: `app.py` hardcodes `_PRIMARY_REPO = Path("/home/decross1/projects/a_bgt_rsi")`
> and `DEFAULT_COORDINATOR_RUN_STATE = _PRIMARY_REPO/"run_state"`,
> `DEFAULT_COORDINATOR_MEMORY = _PRIMARY_REPO/"memory"` — endpoints ALWAYS read the
> primary checkout's `run_state/` + `memory/` regardless of where uvicorn runs.
> So the live artifacts (incl. the missing P3 files + the re-run FASE row + the
> `nemoclaw_agent` iteration) must be produced in the MAIN checkout to be served.

Then curl each endpoint. EXPECTED live responses, tied to the data contracts:

| Endpoint | EXPECTED live response (with the current on-disk data + the integrator's run) | OBSERVED (fill in) | P/F |
|---|---|---|---|
| `GET /api/coordinator/cycles` | `{"cycles":[…]}` — **13 rows today**, newest-first by `timestamp`. Includes a `promote_findings`-only cycle (`coordinator_89ce23df`, `outcomes:[{action:"promote_findings",status:"passed"}]`) and the FASE-topic cycles. **+1 row** once the `run_loop_iteration` demo (`nemoclaw_agent`) lands. | | |
| `GET /api/coordinator/active` | **204 No Content** when idle (file absent now); during a live cycle a body with `kind:"coordinator"` + `current_step` + `narration` (assess→plan→validate→dispatch). | | |
| `GET /api/coordinator/findings` | `{"findings":[…]}` newest-first by `promoted_at`. **`[]` until `memory/surfaced_findings.jsonl` exists (P3)** — empty is a valid clean state, not a failure. | | |
| `GET /api/coordinator/bubbles` | `{"bubbles":[…]}` newest-first by `timestamp`. **`[]` until `memory/coordinator_bubbles.jsonl` exists (P3).** | | |
| `GET /api/coordinator/health_signals` | `{"health_signals":[…]}` newest-first. **`[]` until `run_state/health_signals.jsonl` exists (P3)**; once a degraded run lands, expect `ml_intern_zero_papers` / `qwen_degraded_empty_content` rows. | | |

**Data-contract notes the integrator should verify in the served payloads:**
- **`retrieval.relevance` = `{relevance, low_confidence, reason}`** — present & populated on `iter-2026-06-09-002` (`{relevance:1.0, low_confidence:false, reason:"on-domain retrieval: mean top-3 lexical overlap 0.208 >= 0.05, max cosine 0.656."}`); **`null` on `iter-2026-06-09-001`** (see P1).
- **`novelty.low_confidence` / `critique.low_confidence`** — booleans; `false` on `-002`, **absent/`None`** on `-001` (handle-gracefully contract; the frontend treats absent as no-signal).
- **`seed.source`** — `coordinator` on `-001`, `human_cli` on `-002`; the **new `"nemoclaw_agent"`** value appears only after the demo + the schema-enum add (P2 / spine draft).

---

## 3. RENDER CHECKLIST mapped to LIVE data (integrator fills P/F per surface)

One row per surface. `data-testid` given so the integrator can assert in the live
DOM. **Route map** (verified on disk): `/coordinator` → `CoordinatorCycleCard`;
**Dashboard** → `ResolvedIterationsList` (+ `LowEvidenceBadge`), `SurfacedFindingsPanel`,
`BubblesPanel`, `HealthSignalsPanel`, `RedFlagsTrendStrip`; **Activity** → `CoordinatorPhases`.

| # | Surface (route · testid) | EXPECTED against live data | P/F | Notes |
|---|---|---|---|---|
| R1 | **Coordinator cycle list** (`/coordinator` · `coordinator-cycle-card`) | One card per cycle → **13 cards today** (keyed by `run_id`), newest-first. Empty state (`coordinator-empty`) only if `cycles:[]`. | | |
| R2 | **promote_findings cycle renders** (`/coordinator`) | The `coordinator_89ce23df` card shows action chip `promote_findings` = **PASSED** (emerald). | | |
| R3 | **Failed dispatch = explicit RED row + error** (`coordinator-action-error-*`) | The two `errored` cycles (`coordinator_696791e2`, `coordinator_27629ba6`) render a **red** `noop` chip with the inline error string **`RuntimeError: boom`**. ⚠️ Note: today's errored action is a `noop`, NOT a `run_loop_iteration` dispatch — the handoff's "failed dispatch" example is satisfied by ANY `outcomes[].status:"errored"` row; a `run_loop_iteration`-errored row only appears if the demo dispatch fails. | | |
| R4 | **Card plan chips are OUTCOME-driven** (`coordinator-action-*`) | The card maps `cycle.outcomes` (NOT `cycle.plan`). **Only ~4 of 13 cards show chips** — the 3 `executed` rows + the `promote_findings` row. The `planned` / `no_valid_plan` / first-dispatched rows have `outcomes:[]` → render with topic+source+agent header but an **empty plan list**. This is by-design (not a bug); flag if the integrator expected all 13 to show chips. | | |
| R5 | **FASE low-evidence flag** (Dashboard `ResolvedIterationsList` · `low-evidence-badge`) | `iter-2026-06-09-001` shows the **amber `low-evidence`** badge. **⚠ BLOCKED by P1** — current `-001` has `relevance:null` + 10 neighbors → `isLowEvidence()` = FALSE → badge does NOT render. PASS only after the FASE re-run sets `retrieval.relevance.low_confidence=true`. | | |
| R6 | **On-domain iter does NOT flag** (Dashboard · `ResolvedIterationsList`) | `iter-2026-06-09-002` (on-domain, `low_confidence:false`) renders **WITHOUT** the low-evidence badge. This is satisfied by current data ✓ (verify in live DOM). | | |
| R7 | **Surfaced Findings panel** (Dashboard · `SurfacedFindingsPanel`) | Populates from `surfaced_findings.jsonl`, OR shows a **clean empty state**. **Empty today (P3)** — empty state is a PASS; "populated" needs the integrator's promote_findings run. | | |
| R8 | **Bubbles panel** (Dashboard · `BubblesPanel`) | Populates from `coordinator_bubbles.jsonl`, OR clean empty state. **Empty today (P3).** | | |
| R9 | **Health-signals = AMBER, not red** (Dashboard · `HealthSignalsPanel`) | `ml_intern_zero_papers` / `qwen_degraded_empty_content` render **amber** (degraded), with the "No degraded signals — workers nominal." empty state when none. ⚠ Frontend key is **`qwen_degraded_empty_content`** (the handoff abbreviates it `qwen_degraded`). The panel's only red is for a fetch `error`, NOT a degraded signal — correct per design #6. **Needs `health_signals.jsonl` (P3)** to show real rows. | | |
| R10 | **Agent badges on every row** (all surfaces · `agent-badge`) | Every cycle card header + iteration row carries an `AgentBadge` from the `agent` field. All 13 cycles = `agent:"coordinator"` → **sky** badge. `nara` = emerald, `workflow:*` = indigo (`wf:<role>`), `human` = zinc. Renders nothing for an absent `agent`. | | |
| R11 | **`nemoclaw_agent` provenance badge** (`/coordinator` topic-source + iteration row) | A `nemoclaw_agent`-sourced cycle/iteration shows a **distinct violet** provenance badge. **⚠ BLOCKED by P2 — NOT in merged code** (no `nemoclaw_agent` tone, no `violet` in `ui/frontend/src`). This is the **UI session's Task-2 additive work** + needs the demo row + the schema enum (spine draft). Route to the UI session via the handoff; FAIL/N-A on current `ui/`. | | |
| R12 | **Activity / Dashboard / Experiment pages render w/o console errors** | All three render against live data with no console errors; `CoordinatorPhases` on Activity reflects `active_run` narration during a live cycle. | | |

> **Where a render row FAILS:** route the fix to the **UI session** via
> [`docs/ui_validation_handoff.md`](ui_validation_handoff.md) (its Task-1 validation +
> Task-2 `nemoclaw_agent` badge already cover R5/R11). L3 and the primary session do
> **not** edit `ui/`.

---

## 4. BACKEND UNIT SUITE — READ-ONLY ✓ RUN by L3

```
$ .venv-chroma/bin/python -m pytest ui/backend/tests/ -q
152 passed, 1 warning in 2.82s
```
**152 passed** — matches the expected count. The new autonomy-observability backend
file `test_coordinator.py` alone: **12 passed** (`-m pytest ui/backend/tests/test_coordinator.py -q`).
(The lone warning is a benign `StarletteDeprecationWarning` re: httpx in the FastAPI
TestClient — not a failure.)

**FRONTEND suite — documented, NOT run by L3** (a node/npm toolchain run; the
integrator runs it):
```
cd ui/frontend && npm run test        # vitest run — expect ~200 passed
```
Status: **not run by L3** (out of the read-only Python harness's scope; `package.json`
`"test": "vitest run"`). The integrator should run it as part of the verify gate and
confirm the ~200 count, plus a new test for the `nemoclaw_agent` badge once the UI
session adds it (handoff acceptance).

---

## 5. Done-condition summary (this report)

- ✅ **Pre-restart 404 baseline captured** verbatim (§1) — all 5 `/api/coordinator/*`
  endpoints `404 {"detail":"Not Found"}`; backend alive at `version:65ba344`; root
  cause diagnosed (stale process, router IS on disk → restart fixes it).
- ✅ **Post-restart endpoint + render checklist** delivered (§2, §3) — fill-in P/F
  template, tied to the live data contracts and the exact `data-testid`s.
- ✅ **Backend suite count: 152 passed** (§4), read-only; frontend `npm run test`
  (~200) documented for the integrator.
- ⚠️ **Three preconditions (P1 FASE low-evidence signal, P2 `nemoclaw_agent`
  badge+row+schema-enum, P3 missing EMIT artifact files) reported honestly as
  blockers/carryovers — not coerced into passes** (inviolate rule 4).
