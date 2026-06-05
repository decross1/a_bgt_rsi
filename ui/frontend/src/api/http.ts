// HTTP client for the backend. The API base is derived from the page
// host so the SPA works both through an SSH tunnel (browser at
// localhost -> backend at localhost:8700) and over the LAN (browser at
// 10.0.0.73 -> backend at 10.0.0.73:8700). The backend allows CORS.

import type {
  ActiveIteration,
  AppState,
  BaselineResponse,
  ChainResponse,
  Health,
  IterationsResponse,
  JournalResponse,
  TelemetrySample,
  WorkloadHint,
} from "../types/schemas";

// Port defaults to 8700; VITE_API_PORT lets a worktree preview point at a
// backend on another port without disturbing a primary instance on 8700.
const API_PORT = import.meta.env.VITE_API_PORT ?? "8700";
export const API_BASE = `http://${window.location.hostname}:${API_PORT}`;

async function getJSON<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = (await resp.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* response had no JSON body */
    }
    throw new Error(`${resp.status} ${detail}`);
  }
  return (await resp.json()) as T;
}

// Inspector route: walks a wrapper-call chain rooted at a request_id. Useful
// for inspecting Nara's tool-call chains in logs/calls.jsonl.
export const getChainByRequest = (requestId: string) =>
  getJSON<ChainResponse>(`/api/chain_by_request/${encodeURIComponent(requestId)}`);

export const getHealth = () => getJSON<Health>("/api/health");

export const getState = () => getJSON<AppState>("/api/state");

export const getRecentTelemetry = (limit = 300) =>
  getJSON<{ samples: TelemetrySample[] }>(`/api/telemetry/recent?limit=${limit}`);

export const getBaseline = () => getJSON<BaselineResponse>("/api/baseline");

export const getWorkloadHint = () =>
  getJSON<WorkloadHint>("/api/workload_hint");

// --- LOOP_V0 endpoints (ui/backend/loop_v0.py) ---

// GET /api/loop_v0/active returns 204 when no iteration is in flight. Caller
// gets `null` in that case rather than an error.
export async function getActiveIteration(): Promise<ActiveIteration | null> {
  const resp = await fetch(`${API_BASE}/api/loop_v0/active`);
  if (resp.status === 204) return null;
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = (await resp.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* no JSON body */
    }
    throw new Error(`${resp.status} ${detail}`);
  }
  return (await resp.json()) as ActiveIteration;
}

export const getIterations = () =>
  getJSON<IterationsResponse>("/api/loop_v0/iterations");

export const getJournalEntry = (iterationId: string) =>
  getJSON<JournalResponse>(
    `/api/loop_v0/journal/${encodeURIComponent(iterationId)}`,
  );

export async function startIteration(topic: string): Promise<{ pid: number; iteration_id?: string }> {
  const resp = await fetch(`${API_BASE}/api/loop_v0/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic }),
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = (await resp.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* no JSON body */
    }
    throw new Error(`${resp.status} ${detail}`);
  }
  return (await resp.json()) as { pid: number; iteration_id?: string };
}
