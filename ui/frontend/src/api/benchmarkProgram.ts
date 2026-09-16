import type { BenchmarkProgramResponse } from "../types/benchmarkProgram";
import { HttpError } from "./http";

const API_PORT = import.meta.env.VITE_API_PORT ?? "8700";
const API_BASE = `http://${window.location.hostname}:${API_PORT}`;

export const BENCHMARK_PROGRAM_ENDPOINT = "/api/benchmark_program";

export async function getBenchmarkProgram(release?: string | null): Promise<BenchmarkProgramResponse> {
  const requestedRelease = typeof release === "string" && release.trim() !== ""
    ? release.trim()
    : null;
  const query = requestedRelease === null
    ? ""
    : `?release=${encodeURIComponent(requestedRelease)}`;
  const response = await fetch(`${API_BASE}${BENCHMARK_PROGRAM_ENDPOINT}${query}`);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string" && body.detail) detail = body.detail;
    } catch {
      // An empty error body still has a truthful HTTP status.
    }
    throw new HttpError(response.status, detail);
  }
  const value = (await response.json()) as BenchmarkProgramResponse;
  if (requestedRelease !== null && value.release?.version !== requestedRelease) {
    throw new Error(`Benchmark release integrity error: requested ${requestedRelease}, received ${String(value.release?.version ?? "none")}`);
  }
  return value;
}
