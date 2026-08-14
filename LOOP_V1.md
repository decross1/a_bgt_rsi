# LOOP_V1 Restructure — un-zombie, evidence ladder, memory, frontier tier, micro-org plumbing

> Active build plan, approved by the owner 2026-08-14 (successor to [`LOOP_V0.md`](LOOP_V0.md),
> which stays as the record of the v0 slice). Session note: `human/sessions/2026-08-14.md`.
> Decisions: D-059..D-062 (+ Qwen pin template). CLAUDE.md's "active build plan" pointer is
> updated to this file as part of the G5 human-gated contract edit.

## Context

The apparatus has been silently stalled since 2026-08-05: 20 consecutive coordinator
cycles planned only `promote_findings(max_candidates=1)`, each "passed" in ~12s while
promoting nothing (a fixed point: frozen state snapshot + temp-0.1 planner + gaps that
only say "await human"). All 31 surfaced findings were unanimously refuted by the Qwen
skeptic panel (16 with redteam `fatal_flaw`) and promoted anyway — the promotion
threshold reads 3 of ~15 signals and ignores both negative ones. Zero findings have
ever been human-dispositioned. External literature search was blind on ~60% of recent
iterations (arxiv 429), driving `undecidable` critic verdicts (22/40). Duplication
pathology is measured: 8–10× restatement clusters (May), seed-level rediscovery
(Jul–Aug, 18 distinct seeds across 40 iterations, incl. re-deriving a retrieved paper).
No alerting path exists anywhere; health signals go silent exactly when the loop stalls.

Owner direction (this session): rebuild toward selection-before-the-human. Bar, not
quota: ~1 deeply-vetted finding/week surfaced; consolidate+demote the 31 (archive junk,
no human-validation pass yet); frontier subscriptions (Claude + ChatGPT) wired as a
priority adversarial screen; idea-ledger memory for orchestrator continuity (wiki shape
rejected on measured grounds — two research sweeps grounded the design in MAP-Elites /
IDEAAgent / negative-knowledge literature); micro-org plumbing + self-serve SDLC in this
build; Qwen 3.6→3.8-27B upgrade prep scoped as a gated track. UI redesign parked.

## Settled architecture (from discussion + research sweeps)

1. **Evidence ladder** L0 asserted → L1 literature-consistent → L2 synthetic-tier
   checked → L3 robustness-stable → L4 survived adversarial (redteam + skeptic vote,
   currently ignored) → L5 committee-reviewed. Only L4+ surfaces. Zero-survivor weeks
   report honestly. Supersedes D-053 advisory flip (decision entry).
2. **Idea ledger + archive** (runtime-side; gbrain stays process-memory, D-014 intact):
   canonical claim records {problem, mechanism, predicted_effect, evidence_ref};
   dedup-ladder clusters = niches (no descriptor grid); MAP-Elites elite rule with
   LLM equivalence-or-better as top layer over the embedding/lexical prefilter
   (judge calibrated first against known 8–10× restatement clusters); pre-closed
   niches seeded from retrieved papers (rediscovery must articulate a delta);
   programmatic kill reasons (never LLM prose — Honest Lying 0/121 result);
   mandatory adopt-or-reject of matched failure records at generation time;
   three-section deterministic projection `ideas.md` (live work w/ rung + next test
   owed / graveyard / agenda with provenance) consumed by topic selection +
   hypothesize conditioning. Agenda replaces raw arxiv_pick as topic driver.
3. **Frontier tier = falsifier, never generator.** Early screen at L1→L2: methods
   reviewer + novelty reviewer as opposed jobs split across Claude/ChatGPT; escalate
   disagreements only. Vetoes are attention filters (reproducibility-clean); every
   call logged append-only → frontier-vs-local calibration dataset. Weekly frontier
   agenda-synthesis pass proposes (never writes) agenda items. Never writes
   loop_memory/brain. Amendment entries for D-012/D-033.
4. **Un-zombie + alarms:** staleness + ladder-derived gaps in assess_state; stall
   detector (0 iterations + 0 promotions + 0 ladder advancement → status=stalled +
   health signal); health signals decoupled from dispatched-iteration scoping;
   persist planner state/attempts in cycle rows; fix arxiv 429 blindness; a real
   alert surface.
5. **Micro-org plumbing, enforcement first** (PoE lessons: install the gate before
   the autonomy story): task-packet schema (fields only the dispatcher mechanically
   reads), attempt-increment-before-invoke, dispatcher-owns-ack, branch-per-packet
   worktrees, mechanical pre-merge check (protected paths / banned patterns / no
   test deletions), entrenchment tiers (plumbing merges on green+review; spine /
   schema / pins / promotion-bar require human ratification), admin-actions ledger
   for human overrides.
6. **Self-serve SDLC (this build's execution model):** slice → dynamic-workflow
   build agents (disjoint new files, spawn contracts) → framework code-review skill
   on local range → full suite + one real `env -u MOCK_LLM` smoke → self-merge by
   primary session → run-log + decision entries.
7. **Qwen 3.8-27B prep (gated):** acquisition/quant matching current serving, D-057
   memory-budget fit, fixture-based A/B on the skeptic/judge roles, pin-amendment
   decision template, rollback. Cutover requires human ratification (inviolate rule 2).

## Phases

(To be filled from the two Plan-agent seam reports: concrete files, spine touchpoints,
schemas, migration steps, slice ordering, verification per slice.)

### P0 — Un-zombie + honest telemetry

Seam corrections from code verification: near-miss re-append lives in
`coordinator._persist_near_misses` (coordinator.py:633-656), not finding_promotion;
`workers/ml_intern.py` queries **Semantic Scholar** (not arXiv) and already has
backoff + Retry-After — the 24/40 zero-paper runs are S2 exhaustion (or missing
`SEMANTIC_SCHOLAR_API_KEY`); loop_memory/surfaced JSON is clean (the "python-repr
strings" fact was false — no normalization migration; only 2 leaked-claim rows to
repair at consolidation).

- New `orchestrator/loop_health.py` (non-spine, ~A8) + tests: `staleness_gap`
  ("loop has not iterated in N days", STALE_DAYS=2), `ladder_gaps` ("k candidates
  at L3 awaiting battery"), `detect_stall` (0 iterations + 0 promotions + no ladder
  advancement → `loop_stalled` signal), `write_alert_flag` →
  `run_state/loop_alert.json` {level: red|amber|ok}; CLI `--check` exits non-zero
  on red (cron/MAILTO-able; cockpit polls the flag).
- `coordinator.py`: staleness + ladder gaps into `assess_state`; agenda-first
  `_topic_suggestions` (arxiv pick demoted to last resort); keyed near-miss dedup
  `(source_iteration_id, stage, reason)` — legacy 5,513 rows stay as history and
  seed the key set; planner prompt describes ladder gaps + agenda semantics.
- `coordinator_cycle_log.py`: cycle rows carry `attempts` + compacted `state`
  (planner I/O finally auditable); `emit_health_signals` decoupled from
  dispatched-iteration scoping — stall/staleness always run; **deliberately update
  the pinned test** `tests/test_coordinator_cycle_log.py:285` (documented behavior
  change, not silent coercion).
- `workers/ml_intern.py`: diagnose from health-signal payloads first; then on
  `MLInternFetchError` an **explicit, logged, time-capped fallback** (rule 7) to
  local `papers_recent` Chroma search, result marked `source: local_fallback` —
  the critic's evidence basis never silently degrades.

### P1 — Evidence ladder + promotion refit + consolidation of the 31

Rung derivation is pure Python, never LLM prose, never coerced (missing signal ≠
pass): L0 asserted · L1 literature-consistent (relevance ok + novel + critique
survives + redteam ≠ fatal_flaw; `provisional: external_search_blind` when the
iteration carries ml_intern_zero_papers) · L2 experiment_outcome (trials ≥ 30) ·
L3 robustness/replication from run records · L4 adversarial vote `survived=True`
**AND** redteam `proceed` (the two currently-ignored signals become the L3→L4
gate) · L5 human `valid` verdict. **Only L4+ surfaces.** Zero-survivor weeks
report a count, never a coerced promotion.

- New workers (disjoint, parallel-buildable): `workers/evidence_ladder.py` (A1,
  pure rung derivation + `next_test_owed`), `workers/claim_extract.py` (A2,
  canonical {problem, mechanism, predicted_effect, evidence_ref}; repairs the 2
  leaked-JSON-blob claims), `workers/consolidate_memory.py` (A7, one-shot
  idempotent migration CLI, dry-run default).
- Integrator: `finding_promotion.py` — `_passes_threshold` replaced by ladder
  logic; adversarial vote writes `evidence_level_changed` events instead of a
  binary gate; `NARA_PROMOTION_VOTE_ADVISORY` branch retired (D-059); additive
  `evidence_level` + `cluster_id` on surfaced rows.
- Migration: dry-run → **blocking human gate on the consolidation summary** →
  execute (expected: 68 clusters over 101 rows; 16 killed on redteam fatal_flaw
  with programmatic kill_reason; ~7 at L2; all 31 surfaced findings demoted below
  L4 — honest; near-dup members archived append-only to `memory/idea_archive.jsonl`;
  loop_memory/surfaced_findings **never rewritten**).
- The bogus `iter-2026-06-05-002` "invalid" test verdict: readers are last-row-wins
  (verified) — the **human** appends a superseding gate verdict via
  `orchestrator.gate_cli` (plan prints the exact command and halts; the apparatus
  never writes gate verdicts — rules 3/9).

### P2 — Frontier critic tier

Grounded host facts: `claude` 2.1.233 + `codex` 0.146.0 both installed (npm-global);
`ANTHROPIC_API_KEY` **is set globally** — the metered-API routing trap is live;
codex has stored login. D-033 is already superseded by D-035 (multi-backend substrate);
D-041/D-044 made vllm-qwen the standing skeptic with Claude as skeptic-ladder step 3
(design-only) — this track *executes* that step, plus fixes the stale CLAUDE.md
"second model excluded (D-033)" bullet.

New files (workflow-parallelizable):
- `agent_wrapper/frontier_cli.py` (~200L + test): subprocess seam for `claude -p
  --output-format json` and `codex exec`; spawned env **strips ANTHROPIC_API_KEY /
  ANTHROPIC_AUTH_TOKEN** (mandatory test asserts absence); MOCK_LLM → deterministic
  stub; fail-closed structured errors; every call appended to ledger before return.
- `workers/frontier_review.py` (~300L + test): methods_reviewer + novelty_reviewer
  role prompts, strict-JSON `{verdict: veto|pass|inconclusive, reasoning,
  closest_prior_work?}`; parse failure → inconclusive (fail-open at this seam — a
  frontier outage must not block the local loop); Claude=methods / Codex=novelty
  default (env-overridable); disagreement → cross-run once, then inconclusive +
  escalations.jsonl row.
- `orchestrator/frontier_agenda.py` (~180L + test): deterministic projection →
  both vendors → proposals appended to `memory/frontier_agenda.jsonl` as
  `proposed_by: frontier:<vendor>`, `status: proposed` (inert until accepted).
- `cron/weekly-frontier-agenda.sh`: run-coordinator gate pattern (flock, pause
  file, `run_state/frontier_tos_ratified` sentinel — created only when the human
  clears the ToS gate); committed dark.
- `schema/frontier_call.schema.json` + append-only `run_state/frontier_calls.jsonl`
  `{timestamp, vendor, cli_version, role, candidate_id, verdict, reasoning_digest,
  duration_ms, exit_code, prompt_sha256}` — doubles as the frontier-vs-local
  calibration dataset (join on candidate_id vs the Qwen vote fields).

Spine touchpoints (serial integrator): `finding_promotion.py` gains an env-gated
(`NARA_FRONTIER_SCREEN`, default off) veto stage after the cheap gate and before
the Qwen vote; veto → near_miss `reason: frontier_veto` with both reviews attached;
survivors carry `frontier_screen` annotation (optional field in
`schema/surfaced_finding.schema.json`). Frontier never writes loop_memory or the
brain — annotate-only firewall.

### P3 — Idea ledger, archive, projection, agenda

The ledger is an **append-only event log**; everything else is a projection.
`memory/idea_ledger.jsonl`: events `cluster_created / member_added /
evidence_level_changed / cluster_killed / cluster_reopened / niche_seeded /
agenda_item_added|consumed`; cluster state = deterministic reduction. Overlay
keyed by iteration_id/finding_id — existing ledgers never rewritten.

- New workers: `workers/idea_ledger.py` (A3, events + reducer +
  `schema/idea_ledger.schema.json` + MAP-Elites `accept_candidate` — prefilter
  reuses mine_paper_gap lexical-Jaccard/cosine layers via import; judge is an
  injected seam defaulting to prefilter-only until calibration passes;
  programmatic kill_reason builders + evidence-keyed reopening_condition),
  `workers/idea_projection.py` (A4, byte-stable three-section `ideas.md` +
  `conditioning_lines()` + `agenda_topics()`), `workers/idea_judge.py` (A5,
  equivalent/better_with_delta/distinct strict-JSON judge + `--calibrate` CLI),
  `workers/failure_match.py` (A6, generation-time adopt-or-reject vs killed
  clusters + paper niches).
- Spine touchpoints (serial integrator, minimal): `schema/iteration_record.schema.json`
  additive optional `idea_ledger` block {cluster_id, evidence_level, failure_match};
  `orchestrator/nara.py` post-hypothesize orchestrator-driven failure_match step
  (mirrors the ml_intern pattern — NOT a new registry tool; rediscovery without an
  articulated delta reuses the existing `_hypothesize_retry` path with kill_reason
  as critique). **`tool_registry.py`: zero changes.** ideas-projection conditioning
  flows through `workers/meta_review.py` conditioning_bullets (non-spine edit).
- `workers/mine_paper_gap.py` survivors become **agenda candidates** (ledger
  events), consumed by the coordinator's agenda-first topic suggestions.
- Paper niches: seeded pre-closed from papers_recent titles + retrieval neighbors;
  a candidate matching a paper niche must articulate a delta or is rejected as
  rediscovery.
- **Judge calibration (before the LLM layer activates):** ground truth = the known
  lexical clusters (sizes 10/8/7/4; ~50 positive pairs, ~30 hard negatives by
  cosine, ~20 random); pre-registered bars as module constants — equivalence
  precision ≥ 0.90, recall ≥ 0.80, false-equivalence ≤ 10%, order-symmetry
  disagreement ≤ 10%, verdict flip ≤ 15%; each checked independently via the
  `validate` skill, never coerced. Fail → prefilter-only stands, judge logged
  advisory-only; result recorded via the `experiment` skill either way.

### P4 — Micro-org plumbing + SDLC codification

This is `orchestrator/authorize_fix.py`'s documented "stage-(ii)" dispatcher.
Ordering per PoE lessons: **gate script + ledger land and are tested before any
dispatcher runs.**

New files:
- `schema/task_packet.schema.json`: {task_id, objective, files_in_scope/out,
  preconditions (zero-token shell gates), acceptance_criteria {test_cmd,
  must_fail_before: true}, budgets {max_attempts, wall_clock_minutes,
  max_diff_lines}, forbidden_actions, rollback}. A test walks schema properties and
  greps the dispatcher for each — "a field the dispatcher doesn't read is
  documentation, not control", made mechanical.
- `tools/premerge_check.sh` (~150L bash, no LLM) + fixture tests: FAIL on protected
  paths (nara.py, tool_registry.py, schema/, run_state/, CLAUDE.md, DECISIONS.md,
  cron/serve-models.sh, agent/, ui/ when a ui-session worktree is live, version-pin
  strings), deleted/skipped tests, banned patterns, diff-lines over packet budget.
- `orchestrator/packet_dispatcher.py` (~350L + test): NEW `run_state/packets.jsonl`
  ledger (spawn.jsonl stays a discipline; packets.jsonl is a machine-enforced
  control — don't mix semantics). Two-line open/close; **attempt incremented
  before invoke**; per attempt: preconditions → acceptance test must FAIL
  (red-first) → worktree branch `pkt/<id>` → invoke agent (subprocess-injectable;
  salvage sentinel/timeout/escalation patterns from stale
  `dispatch_coding_agent.py`, don't import it) → dispatcher (never the agent) runs
  acceptance test + premerge_check → done/retry/exhausted. Dispatcher never merges.
  Consumes `memory/authorize_fix_queue.jsonl` rows as one packet source.
- `run_state/overrides.jsonl` + `orchestrator/override_log.py` (~60L): every human
  override as `{timestamp, actor, packet_id, action, rationale}` (attestations
  pattern).
- `docs/packet_sdlc.md`: codifies the execution path (slice → workflow build agents
  → framework code-review skill on local range → suite + real smoke → primary
  self-merge → run-log/decision entries) + the **entrenchment tier list**:
  Tier P (workers/, tools/, tests/, docs/) merges on green + review;
  Tier S (spine, schema/, pins, promotion-bar constants, CLAUDE.md, DECISIONS.md,
  cron/serve-models.sh) requires human ratification logged in overrides.jsonl /
  DECISIONS.md.

Spine touchpoints: none mandatory this build (dispatcher is dev-time, primary-
session-invoked). A coordinator action-menu entry is deliberately deferred —
runtime dispatching coding agents crosses the D-014 dev/runtime line and is its
own gated decision.

### P5 — Qwen 3.6→3.8-27B upgrade prep (gated; NO cutover this build)

Current serve config grounded: vLLM v0.21.0 pin, `/mnt/models/qwen3.6-27b-nvfp4-mtp`,
`--quantization modelopt --kv-cache-dtype fp8 --gpu-memory-utilization 0.25`,
MTP `qwen3_5_mtp`, parsers `qwen3`/`qwen3_coder`. No 3.8 weights on disk.

New files: `docs/qwen38_upgrade_checklist.md` (acquisition: NVFP4 ModelOpt + MTP
head matching 3.6, to `/mnt/models/qwen3.8-27b-nvfp4-mtp`; open question resolved by
reading not pulling: does vLLM v0.21.0 support 3.8's MTP/parsers — if not, that's a
pin-amendment question under rule 2, never a workaround; disk needs ~19 GiB free
alongside 3.6 for rollback; `preflight_mem.sh 0` after swap, margin HELD, MARLIN
re-verified) + `bench/critic_eval/qwen_ab.py` (~250L + test): side-by-side battery
on the roles Qwen actually plays — skeptic-ladder cases (D-044 pass criteria
verbatim), finding_promotion multi-vote on fixed historical candidates, two-voice
attacker spot-run; A/B window may require stopping Gemma (say so; don't thin the
margin). Verify at build: whether restate_skeptic is even on Qwen (it uses
call_sync → default Gemma backend; possibly not a Qwen role).
Decision-entry template `D-0zz` (battery table, pass criteria verbatim, serve-diff,
rollback: 3.6 weights retained ≥30 days; inventory hardcoded model-name strings).
Human gates: weight acquisition, A/B serve window, cutover ratification.

## Execution model (waves, maximizing dynamic workflows)

- **Wave 0 (serial):** D-059/D-060 decision entries; spawn contracts + spawn.jsonl
  rows for the whole build wave; commit the plan into the repo (session note +
  LOOP_V1 doc per the plan-mode-artifacts rule).
- **Wave 1 (parallel, ~13 build agents across tracks, disjoint new file + test
  each, done-condition = own test green under MOCK_LLM):** A1–A8 (ladder/ledger/
  health), frontier_cli + frontier_review, premerge_check + task_packet schema,
  qwen checklist + qwen_ab. Cross-import signatures carried verbatim in the spawn
  contracts.
- **Wave 2 (serial integrator, suite after each):** finding_promotion (ladder +
  frontier veto stage) → coordinator/cycle_log + pinned-test update → nara/schema
  additive block → meta_review/mine_paper_gap/ml_intern → packet_dispatcher +
  overrides ledger → frontier_agenda + cron (dark).
- **Wave 3:** judge-calibration real run (gated activation); packet-dispatcher
  end-to-end on a trivial known-red fixture packet.
- **Wave 4:** migration of the 31 + 101 (two blocking human gates: consolidation
  summary; superseding gate-verdict command printed for the human).
- **Wave 5 (verify gate per merge + final):** framework `code-review` skill on
  `git diff <merge-base>..HEAD` (never the GitHub builtin), full suite, one real
  `env -u MOCK_LLM` smoke. Single merge authority = primary session. UI work order
  (L4+-only cockpit view + loop_alert.json red-state polling) authored into the
  session note for a UI session — no workflow agent touches ui/.

## Governance / decision entries to file

- **D-059** — evidence ladder supersedes D-053: `NARA_PROMOTION_VOTE_ADVISORY`
  retired; the adversarial vote is the L4 rung, neither binary gate nor ignored
  advisory. Surfacing bar = L4+.
- **D-060** — idea ledger + MAP-Elites acceptance + judge-calibration precondition
  (wiki shape rejected on measured grounds, citations in session notes).
- **D-061** — frontier critic tier: executes D-041 skeptic-ladder step 3;
  supersedes-in-part D-012's no-routing posture *for the screen seam only*;
  annotate-only firewall (frontier never writes loop_memory/brain). Includes the
  CLAUDE.md fix for the stale "second model excluded (D-033)" bullet (D-033 was
  already superseded by D-035 live practice).
- **D-062** — task-packet micro-orgs (stage-(ii) of the D-046 authorize-fix path)
  + entrenchment tier list (Tier P merges on green+review; Tier S human-ratified).
- **D-0zz** — Qwen 3.6→3.8 pin amendment: template only; ratified at cutover.

## Human gates (explicit, blocking)

- **G1 — frontier ToS/off-box** (per vendor: Claude Max headless via `claude -p`;
  ChatGPT via `codex exec`; hypothesis/corpus text leaves the box): cleared by
  creating `run_state/frontier_tos_ratified`; the first real frontier smoke and the
  cron stay dark until then. `ANTHROPIC_API_KEY` env-strip guard is code + test,
  landing regardless.
- **G2 — consolidation summary** (dry-run output of the 31+101 migration) before
  events are written. Demotion is append-only events — reversible by design.
- **G3 — superseding gate verdict** for `iter-2026-06-05-002`: human runs the
  printed `gate_cli` command; the apparatus never writes gate verdicts.
- **G4 — entrenchment tier list ratification** (it constrains the human too).
- **G5 — D-061 + CLAUDE.md bullet fix** (operating-contract edit).
- **G6 — Qwen weights acquisition go/no-go; A/B serve window (may require stopping
  Gemma); cutover ratification** (inviolate rule 2). Cutover is NOT this build.

## Verification

- Standing gate per merged slice: framework `code-review` skill on the local range
  + full MOCK_LLM=1 suite + one real `env -u MOCK_LLM` smoke.
- Non-coercion regression pins: a row with redteam `fatal_flaw` + critique
  `survives` never reaches L1 (today's blind spot); ladder missing-signal ≠ pass;
  consolidate idempotency (second run appends zero events); near-miss keyed append
  (second identical cycle appends zero rows); premerge_check fails a synthetic
  protected-path diff; frontier subprocess env asserts ANTHROPIC_API_KEY absent.
- Final end-to-end (the fixed-point regression check): two consecutive real
  `coordinator --once` cycles must (a) show staleness/ladder gaps in the persisted
  planner input, (b) produce **differing plans**, (c) plan a loop iteration again,
  (d) write stall/health telemetry honestly if nothing advanced. Judge-calibration
  result reported before the LLM acceptance layer activates. One real dispatched
  packet walks the full premerge gate before D-062 is marked done.

## Explicitly out of scope this build

- Cockpit/UI redesign (parked; only the L4+ view + alert polling as a UI-session
  work order). Qwen 3.8 cutover. Coordinator-runtime packet dispatch (D-014 line —
  own gated decision later). Free-text→bespoke-experiment synthesis (S4 keystone).
  External-literature wiki layer (Phase 2, after S2 search is proven healthy).
