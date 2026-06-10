// HTTP client for the backend. The API base is derived from the page
// host so the SPA works both through an SSH tunnel (browser at
// localhost -> backend at localhost:8700) and over the LAN (browser at
// 10.0.0.73 -> backend at 10.0.0.73:8700). The backend allows CORS.

import type { ActiveRunsResponse } from "../types/activity";
import type {
  ActiveIteration,
  AppState,
  BaselineResponse,
  BubblesResponse,
  ChainResponse,
  CoordinatorActiveRun,
  CoordinatorCyclesResponse,
  Health,
  HealthSignalsResponse,
  HumanTodoResponse,
  IterationsResponse,
  JournalResponse,
  SurfacedFindingsResponse,
  TelemetrySample,
  WorkloadHint,
} from "../types/schemas";

// Port defaults to 8700; VITE_API_PORT lets a worktree preview point at a
// backend on another port without disturbing a primary instance on 8700.
const API_PORT = import.meta.env.VITE_API_PORT ?? "8700";
export const API_BASE = `http://${window.location.hostname}:${API_PORT}`;

// Non-2xx response error carrying the STATUS as data, not just message text.
// The frontend regularly runs newer than the :8700 backend binary, so a 404
// from a known list/capability endpoint is VERSION SKEW, not a failure —
// distinguishing it requires the status code, which the old bare
// `Error(`${status} ${detail}`)` buried in a string. Consumers:
// `isVersionSkew404` in components/EndpointMissingNote.tsx (which duck-types
// `.status` rather than `instanceof`, so a test that module-mocks this file
// can never break the check).
export class HttpError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    // Message keeps the old `${status} ${detail}` shape so existing
    // string-matching consumers/tests (e.g. /500/ assertions) still hold.
    super(`${status} ${detail}`);
    this.name = "HttpError";
    this.status = status;
    this.detail = detail;
  }
}

// Build the HttpError for a non-ok response: FastAPI errors carry a JSON
// `detail`; fall back to statusText when the body has none.
async function errorFromResponse(resp: Response): Promise<HttpError> {
  let detail = resp.statusText;
  try {
    const body = (await resp.json()) as { detail?: string };
    if (body.detail) detail = body.detail;
  } catch {
    /* response had no JSON body */
  }
  return new HttpError(resp.status, detail);
}

async function getJSON<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) {
    throw await errorFromResponse(resp);
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
    throw await errorFromResponse(resp);
  }
  return (await resp.json()) as ActiveIteration;
}

export const getIterations = () =>
  getJSON<IterationsResponse>("/api/loop_v0/iterations");

export const getJournalEntry = (iterationId: string) =>
  getJSON<JournalResponse>(
    `/api/loop_v0/journal/${encodeURIComponent(iterationId)}`,
  );

// --- AUTONOMY OBSERVABILITY endpoints (ui/backend/coordinator.py) ---
// Surface the coordinator loop so the human-as-auditor can see what it decided
// and on what basis. All read-only; tolerant of absent (gitignored) data files.

export const getCoordinatorCycles = () =>
  getJSON<CoordinatorCyclesResponse>("/api/coordinator/cycles");

// GET /api/coordinator/active returns 204 when no cycle is live (mirrors
// getActiveIteration). Caller gets `null` rather than an error.
export async function getCoordinatorActive(): Promise<CoordinatorActiveRun | null> {
  const resp = await fetch(`${API_BASE}/api/coordinator/active`);
  if (resp.status === 204) return null;
  if (!resp.ok) {
    throw await errorFromResponse(resp);
  }
  return (await resp.json()) as CoordinatorActiveRun;
}

export const getSurfacedFindings = () =>
  getJSON<SurfacedFindingsResponse>("/api/coordinator/findings");

export const getBubbles = () => getJSON<BubblesResponse>("/api/coordinator/bubbles");

export const getHealthSignals = () =>
  getJSON<HealthSignalsResponse>("/api/coordinator/health_signals");

// --- HUMAN TODO (ui/backend, observability_reconciliation_plan.md §B3) ---
// Read-only composition of everything awaiting a human: pending gate verdicts,
// findings in review, unacked bubbles, stale active_run, state-file gates.
export const getHumanTodo = () => getJSON<HumanTodoResponse>("/api/human_todo");

// --- NOW BOARD (D-047 multi-run registry) ---
// GET /api/activity/active_runs — one doc per live run (run_state/
// active_runs/*.json), or a legacy_mirror-wrapped single doc on a pre-D-047
// apparatus. Always 200 on the new backend ({runs: []} when idle); a 404
// means the RUNNING BINARY predates the endpoint — version skew, which the
// HttpError status lets NowBoard render as a quiet EndpointMissingNote.
export const getActiveRuns = () =>
  getJSON<ActiveRunsResponse>("/api/activity/active_runs");

export async function startIteration(topic: string): Promise<{ pid: number; iteration_id?: string }> {
  const resp = await fetch(`${API_BASE}/api/loop_v0/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic }),
  });
  if (!resp.ok) {
    throw await errorFromResponse(resp);
  }
  return (await resp.json()) as { pid: number; iteration_id?: string };
}
