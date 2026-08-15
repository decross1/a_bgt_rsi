// TypeScript mirrors of the backend's JSON responses. Call-log payload
// fields are deliberately left open (`raw`) so a future schema addition
// does not break the inspector.

// Retrieval-context entry: a chunk of a retrieved document. The backend
// only forwards the field if the call record carried a list of objects;
// the inspector renders each entry as a collapsible row.
export interface RetrievalDoc {
  doc_id?: string;
  content_hash?: string;
  chunk_offset?: number;
  chunk_length?: number;
  [key: string]: unknown;            // forward-compatible — render generically
}

export interface ChainNode {
  // "tool" nodes are tool calls — either separate call-log lines or, when
  // `embedded` is true, synthesized from a wrapper record's tool_calls array.
  kind: "dispatch" | "call" | "tool";
  request_id: string | null;
  parent_request_id: string | null;
  caller_tag?: string | null;
  task_id?: string;
  task_type?: string | null;
  status?: string | null;
  worker_pid?: number | null;
  timestamp: string | null;
  latency_ms: number | null;
  parse_error?: boolean;
  // True when a wrapper recorded its tool_calls in the wrong shape (string,
  // dict, etc.) instead of a list — the inspector surfaces this as a red
  // banner rather than silently format-fixing.
  tool_calls_malformed?: boolean;
  embedded?: boolean;
  // Optional list of {doc_id, content_hash, chunk_offset, chunk_length}.
  // Null when the call record did not carry it.
  retrieval_context?: RetrievalDoc[] | null;
  raw: Record<string, unknown>;
  children: ChainNode[];
}

export interface ChainResponse {
  root_request_id?: string;          // wrapper-rooted chain
  found: boolean;
  malformed: boolean;
  root: ChainNode | null;
  node_count: number;
  total_latency_ms: number;
  malformed_tool_calls?: number;     // count of parse-error nodes in the chain
}

// /api/workload_hint — workload-shape annotation for the decode-tok/s tile.
// Lets the dashboard contextualize the tile so a prefill-bound workload
// doesn't read as a regression against the decode-bound band.
export interface WorkloadHint {
  available: boolean;
  sample_size: number;
  calls_per_s: number | null;
  median_output_tokens: number | null;
  regime: "short_completion" | "decode_bound" | "mixed" | "idle";
  expected_decode_tok_s_lower: number | null;
  expected_decode_tok_s_upper: number | null;
  window_s: number;
  note: string;
}

export interface Health {
  ok: boolean;
  hostname: string;
  telemetry_last_seen: string | null;
  version: string;
}

// --- telemetry (mirrors ui/schema/telemetry.jsonl.schema.json) ---

export interface GpuSample {
  util_pct: number | null;
  mem_used_mb: number | null;
  mem_total_mb: number | null;
  temp_c: number | null;
  power_w: number | null;
}

export interface HostSample {
  cpu_pct: number;
  mem_used_mb: number;
  cpu_temp_c: number | null;
  load_avg: [number, number, number];
}

export interface VllmSample {
  running_requests: number;
  waiting_requests: number;
  gpu_cache_usage_pct: number;
  gpu_prefix_cache_hit_rate: number | null;
  tokens_per_sec_decode: number | null;
  mtp_acceptance_rate: number | null;
  mtp_draft_tokens: number | null;
  mtp_accepted_tokens: number | null;
}

export interface ProcessSample {
  pid: number;
  name: string;
  cpu_pct: number;
  rss_mb: number;
  threads: number;
}

export interface TelemetrySample {
  timestamp: string;
  gpu: GpuSample | null;
  host: HostSample | null;
  vllm: VllmSample | null;
  // Second vLLM endpoint (Qwen3.6-27B NVFP4-MTP on :8001). Null when
  // VLLM_QWEN_METRICS_URL is empty/unset or the endpoint is unreachable
  // (graceful degradation, see ui/sampler/sources/vllm_metrics.py).
  // Same shape as `vllm` — both are parsed by VllmMetricsReader.
  vllm_qwen?: VllmSample | null;
  processes: ProcessSample[];
  read_errors: Record<string, string> | null;
}

// Message shape from the /api/live WebSocket.
export interface LiveMessage {
  source: "telemetry" | "orchestrator";
  line: Record<string, unknown>;
}

// --- LOOP_V0 ---
// Shared contract: the primary session writes run_state/active_iteration.json
// + memory/loop_memory.jsonl + journal/iterations/NNN.md; the UI reads them
// via /api/loop_v0/iterations and /api/loop_v0/journal/{id} (the single-slot
// active mirror retired in S3 — the D-047 registry is the live-run source;
// ActiveIteration stays as the nowVerdict input type). See LOOP_V0.md and
// ui_plan.md §LOOP_V0.

// Matches schema/active_iteration.schema.json. current_step is the tool
// currently in flight, "starting" at iteration open, or "nara_thinking"
// between calls (what the producer writes in nara.py).
export type LoopV0Step =
  | "starting"
  | "summarize_paper"
  | "play_pd_match"
  | "query_chroma"
  | "journal_writer_stub"
  | "nara_thinking";

// status mirrors schema enum ["in_progress", "passed", "error"].
export type LoopV0ToolStatus = "in_progress" | "passed" | "error";

export interface LoopV0ToolCall {
  tool: string;
  started_at: string;
  ended_at?: string | null;
  status?: LoopV0ToolStatus | string | null;
  narration?: string | null;
  // Backend that powered this tool's LLM calls (registry name, e.g.
  // "vllm-gemma"). Inherits from `ActiveIteration.orchestrator_backend`
  // unless the worker reported a `backend_used` override in its
  // tool_result. Null for tools that make no LLM calls (e.g.
  // retrieve_literature, journal_writer).
  backend?: string | null;
  // Served-model-name the tool used (e.g. "gemma-4-26b-a4b"). Pairs
  // with `backend`.
  model?: string | null;
  // When a tool dispatched a SubAgent (today: critic_loop_v0), the
  // backend that powered the sub-agent. May differ from the tool's own
  // backend once Phase 3's critic-flip lands (Co-Scientist insight; D-035).
  subagent_backend?: string | null;
  // Served-model-name the sub-agent used. Pairs with `subagent_backend`.
  subagent_model?: string | null;
}

// One entry of active_iteration.json's OPTIONAL `steps[]` board (2026-06-10,
// schema/active_iteration.schema.json): the planned LOOP_V0 chain — meta_review
// + hypothesize/retrieve_literature/novelty_classify/critic_loop_v0/
// journal_writer — with dynamic sub-loop steps (redteam, ml_intern) inserted by
// the producer when those sub-loops fire. `status` stays an open string so an
// unknown future status renders generically rather than crashing; UNKNOWN step
// NAMES likewise render raw (the producer may add steps; never filter).
export interface IterationStep {
  name: string;
  status: "pending" | "running" | "passed" | "failed" | "skipped" | string;
  started_at?: string | null;
  ended_at?: string | null;
}

export interface ActiveIteration {
  iteration_id: string;
  topic: string;
  started_at: string;
  current_step: LoopV0Step | string;
  step_started_at?: string | null;
  // The producer writes `latest_narration` (schema/active_iteration.schema.json).
  latest_narration?: string | null;
  // Backend (registry name, e.g. "vllm-gemma", "anthropic") that drives
  // the Nara orchestrator brain for this iteration. Null on legacy
  // iterations written before the multi-backend substrate landed.
  orchestrator_backend?: string | null;
  // Served-model-name the orchestrator backend is using (e.g.
  // "gemma-4-26b-a4b"). Pairs with `orchestrator_backend`; null on
  // legacy iterations.
  orchestrator_model?: string | null;
  // OPTIONAL planned-chain status board (2026-06-10). Absent on
  // pre-2026-06-10 iterations — the panel falls back to its static strip.
  steps?: IterationStep[];
  tool_calls_so_far?: LoopV0ToolCall[];
  // Loop v1 blocks may surface on the active record too: meta_review is
  // computed at iteration start (Step 1.5), and redteam / gate_status
  // appear once those steps run. Same shapes as on IterationRecord; all
  // optional so the panel renders cleanly across pre-v1 and v1 rows.
  meta_review?: {
    conditioning_bullets?: string[];
    rows_considered?: number;
  } | null;
  redteam?: {
    verdict?: "fatal_flaw" | "proceed" | string;
    critique?: string;
    suggested_revision?: string | null;
    confidence?: number;
    retries_used?: number;
  } | null;
  gate_status?: "pending" | "valid" | "invalid" | "needs_revision" | string;
}

// One row of memory/loop_memory.jsonl. Part-1 hello-world fills the
// novelty/critique/retrieval blocks with placeholders; the fields are
// declared optional so the UI can render across both Part-1 and Part-2.
export interface IterationRecord {
  iteration_id: string;
  started_at: string;
  ended_at: string;
  seed?: { topic?: string; source?: string } | null;
  hypothesis?: { text?: string; candidates_considered?: number } | null;
  retrieval?: {
    k?: number;
    neighbors?: unknown[];
    // Topical-relevance gate (EMIT: workers/retrieval_relevance.py, schema
    // iteration_record.relevance). Drives the low-evidence badge: a
    // `novel/survives` verdict resting on thin/off-domain retrieval is flagged.
    // Field names ARE the EMIT contract (not score/flag): `relevance` is the
    // blended score in [0,1] (higher = more grounded), `low_confidence` the
    // boolean the worker sets when retrieval is thin/irrelevant, `reason` the
    // human-readable why. Absent on pre-2026-06-09 rows.
    relevance?: {
      relevance?: number;
      low_confidence?: boolean;
      reason?: string;
      // Additive diagnostics (EMIT: workers/retrieval_relevance.py `_out`,
      // close-out 2026-06-09 evening additions + `topicality` 2026-06-10).
      // The three keys above are FROZEN (UI join contract, commit 0fdb671);
      // the additive set — anchor_cosine, curated_overlap, neighbor_spread,
      // topicality, category, rule_fired — is optional and absent on rows
      // written before the diagnostic ladder landed. `anchor_cosine` is the
      // hypothesis↔GT-domain-anchor cosine (null under MOCK_LLM or when no
      // anchor is usable); `topicality` is the caller-computed LLM domain
      // judgment ("on"|"off"|"unsure"|null, orchestrator/topicality.py) that
      // drives the condemn-only ladder rule R0 (live on rows since
      // iter-2026-06-09-006); `rule_fired` is the first R0..R5 ladder rule
      // that fired (null when none did — note R3/R4/R5 ship inert until
      // their constants are calibrated).
      anchor_cosine?: number | null;
      curated_overlap?: number | null;
      neighbor_spread?: number | null;
      topicality?: "on" | "off" | "unsure" | string | null;
      // ADVISORY-ONLY topicality dissent (EMIT: orchestrator/nara.py attaches it
      // AFTER relevance(); DATA_SHAPES Changelog 2026-06-14 / D-052). The
      // independent adversarial topicality judge that D-052 RETIRED as a gate
      // (it over-flags novel on-domain claims). Present ONLY when
      // NARA_TOPICALITY_ADVISORY=1 (dark by default) AND the primary judge did
      // NOT already condemn → ABSENT on normal rows. It is NON-GATING: it never
      // feeds `low_confidence`, novelty, or critic verdicts, and must NOT reuse
      // the amber low-evidence styling. The UI surfaces an `"off"` as a weak
      // "independent topicality dissent (advisory)" hint; other values render
      // nothing (the raw field still shows in the detail modal).
      topicality_advisory?: "on" | "off" | "unsure" | string | null;
      category?: "off_domain" | "thin" | "no_sharp_match" | "empty" | "ok" | string;
      rule_fired?: string | null;
    } | null;
  } | null;
  novelty?: {
    class?: "novel" | "rediscovery" | "nonsense" | "unclear" | string;
    rationale?: string;
    top_neighbor_id?: string | null;
    // Set true when the underlying retrieval was thin/off-domain (EMIT:
    // workers/novelty_classify.py; live since 2026-06-09; absent on older rows).
    low_confidence?: boolean;
    // Decomposed novelty judgment (EMIT: workers/novelty_classify.py, close-out
    // 2026-06-09 evening additions). Null on sentinel/legacy outputs — the
    // producer emits an explicit null, so model `| null` as well as absent.
    novelty_axes?: {
      phenomenon?: "known" | "novel" | string;
      substrate?: "studied_llm" | "unstudied_llm" | "na" | string;
      predicted_direction?: "matches" | "deviates" | "silent" | string;
    } | null;
    // Present only when a deterministic override fired (e.g. low-confidence
    // retrieval downgraded a derived "novel" to "unclear"). Render as plain
    // strings; absent on legacy rows.
    verdict_overridden_from?: string;
    override_reason?: string;
    // Declared on both blocks per the close-out; today only critic_loop_v0
    // actually emits it (the novelty producer does not run the skeptic).
    skeptic_verdict?: string | null;
  } | null;
  critique?: {
    // "undecidable" added 2026-06-09 (EMIT: workers/critic_loop_v0.py) —
    // fails closed; every consumer gates on `== "survives"`. Render it as a
    // plain string chip like the other verdicts.
    verdict?:
      | "survives"
      | "falsified"
      | "restated"
      | "malformed"
      | "undecidable"
      | string;
    rationale?: string;
    contradicting_paper_id?: string | null;
    // Set true when the underlying retrieval was thin/off-domain (EMIT:
    // workers/critic_loop_v0.py; live since 2026-06-09; absent on older rows).
    low_confidence?: boolean;
    // Present only when a deterministic override fired (coverage bar,
    // low-confidence hard rule, or skeptic refutation — EMIT:
    // workers/critic_loop_v0.py, close-out 2026-06-09 evening additions).
    verdict_overridden_from?: string;
    override_reason?: string;
    // Present only when the β skeptic-gate seam ran (env NARA_SKEPTIC=1,
    // D-041); may be null when the attack returned no verdict.
    skeptic_verdict?: string | null;
  } | null;
  // Loop v1 Step 1.5: conditioning synthesis from prior loop memory. The
  // bullets are injected into this iteration's initial message. Absent on
  // pre-v1 rows and when meta_review degraded (schema/iteration_record).
  meta_review?: {
    conditioning_bullets?: string[];
    rows_considered?: number;
  } | null;
  // Loop v1 Step 2.5: orchestrator-driven red-team retry sub-loop. `verdict`
  // is "fatal_flaw" or "proceed"; `retries_used` counts revision rounds.
  // Absent on pre-v1 rows.
  redteam?: {
    verdict?: "fatal_flaw" | "proceed" | string;
    critique?: string;
    suggested_revision?: string | null;
    confidence?: number;
    retries_used?: number;
  } | null;
  // Loop v1 Step 8: human-gate state. "pending" at finalize; a human
  // verdict resolves it. Absent on pre-v1 rows.
  gate_status?: "pending" | "valid" | "invalid" | "needs_revision" | string;
  // Cross-tier bridge (schema/iteration_record.schema.json): populated when
  // this iteration was bridged from a Tier-1/Tier-2 sandbox experiment (e.g.
  // exp003 Vickrey-rediscovery). `value` is scalar for single-metric outcomes
  // and an object for multi-metric — consumers must scalar-guard (the
  // Experiments.tsx bridgeLabel idiom). `summary` carries the human verdict
  // line ("Verdict=YES. …"). Absent for pure-Tier-3 iterations.
  experiment_outcome?: {
    experiment_id?: string;
    metric?: string;
    value?: number | Record<string, unknown>;
    trials?: number;
    summary?: string;
    results_path?: string;
  } | null;
  journal_entry_path: string;
  nara_summary?: string | null;
  model_version?: string | null;
  wrapper_call_ids?: string[];
  seed_value?: number | null;
  // Joined in by /api/loop_v0/iterations when the topic matches a tracked
  // subprocess (the backend's in-memory spawn tracker). Absent when no match.
  process_status?: string;
  process_pid?: number;
  process_exit_code?: number;
}

export interface IterationsResponse {
  iterations: IterationRecord[];
}

// GET /api/iteration/{iteration_id}/journey — the full pipeline journey for one
// iteration (PipelineJourney, the S2 cockpit reframe). Returns the whole
// loop_memory row as an IterationRecord. Unknown id -> {found:false} at HTTP 200
// (the journey view degrades in place, never 404-blanks).
export interface IterationJourneyResponse {
  found: boolean;
  iteration_id: string;
  iteration?: IterationRecord | null;
}

export interface JournalResponse {
  iteration_id: string;
  path: string;
  content: string;
}

// --- AUTONOMY OBSERVABILITY ---
// Mirrors of the coordinator-loop data contracts (ui_autonomy_observability_plan.md
// §"Data contracts"). The primary session writes these as append-only JSONL,
// gitignored, read live by ui/backend/coordinator.py exactly as loop_memory.jsonl
// is. Post-S3 the UI reads /api/coordinator/cycles (the narrative) — the
// findings/bubbles/health_signals/active siblings retired with their panels.
// Fields are kept optional/forward-compatible (like IterationRecord) so an EMIT
// schema addition does not break the views; `status`/`severity`/etc. stay open
// strings so an unrecognized enum value renders generically rather than crashing.

// One proposed action in a coordinator cycle's plan. `args` is left open.
export interface CoordinatorPlanStep {
  action: string;
  args?: Record<string, unknown>;
}

// Per-action outcome. `status` mirrors the EMIT enum
// (passed | skipped | errored) but stays open; `error` carries the failure
// detail for the explicit failed-dispatch row (never a silent gap).
export interface CoordinatorOutcome {
  action: string;
  status: "passed" | "skipped" | "errored" | string;
  error?: string | null;
}

// One row of run_state/coordinator_cycles.jsonl — the join key for the
// Coordinator Cycle view. `topic_source` is the auto-chosen-topic provenance
// (e.g. "coordinator" / "human" / "arxiv_pick"); `agent` is the actor badge.
export interface CoordinatorCycle {
  timestamp: string;
  run_id: string;
  agent: string;
  topic: string;
  topic_source: string;
  // Overall cycle status (report.status: e.g. "executed"/"no_valid_plan"); EMIT
  // emits it top-level. Optional — the per-action `outcomes` carry the detail.
  status?: string;
  plan: CoordinatorPlanStep[];
  outcomes: CoordinatorOutcome[];
  dispatched_iteration_id?: string | null;
  promoted_finding_ids?: string[];
  bubble_run_ids?: string[];
}

// run_state/active_run.json — the coordinator's live cycle (the generalized
// active_run helper, kind="coordinator"). The live row is {run_id, kind, label,
// started_at, current_step, narration, step_started_at}: `current_step` walks
// assess → plan → validate → dispatch and `narration` carries the chosen topic
// + why. There is NO top-level topic field — the topic lives in narration/label.
export interface CoordinatorActiveRun {
  kind: "coordinator" | string;
  run_id?: string | null;
  label?: string | null;
  current_step?: "assess" | "plan" | "validate" | "dispatch" | string | null;
  step_started_at?: string | null;
  narration?: string | null;
  started_at?: string | null;
}

export interface CoordinatorCyclesResponse {
  cycles: CoordinatorCycle[];
}

// --- HUMAN TODO (GET /api/human_todo) ---
// The human's work queue, composed read-only by the backend from data that
// already exists (observability_reconciliation_plan.md §B3): pending gate
// verdicts (loop_memory × loop_feedback join), findings awaiting review,
// unacked bubbles, a stale active_run, and run_state/week1.state.json
// human_gates_pending entries. Each item carries the EXACT copy-pastable CLI
// command that resolves it (e.g. `python -m orchestrator.gate_cli
// --iteration-id <id> --verdict <valid|invalid|needs_revision>`) — the UI
// renders it verbatim, it never invents one. `kind`/`id` are the only fields
// the producer must set; everything else is defensive-optional and the panel
// degrades per-field. `kind` stays an open string so a new queue source
// renders generically (raw, quiet) instead of crashing.
export interface HumanTodoItem {
  kind:
    | "gate_verdict"
    | "finding_review"
    | "bubble_unacked"
    | "stale_active_run"
    | "state_file_gate"
    | string;
  id: string;
  title?: string | null;
  // ISO timestamp of when the item started waiting (oldest-first ordering key).
  since?: string | null;
  detail?: string | null;
  resolve_command?: string | null;
  // Evidence-ladder level ("L0".."L5") passed through verbatim on
  // finding_review items whose surfaced row carries one (D-059 producers).
  // ABSENT on legacy rows — the cockpit reads absence as below-bar/demoted.
  evidence_level?: string | null;
  [key: string]: unknown;
}

export interface HumanTodoResponse {
  items: HumanTodoItem[];
  // Per-kind item counts (e.g. {"gate_verdict": 11}); the panel's total badge
  // is derived from `items` so a counts/items drift can't mislead.
  counts: Record<string, number>;
}

// --- FINDING DETAIL (GET /api/finding/{finding_id}) ---
// Read-only finding overview for the /todo tutor (U1, 2026-06-17 work order).
// The backend JOINS one memory/surfaced_findings.jsonl row (the finding) with
// its source iteration in memory/loop_memory.jsonl — read-only, NO writer (the
// tutor is fenced from the verdict, D-054). Unknown finding_id => `found:false`
// at HTTP 200 (the tutor degrades to "detail unavailable", never 404-blanks).
// Every field is defensive-optional: the producer JSONL is unvalidated, and the
// status-overlay (surfaced_findings.status.jsonl) may be absent.

// The finding's `evidence` object (surfaced_findings.jsonl `evidence` is a DICT,
// not a list): the read-only refs that ground the claim. Index signature keeps
// producer-added refs forward-compatible.
export interface FindingEvidence {
  journal_entry_path?: string | null;
  results_path?: string | null;
  experiment_outcome?: unknown;
  critic_rationale?: string | null;
  [key: string]: unknown;
}

// A read-only subset of the source loop_memory.jsonl row — enough to anchor
// "which iteration produced this finding, on what topic, and is it gated". NOT
// the whole iteration record.
export interface FindingSourceIteration {
  iteration_id: string;
  topic?: string | null; // seed.topic
  nara_summary?: string | null;
  gate_status?: string | null;
  journal_entry_path?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
}

export interface FindingDetail {
  found: boolean;
  finding_id: string;
  title?: string | null;
  claim?: string | null;
  why_it_matters?: string | null;
  // The finding's falsifier — "what would change the verdict". This is the
  // "blocker / why-deferred" surface (no extra file is read).
  what_would_change_it?: string | null;
  novelty_class?: string | null;
  critic_verdict?: string | null;
  // EFFECTIVE status (the surfaced_findings.status.jsonl overlay applied; the
  // base row's status when the overlay is absent).
  status?: string | null;
  promoted_at?: string | null;
  source_iteration_id?: string | null;
  evidence?: FindingEvidence | null;
  source_iteration?: FindingSourceIteration | null;
  [key: string]: unknown;
}

// --- LOOP ALERT (GET /api/loop_alert, 2026-08-14 work order A) ---
// run_state/loop_alert.json verbatim (orchestrator/loop_health.py's
// write_alert_flag, rewritten every executed coordinator cycle). 204 = the
// flag has never been written on this checkout -> the client gets null.
// Every field is producer-owned/defensive-optional; the banner coerces.
export interface LoopAlert {
  level?: "red" | "amber" | "ok" | string | null;
  reasons?: unknown;
  // ISO timestamp of the last executed cycle. The FRONTEND judges staleness
  // (~26h) off this — a fresh "ok" hides the banner; a stale one cannot.
  updated_at?: string | null;
  [key: string]: unknown;
}

// --- IDEAS BOARD (GET /api/ideas, 2026-08-14 work order C) ---
// memory/ideas.md verbatim — the deterministic idea-ledger projection
// (workers/idea_projection.py). Read-only; a plain markdown render is the
// correct surface. 204 (absent file) -> null at the client.
export interface IdeasResponse {
  markdown?: string | null;
  [key: string]: unknown;
}

// --- LADDER (GET /api/ladder, UI simplification S1) ---
// The reduced idea-ledger state (ui/backend/ladder.py over
// workers/idea_ledger.load_state + idea_projection helpers). 204 (no ledger
// on this checkout) -> null at the client; 404 = version skew (older
// backend binary). Every field is producer-owned/defensive-optional; the
// /ladder page coerces per-field.

// One reduced cluster row. kill_reason / reopening_condition are the
// ledger's own dicts, passed through verbatim (null while the cluster lives).
export interface LadderCluster {
  cluster_id: string;
  stem?: string | null;
  status?: "open" | "surfaced" | "killed" | string | null;
  evidence_level?: string | null;
  origin?: string | null;
  // Member ids — normally iteration_ids (niche-seeded clusters carry
  // "paper:<arxiv_id>"); member_count is their length.
  members?: string[] | null;
  member_count?: number | null;
  last_event_ts?: string | null;
  kill_reason?: {
    code?: string | null;
    evidence_key?: string | null;
    detail?: string | null;
    [key: string]: unknown;
  } | null;
  reopening_condition?: {
    requires?: string | null;
    evidence_kind?: string | null;
    [key: string]: unknown;
  } | null;
  open_agenda_count?: number | null;
  [key: string]: unknown;
}

// One open agenda item (idea_projection.agenda_topics shape).
export interface LadderAgendaItem {
  topic?: string | null;
  source?: string | null;
  cluster_id?: string | null;
  [key: string]: unknown;
}

export interface LadderResponse {
  clusters?: LadderCluster[];
  // Non-killed clusters per rung, zero-filled L0..L5.
  histogram?: Record<string, number>;
  counts?: { open?: number; surfaced?: number; killed?: number };
  agenda?: LadderAgendaItem[];
  // Per-rung "next test owed" labels (workers/evidence_ladder wording).
  next_owed?: Record<string, string>;
  [key: string]: unknown;
}

// --- LAB TODO (GET /api/lab_todo) ---
// The LAB's own queue — what Nara + the PI advance without the human, as
// opposed to /api/human_todo (what the human owes). Composed by
// ui/backend/lab_todo.py from coordinator.assess_state's gaps (split by
// nara_daemon's own agent/human rule) + the idea ledger. Always 200 on a
// backend that has it (a cold checkout returns gaps with empty lists); a 404
// means the RUNNING BINARY predates the endpoint (version skew). Every field
// is producer-owned/defensive-optional; the panel coerces per-field.

// One cluster inside an owed-test group.
export interface LabTodoOwedCluster {
  cluster_id?: string | null;
  stem?: string | null;
  last_event_ts?: string | null;
  [key: string]: unknown;
}

// The OPEN clusters parked on one rung, and the test that rung owes
// (workers/idea_projection._owed — the same text ideas.md renders).
export interface LabTodoOwedGroup {
  test?: string | null;
  rung?: string | null;
  clusters?: LabTodoOwedCluster[];
  [key: string]: unknown;
}

// A killed cluster D-064's `refine_idea` could still improve: a critique-shaped
// kill (redteam_fatal_flaw / paper_prior_exists) with no refine_history yet.
export interface LabTodoRefineCandidate {
  cluster_id?: string | null;
  stem?: string | null;
  kill_code?: string | null;
  [key: string]: unknown;
}

export interface LabTodoResponse {
  // assess_state gaps the AGENT can advance (the daemon's work_exists set).
  agent_gaps?: string[];
  // assess_state gaps that wait on the HUMAN — surfaced as ONE muted line
  // pointing at the OweStrip hero, never as a second todo list.
  human_gaps?: string[];
  // WHICH path produced the gaps (rule 7 — the fallback is named, never
  // silent): "assess_state" = a live read; "last_cycle" = the gaps the
  // coordinator persisted on its most recent cycle (the production backend
  // cannot import the coordinator — see ui/backend/lab_todo.py); and
  // "unavailable" = neither, which the panel renders as UNKNOWN, not empty.
  gaps_source?: "assess_state" | "last_cycle" | "unavailable" | string | null;
  // The cycle timestamp the gaps are from — null on the live path.
  gaps_as_of?: string | null;
  owed?: LabTodoOwedGroup[];
  agenda?: LadderAgendaItem[];
  refine_candidates?: LabTodoRefineCandidate[];
  generated_at?: string | null;
  [key: string]: unknown;
}
