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
  it("renders the chained-shape run table, with caller_tag and outcomes", async () => {
    // read_robustness returns one trial per robustness run, keyed on the
    // run's caller_tag, with outcomes ok / missed / malformed.
    responses["/api/robustness"] = {
      available: true,
      trials: [
        {
          trial_id: 1,
          caller_tag: "test_tool_call_robustness/run0",
          invoked: true,
          outcome: "ok",
          tool_name: "get_payoff_matrix",
          latency_ms: 100,
        },
        {
          trial_id: 2,
          caller_tag: "test_tool_call_robustness/run1",
          invoked: false,
          outcome: "missed",
          latency_ms: 90,
        },
        {
          trial_id: 3,
          caller_tag: "test_tool_call_robustness/run2",
          invoked: false,
          outcome: "malformed",
          latency_ms: 120,
        },
      ],
      trial_count: 3,
      invocations: 1,
      invocation_rate: 0.333,
      median_latency_ms: 100,
      outcomes: { ok: 1, missed: 1, malformed: 1 },
    };
    render(<RobustnessPanel />);
    await waitFor(() => expect(screen.getByText("33.3%")).toBeInTheDocument());
    // The run column shows the caller_tag, not a synthetic trial index.
    expect(
      screen.getByText("test_tool_call_robustness/run0"),
    ).toBeInTheDocument();
    // The malformed outcome is surfaced in the per-run table and the tally.
    expect(screen.getByText("malformed")).toBeInTheDocument();
    expect(screen.getByText(/malformed:/)).toBeInTheDocument();
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
