import type { BenchmarkProgressResponse } from "../types/benchmarkProgress";
import { HttpError } from "./http";

const API_PORT = import.meta.env.VITE_API_PORT ?? "8700";
const API_BASE = `http://${window.location.hostname}:${API_PORT}`;

export const BENCHMARK_PROGRESS_ENDPOINT = "/api/weekly_upgrade/progress";
export const BENCHMARK_PROGRESS_POLL_KEY = "weekly-upgrade:progress";
export const BENCHMARK_PROGRESS_FETCH_DEADLINE_MS = 15_000;

export async function getBenchmarkProgress(): Promise<BenchmarkProgressResponse> {
  const controller = new AbortController();
  const timer = setTimeout(
    () => controller.abort(),
    BENCHMARK_PROGRESS_FETCH_DEADLINE_MS,
  );
  try {
    const response = await fetch(`${API_BASE}${BENCHMARK_PROGRESS_ENDPOINT}`, {
      signal: controller.signal,
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = (await response.json()) as { detail?: unknown };
        if (typeof body.detail === "string" && body.detail) detail = body.detail;
      } catch {
        /* response had no JSON detail */
      }
      throw new HttpError(response.status, detail);
    }
    return (await response.json()) as BenchmarkProgressResponse;
  } finally {
    clearTimeout(timer);
  }
}
