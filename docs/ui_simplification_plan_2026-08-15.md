# UI Simplification — 3-surface rebuild (Pulse · Ladder · Dossier reader)

## Context

The cockpit accreted into a 19,291-line, 54-component, 8-route console with
four parallel "what is running" surfaces, three parallel iteration renderers,
and five finding surfaces — only one of which (the /todo inbox, fixed
2026-08-15) is evidence-ladder-aware. The owner still sees "31 findings
awaiting approval" because the Dashboard's SurfacedFindingsPanel, the
ResolveRail, and InFlightRollup all render the pre-ladder list raw. The
2026-08 restructure inverted the apparatus to selection-before-the-human
(D-059: only L4+ deserves attention); the UI must now match — the owner's
words: "the cockpit is too complex… the journey through research, its
validations and novelty, what the critic tested against, the experiments —
need to be communicated elegantly for me to even engage."

Owner decisions (2026-08-15): rebuild around 3 surfaces; home split into TWO
pages (Pulse = healthy + do I owe anything; Ladder = what's cooking); the
Dossier reader is the product with two-voice chat inside it; the verdict
fence stays load-bearing (forms are the only dispositions); old routes:
delete what overlaps, keep only uniquely useful.

## Target shell (nav: Pulse · Ladder · Dossiers · Engine ▾)

1. **Pulse `/`** — LoopAlertBanner (already global) + ONE merged Now card
   (NowBoard absorbs SystemActivityHero/InFlightRollup/ActiveIterationPanel-
   compact) + "You owe" strip (gate verdicts + L4+ findings ONLY, linking
   into dossiers) + last-cycle one-liner (plan + gaps from
   /api/coordinator/cycles) + one parameterized ModelServerCard ×2 (merges
   VllmPanel/QwenPanel).
2. **Ladder `/ladder`** — NEW read-only `GET /api/ladder` (ui/backend
   imports workers.idea_ledger.load_state — precedent: loop_alert.py):
   per-rung histogram, cluster table (status/rung/kill_reason filters),
   agenda; ideas.md render as fallback body. /ideas folds in.
3. **Dossier reader `/dossier` + `/dossier/:id`** — index = ResolveRail-style
   fetch-free picker, owe-first ordering; reader = trimmed TutorPanel
   overview → PipelineJourney spine (absorbing IterationDetailModal's unique
   bits) → optional CalibrationCapture → ONE merged chat pane
   (mode: tutor | two-voice) → verdict forms at bottom per kind. Serves both
   sf-* and iter-* ids via existing /api/finding/{id} +
   /api/iteration/{id}/journey. /todo becomes an alias → /dossier.
4. **Engine ▾ (collapsed nav)** — uniquely-useful survivors only:
   /experiments + /experiments/:id (only Recharts consumer), /cycles
   (Coordinator narratives), /chain/req/:id (deep-linked Inspector),
   ActivityGraph if kept as /graph. Zero redesign work.

## Route fates

| Route | Fate |
|---|---|
| `/` | NEW Pulse (`routes/Pulse.tsx`) |
| `/ladder` | NEW (`routes/Ladder.tsx`); `/ideas` → redirect |
| `/dossier`, `/dossier/:id` | NEW index + reader; `/todo` → redirect |
| `/cycles` | Coordinator renamed (`Cycles.tsx`, gains CoordinatorPhases); `/coordinator` → redirect |
| `/experiments`, `/experiments/:expId` | KEEP as-is (unique research index + only Recharts consumer) |
| `/graph` | NEW thin page for ActivityGraph (extracted) |
| `/chain/req/:id` | KEEP (deep-link only) |
| `/activity`, old Dashboard | DELETED (S1 keeps Dashboard at `/dashboard`; S3 removes) |

Nav: `pulse · ladder · dossiers · engine ▾ (cycles, experiments, graph) · brain↗`.

## Pulse (`routes/Pulse.tsx`)

HealthVerdict (kept verbatim incl. excludeQwenReadErrors guards) → **NowBoard
extended in place** as the ONE now-card (absorbs SystemActivityHero's pure
`computeActivity()`/evidence builders into `components/nowVerdict.ts`;
"registered" derives from the D-047 registry — the activeIteration/
coordinatorActive props + 2 endpoints drop) → NEW `OweStrip` (~120L: one
/api/human_todo poll; gate_verdict + state_gate + L4+-bar findings only,
rows link to /dossier/:id; ladder histogram line; bar logic extracted to
shared `src/ladderBar.ts` from HumanTodoPanel; 404 → honest "queue UNKNOWN")
→ NEW `LastCycleLine` (~80L: cycles[0] one-liner; `no_valid_plan` amber,
errored count red, +N findings; links /cycles) → HealthStrip (kept) → NEW
`ModelServerCard` ×2 (~200L, replaces VllmPanel+QwenPanel; props pick/accent/
workloadHint/transientDropBanner) → NaraPromptForm behind a disclosure.

Dashboard panel fates: KEEP HealthVerdict, HealthStrip(+tiles), NaraPromptForm.
DIE: SystemActivityHero, InFlightRollup, ActiveIterationPanel, VllmPanel,
QwenPanel, RedFlagsTrendStrip (note in ui_plan for /ladder revival if missed),
HealthSignalsPanel (LoopAlertBanner supersedes), SurfacedFindingsPanel,
BubblesPanel (items survive via OweStrip footer + picker; BubbleAckForm lives
in the reader), ResolvedIterationsList (browse moves to dossier index;
JournalScroll survives in reader), BaselineCard, ProcessGrid.

## Ladder (`routes/Ladder.tsx` + NEW `ui/backend/ladder.py`)

`GET /api/ladder` (~120L, loop_alert.py idiom): sys.path bootstrap to the
primary repo (uvicorn cwd is ui/ — verified import chain is stdlib-only and
load_state reduces 70 clusters in ui/.venv), lazy import in handler; absent
ledger → 204; malformed → honest 500 (rule 4). Returns {clusters[stem,
status, evidence_level, kill_reason, reopening_condition, …], histogram,
counts, agenda, next_owed} via idea_projection helpers. Page: counts header,
pure-div rung histogram (labeled with next-owed test), status/rung filter
chips, cluster table (killed rows expand to kill detail + reopen condition),
agenda section; 404/204 fallback = EndpointMissingNote + ideas.md render
(current Ideas.tsx body becomes the fallback branch; GET /api/ideas stays).

## Dossier reader (the product)

**Index `/dossier`** (~300L): fetch-owning page evolution of ResolveRail
(rows are Links; stem-clustering ported verbatim with a cluster_id-future
comment). Feeds /api/human_todo + /api/loop_v0/iterations. Sections:
(1) you owe (gate_verdict + state_gate), (2) cleared the bar (L4+; honest
"Nothing cleared L4 this week." when empty), (3) everything else searchable
(31 legacy findings, bubbles, stale runs, resolved iterations).

**Reader `/dossier/:id`** (~350L): kind from human_todo item else sf-*/iter-*
prefix. ConcurrencyWarning → header → TutorPanel (TRIMMED: drop the pros/cons
considerations section) → **PipelineJourney as the spine** (582→~850L,
absorbing IterationDetailModal's unique bits: verdict-header badge row,
NoveltyAxesChip, override provenance visible, conditioning bullets, full
evidence grid + lowEvidenceDetail, redteam adversarial detail, experiment
extras, candidates_considered, lazy JournalScroll, links to /chain//experiments
//cycles) → CalibrationCapture (opt-in, pre-reveal, per-id set lifted) →
reveal fence → NEW merged `ChatPane` (~250L, mode tutor|two_voice, replaces
TutorChatPane+TwoVoiceChatPane; NO disposition prop exists — structurally
fence-preserving; useChatSession untouched) → disposition footer per kind
(GateVerdictForm + CLI-fallback block / FindingReviewForm + 4 aux forms /
BubbleAckForm / DeferForm; capability wiring lifted verbatim from Todo.tsx).
Chip primitives move first to NEW `components/chips.tsx` (toneFor, Badge,
RedteamChip, ExperimentChip, etc. — verbatim from IterationDetailModal).

## Kill list (S3 unless noted)

Components: ActiveRunCard (dead, S1), SystemActivityHero, InFlightRollup,
ActiveIterationPanel, VllmPanel+QwenPanel (S1), RedFlagsTrendStrip,
HealthSignalsPanel, SurfacedFindingsPanel, BubblesPanel,
ResolvedIterationsList, IterationDetailModal (S2), HumanTodoPanel (S2),
ResolveRail (S2), TutorChatPane+TwoVoiceChatPane (S2), LiveCallsBanner,
ActiveWorkersPanel, SyntheticInferencePanel. Moved: CoordinatorPhases →
/cycles; ActivityGraph → /graph.
Routes: Dashboard, Activity, Todo, Ideas (Coordinator renamed).
Clients/types: getState, getExperiments(index), getActiveRun(singular),
getProcesses, getSurfacedFindings, getBubbles, getHealthSignals, getBaseline.
Backend endpoints: /api/state, /api/experiments(index), /api/coordinator/
{findings,bubbles,health_signals,active}, /api/activity/active_run(singular),
/api/loop_v0/{active,processes}, /api/baseline (+module). KEEP: workload_hint,
telemetry/recent, WS live, chain, health, all attest/todo/chat/human_todo/
finding/journey/loop_alert/ideas, research, experiments/{id}, NEW ladder.

Tests: ~38 frontend suites DELETE with their surfaces; behavior pins PORT
(computeActivity → test_now_verdict; chip pins → test_chips; VllmPanel/Qwen +
chat panes → parameterized suites; ladder-bar → ladderBar/OweStrip; ResolveRail
stems → dossier index; route sweeps rewritten). Backend: 5 robust-suites die,
cases pruned from test_api/experiments/coordinator/loop_v0/live probes; ADD
test_ladder.py (+ live /api/ladder probe expecting 70 clusters). Net honest
shrink ≈ −12k test lines tracking the surface shrink.

## Phasing (worktree UI agents; primary merges each slice)

- **S1** shell + Pulse + Ladder + /api/ladder; old surfaces reachable
  (Dashboard at /dashboard); ladderBar.ts extraction keeps HumanTodoPanel
  green; delete VllmPanel/QwenPanel/ActiveRunCard same-slice. Gate: vitest +
  ui-backend pytest green; :8700 smoke (curl /api/ladder → 70 clusters; / and
  /ladder render live; ensure-cron untouched); ui_plan.md entry.
- **S2** chips.tsx → journey absorption → ChatPane merge → TutorPanel trim →
  DossierIndex + DossierReader → /todo redirect → delete Todo/HumanTodoPanel/
  ResolveRail/chat panes/IterationDetailModal + port tests. Gate: suites +
  smoke (gate_verdict dossier from owe strip: journey full evidence +
  overrides + journal; chat capability-gated; GateVerdictForm sole
  disposition; sf-* dossier resolves source iteration); ui_plan.md entry.
- **S3** delete Dashboard/Activity; Graph.tsx extraction; Cycles rename +
  redirects; dead components/clients/types/fixtures; backend endpoint
  removals + test prune; final nav. Gate: suites + full-nav smoke + redirects
  + `git grep` proves no retired-endpoint references; ensure-cron check;
  ui_plan.md entry + cluster_id-join follow-on note.

Execution note: F3 (frontier packet agents) may power S-slices where the seam
fits; the docker allow rule the owner just added means the Qwen A/B window in
the same 10h loop is now self-serve.

## Frontier utilization workstream (owner ask 2026-08-15: "maximize the
## Claude/ChatGPT plans")

All within D-061 (falsifier/engineering only; annotate-never-write; every
call ledgered to run_state/frontier_calls.jsonl):

- **F1 — open-cluster triage sweep (this loop):** opposed-jobs screen
  (Claude=methods / Codex=novelty) over every OPEN L0/L1 cluster (~21) as
  ledger ANNOTATION (`frontier_screen` on the cluster, non-gating). Output:
  early rediscovery kills proposed for ladder events + the frontier-vs-local
  calibration dataset bulk-populated. Small driver script (Tier P) reusing
  workers/frontier_review.screen_candidate over reduced ledger state.
- **F2 — judge re-calibration, frontier as judge (this loop):** re-run
  workers/idea_judge --calibrate with judge_fn backed by frontier_cli
  (methods vendor). Same pre-registered bars; pass ⇒ dedup top layer
  activates with frontier judge (filter ⇒ reproducibility-clean); fail ⇒
  recorded honestly like the Gemma run.
- **F3 — frontier packet agents:** dispatcher agent_cmd seam gets a blessed
  `claude -p`-based builder command (env-stripped already); UI slices and
  future plumbing packets run on subscription compute through the full
  mechanical gate. First workload: the S-slices below where marked.
- **F4 — agenda cron install (human, 1 line)** + optional 2-3×/week cadence.
- **F5 (parked, own session):** frontier-synthesized literature notes over
  the 572-paper corpus (the D-060-sanctioned wiki layer) targeting the
  critic's undecidable flood.

## Invariants

- **Verdict fence**: GateVerdictForm / FindingReviewForm remain the ONLY
  dispositions; chat exposes none. Test-pinned.
- Capability handshake + EndpointMissingNote version-skew pattern preserved.
- Execution via worktree-isolated UI agents (ui/ + ui_plan.md only), primary
  merges --no-ff after vitest + backend pytest + real :8700 smoke per slice.
- ui_plan.md dated entry per slice; UI stays shippable between slices.
- Runs inside the owner's 10-hour loop alongside the Qwen A/B window and
  10-minute progress updates.

## Verification (end-to-end)

Per slice: `npx vitest run` (ui/frontend) + `ui/.venv` pytest (ui/backend)
green in the worktree; `tools/premerge_check.sh` on the branch range; primary
merges `--no-ff`; real `:8700` smoke per the slice gates above. Final:
every nav destination + all three redirects load against live data;
`/api/ladder` returns the real 70 clusters; a gate-verdict dossier walks
calibrate → reveal → chat → verdict end-to-end; the pre-ladder 31 appear
ONLY in the picker's "everything else" section; `git grep` shows no retired
endpoint references; `ui-services.sh ensure` still passes. 10h-loop
integration: Qwen A/B window now self-serve (docker allow rule added by
owner 2026-08-15) — open window → stage3a driver both models → restore +
MARLIN/margin verify → D-0zz draft; frontier F1 sweep + F2 re-calibration
interleave; PushNotification updates every ~10 min.
