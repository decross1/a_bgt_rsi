// PAGE A (/activity) response types. Mirrors ui/backend/activity.py.
// Kept in its own module so PAGE A does not touch the shared
// types/schemas.ts (operating contract: write only files I own).

// Node coloring tone. The backend normalizes orchestrator/call status into
// these; "tool" nodes pass through "ok" | "error" directly.
export type ActivityStatus = "active" | "ok" | "error" | "unknown";

export interface ActivityNode {
  id: string;
  kind: "dispatch" | "call" | "tool";
  label: string;
  task_id: string | null;
  // Only real wrapper/orchestrator request_ids are non-null and
  // deep-linkable into /chain/req/:requestId. Synthesized tool nodes are
  // null — the frontend must NOT link them.
  request_id: string | null;
  status: ActivityStatus | string | null;
}

export interface ActivityEdge {
  id: string;
  source: string;
  target: string;
}

export interface ActivityGraphResponse {
  available: boolean;
  reason?: string;
  nodes: ActivityNode[];
  edges: ActivityEdge[];
  task_count?: number;
  // "overview" = one node per task; "full" = whole chain (node-capped).
  detail?: "overview" | "full" | string;
  // True when the graph hit the backend node budget (a single experiment
  // chain can be thousands of calls); the inspector shows full chains.
  truncated?: boolean;
  node_limit?: number;
  generated_at: string;
}

export interface MonitorWorker {
  task_id: string | null;
  task_type: string | null;
  status: string | null;
  worker_pid: number | null;
  timestamp?: string | null;
  // From the latest telemetry sample's processes[]; null when telemetry is
  // absent or the worker_pid has no matching process sample.
  cpu_pct: number | null;
  rss_mb: number | null;
}

// Per-worker inference internals. NOT measured — sourced from a fixture.
// `synthetic: true` is load-bearing: the UI renders a visible marker so
// these are never mistaken for measured numbers (CLAUDE.md rule 4).
export interface SyntheticInferenceWorker {
  task_id: string;
  decode_step: number;
  tokens_generated: number;
  tokens_target: number;
  eta_s: number;
  tok_per_s: number;
}

export interface SyntheticInference {
  synthetic: boolean;
  source: string;
  needs: string;
  note: string;
  workers: SyntheticInferenceWorker[];
}

export interface MonitorResponse {
  available: boolean;
  reason?: string;
  telemetry_available?: boolean;
  active: MonitorWorker[];
  recent: MonitorWorker[];
  synthetic_inference: SyntheticInference;
  generated_at: string;
}
