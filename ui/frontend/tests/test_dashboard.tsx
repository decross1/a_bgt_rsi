// Dashboard-level integration tests for the health-first realignment.
// These verify the wiring the per-component tests cannot: that BOTH
// model-server panels (Gemma/VllmPanel + Qwen/QwenPanel) mount side-by-side,
// that the HealthVerdict hero is fed the right (Qwen-filtered) inputs, and
// that selecting a resolved iteration mounts JournalScroll inline. They
// guard the adversarial-review constraint that neither LLM panel nor the
// resolved list was dropped in the refactor.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Dashboard from "../src/routes/Dashboard";
import type { TelemetrySample, VllmSample } from "../src/types/schemas";

// A vllm block so gemmaUp is true (HEALTHY) and VllmPanel shows "● up".
function vllmSample(): VllmSample {
  return {
    running_requests: 1,
    waiting_requests: 0,
    gpu_cache_usage_pct: 12,
    gpu_prefix_cache_hit_rate: 0.8,
    tokens_per_sec_decode: 42,
    mtp_acceptance_rate: 0.6,
    mtp_draft_tokens: 100,
    mtp_accepted_tokens: 60,
  };
}

// Two telemetry samples carrying a vllm block so the debounced gemmaUp is
// up. A "vllm-qwen-metrics" read error is present to prove it is filtered
// out of the verdict (the Qwen-exclusion fix).
function samples(): TelemetrySample[] {
  const s: TelemetrySample = {
    timestamp: new Date().toISOString(),
    gpu: null,
    host: null,
    vllm: vllmSample(),
    vllm_qwen: null,
    processes: [],
    read_errors: { "vllm-qwen-metrics": "connection refused" },
  } as unknown as TelemetrySample;
  return [s, { ...s, timestamp: new Date().toISOString() }];
}

// Mock the telemetry hook so the dashboard gets a live, fresh stream with a
// Gemma vllm block present.
vi.mock("../src/hooks/useTelemetryStream", () => ({
  useTelemetryStream: () => ({
    samples: samples(),
    latest: samples()[1],
    connected: true,
  }),
}));

// Mock the HTTP layer the child panels poll. ResolvedIterationsList ->
// getIterations; JournalScroll -> getJournalEntry; the rest are quiet.
// The mock factory is hoisted above imports, so the fixture is loaded
// inside the factory rather than referencing the top-level import.
vi.mock("../src/api/http", async () => {
  const { ITERATIONS_FIXTURE: ITER } = await import("../src/fixtures/loop_v0");
  return {
    getHealth: vi.fn().mockResolvedValue({
      ok: true,
      hostname: "spark",
      telemetry_last_seen: new Date().toISOString(),
      version: "test",
    }),
    getState: vi.fn().mockResolvedValue({ current_day: "2026-06-05" }),
    getIterations: vi.fn().mockResolvedValue({ iterations: ITER }),
    getJournalEntry: vi.fn().mockResolvedValue({
      iteration_id: "iter-2026-05-26-001",
      path: "journal/iterations/001.md",
      content: "# Journal\n\nbody",
    }),
    getActiveIteration: vi.fn().mockResolvedValue(null),
    getBaseline: vi.fn().mockResolvedValue({ rows: [] }),
    getWorkloadHint: vi.fn().mockResolvedValue({ regime: "idle" }),
    // Autonomy block (SurfacedFindingsPanel + BubblesPanel + HealthSignalsPanel
    // self-poll these). Empty responses keep the dashboard focus on the
    // health-first assertions.
    getSurfacedFindings: vi.fn().mockResolvedValue({ findings: [] }),
    getBubbles: vi.fn().mockResolvedValue({ bubbles: [] }),
    getHealthSignals: vi.fn().mockResolvedValue({ health_signals: [] }),
  };
});

describe("Dashboard realignment", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("mounts BOTH model-server panels (Gemma + Qwen) side-by-side", () => {
    render(<Dashboard />);
    // Gemma panel header + up status (vllm block present).
    expect(screen.getByText("gemma-4-26b-a4b")).toBeInTheDocument();
    expect(screen.getByTestId("vllm-status")).toHaveTextContent("up");
    // Qwen panel still present (untouched by the refactor).
    expect(screen.getByText(/Qwen3.6-27B/)).toBeInTheDocument();
  });

  it("feeds the verdict Qwen-filtered inputs so a Qwen read error stays HEALTHY", () => {
    render(<Dashboard />);
    const verdict = screen.getByTestId("health-verdict");
    // "vllm-qwen-metrics" is the only read error and is filtered out, the
    // stream is fresh and connected, and gemmaUp is true -> HEALTHY.
    expect(verdict.getAttribute("data-level")).toBe("healthy");
  });

  it("keeps ResolvedIterationsList reachable and opens JournalScroll on selection", async () => {
    render(<Dashboard />);
    // The list polls getIterations; let the microtask/poll resolve.
    await waitFor(() =>
      expect(screen.getByTestId("resolved-iterations-list")).toBeInTheDocument(),
    );
    // Before selection: no journal mounted (the visible-behavior change the
    // review flagged — JournalScroll only mounts on selection now).
    expect(screen.queryByTestId("journal-scroll")).toBeNull();

    // Select the first resolved row -> JournalScroll mounts inline.
    const row = await screen.findByLabelText(
      "load journal iter-2026-05-26-001",
    );
    fireEvent.click(row);
    expect(screen.getByTestId("journal-scroll")).toBeInTheDocument();
  });
});
