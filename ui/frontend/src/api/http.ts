// HTTP client for the backend. The API base is derived from the page
// host so the SPA works both through an SSH tunnel (browser at
// localhost -> backend at localhost:8700) and over the LAN (browser at
// 10.0.0.73 -> backend at 10.0.0.73:8700). The backend allows CORS.

import type {
  AppState,
  ChainResponse,
  Health,
  RecentTask,
  TelemetrySample,
} from "../types/schemas";

export const API_BASE = `http://${window.location.hostname}:8700`;

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

export const getChain = (taskId: string) =>
  getJSON<ChainResponse>(`/api/chain/${encodeURIComponent(taskId)}`);

export const getRecentTasks = (limit = 50) =>
  getJSON<{ tasks: RecentTask[] }>(`/api/recent_tasks?limit=${limit}`);

export const getHealth = () => getJSON<Health>("/api/health");

export const getState = () => getJSON<AppState>("/api/state");

export const getRecentTelemetry = (limit = 300) =>
  getJSON<{ samples: TelemetrySample[] }>(`/api/telemetry/recent?limit=${limit}`);
