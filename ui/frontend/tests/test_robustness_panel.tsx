// RobustnessPanel surfaces invocation rate, median latency, and per-trial
// outcomes from /api/robustness. day-4 surface.
import { render, screen, waitFor } from "@testing-library/react";
import RobustnessPanel from "../src/components/RobustnessPanel";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const responses: Record<string, unknown> = {};

beforeEach(() => {
  vi.stubGlobal("fetch", (url: string) => {
    for (const [key, value] of Object.entries(responses)) {
      if (url.endsWith(key)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          statusText: "OK",
          json: () => Promise.resolve(value),
        } as Response);
      }
    }
    return Promise.resolve({
      ok: false,
      status: 404,
      statusText: "not found",
      json: () => Promise.resolve({ detail: "missing" }),
    } as Response);
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  for (const key of Object.keys(responses)) delete responses[key];
});

describe("RobustnessPanel", () => {
  it("renders invocation rate and median latency when available", async () => {
    responses["/api/robustness"] = {
      available: true,
      trials: [
        { trial_id: 1, invoked: true, outcome: "ok", latency_ms: 100 },
        { trial_id: 2, invoked: false, outcome: "missed", latency_ms: null },
      ],
      trial_count: 2,
      invocations: 1,
      invocation_rate: 0.5,
      median_latency_ms: 100,
      outcomes: { ok: 1, missed: 1 },
    };
    render(<RobustnessPanel />);
    await waitFor(() => expect(screen.getByText("50.0%")).toBeInTheDocument());
    // "100 ms" appears twice: once in the summary median, once in the trial row.
    expect(screen.getAllByText("100 ms").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/ok:/)).toBeInTheDocument();
    expect(screen.getByText(/missed:/)).toBeInTheDocument();
  });

  it("shows the not-yet-available notice when day4_robust.jsonl is absent", async () => {
    responses["/api/robustness"] = {
      available: false,
      trials: [],
      trial_count: 0,
      invocations: 0,
      invocation_rate: null,
      median_latency_ms: null,
      outcomes: {},
    };
    render(<RobustnessPanel />);
    await waitFor(() =>
      expect(
        screen.getByText(/day4_robust.jsonl is not present yet/),
      ).toBeInTheDocument(),
    );
  });
});
