> ARCHIVED 2026-06-14 — executed/ superseded work order, kept for the record. Current UI handoffs live in the session note (human/sessions/), current state in LOOP_V0.md.

# UI session handoff — 2026-06-10 (RENDER side of today's EMIT)

> **To the UI session.** This document is your full work order; it is
> self-contained — execute it verbatim, in task order. Your write boundary is
> unchanged: **`ui/` + `ui_plan.md` only** (your worktree
> `.claude/worktrees/ui-session`, branch `worktree-ui-session`). Never touch
> `run_state/`, `memory/`, `logs/`, `workers/`, `orchestrator/`,
> `agent_wrapper/`, `schema/`, or `docs/`. The suite must be green from **BOTH**
> the worktree **and** the main checkout (`/home/decross1/projects/a_bgt_rsi`)
> before you finish. Print **`UI READY TO MERGE`** when done.
>
> Supersedes `docs/ui_next_session_plan.md` (2026-06-09 evening): its Task-1
> review fixes were never landed (your worktree HEAD is still `73b431b`) and are
> carried over here as **Task 0, blocking**. Its Task 3 (override hint +
> transfer label) is absorbed into Task 0 item 9 and Task 4.

## What the primary session shipped today (the EMIT you render)

Read these before writing code — they are the producer contracts:

- `docs/DATA_SHAPES.md` — **the 2026-06-10 changelog entry** is today's new
  shapes: top-level `backend` on every `logs/calls.jsonl` record;
  `backend`/`model` + wider emission coverage on `logs/worker_activity.jsonl`
  (Nara turns as `task_id="nara.run_iteration"`, sub-agent turns as
  `task_id="subagent.<name>"`); the `steps[]` board in
  `run_state/active_iteration.json`; new run-log event types
  `loop_v0_active_step` / `subagent_start` / `subagent_finish`; and run
  registration for the formerly anonymous drivers (lit-falsification battery,
  exp001, exp007, exp008×2, skeptic smoke).
- `schema/active_iteration.schema.json` — the new optional `steps[]`:
  `{name, status ∈ pending|running|passed|failed|skipped, started_at?,
  ended_at?}`. Absent on pre-2026-06-10 iterations.
- `schema/calls.jsonl.schema.json` — new OPTIONAL top-level `backend`
  ("Backend registry name that served this call (e.g. 'vllm-gemma',
  'vllm-qwen', 'ollama-coder', 'anthropic')… absent on all pre-2026-06-10
  records. Distinct from `host_metadata.backend`"). **Verified live**: fresh
  `calls.jsonl` rows already carry `"backend": "vllm-gemma"` +
  `"model": "gemma-4-26b-a4b"`.
- `docs/human_writeback_contract.md` — **D-046, blessed.** The CLI write-back
  contract Task 3 builds against. The argv table is copied faithfully below;
  the enums are frozen.
- Multi-run registry (D-047, LANDED — see DECISIONS.md):
  `run_state/active_runs/<run_id>.json`, one file per live run, with a
  `heartbeat_at` field; legacy `run_state/active_run.json` stays as the
  foreground mirror. **The directory may not exist yet** — absent dir ==
  no live runs; your endpoint must tolerate that (Task 1).
- D-048 purge (DONE — see DECISIONS.md): the 23 `RuntimeError: boom`
  failed-dispatch cycles in `run_state/coordinator_cycles.jsonl` and **3,930**
  `fake-model` rows in `logs/calls.jsonl` (82% of the file — the plan-time
  "~171" estimate was a tail sample) were removed, with
  `.pre_purge_2026-06-10` backups kept beside each file. Task 6 lists the
  live-validation assertions of yours that pinned their existence.

Two live facts to anchor your renders: vllm-gemma serves model name
`gemma-4-26b-a4b`; vllm-qwen serves `qwen3.6-27b-nvfp4-mtp`. Live sub-agent
caller tags today: `subagent.finding_skeptic_1/2/3`.

---

## Task 0 (BLOCKING) — carry-over review fixes

All eight findings from `docs/ui_next_session_plan.md` Task 1 are still open
(verified against the tree this morning), plus two adjudicated items (9, 10).
Land these first; the live-data tests are red in the main checkout until you do.

1. **REPO_ROOT walk-up (blocking).**
   `ui/frontend/tests/test_revalidate_live_rows.tsx:51-55`,
   `test_validate_iterations.tsx:41`, `test_validate_lowevidence.tsx:42` all
   hardcode the ui-session worktree depth (`resolve(here, "../../../../../..")`),
   so the live tests die at import (`ENOENT .../memory/loop_memory.jsonl`) when
   run from the merged main checkout. Fix = ONE shared helper, e.g. a new
   `ui/frontend/tests/livePaths.ts`, exporting the primary repo root found by
   **walking up from the test file's directory until a directory containing
   `memory/loop_memory.jsonl` exists** (fail loudly with the searched paths if
   the walk exhausts). All three tests import it; delete the three inline
   `resolve(..)` idioms. This is what makes "suite green from BOTH checkouts"
   possible at all.
2. **`KNOWN_RELEVANCE_KEYS` misses `topicality` (blocking).**
   `test_revalidate_live_rows.tsx:330-339` — the drift census is red on live
   rows 006/007. Add `"topicality"`, and add it to the additive-key comment
   block + type in `ui/frontend/src/types/schemas.ts:253-266` (the optional
   relevance diagnostics). Full additive set: `anchor_cosine, curated_overlap,
   neighbor_spread, topicality, category, rule_fired`.
3. **Axes-census double-render (blocking).**
   `test_revalidate_live_rows.tsx:380-396` — inside the `WITH_AXES` loop the
   test mounts `ResolvedIterationsList` (which renders the chip) and then a
   standalone `NoveltyAxesChip` **before** `cleanup()`, so
   `screen.getByTestId("novelty-axes-chip")` throws `Found multiple elements`
   on any live axes row. Insert `cleanup()` between the two renders (or scope
   the second query to the standalone render's container).
4. **Off-domain tile pinned at literal `"0%"`.**
   `ui/frontend/tests/test_validate_lowevidence.tsx:140-153` pins both trust
   tiles to the literal string `"0%"`; live row 007 makes off-domain 1-of-55.
   Re-pin as a cohort invariant computed from the loaded rows (count
   low-evidence/off-domain rows, assert the rendered percentage matches), not
   a literal.
5. **`test_live_8700.py` never probes `/api/human_todo`.**
   `ui/backend/tests/test_live_8700.py` — add the GET (assert 200 and the
   `{items, counts}` wrapper shape). While here, add probes for the endpoints
   you ship today: `/api/activity/active_runs` (200) and
   `/api/attest/available` (200) — see Verification.
6. **`_git_sha()` is called per-request.**
   `ui/backend/app.py:50-57` defines it; line 101 uses it for the FastAPI
   `version` and **line 119 calls it inside `/api/health` on every request**,
   reporting working-tree HEAD rather than the loaded code — an unsound
   stale-binary signal. Snapshot once at import
   (`_GIT_SHA = _git_sha()` at module level) and serve the snapshot from both
   sites. (Task 2's skew note consumes this version string — it must mean
   "the running binary".)
7. **`<Link>` inside `<summary>` (nit).**
   `ui/frontend/src/routes/Dashboard.tsx:268-277` — the "drill into activity →"
   `<Link>` sits inside the `<summary>`, so a click both navigates and toggles
   the disclosure. Move the link out of `<summary>` (e.g. beside it) or
   `e.stopPropagation()` + `preventDefault` on the summary-toggle path.
8. **Stray fixture file (nit — likely MOOT).** The old `ui-session` worktree
   (HEAD 73b431b) was removed on 2026-06-10; a fresh `claude --worktree
   ui-session` starts clean from current main. If your worktree root somehow
   still carries an untracked 7-byte file `fixture` (contents `stale-`),
   delete it; otherwise skip this item.
9. **Override tooltip drops `override_reason`.**
   `ui/frontend/src/components/ResolvedIterationsList.tsx:139-153`
   (`overrideTooltip`) surfaces `verdict_overridden_from` + `skeptic_verdict`
   but NOT `override_reason` — the *why* of the demotion (skeptic vs coverage
   vs low-confidence) is exactly what the human auditor needs. Add it
   (`reason: <override_reason>` as a third part, same `badgeText` guard). Task
   4's modal additionally shows all three as visible text.
10. **NoveltyAxesChip TRANSFER condition — ADJUDICATED, pin this.**
    `ui/frontend/src/components/NoveltyAxesChip.tsx:64` currently fires the
    cyan transfer emphasis on `phenomenon === "known" && substrate ===
    "unstudied_llm"`. That is **wrong** against
    `docs/novelty_two_axis_rubric.md`. The pinned condition is:

    ```ts
    const transfer =
      phenomenon === "known" &&
      (direction === "matches" || direction === "silent");
    ```

    Rationale: the rubric's decision rule keys the class on
    `predicted_direction`, not substrate — `known + deviates` derives class
    **`novel`** (the current condition wrongly paints
    `known/unstudied_llm/deviates` cyan as mere transfer), while the
    transfer/replication bucket is `known + matches|silent` "**even on an
    `unstudied_llm` substrate**" and substrate is explicitly
    not-class-determining (a bad substrate defaults to `na` with a warning).
    The previous handoff's Task 3 already stated the same bucket:
    `{known, *, matches|silent}`. Update the chip's header comment, the `title`
    text, and the tests that pin the old condition —
    `ui/frontend/tests/test_novelty_axes_chip.tsx:4-5` (header), `:25-44`
    (the quiet-zinc and cyan cases; add a case asserting
    `known/unstudied_llm/deviates` is NOT cyan and `known/na/silent` IS).

---

## Task 1 — Now board / attribution

Kills the two screenshot-review legibility failures: "BUSY (unregistered)"
anonymity, and the one-model-label bug (the banner shows a single top `model`
even when two backends are serving).

### Backend (`ui/backend/activity.py`)

- `_live_calls()` (line 216) gains **`groups[]`**: aggregate the same
  windowed records per `(caller_tag, model, backend, run_id)` →
  `{tag, model, backend, run_id, count, last_call_at}`, sorted count-desc,
  **cap 12**, plus `groups_truncated: bool` and `other_count: int` (calls in
  groups beyond the cap). `backend` and `run_id` are **passthrough from the
  record** — `backend` is stamped by today's EMIT and is `null` on old rows;
  `run_id` is optional. **NEVER fabricate either** — a null backend renders
  as absent, not guessed from the model name. Keep the existing keys
  (`caller_tags`, `model`, …) untouched — `groups` is additive; existing
  tests/renders stay valid.
- **New `GET /api/activity/active_runs`** reading
  `run_state/active_runs/*.json` — one file per live run (D-047), each
  carrying a `heartbeat_at` field; **malformed/unparseable files are skipped**
  (count them as `skipped: N` in the payload, don't 500). Absent directory ==
  `{runs: []}`. **Fallback**: when the directory is absent/empty but legacy
  `run_state/active_run.json` exists, wrap it as
  `{runs: [{...legacy fields, legacy_mirror: true}]}` so the board renders on
  a pre-D-047 apparatus. Respect the existing env-override/test-path pattern
  (`DEFAULT_COORDINATOR_RUN_STATE` idiom in `app.py`). Note: `active_run`
  kinds in the tree are now
  `{experiment, autoresearch, loop_v0, ad_hoc, coordinator}`
  (`orchestrator/active_run.py:_KINDS` — `coordinator` is newer than the
  DATA_SHAPES 2026-06-08 note); render unknown kinds raw.

### Frontend

- **`ui/frontend/src/components/LiveCallsBanner.tsx`** — render per-group
  rows from `groups[]` (fallback to today's aggregate line when `groups` is
  absent — older backend, see Task 2): each row
  `tag · ×count · model` + a backend chip (tones from `src/roles.ts`, see
  IA/colors) + a run chip linking the `run_id` when present, or a quiet
  zinc "unregistered" when `run_id` is null. Show
  `+N more calls` when `groups_truncated`.
- **`ui/frontend/src/components/SystemActivityHero.tsx`** — the
  busy-unregistered headline names the top groups instead of the anonymous
  aggregate, e.g.
  `skeptic_attack ×12 on qwen3.6-27b-nvfp4-mtp · last 3s — no registered run`.
  Keep the existing state machine (`registered | busy-unregistered | idle`);
  only the evidence/headline strings change.
- **New `ui/frontend/src/components/NowBoard.tsx` on `/activity`**
  (`ui/frontend/src/routes/Activity.tsx`): one card per run from
  `/api/activity/active_runs` — kind chip, `label`, `current_step`,
  `progress` (`{done,total,unit}` when present), and a **stale-heartbeat
  amber** state when `now - heartbeat_at > 120s` (a `legacy_mirror` run uses
  its freshest timestamp; reuse the staleness idiom from
  `ActiveRunCard.tsx`). NowBoard takes over the single-run slot; keep
  `ActiveRunCard` as the per-card renderer or absorb it — your call, but the
  empty state stays honest ("no registered runs") and never invents a run.
- **`QwenPanel.tsx` / `VllmPanel.tsx` — BOTH STAY** (standing rule: never
  remove/demote the Qwen panel). Each gains one sub-line
  `driving: <tag> ×N` derived from live-call groups whose `model`
  **exactly equals that panel's served model name**
  (`gemma-4-26b-a4b` / `qwen3.6-27b-nvfp4-mtp`) — exact match only, no
  substring/heuristic matching, absent when no group matches.

## Task 2 — graceful version skew

The frontend regularly runs newer than the `:8700` backend binary (today's
live server predates `/api/attest/*` and `/api/activity/active_runs`).
A 404 from a **known list/capability endpoint** is version skew, not an error.

- **New `HttpError` class in `ui/frontend/src/api/http.ts`** carrying
  `status: number` (and the detail string). `getJSON` (and the bespoke
  fetchers in that file) throw it instead of the bare
  `Error(\`${resp.status} ${detail}\`)`.
- **New `ui/frontend/src/components/EndpointMissingNote.tsx`**: a quiet zinc
  note — `endpoint not in this backend build (sha <version>)` — where
  `<version>` is `/api/health`'s `version` field (Task 0 item 6 makes that
  the running binary's sha). Known **list/capability** endpoints
  (`/api/activity/active_runs`, `/api/attest/available`, `/api/human_todo`,
  the attest POST surfaces via the handshake) render a 404 as this note,
  **never red**. A 500 stays red. **Resource-404s keep existing semantics**
  (e.g. journal-by-id "no journal entry for this iteration").

## Task 3 — in-UI attestation (gated on D-046, which is NOW BLESSED)

Builds the write-back ("B4") seam against `docs/human_writeback_contract.md`.
The contract's non-negotiables, quoted:

> 1. **CLIs are the writers of record.** The UI backend NEVER opens
>    `run_state/` or `memory/` files for writing. A POST endpoint execs the
>    blessed CLI below as an **argv array — no shell strings, no string
>    interpolation into a shell**, `cwd` = the primary repo root,
>    interpreter = `.venv-chroma/bin/python`.
> 2. **The CLI's validation is the gate.** Out-of-enum values exit nonzero
>    and write NOTHING — never coerced (inviolate rule 4).
> 3. **Failure semantics:** nonzero exit → the endpoint returns an error
>    payload carrying the CLI's **stderr verbatim** and the exit code.
> 4. **Success semantics:** each CLI prints the appended row as JSON on
>    stdout; the endpoint returns it.
> 5. **Confirmation = the queue.** After a successful POST the UI re-polls
>    `GET /api/human_todo`; the item leaving the queue … is the durable
>    confirmation, not the POST response.
> 6. **Identity:** writes initiated from the UI stamp `human:ui`.

### Blessed commands by TODO kind (copied faithfully; enums are FROZEN)

(`PY` = `.venv-chroma/bin/python`, run from the repo root.)

| TODO kind | Blessed argv | Writer of record |
| --- | --- | --- |
| `gate_verdict` | `PY -m orchestrator.gate_cli --iteration-id <iter-ID> --verdict <valid\|invalid\|needs_revision> --note <why> --gated-by human:ui` | `memory/loop_feedback.jsonl` (schema-frozen enum) |
| `finding_review` (quick disposition) | `PY -m orchestrator.finding_session --set-status <finding_id> <validated\|rejected\|in_review> --note <why> --by human:ui` | `memory/surfaced_findings.status.jsonl` (+ `memory/loop_feedback.jsonl` for validated/rejected, against the finding's source iteration) |
| `bubble_ack` | `PY -m orchestrator.todo_cli ack --bubble-run-id <run_id> --note <why> --by human:ui` | `memory/coordinator_acks.jsonl` (`bubble_run_id` is the join key `ui/backend/human_todo.py` reads) |
| `defer to dev session` (ANY kind) | `PY -m orchestrator.todo_cli defer --kind <gate_verdict\|finding_review\|bubble_ack\|stale_active_run\|state_gate> --ref-id <id> --note <why> --by human:ui` | `memory/dev_session_queue.jsonl` |
| `stale_active_run`, `state_gate` (direct resolution) | **not blessed** — these stay primary-session human actions (process autopsy / state-file edit). The UI offers only the defer action for them. | — |

All five modules exist in the tree (`orchestrator/gate_cli.py`,
`orchestrator/todo_cli.py`, `orchestrator/finding_session.py` `--set-status`
dispatch at line 661). Verified enums: gate verdicts
`["valid","invalid","needs_revision"]` (`schema/loop_feedback.schema.json`);
finding statuses `("validated","rejected","in_review")`
(`finding_session.QUICK_STATUSES`); defer kinds `("gate_verdict",
"finding_review","bubble_ack","stale_active_run","state_gate")`
(`todo_cli.DEFER_KINDS`, argparse `choices`-enforced).

### Backend — new `ui/backend/attest.py`

Register on the app like the sibling modules (`human_todo.register(app, …)`
pattern). All paths resolve against the primary repo root (`_PRIMARY_REPO`
idiom in `app.py`), overridable for tests.

- **`GET /api/attest/available`** — capability handshake: existence-check the
  three orchestrator modules + the `.venv-chroma/bin/python` interpreter
  under the primary repo; return
  `{available: bool, actions: {gate_verdict: bool, finding_review: bool,
  bubble_ack: bool, defer: bool}}`. A frontend seeing `available: false` (or
  a 404 on this endpoint — older backend, Task 2) degrades every form to the
  copy-paste fallback.
- **`POST /api/attest/gate_verdict`** `{iteration_id, verdict, note}` → argv
  exec of `orchestrator.gate_cli` with `--gated-by human:ui`.
- **`POST /api/attest/finding_review`** `{finding_id, status, note}` with
  `status ∈ validated|rejected|in_review` → `orchestrator.finding_session
  --set-status <finding_id> <status> --note <note> --by human:ui`.
- **`POST /api/attest/bubble_ack`** `{bubble_run_id, note}` →
  `orchestrator.todo_cli ack … --by human:ui`.
- **`POST /api/attest/defer`** `{kind, ref_id, note}` →
  `orchestrator.todo_cli defer … --by human:ui`. Defer is available for
  **EVERY item kind including `stale_active_run` and `state_gate`**, whose
  direct resolution is NOT blessed (table row 5) — for those two kinds the
  UI offers ONLY defer.

Endpoint discipline (all four POSTs):

- **Validate BEFORE spawn** (422 on failure, nothing executed): the enum
  fields against the frozen enums above; `note` **required non-empty** for
  all four (the contract: the CLI permits an empty gate note but the UI
  SHOULD require one — you require it); ids against a conservative charset
  `^[A-Za-z0-9][A-Za-z0-9._:-]*$` — note the **no-leading-dash** rule: there
  is no shell, so the injection risk is argv-flag confusion, and a leading
  `-` would parse as a flag.
- **argv arrays only, no shell** (`subprocess.run(list, …)`, never
  `shell=True`, never string-joined commands), `cwd` = primary repo root,
  interpreter `.venv-chroma/bin/python` (precedent:
  `POST /api/loop_v0/start` in `ui/backend/loop_v0.py`).
- **Injectable runner** (constructor/`register` kwarg defaulting to
  `subprocess.run`) so tests stub the exec.
- `rc != 0` → **502** with `{rc, stderr}` — stderr **verbatim**, rendered
  un-summarized by the frontend. `rc == 0` → return the CLI's stdout JSON
  (parse it). **Stdout shapes differ by CLI**: `gate_cli` and `todo_cli`
  print the appended ledger row itself (render its `gated_by` / `ack_by` /
  `attested_by`); `finding_session --set-status` prints an ENVELOPE
  `{finding_id, session_id, outcome, loop_feedback_row, status_audit_row}`
  — render `status_audit_row` (its `changed_by` is the `human:ui` stamp;
  `loop_feedback_row` is null for `in_review`). Do not assume one shape.

### Backend — `ui/backend/human_todo.py` (additive)

Read `memory/dev_session_queue.jsonl` alongside the existing sources: fold
rows by `ref_id`, **last status wins** (`defer` appends `status:"open"`,
`close` appends `status:"closed"`). An item whose `ref_id` has an open
deferral gets tagged `deferred: true` (+ the deferral note/by/at) — it is
**still listed and still counted** (the contract: "A deferral assigns the
work; it does not resolve the item"). No existing keys change.

### Frontend

- **`GateVerdictForm`** — three buttons: `valid` emerald, `needs_revision`
  amber, `invalid` red — plus a **required** note field (submit disabled
  while empty). Renders on `gate_verdict` items in
  `ui/frontend/src/components/HumanTodoPanel.tsx` and inline in the Task-4
  modal's gate panel.
- **`FindingReviewForm`** (validated / rejected / in_review + required note)
  and **`BubbleAckForm`** (ack + required note) on their item kinds.
- **Defer button on every item kind** (all five), opening a one-field note
  form → `POST /api/attest/defer`. Deferred items render their "deferred to
  dev session" tag.
- Submission flow: optimistic `submitting…` state, then **RE-POLL
  `GET /api/human_todo` — the item leaving the queue is the confirmation**
  (contract principle 5). Render the returned ledger row (its
  `gated_by`/`by` field reading `human:ui`) as the success toast/inline
  confirmation; on 502 render the stderr verbatim.
- The copy-paste `resolve_command` rendering is **demoted to a "CLI
  fallback" disclosure** (`<details>`) on each item — it stays, as the
  degradation path when `/api/attest/available` is false/404.

### Tests

**Tests NEVER exec against the live ledgers.** Backend tests use tmp paths +
the stubbed runner (assert the exact argv array built, incl. `--gated-by
human:ui`/`--by human:ui`; assert 422 paths spawn nothing; assert 502 carries
stderr verbatim; assert the dev-queue fold last-status-wins). Frontend tests
stub fetch. The **final acceptance is one manual live gate resolution with
the human present** — see Verification.

## Task 4 — condensed resolved-iteration cards + detail modal (NOT gated)

`ui/frontend/src/components/ResolvedIterationsList.tsx` rows (lines 543-613)
currently stack ~8 chips + topic + conditioning bullets per row. Condense:

- **Card line 1**: mono `iteration_id` + **max 4 badges**: critique verdict,
  novelty class, `gate_status`, and **one ALARM slot** with priority
  low-evidence > redteam fatal/retries > experiment `Verdict` chip (the
  first present wins; the rest live in the modal). Plus `SourceBadge` ONLY
  when `seed.source === "nemoclaw_agent"` (the β provenance is the one
  origin worth row-level ink; all other sources move to the modal).
  Timestamp stays right-aligned.
- **Card line 2**: topic clamped to one line (`truncate`), full text in the
  `title` attr.
- **MOVE to the modal**: `NoveltyAxesChip`, conditioning bullets, the
  process badge, non-nemoclaw source badges, the second/third alarm chips.
- **New `ui/frontend/src/components/IterationDetailModal.tsx`** on native
  `<dialog>` — `showModal()`, Esc + backdrop click close, focus restored to
  the opening card on close, **no new deps**. jsdom may need a tiny
  `showModal`/`close` polyfill — put it in `ui/frontend/tests/setup.ts`.
  Opens from a card click (keep `onSelect` journal behavior working — opening
  the modal selects the iteration).

Modal sections, in order:

1. **Verdict header** — full badge set + override provenance **AS VISIBLE
   TEXT** (not tooltip-only): `verdict_overridden_from`, `override_reason`,
   `skeptic_verdict` on whichever blocks carry them.
2. **Hypothesis** — `hypothesis.text`, `source`, `candidates_considered`.
3. **Evidence** — `retrieval.relevance` detail (`relevance`, `category`,
   `rule_fired`, `topicality`, `anchor_cosine`, `curated_overlap`,
   `neighbor_spread`, `reason`) + `NoveltyAxesChip` + `novelty.rationale` +
   the low-evidence detail inline (what `LowEvidenceBadge`'s tooltip says).
4. **Adversarial record** — critique `rationale` /
   `contradicting_paper_id` / `skeptic_verdict` + redteam `verdict` /
   `critique` / `suggested_revision` / `confidence` / `retries_used`.
5. **Conditioning bullets** (the `meta_review.conditioning_bullets` block
   that left the row).
6. **`experiment_outcome` block when present** — scalar-guard idiom
   (`value: number|object`); expect `Verdict=YES|NO` summaries from the
   queued PD (exp001) / Cournot (exp009) real runs.
7. **Gate panel** — current `gate_status` + the Task-3 `GateVerdictForm`
   inline (capability-gated via `/api/attest/available`; copy-paste fallback
   disclosure when unavailable).
8. **Links** — journal (existing `getJournalEntry` +
   `JournalScroll`/`MiniMarkdown`), call chain
   `/chain/req/<wrapper_call_ids[0]>`, the experiment page when an outcome
   names one, and the coordinator cycle whose `dispatched_iteration_id`
   matches this iteration.

**Intentional contract change**: list tests that asserted conditioning
bullets / axes chips / process badges IN THE ROW move to modal scope (at
least `test_resolved_iterations_list.tsx`, the axes census in
`test_revalidate_live_rows.tsx`, `test_harden_ResolvedIterationsList.tsx`,
relevant `test_forwardcompat_iterations_list.tsx` cases). **Flag this in the
commit message.**

## Task 5 — iteration timeline (render now against fixtures; lights up live)

Upgrade the `StepStrip` inside
`ui/frontend/src/components/ActiveIterationPanel.tsx` (the static
`STEP_STRIP` at line 11 is the legacy fallback):

- When `active_iteration.json` has `steps[]`, render it **in producer
  order** — the board is `meta_review` + the 5-step chain
  (`hypothesize, retrieve_literature, novelty_classify, critic_loop_v0,
  journal_writer` — `orchestrator/nara.py:_LOOP_V0_STEPS`) with dynamic
  `redteam` / `ml_intern` chips inserted by the producer when those
  sub-loops fire. **Unknown names render raw** (the producer may add steps;
  never filter).
- Tones: `pending` zinc; `running` emerald-border + ticking elapsed (reuse
  `useNow`/`elapsed` from `src/time.ts`); `passed` quiet emerald + duration
  (`ended_at - started_at`); `failed` red + duration; `skipped` dim zinc.
- **Legacy fallback**: `steps` absent → today's static strip, unchanged.
- Caption under the strip: *"steps run sequentially within an iteration —
  concurrency happens across runs (see the Now board)"*.
- **Sub-agent visibility — there is NO `subagents[]` field (pinned).**
  Sub-agent presence renders from: (a) live-calls groups whose `caller_tag`
  starts with `"subagent."` (works today —
  `subagent.finding_skeptic_1/2/3` are in the live log), and (b)
  `logs/worker_activity.jsonl` rows with `task_id "subagent.<name>"`, now
  carrying `backend`/`model`. `ActiveWorkersPanel.tsx` empty-state copy
  (line 96, currently "No workers in flight.") becomes
  **"No orchestrator workers in flight — N sub-agent call groups active
  (see live calls)"** when such groups exist.
- New run-log event types exist if useful (`run_state/week1.run.jsonl`):
  `loop_v0_active_step {iteration_id, step, status}` per board transition,
  `subagent_start` / `subagent_finish` — optional enrichment, not required
  for the strip.

Build the strip against fixtures shaped exactly like the schema (statuses in
all five values, a dynamic `redteam` insertion, an unknown name); it lights
up live on the next post-EMIT iteration.

## Task 6 — small honest renders

- **D-048 purge fallout**: the 23 boom failed-dispatch cycles and 3,930
  fake-model calls were PURGED by the primary (D-048; backups beside each
  file). **Fixtures and live assertions must not pin their existence.**
  Verified pins to fix on your side:
  `ui/backend/tests/test_validate_live_real_data.py:131` (docstring
  "The live file has 2 such outcomes (RuntimeError: boom)") and
  `test_live_cycle_provenance_snapshot` (same file, ~line 160) asserting
  `n_errored >= 1` — **ALL 23 errored outcomes in the live file were boom
  rows, so this is red against the purged live file TODAY** (the primary
  measured 214 passed / this 1 failed post-purge). Re-shape both as
  conditional invariants: every errored outcome that EXISTS carries a
  non-empty error string; drop the ≥1-errored floor. Constructed fixtures
  (e.g. `test_failed_dispatch_grouping.tsx`'s `boomCycle`) are fine — they
  are explicitly synthetic, not live-count pins.
- `experiment_outcome` chips per Task 4 (the alarm slot + modal section 6).
- **Never filter by model name to hide data** — no render may special-case
  `fake-model` (or any model string) out of a list; the purge is the
  primary's job, honesty is yours.

## IA / colors

Placement (current mounts verified in the tree):

- **Dashboard `/`** (`src/routes/Dashboard.tsx`): `SystemActivityHero` (now
  naming top groups), `HumanTodoPanel` (now with attestation forms),
  `VllmPanel` + `QwenPanel` (both stay; driving sub-line), compact
  `ActiveIterationPanel` (steps strip), condensed `ResolvedIterationsList`
  + `IterationDetailModal`.
- **`/activity`** (`src/routes/Activity.tsx`): `LiveCallsBanner` (per-group
  rows), **`NowBoard`** (new, the multi-run board), `ActiveWorkersPanel`
  (sub-agent empty-state copy), full `ActiveIterationPanel`.
- **`/todo`**: the full `HumanTodoPanel` with forms + defer everywhere.

**New `ui/frontend/src/roles.ts`** — additive tone map; **never retint
existing badges** (NOVELTY_TONE / VERDICT_TONE / GATE_TONE etc. stay):

- Backend tones: `vllm-gemma` emerald, `vllm-qwen` sky, `ollama-coder`
  amber, `anthropic` fuchsia.
- Caller-tag accents: `skeptic_*` + `subagent.finding_skeptic_*` rose;
  `topicality_check` + `novelty_classify` indigo; `nara.*` + `hypothesize`
  + `meta_review` emerald; `coordinator.*` sky; battery cyan; unknown zinc.
- **Own-key lookup** (the `Object.prototype` hazard `SourceBadge`/`toneFor`
  already guard): `Object.prototype.hasOwnProperty.call` / `Map`, never a
  bare `obj[key]` on producer-owned strings.

## Boundaries (restated; they don't bend)

- Write only `ui/` + `ui_plan.md`. No `run_state/`, `memory/`, `logs/`,
  `orchestrator/`, `workers/`, `schema/`, `docs/` writes. Commit only
  `ui/` + `ui_plan.md` on your branch — no `git add -A`.
- **CLIs remain the writers of record** — the argv allowlist table above is
  exhaustive; no shell, no generic exec endpoint, no new blessed commands.
- **No fabricated fixture data** — fixture rows are verbatim-real rows
  (heavy payloads elided) or explicitly-synthetic constructions; never
  plausible-fakes presented as live.
- **Additive types only** in `src/types/*` (optional fields; nothing removed
  or required).
- **No new frontend deps**; ports unchanged (`:8700` backend, Vite dev
  port / `VITE_API_PORT` as-is).

## Verification (all must pass before the sentinel)

1. `tsc --noEmit` clean + `vite build` clean.
2. `vitest` green from **BOTH** the worktree and the main checkout (Task 0
   item 1 is what makes this possible).
3. `ui/backend` pytest green from BOTH checkouts, with **ZERO rows added to
   live artifacts** — snapshot `wc -l` of `memory/loop_feedback.jsonl`,
   `memory/dev_session_queue.jsonl`, `memory/coordinator_acks.jsonl`,
   `memory/surfaced_findings.status.jsonl` before/after the suite and diff.
4. Live `:8700` probes (running server): `/api/human_todo` 200,
   `/api/activity/active_runs` 200, `/api/attest/available` 200,
   `/api/health` `version` non-empty. (Until the primary restarts the
   server on merged code, the new endpoints 404 — that is exactly Task 2's
   skew note; the in-process tests are your green signal, the live probes
   are the post-merge check.)
5. The four screenshot-scenario re-validations:
   - unregistered battery load → the hero/banner shows a **named rollup**
     (tag ×count on model), not anonymous "BUSY (unregistered)";
   - registered iteration → steps strip live + sub-agent rows visible;
   - **one REAL gate resolution via the UI with the human present** →
     `memory/loop_feedback.jsonl` gains a row with `gated_by: "human:ui"`
     AND the item leaves `/todo` on the re-poll — this is Task 3's final
     acceptance;
   - old backend (the pre-merge running server) → quiet skew note, no red.
6. Print **`UI READY TO MERGE`**.
