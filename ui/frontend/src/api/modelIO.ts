// Model I/O fetchers (the /model-io page — owner request 2026-08-18: the
// health panels show THAT gemma/qwen are alive, this page shows what passes
// THROUGH them). Own module so the build does not edit the shared api/http.ts
// (the api/activity.ts precedent); reuses the API_BASE derivation.
import { HttpError } from "./http";

const API_PORT = import.meta.env.VITE_API_PORT ?? "8700";
const API_BASE = `http://${window.location.hostname}:${API_PORT}`;

// FETCH DEADLINE (adversarial review 2026-08-18): a hung backend request —
// the >120 s /api/lab_todo shape — must be torn down, not waited out. Every
// fetcher on the /model-io stack goes through this AbortController timeout;
// on abort the promise rejects, the pollhub's SWR path keeps the rendered
// snapshot with `failing` set and `asOf` frozen honestly, and the next tick
// retries. (The pollhub also runs its own slightly-larger deadline race as
// a backstop for any fetcher that skips this helper.)
export const FETCH_DEADLINE_MS = 15_000;

export async function fetchWithDeadline(
  url: string,
  deadlineMs: number = FETCH_DEADLINE_MS,
): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(
    () =>
      ctrl.abort(new Error(`fetch deadline ${deadlineMs}ms exceeded: ${url}`)),
    deadlineMs,
  );
  try {
    return await fetch(url, { signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function getJSON<T>(path: string): Promise<T> {
  const resp = await fetchWithDeadline(`${API_BASE}${path}`);
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = (await resp.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* no JSON body */
    }
    throw new HttpError(resp.status, detail);
  }
  return (await resp.json()) as T;
}

// One table row: previews + scalar metadata, all backend-passthrough (a
// missing field is null, never derived — see backend/model_io.py).
export interface ModelIOCall {
  ts: string | null;
  request_id: string | null;
  parent_request_id: string | null;
  model: string | null;
  backend: string | null;
  caller_tag: string | null;
  run_id: string | null;
  latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  prompt_preview: string | null;
  completion_preview: string;
  empty: boolean;
}

export interface ModelIOResponse {
  calls: ModelIOCall[];
  source: string;
  // True when the bounded backward scan hit its byte bound with the limit
  // unfilled — older matching rows may exist unexamined.
  window_truncated: boolean;
  scanned_bytes: number;
  max_scan_bytes: number;
  generated_at: string;
}

// The FULL raw calls.jsonl row (schema/calls.jsonl.schema.json). Only the
// fields the expansion renders are typed; the rest passes through.
export interface ModelIOCallDetail {
  timestamp?: string;
  request_id?: string;
  parent_request_id?: string | null;
  model?: string;
  backend?: string;
  caller_tag?: string;
  run_id?: string;
  temperature?: number;
  seed?: number | null;
  latency_ms?: number;
  prompt_messages?: { role: string; content: string }[];
  completion?: string;
  usage?: { input_tokens?: number; output_tokens?: number };
  [key: string]: unknown;
}

export interface ModelIODetailResponse {
  found: boolean;
  call: ModelIOCallDetail;
}

export interface DispatchTask {
  task_id: string;
  task_type: string | null;
  status: string | null;
  stage: string | null;
  duration_ms: number | null;
  ts: string | null;
  run_id: string | null;
}

export interface SpawnEntry {
  spawn_id: string | null;
  status: string | null;
  ts: string | null;
  task_statement: string | null;
}

export interface DispatchTraceResponse {
  orchestrator_available: boolean;
  spawn_available: boolean;
  tasks: DispatchTask[];
  spawns: SpawnEntry[];
  generated_at: string;
}

export interface ModelIOFilters {
  model?: string;
  callerTag?: string;
  runId?: string;
}

export const getModelIO = (filters: ModelIOFilters = {}, limit = 50) => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (filters.model) params.set("model", filters.model);
  if (filters.callerTag) params.set("caller_tag", filters.callerTag);
  if (filters.runId) params.set("run_id", filters.runId);
  return getJSON<ModelIOResponse>(`/api/model_io?${params.toString()}`);
};

export const getModelIODetail = (requestId: string) =>
  getJSON<ModelIODetailResponse>(
    `/api/model_io/${encodeURIComponent(requestId)}`,
  );

export const getDispatchTrace = (limit = 30) =>
  getJSON<DispatchTraceResponse>(`/api/dispatch_trace?limit=${limit}`);
