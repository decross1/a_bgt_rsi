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

// day4_robust.jsonl summary.
export interface RobustnessTrial {
  trial_id?: number;
  invoked?: boolean;
  outcome?: string;
  latency_ms?: number | null;
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
  dispatch_ts: string | null;
  receipt_ts: string | null;
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
