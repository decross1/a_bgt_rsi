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

// run_state/week1.state.json passthrough — only the fields the UI reads.
export interface AppState {
  plan_id?: string;
  current_day?: string;
  completed_tasks?: string[];
  [key: string]: unknown;
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

// --- healthy-baseline card (/api/baseline) ---

export interface BaselineRow {
  key: string;
  label: string;
  value: string;
  source: "measured" | "documented";
  documented?: string;
}

export interface BaselineResponse {
  rows: BaselineRow[];
}

// Message shape from the /api/live WebSocket.
export interface LiveMessage {
  source: "telemetry" | "orchestrator";
  line: Record<string, unknown>;
}

// --- LOOP_V0 ---
// Shared contract: the primary session writes run_state/active_iteration.json
// + memory/loop_memory.jsonl + journal/iterations/NNN.md; the UI reads
// them via /api/loop_v0/active, /api/loop_v0/iterations and
// /api/loop_v0/journal/{id}. See LOOP_V0.md and ui_plan.md §LOOP_V0.

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
    // Topical-relevance signal (EMIT: hypothesis-vs-neighbor similarity, the
    // one genuinely new emit per ui_autonomy_observability_plan.md). Drives the
    // low-evidence badge: a `novel/survives` verdict resting on thin or
    // off-domain retrieval (flag "low"/"thin") is flagged as low-confidence.
    // Absent on pre-coordinator rows.
    relevance?: {
      score?: number;
      flag?: "low" | "thin" | "ok" | string;
      topical_match?: number;
    } | null;
  } | null;
  novelty?: {
    class?: "novel" | "rediscovery" | "nonsense" | "unclear" | string;
    rationale?: string;
    top_neighbor_id?: string | null;
  } | null;
  critique?: {
    verdict?: "survives" | "falsified" | "restated" | "malformed" | string;
    rationale?: string;
    contradicting_paper_id?: string | null;
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
  journal_entry_path: string;
  nara_summary?: string | null;
  model_version?: string | null;
  wrapper_call_ids?: string[];
  seed_value?: number | null;
  // Joined in by /api/loop_v0/iterations when the topic matches a tracked
  // subprocess. Mirrors `/api/loop_v0/processes`. Absent when no match.
  process_status?: string;
  process_pid?: number;
  process_exit_code?: number;
}

export interface IterationsResponse {
  iterations: IterationRecord[];
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
// is. The UI reads them via /api/coordinator/{cycles,active,findings,bubbles}.
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
  plan: CoordinatorPlanStep[];
  outcomes: CoordinatorOutcome[];
  dispatched_iteration_id?: string | null;
  promoted_finding_ids?: string[];
  bubble_run_ids?: string[];
}

// One row of memory/surfaced_findings.jsonl (promote_findings output). The
// index signature keeps it forward-compatible with EMIT-side additions.
export interface SurfacedFinding {
  finding_id: string;
  iteration_id?: string | null;
  agent?: string | null;
  text: string;
  timestamp?: string | null;
  [key: string]: unknown;
}

// One row of memory/coordinator_bubbles.jsonl — the loop's "raise to the
// human" channel. `severity` stays open; "raise" is the prominent tier.
export interface Bubble {
  bubble_id: string;
  run_id?: string | null;
  agent?: string | null;
  text: string;
  severity?: "info" | "warn" | "raise" | string | null;
  timestamp?: string | null;
}

// run_state/active_run.json — the coordinator's live cycle. `kind` is
// "coordinator" (mirrors the seed.source="coordinator" fix); `current_step`
// walks assess → plan → validate → dispatch; `narration` carries the chosen
// topic + why so the active panel can say what stage and why.
export interface CoordinatorActiveRun {
  kind: "coordinator" | string;
  run_id?: string | null;
  current_step?: "assess" | "plan" | "validate" | "dispatch" | string | null;
  narration?: string | null;
  topic?: string | null;
  topic_source?: string | null;
  started_at?: string | null;
}

export interface CoordinatorCyclesResponse {
  cycles: CoordinatorCycle[];
}

export interface SurfacedFindingsResponse {
  findings: SurfacedFinding[];
}

export interface BubblesResponse {
  bubbles: Bubble[];
}
