// TypeScript mirrors of the backend's JSON responses. See ui_plan.md
// sections 4.2-4.3, 5.2. Call-log payload fields are deliberately left
// open (`raw`) so a future day-2 schema addition does not break the UI.

// Day-3.5 retrieval-context entry: a chunk of a retrieved document. The
// backend only forwards the field if the call record carried a list of
// objects; the inspector renders each entry as a collapsible row.
export interface RetrievalDoc {
  doc_id?: string;
  content_hash?: string;
  chunk_offset?: number;
  chunk_length?: number;
  [key: string]: unknown;            // forward-compatible — render generically
}

export interface ChainNode {
  // "tool" nodes are tool calls — either separate call-log lines or, when
  // `embedded` is true, synthesized from a wrapper record's tool_calls array
  // (ui_plan.md section 9, resolved r4).
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
  // Day-3.5 optional: list of {doc_id, content_hash, chunk_offset,
  // chunk_length}. Null when the call record did not carry it.
  retrieval_context?: RetrievalDoc[] | null;
  raw: Record<string, unknown>;
  children: ChainNode[];
}

export interface ChainResponse {
  task_id?: string;                  // dispatch-rooted (day-6 orchestrator)
  root_request_id?: string;          // wrapper-rooted (day-4 chains)
  found: boolean;
  malformed: boolean;
  root: ChainNode | null;
  node_count: number;
  total_latency_ms: number;
  malformed_tool_calls?: number;     // count of parse-error nodes in the chain
}

// --- day-4 surfaces ---

export interface Day4ChainSummary {
  request_id: string;
  caller_tag: string | null;
  timestamp: string | null;
  node_count: number;
  total_latency_ms: number;
  malformed_tool_calls: number;
}

export interface Day4ChainsResponse {
  available: boolean;
  chains: Day4ChainSummary[];
}

// events.jsonl (day-3.5). The schema has not been committed, so the
// inspector enforces only `event_type` and renders the rest generically.
export interface EventRecord {
  event_type: string;
  timestamp?: string;
  [key: string]: unknown;
}

export interface EventsResponse {
  available: boolean;
  events: EventRecord[];
}

// One robustness run, derived by read_robustness from day4_robust.jsonl's
// chained call log: a run is a wrapper-root call (caller_tag identifies it)
// whose `completion` did or did not carry a tool call.
export interface RobustnessTrial {
  trial_id?: number;
  caller_tag?: string | null;        // e.g. test_tool_call_robustness/run0
  request_id?: string | null;
  invoked?: boolean;
  outcome?: string;                  // ok | missed | malformed
  tool_name?: string | null;         // name of the invoked tool, when any
  latency_ms?: number | null;        // root-call latency, rounded to 0.1 ms
  [key: string]: unknown;
}

export interface RobustnessResponse {
  available: boolean;
  trials: RobustnessTrial[];
  trial_count: number;
  invocations: number;
  invocation_rate: number | null;
  median_latency_ms: number | null;
  outcomes: Record<string, number>;
}

export interface RecentTask {
  task_id: string;
  task_type: string | null;
  status: string | null;
  worker_pid: number | null;
  // Day-6+ orchestrator schema fields. `timestamp` is the latest line's
  // wall-clock; `stage` is the orchestrator state machine position
  // (orchestrator_dispatch / worker_invocation / orchestrator_receipt /
  // orchestrator_reject). Both null on pre-Day-6 records.
  timestamp: string | null;
  stage: string | null;
  // Legacy pre-Day-6 fields — still surfaced for old fixtures.
  dispatch_ts: string | null;
  receipt_ts: string | null;
}

// /api/workload_hint — workload-shape annotation for the decode-tok/s tile
// (ui_plan.md r10). Lets the dashboard contextualize the tile so a
// prefill-bound workload (PD experiment, ~2 tok/call) doesn't read as a
// regression against the day-1 decode-bound band [80,130].
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
  processes: ProcessSample[];
  read_errors: Record<string, string> | null;
}

// --- healthy-baseline card (/api/baseline) ---

export interface BaselineRow {
  key: string;
  label: string;
  value: string;
  // "measured" — sourced from bench/mtp.csv, bench/day1.csv or metric_log;
  // "documented" — the ui_plan.md section 5.3 constant, no measurement yet.
  source: "measured" | "documented";
  documented?: string; // expected figure, present on measured rows
}

export interface BaselineResponse {
  rows: BaselineRow[];
}

// Message shape from the /api/live WebSocket.
export interface LiveMessage {
  source: "telemetry" | "orchestrator";
  line: Record<string, unknown>;
}

// --- Week-2 unlock prerequisites (/api/unlock_status) ---
// Mirrors backend/unlock.py:compute_unlock_status. Five sections, each
// independently `available` so the panel renders partial state cleanly.
// See ui_plan.md §11.3.

export interface RunLogIntegrity {
  available: boolean;
  ok: boolean | null;                  // null when file is absent
  total_lines: number;
  malformed_lines: number[];           // 1-based line numbers
  rolling_window_days: number;
  rolling_count: number;
}

export interface SoftGatePending {
  task_id: string;
  agent_id?: string | null;
  summary?: string | null;
  expected_observable?: string | null;
  observed_actual?: string | null;
  ts?: string | null;
  sla_hours?: number | null;
  rollback_command: string;            // informational CLI string; UI does not execute
}

export interface SoftGateQueue {
  available: boolean;
  pending: SoftGatePending[];
}

export interface HardGatePending {
  task_id?: string | null;
  attest_command: string | null;       // informational CLI string; UI does not execute
  [key: string]: unknown;              // pass through any extra fields the state file carries
}

export interface HardGatesPending {
  available: boolean;
  pending: HardGatePending[];
}

export interface UnlockStatus {
  milestone: string;
  current_day: string | null;
  run_log_integrity: RunLogIntegrity;
  soft_gate_queue: SoftGateQueue;
  hard_gates_pending: HardGatesPending;
  metric_log: Record<string, number | string | null>;
  fallbacks_taken: Record<string, string>;
}
