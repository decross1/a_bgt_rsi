// HTTP client for the backend. The API base is derived from the page
// host so the SPA works both through an SSH tunnel (browser at
// localhost -> backend at localhost:8700) and over the LAN (browser at
// 10.0.0.73 -> backend at 10.0.0.73:8700). The backend allows CORS.

import type { ActiveRunsResponse } from "../types/activity";
import type {
  ChainResponse,
  CoordinatorCyclesResponse,
  FindingDetail,
  Health,
  HumanTodoResponse,
  IdeasResponse,
  IterationJourneyResponse,
  IterationsResponse,
  JournalResponse,
  LabTodoResponse,
  LadderResponse,
  LoopAlert,
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

// Live served-model names, per vLLM endpoint (2026-08-16). The Pulse model
// cards used to carry HARDCODED titles: during an A/B window the dashboard
// announced "Qwen3.6-27B · NVFP4-MTP" while :8001 was serving 3.8. A panel
// that names a model must name the one actually answering, so the name is
// fetched, never remembered. `model: null` (with `error`) renders as
// "unknown", which is true — the old behaviour was a confident lie.
export interface ServedModel {
  url: string;
  model: string | null;
  error: string | null;
}
export const getServedModels = () =>
  getJSON<Record<string, ServedModel>>("/api/served_models");

export const getRecentTelemetry = (limit = 300) =>
  getJSON<{ samples: TelemetrySample[] }>(`/api/telemetry/recent?limit=${limit}`);

export const getWorkloadHint = () =>
  getJSON<WorkloadHint>("/api/workload_hint");

// --- LOOP_V0 endpoints (ui/backend/loop_v0.py) ---
// (The single-slot active-iteration mirror + the processes rollup were
// retired in UI simplification S3 — the D-047 registry, getActiveRuns below,
// is the one live-run source.)

export const getIterations = () =>
  getJSON<IterationsResponse>("/api/loop_v0/iterations");

// The full pipeline journey for one iteration (PipelineJourney, S2 reframe).
// Unknown id -> {found:false} at 200, so the journey view degrades in place.
export const getIterationJourney = (iterationId: string) =>
  getJSON<IterationJourneyResponse>(
    `/api/iteration/${encodeURIComponent(iterationId)}/journey`,
  );

export const getJournalEntry = (iterationId: string) =>
  getJSON<JournalResponse>(
    `/api/loop_v0/journal/${encodeURIComponent(iterationId)}`,
  );

// --- AUTONOMY OBSERVABILITY (ui/backend/coordinator.py) ---
// The one surviving coordinator endpoint post-S3: the cycle narrative. The
// findings/bubbles/health_signals/active siblings were retired with their
// panels (the dossier picker + OweStrip + LoopAlertBanner + the D-047
// registry cover those reads now).

export const getCoordinatorCycles = () =>
  getJSON<CoordinatorCyclesResponse>("/api/coordinator/cycles");

// --- HUMAN TODO (ui/backend, observability_reconciliation_plan.md §B3) ---
// Read-only composition of everything awaiting a human: pending gate verdicts,
// findings in review, unacked bubbles, stale active_run, state-file gates.
export const getHumanTodo = () => getJSON<HumanTodoResponse>("/api/human_todo");

// --- LOOP ALERT + IDEAS (ui/backend/loop_alert.py, 2026-08-14 work order) ---
// GET /api/loop_alert returns 204 when run_state/loop_alert.json has never
// been written -> null (mirrors getCoordinatorActive). The BANNER judges
// staleness off updated_at; this client just fetches.
export async function getLoopAlert(): Promise<LoopAlert | null> {
  const resp = await fetch(`${API_BASE}/api/loop_alert`);
  if (resp.status === 204) return null;
  if (!resp.ok) {
    throw await errorFromResponse(resp);
  }
  return (await resp.json()) as LoopAlert;
}

// --- LADDER (ui/backend/ladder.py, UI simplification S1) ---
// GET /api/ladder returns 204 when memory/idea_ledger.jsonl has never been
// written on this checkout -> null (mirrors getIdeas). A 404 means the
// RUNNING BINARY predates the endpoint — version skew, which the HttpError
// status lets the /ladder page render as a quiet EndpointMissingNote.
export async function getLadder(): Promise<LadderResponse | null> {
  const resp = await fetch(`${API_BASE}/api/ladder`);
  if (resp.status === 204) return null;
  if (!resp.ok) {
    throw await errorFromResponse(resp);
  }
  return (await resp.json()) as LadderResponse;
}

// --- LAB TODO (ui/backend/lab_todo.py) ---
// GET /api/lab_todo — the LAB's queue (assess_state's agent-actionable gaps +
// the ledger's owed tests / agenda / refine candidates), the counterpart to
// getHumanTodo's "what the human owes". Always 200 on a backend that has it,
// even on a cold checkout (gaps ship, the ledger lists are empty); a 404 means
// the RUNNING BINARY predates the endpoint — version skew, which the HttpError
// status lets LabTodo render as a quiet EndpointMissingNote.
export const getLabTodo = () => getJSON<LabTodoResponse>("/api/lab_todo");

// GET /api/ideas returns 204 when memory/ideas.md is absent -> null.
export async function getIdeas(): Promise<IdeasResponse | null> {
  const resp = await fetch(`${API_BASE}/api/ideas`);
  if (resp.status === 204) return null;
  if (!resp.ok) {
    throw await errorFromResponse(resp);
  }
  return (await resp.json()) as IdeasResponse;
}

// --- FINDING DETAIL (ui/backend finding_detail.py, U1 2026-06-17 work order) ---
// Read-only finding overview for the /todo tutor: joins surfaced_findings.jsonl
// with its source loop_memory.jsonl iteration. Unknown id => {found:false} at
// 200, so the tutor degrades in place (the GET writes NOTHING — tutor fence).
export const getFindingDetail = (findingId: string) =>
  getJSON<FindingDetail>(
    `/api/finding/${encodeURIComponent(findingId)}`,
  );

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
