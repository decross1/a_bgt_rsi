// Page B HTTP client. Mirrors the existing http.ts pattern (host-derived
// base, detail-aware error). Kept separate so the integrator does not have
// to touch the shared http.ts.
import type {
  ExperimentDetail,
  ResearchResponse,
} from "../types/experiments";

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

// (The /api/experiments INDEX endpoint + its getExperiments client were
// retired in UI simplification S3 — /api/research is the experiments index
// the page actually renders; /api/experiments/{expId} stays for the detail.)

export const getExperimentDetail = (expId: string) =>
  getJSON<ExperimentDetail>(
    `/api/experiments/${encodeURIComponent(expId)}`,
  );

export const getResearch = () => getJSON<ResearchResponse>("/api/research");
