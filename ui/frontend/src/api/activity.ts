// Activity fetchers (the /graph page + Pulse's monitor poll). Own module so
// the original PAGE A build did not edit the shared api/http.ts; kept
// separate post-S3 for the same reason. Reuses the API_BASE derivation.
// (The /api/activity/active_run SINGULAR mirror was retired in S3 — the
// D-047 registry, getActiveRuns in api/http.ts, is the live-run source.)
import { HttpError } from "./http";
import type {
  ActivityGraphResponse,
  MonitorResponse,
} from "../types/activity";

const API_PORT = import.meta.env.VITE_API_PORT ?? "8700";
const API_BASE = `http://${window.location.hostname}:${API_PORT}`;

async function getJSON<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`);
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

// Defaults to the navigable "overview" (one node per task); "full" expands
// each task's whole causal chain (node-capped) for drilling in place.
export const getActivityGraph = (
  detail: "overview" | "full" = "overview",
  limit = 25,
) =>
  getJSON<ActivityGraphResponse>(
    `/api/activity/graph?limit=${limit}&detail=${detail}`,
  );

export const getActivityMonitor = (limit = 25) =>
  getJSON<MonitorResponse>(`/api/activity/monitor?limit=${limit}`);
