// Dashboard-level integration tests for the health-first realignment.
// These verify the wiring the per-component tests cannot: that BOTH
// model-server panels (Gemma/VllmPanel + Qwen/QwenPanel) mount side-by-side,
// that the HealthVerdict hero is fed the right (Qwen-filtered) inputs, and
// that selecting a resolved iteration mounts JournalScroll inline. They
// guard the adversarial-review constraint that neither LLM panel nor the
// resolved list was dropped in the refactor.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Dashboard from "../src/routes/Dashboard";
import { getHumanTodo } from "../src/api/http";
import type { TelemetrySample, VllmSample } from "../src/types/schemas";

// Dashboard renders react-router <Link>s (the B5 "drill into" links), so it
// needs a Router in the tree. MemoryRouter is the test idiom
// (test_validate_routes_console.tsx).
function renderDashboard() {
  return render(
    <MemoryRouter>
      <Dashboard />
    </MemoryRouter>,
  );
}

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
    // SystemActivityHero feeds (registered-run mirrors) + the HUMAN TODO
    // panel. Quiet defaults: no registered run, empty queue.
    getCoordinatorActive: vi.fn().mockResolvedValue(null),
    getHumanTodo: vi.fn().mockResolvedValue({ items: [], counts: {} }),
    // InFlightRollup feed (FE5): Dashboard polls getProcesses in the HERO 7s
    // effect. Quiet empty default — the closed-allowlist mock would otherwise
    // hand back an undefined mock and Dashboard would throw on the call.
    getProcesses: vi.fn().mockResolvedValue({ processes: [] }),
  };
});

// SystemActivityHero's live-calls feed (Dashboard polls the same activity
// monitor the /activity page uses). No live_calls block -> the hero decides
// from telemetry alone.
vi.mock("../src/api/activity", () => ({
  getActivityMonitor: vi.fn().mockResolvedValue({
    available: true,
    active: [],
    recent: [],
    synthetic_inference: { synthetic: true, source: "fixture", workers: [] },
    generated_at: new Date().toISOString(),
  }),
  getActivityGraph: vi.fn().mockResolvedValue({
    available: false,
    nodes: [],
    edges: [],
    generated_at: new Date().toISOString(),
  }),
  getActiveRun: vi.fn().mockResolvedValue(null),
}));

describe("Dashboard realignment", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("mounts BOTH model-server panels (Gemma + Qwen) side-by-side", () => {
    renderDashboard();
    // Gemma panel header + up status (vllm block present).
    expect(screen.getByText("gemma-4-26b-a4b")).toBeInTheDocument();
    expect(screen.getByTestId("gemma-4-26b-a4b-status")).toHaveTextContent(
      "up",
    );
    // Qwen panel still present (untouched by the refactor).
    expect(screen.getByText(/Qwen3.6-27B/)).toBeInTheDocument();
  });

  it("feeds the verdict Qwen-filtered inputs so a Qwen read error stays HEALTHY", () => {
    renderDashboard();
    const verdict = screen.getByTestId("health-verdict");
    // "vllm-qwen-metrics" is the only read error and is filtered out, the
    // stream is fresh and connected, and gemmaUp is true -> HEALTHY.
    expect(verdict.getAttribute("data-level")).toBe("healthy");
  });

  it("keeps ResolvedIterationsList reachable and opens JournalScroll on selection", async () => {
    renderDashboard();
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

  it("mounts the SystemActivityHero under the health hero and reads BUSY off vllm load", async () => {
    renderDashboard();
    // Telemetry carries running_requests: 1 with no registered run (both
    // mirrors resolve null) -> the amber busy-unregistered state, never
    // "idle" while the machine works.
    const hero = screen.getByTestId("system-activity-hero");
    await waitFor(() =>
      expect(hero.getAttribute("data-state")).toBe("busy-unregistered"),
    );
    // The health hero is still above it, untouched.
    expect(screen.getByTestId("health-verdict")).toBeInTheDocument();
  });

  it("does NOT mount HumanTodoPanel — it moved to /todo (2026-06-14 PART 1)", async () => {
    renderDashboard();
    // The panel is gone from the dashboard; the at-a-glance signal is now the
    // hero's "N need you →" coupling, which links to the /todo cockpit.
    expect(screen.queryByTestId("human-todo-panel")).toBeNull();
    const link = await screen.findByTestId("dashboard-needs-you");
    expect(link.getAttribute("href")).toBe("/todo");
    // Empty A+B counts -> the calm "none need you" form, still a live link.
    expect(link).toHaveTextContent(/none need you/i);
  });

  it("the 'N need you' count is taxonomy A+B ONLY (gate_verdict + state_gate)", async () => {
    // bubble_ack / stale_active_run (C) and finding_review are NOT decisions
    // and must be excluded: N = 2 + 1 = 3, never 3 + 9 + 4.
    vi.mocked(getHumanTodo).mockResolvedValueOnce({
      items: [],
      counts: {
        gate_verdict: 2,
        state_gate: 1,
        bubble_ack: 9,
        stale_active_run: 5,
        finding_review: 4,
      },
    });
    renderDashboard();
    const link = await screen.findByTestId("dashboard-needs-you");
    await waitFor(() => expect(link).toHaveTextContent("3 need you →"));
  });

  it("offers drill-into links to the deep-dive pages (B5)", () => {
    renderDashboard();
    const links = screen.getAllByRole("link", { name: /drill into/ });
    const hrefs = links.map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/activity");
    expect(hrefs).toContain("/coordinator");
  });
});
