// Pulse (/) — the S1 home page: HealthVerdict hero + the ONE merged now-card
// (NowBoard + headline strip) + OweStrip + LastCycleLine + HealthStrip + the
// two ModelServerCards + the launch disclosure. Route-level smoke against
// mocked feeds: every surface mounts, the owed row links into the dossier
// reader, and the render stays console-clean (the route-sweep bar).
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TelemetrySample } from "../src/types/schemas";

const D = vi.hoisted(() => {
  const sample = {
    timestamp: new Date().toISOString(),
    gpu: { util_pct: 10, mem_used_mb: null, mem_total_mb: null, temp_c: 41, power_w: 5.5 },
    host: { cpu_pct: 10, mem_used_mb: 5000, cpu_temp_c: 44, load_avg: [1, 1, 1] },
    vllm: {
      running_requests: 0,
      waiting_requests: 0,
      gpu_cache_usage_pct: 12,
      gpu_prefix_cache_hit_rate: 0.8,
      tokens_per_sec_decode: 42,
      mtp_acceptance_rate: 0.6,
      mtp_draft_tokens: 100,
      mtp_accepted_tokens: 60,
    },
    vllm_qwen: null,
    processes: [],
    read_errors: null,
  } as unknown as TelemetrySample;
  return { samples: [sample, { ...sample }] };
});

vi.mock("../src/hooks/useTelemetryStream", () => ({
  useTelemetryStream: () => ({
    samples: D.samples,
    latest: D.samples[D.samples.length - 1],
    connected: true,
  }),
}));

vi.mock("../src/api/http", () => ({
  getHealth: vi.fn().mockResolvedValue({
    ok: true,
    hostname: "spark",
    telemetry_last_seen: new Date().toISOString(),
    version: "testsha",
  }),
  getHumanTodo: vi.fn().mockResolvedValue({
    items: [
      {
        kind: "gate_verdict",
        id: "iter-2026-08-14-001",
        title: "iter-2026-08-14-001 awaiting verdict",
        since: "2026-08-14T10:00:00Z",
      },
      {
        // Below-bar legacy finding — must stay OFF the owe strip.
        kind: "finding_review",
        id: "sf-legacy-001",
        title: "pre-ladder finding",
        since: "2026-06-01T00:00:00Z",
      },
    ],
    counts: { gate_verdict: 1, finding_review: 1 },
  }),
  getCoordinatorCycles: vi.fn().mockResolvedValue({
    cycles: [
      {
        timestamp: "2026-08-14T09:30:00Z",
        run_id: "coordinator_001",
        agent: "coordinator",
        topic: "pulse smoke cycle",
        topic_source: "arxiv_pick",
        status: "executed",
        plan: [],
        outcomes: [],
        promoted_finding_ids: [],
        bubble_run_ids: [],
      },
    ],
  }),
  getWorkloadHint: vi.fn().mockResolvedValue({
    available: false,
    sample_size: 0,
    calls_per_s: null,
    median_output_tokens: null,
    regime: "idle",
    expected_decode_tok_s_lower: null,
    expected_decode_tok_s_upper: null,
    window_s: 120,
    note: "",
  }),
  getActiveRuns: vi.fn().mockResolvedValue({ runs: [], skipped: 0 }),
  startIteration: vi.fn().mockResolvedValue({ pid: 1 }),
}));

vi.mock("../src/api/activity", () => ({
  getActivityMonitor: vi.fn().mockResolvedValue({
    available: true,
    telemetry_available: true,
    active: [],
    recent: [],
    live_calls: {
      active: false,
      count: 0,
      window_s: 60,
      calls_per_s: null,
      last_call_at: null,
      caller_tags: [],
      model: null,
    },
    synthetic_inference: {
      synthetic: true,
      source: "fixture",
      needs: "worker_activity.jsonl",
      note: "synthetic placeholder",
      workers: [],
    },
    generated_at: new Date().toISOString(),
  }),
}));

import Pulse from "../src/routes/Pulse";

afterEach(() => {
  vi.clearAllMocks();
});

describe("Pulse (/)", () => {
  it("mounts every S1 surface and stays console-clean", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(
      <MemoryRouter>
        <Pulse />
      </MemoryRouter>,
    );

    // 1 — healthy? The composed hero, healthy off the fixture stream.
    expect(screen.getByTestId("health-verdict")).toBeInTheDocument();

    // The ONE now-card: registry board + headline strip. Zero registered
    // runs + no calls + quiet GPU = an honest IDLE, never a blank.
    await waitFor(() =>
      expect(screen.getByTestId("now-board")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("now-verdict")).toHaveAttribute(
      "data-state",
      "idle",
    );
    expect(screen.getByTestId("now-board-empty")).toBeInTheDocument();

    // 2 — do I owe anything? The gate item shows; the below-bar legacy
    // finding stays off the strip (it is dossier-index material).
    await waitFor(() =>
      expect(screen.getByTestId("owe-strip")).toHaveTextContent(
        "iter-2026-08-14-001 awaiting verdict",
      ),
    );
    expect(screen.getByTestId("owe-strip").textContent).not.toContain(
      "pre-ladder finding",
    );
    expect(
      screen.getByRole("link", { name: /awaiting verdict/ }),
    ).toHaveAttribute("href", "/dossier/iter-2026-08-14-001");

    // Last-cycle one-liner.
    await waitFor(() =>
      expect(screen.getByTestId("last-cycle-line")).toHaveTextContent(
        "pulse smoke cycle",
      ),
    );

    // Both model servers, parameterized off the one card.
    expect(screen.getByTestId("gemma-4-26b-a4b-status")).toHaveTextContent(
      "up",
    );
    expect(
      screen.getByTestId("qwen3.6-27b-nvfp4-mtp-status"),
    ).toHaveTextContent("down");

    // Launching an iteration is disclosed, not ambient.
    const disclosure = screen.getByTestId("pulse-launch-disclosure");
    expect(disclosure.querySelector("form, button, textarea, input")).not.toBeNull();

    // Console-clean (the route-sweep bar).
    await waitFor(() => expect(true).toBe(true));
    expect(
      errSpy.mock.calls.map((c) => String(c[0])),
      `console.error: ${errSpy.mock.calls.map((c) => String(c[0])).join(" | ")}`,
    ).toHaveLength(0);
    expect(
      warnSpy.mock.calls.map((c) => String(c[0])),
      `console.warn: ${warnSpy.mock.calls.map((c) => String(c[0])).join(" | ")}`,
    ).toHaveLength(0);
    errSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("retired mirror endpoints are NOT polled (registered derives from the registry)", async () => {
    // The plan drops getActiveIteration/getCoordinatorActive from the home
    // page — their absence from the api/http mock above IS the pin: if Pulse
    // (or anything it mounts) called them, the mocked module would throw on
    // the missing export and the render below would crash.
    render(
      <MemoryRouter>
        <Pulse />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("pulse-page")).toBeInTheDocument(),
    );
  });
});
