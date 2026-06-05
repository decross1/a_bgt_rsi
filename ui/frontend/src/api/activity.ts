// PAGE A (/activity) fetchers. Own module so PAGE A does not edit the
// shared api/http.ts. Reuses the same API_BASE derivation pattern.
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
    throw new Error(`${resp.status} ${detail}`);
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
