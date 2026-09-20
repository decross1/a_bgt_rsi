// Pulse (/) — the S1 home page: HealthVerdict hero + the ONE merged now-card
// (NowBoard + headline strip) + OweStrip + LastCycleLine + HealthStrip + the
// two ModelServerCards + the launch disclosure. Route-level smoke against
// mocked feeds: every surface mounts, the owed row links into the dossier
// reader, and the render stays console-clean (the route-sweep bar).
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import CommandPalette from "../src/design/CommandPalette";
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
  // Event fixtures are RELATIVE to now: the sparkgrid only counts events
  // inside its trailing window, so hard-coded dates would silently stop being
  // counted once the wall clock moved past the window (a test that decays
  // into a false pass).
  const dayAgo = (n: number) =>
    new Date(Date.now() - n * 86_400_000).toISOString();
  return {
    samples: [sample, { ...sample }],
    connected: true,
    iterEnded: [dayAgo(1), dayAgo(2)],
    cycleAt: dayAgo(1),
  };
});

vi.mock("../src/hooks/useTelemetryStream", () => ({
  useTelemetryStream: () => ({
    samples: D.samples,
    latest: D.samples[D.samples.length - 1],
    connected: D.connected,
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
        timestamp: D.cycleAt,
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
  // Live served-model probe (2026-08-16): the card titles read from this,
  // never from a constant.
  getServedModels: vi.fn().mockResolvedValue({
    gemma: { url: "http://localhost:8000", model: "gemma-4-26b-a4b", error: null },
    qwen: { url: "http://localhost:8001", model: "qwen3.6-27b-nvfp4-mtp", error: null },
  }),
  getModelRuntime: vi.fn().mockResolvedValue({
    schema_version: "model-runtime/v1",
    observed_at: new Date().toISOString(),
    mode: "unknown",
    mode_source: "none",
    mode_source_sha256: null,
    resident_services_expected: "unknown",
    nara_service_expected: "unknown",
    run_id: null,
    phase: null,
    source_error: null,
  }),
  getResearchOpsStatus: vi.fn().mockResolvedValue({
    schema: "research-ops-status/v1",
    observed_at: new Date().toISOString(),
    active_campaign: { campaign_id: "campaign-1", manifest_sha256: "a".repeat(64) },
    campaign_queue: { status: "all_registered_topics_consumed", eligible_count: 0,
      consumed_count: 1, loop_source_sha256: "b".repeat(64) },
    next_registered_campaign: null,
    last_productive: { kind: "campaign_iteration_recorded", iteration_id: "iter-1",
      topic_id: "topic-1", at: new Date().toISOString(), loop_source_sha256: "b".repeat(64) },
    last_cycle: { run_id: "cycle-1", at: new Date().toISOString(), action_code: "noop",
      planned_count: 0, dispatched_count: 0, outcome_count: 1,
      raw_row_sha256: "c".repeat(64), cycles_source_sha256: "d".repeat(64) },
    budget: { source_status: "available", spent_today: 3, daily_cap: 60,
      paced_allowance: 44, ledger_sha256: "e".repeat(64) },
    dispatch_gate: { operator_pause: false, other_actionable_work: "not_assessed" },
    ingestion: { source_status: "unknown", latest_attempt_status: "unknown" },
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
  // R3 additions: the sparkgrid's second series, and the ladder mini-funnel.
  getIterations: vi.fn().mockResolvedValue({
    iterations: [
      { iteration_id: "iter-a", ended_at: D.iterEnded[0] },
      { iteration_id: "iter-b", ended_at: D.iterEnded[1] },
    ],
  }),
  getLadder: vi.fn().mockResolvedValue({
    clusters: [],
    histogram: { L0: 9, L1: 4, L2: 2, L3: 1, L4: 1, L5: 0 },
    counts: { open: 12, surfaced: 2, killed: 3 },
    agenda: [],
    next_owed: {},
  }),
  // The lab's queue, mounted directly below the hero. Its human_gaps deliver
  // the SAME pending gate verdict the OweStrip fixture above carries — the
  // pin below is that it renders as a pointer, never as a second copy of the
  // human's queue.
  getLabTodo: vi.fn().mockResolvedValue({
    agent_gaps: ["4 open cluster(s) at L1 awaiting synthetic experiment"],
    human_gaps: ["1 recent iteration(s) await a human gate verdict"],
    owed: [
      {
        test: "synthetic experiment",
        rung: "L1",
        clusters: [
          { cluster_id: "cl-a", stem: "KV-cache eviction bias", last_event_ts: null },
        ],
      },
    ],
    agenda: [],
    refine_candidates: [],
    generated_at: new Date().toISOString(),
  }),
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

import Pulse, {
  inventoryGenerationKey,
  isModelRuntime,
  permanentDeploymentHealth,
  stripMonitorChurn,
} from "../src/routes/Pulse";
import { getLabTodo, type ServedModel } from "../src/api/http";
import type { ModelRuntime } from "../src/api/http";
import { refreshPoll } from "../src/api/pollhub";
import type { MonitorResponse } from "../src/types/activity";

const baselineTelemetry = D.samples;

function modelInventoryRow(overrides: Partial<ServedModel> = {}): ServedModel {
  return {
    url: "http://127.0.0.1:8000",
    model: "model",
    error: null,
    probed_at: new Date().toISOString(),
    configured_model: "model",
    configured_max_context_tokens: 16384,
    observed_max_context_tokens: 16384,
    deployment_role: "production_resident",
    benchmark_cohort: "resident",
    promotion_authorized: false,
    models_endpoint_status: "available",
    service_status: "online",
    identity_status: "match",
    metrics_endpoint_status: "available",
    activity_status: "idle",
    metrics: D.samples[0].vllm,
    metrics_error: null,
    ...overrides,
  };
}

function permanentRuntime(): ModelRuntime {
  return {
    schema_version: "model-runtime/v1",
    observed_at: new Date().toISOString(),
    mode: "resident",
    mode_source: "permanent_deployment",
    production_authorized: true,
    mode_source_sha256: "a".repeat(64),
    resident_services_expected: "stopped",
    nara_service_expected: "running",
    run_id: "flash-permanent-20260919",
    phase: "ready",
    candidate_variant: null,
    source_error: null,
  };
}

describe("permanent Flash deployment health", () => {
  it("uses the production-resident Flash inventory instead of absent Gemma telemetry", () => {
    const flash = modelInventoryRow({
      url: "http://127.0.0.1:30080",
      model: "nvidia/Qwen3.8-Flash-Next-NVFP4",
      configured_model: "nvidia/Qwen3.8-Flash-Next-NVFP4",
      deployment_role: "production_resident",
      promotion_authorized: true,
      service_status: "online",
      identity_status: "match",
      metrics_endpoint_status: "available",
    });
    expect(permanentDeploymentHealth(permanentRuntime(), { flash }, false)).toMatchObject({
      active: true,
      level: "healthy",
      headline: "Flash production resident online",
    });
  });

  it("reports the selected endpoint offline or stale without falling back to Gemma", () => {
    const flash = modelInventoryRow({
      deployment_role: "production_resident",
      promotion_authorized: true,
      service_status: "offline",
      identity_status: "unknown",
      metrics_endpoint_status: "unreachable",
    });
    expect(permanentDeploymentHealth(permanentRuntime(), { flash }, false).level).toBe("down");
    expect(permanentDeploymentHealth(permanentRuntime(), {
      flash: { ...flash, service_status: "online", identity_status: "match" },
    }, true).level).toBe("unknown");
  });
});

afterEach(() => {
  D.samples = baselineTelemetry.map((sample) => ({
    ...sample,
    timestamp: new Date().toISOString(),
  }));
  D.connected = true;
  // Pulse registers palette verbs on mount and withdraws them on unmount —
  // an un-cleaned render would leak them into the next test's registry.
  cleanup();
  vi.clearAllMocks();
});

describe("Pulse (/)", () => {
  it("mounts every S1 surface and stays console-clean", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(
      <MemoryRouter initialEntries={["/?research_scope=all"]}>
        <Pulse />
      </MemoryRouter>,
    );

    // 1 — healthy? The composed hero, healthy off the fixture stream.
    expect(screen.getByTestId("health-verdict")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View model evidence" })).toHaveAttribute("href", "/benchmarks");

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

    fireEvent.click(screen.getByText("Recorded human requests"));
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
    ).toHaveAttribute("href", "/dossier/iter-2026-08-14-001?research_scope=all");

    // The demoted mass is INFORMATION, not a queue: one muted line, and the
    // owed count stays at the one real gate item.
    await waitFor(() =>
      expect(screen.getByTestId("owe-below-bar")).toHaveTextContent(
        "1 below-bar finding demoted to the ladder",
      ),
    );
    expect(screen.getByTestId("owe-count")).toHaveTextContent("1");

    expect(getLabTodo).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Load lab queue" }));
    // 2b — and what is the LAB carrying? The lab's queue sits directly below
    // the hero, in DOM order (the hierarchy is the point: the human's queue
    // is the hero, the lab's is the secondary zone).
    await waitFor(() =>
      expect(screen.getByTestId("lab-todo")).toHaveTextContent(
        "1 cluster owes synthetic experiment",
      ),
    );
    const page = screen.getByTestId("pulse-page");
    const order = Array.from(
      page.querySelectorAll("[data-testid='owe-strip'], [data-testid='lab-todo']"),
    ).map((el) => el.getAttribute("data-testid"));
    expect(order).toEqual(["owe-strip", "lab-todo"]);

    // The human-owed gap the lab reports is a POINTER to the hero, never a
    // second copy of the human's queue.
    expect(screen.getByTestId("lab-todo-blocked")).toHaveTextContent(
      "1 of the loop's gaps wait on you",
    );
    expect(screen.getByTestId("lab-todo").textContent).not.toContain(
      "await a human gate verdict",
    );

    // Zone 2 — is the lab alive? Both series bucket into the sparkgrid.
    await waitFor(() =>
      expect(screen.getByTestId("lab-sparkgrid-summary")).toHaveTextContent(
        "2 iterations · 1 coordinator cycle",
      ),
    );
    // …and the idle run board names when the loop last finished, rather than
    // implying nothing ever has.
    expect(screen.getByTestId("now-board-empty")).toHaveTextContent(
      /last finished .* ago/,
    );

    // Ladder mini-funnel, off /api/ladder's histogram.
    await waitFor(() =>
      expect(screen.getByTestId("ladder-funnel-L0")).toHaveAttribute(
        "data-count",
        "9",
      ),
    );

    // Last-cycle one-liner (now fed by Pulse's single cycles poll).
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

  it("registers its verbs in the ⌘K palette, and withdraws them on unmount", async () => {
    const { unmount } = render(
      <MemoryRouter initialEntries={["/?research_scope=all"]}>
        <CommandPalette />
        <Pulse />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("pulse-page")).toBeInTheDocument(),
    );

    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.getByText("launch an iteration")).toBeInTheDocument();
    expect(screen.getByText("review what you owe")).toBeInTheDocument();
    expect(screen.getByText("show lab activity")).toBeInTheDocument();
    expect(screen.getByText("lab queue")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    unmount();

    // A route's verbs must not outlive the route — the registry is global.
    render(
      <MemoryRouter>
        <CommandPalette />
      </MemoryRouter>,
    );
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.queryByText("launch an iteration")).toBeNull();
  });

  it("the ladder mini-funnel HIDES on a 204, rather than showing empty rungs", async () => {
    const { getLadder } = await import("../src/api/http");
    vi.mocked(getLadder).mockResolvedValueOnce(null);
    render(
      <MemoryRouter>
        <Pulse />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("pulse-page")).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(screen.getByTestId("lab-sparkgrid")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("ladder-funnel")).toBeNull();
  });

  it("a FAILED cycles read says UNKNOWN — it never renders as an empty slot", async () => {
    // Regression pin: Pulse took the cycles poll over from LastCycleLine, and
    // an early cut swallowed the rejection — which silently removed the line
    // entirely, reading as "the loop has done nothing" instead of "the read
    // failed".
    const { getCoordinatorCycles } = await import("../src/api/http");
    vi.mocked(getCoordinatorCycles).mockRejectedValueOnce(new Error("500 boom"));
    render(
      <MemoryRouter initialEntries={["/?research_scope=all"]}>
        <Pulse />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("pulse-cycles-unavailable")).toHaveTextContent(
        "UNKNOWN, not absent",
      ),
    );
    expect(screen.queryByTestId("last-cycle-line")).toBeNull();
  });

  it("arriving at /#lab-queue scrolls the lab's queue into view", async () => {
    // /ladder's "lab queue →" link navigates here with a hash; React Router
    // does not scroll for one, so Pulse does it. Without this the link would
    // land the reader at the top of Pulse with no sign of why.
    const scrollSpy = vi
      .spyOn(Element.prototype, "scrollIntoView")
      .mockImplementation(() => {});
    render(
      <MemoryRouter initialEntries={["/#lab-queue"]}>
        <Pulse />
      </MemoryRouter>,
    );
    await waitFor(() => expect(scrollSpy).toHaveBeenCalled());
    const scrolled = scrollSpy.mock.instances[0] as Element;
    expect(scrolled.querySelector("[data-testid='pulse-queue-not-read']")).not.toBeNull();
    expect(getLabTodo).not.toHaveBeenCalled();
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

  it("the model cards name the model that is ACTUALLY serving, not a constant", async () => {
    // 2026-08-16: an A/B window served Qwen 3.8 on :8001 while this card kept
    // announcing "Qwen3.6-27B · NVFP4-MTP" — the title was a hardcoded string.
    // The title must track the live probe, whatever it reports.
    const http = await import("../src/api/http");
    (http.getServedModels as unknown as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({
        gemma: { url: "u", model: "gemma-4-26b-a4b", error: null },
        qwen: { url: "u", model: "qwen3.8-27b-nvfp4-mtp", error: null },
      });
    render(
      <MemoryRouter>
        <Pulse />
      </MemoryRouter>,
    );
    expect(await screen.findByText("qwen3.8-27b-nvfp4-mtp")).toBeInTheDocument();
    expect(screen.queryByText("Qwen3.6-27B · NVFP4-MTP")).toBeNull();
  });

  it("an IDLE monitor payload reads UNCHANGED once generated_at is stripped (fix 2)", () => {
    // /api/activity/monitor stamps a fresh top-level generated_at on EVERY
    // response, which made an idle payload always read "changed" to the
    // pollhub's JSON change detection — NowBoard + both ModelServerCards
    // re-rendered per 15 s poll of a quiet lab. Pulse's fetchMonitor strips
    // it before the hub sees the payload; two idle responses that differ
    // ONLY in generated_at must therefore stringify identically (stringify
    // IS the hub's deep-equal).
    const idle = (iso: string): MonitorResponse => ({
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
      generated_at: iso,
    });
    const a = stripMonitorChurn(idle("2026-08-18T10:00:00Z"));
    const b = stripMonitorChurn(idle("2026-08-18T10:00:15Z"));
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
    expect("generated_at" in a).toBe(false);
    // Everything the page reads survives the strip.
    expect(a.live_calls?.count).toBe(0);
    expect(a.available).toBe(true);
  });

  it("an unreachable model server reads UNKNOWN, never a remembered name", async () => {
    const http = await import("../src/api/http");
    (http.getServedModels as unknown as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({
        gemma: { url: "u", model: null, error: "OSError: refused" },
        qwen: { url: "u", model: null, error: "OSError: refused" },
      });
    render(
      <MemoryRouter>
        <Pulse />
      </MemoryRouter>,
    );
    expect(await screen.findAllByText("unknown")).toHaveLength(2);
  });

  it("renders every configured endpoint from the dynamic inventory without promoting the candidate", async () => {
    const http = await import("../src/api/http");
    (http.getServedModels as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      gemma: modelInventoryRow({ model: "gemma-live", configured_model: "gemma-live" }),
      qwen: modelInventoryRow({ url: "http://127.0.0.1:8001", model: "qwen-live", configured_model: "qwen-live" }),
      flash: modelInventoryRow({
        url: "http://127.0.0.1:8012",
        model: null,
        configured_model: "qwen3.8-flash-next",
        deployment_role: "research_candidate",
        benchmark_cohort: "flash",
        service_status: "offline",
        models_endpoint_status: "unreachable",
        identity_status: "unknown",
        metrics_endpoint_status: "unreachable",
        activity_status: "unknown",
        metrics: null,
      }),
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);

    expect(await screen.findByText("3 configured endpoints")).toBeInTheDocument();
    expect(screen.getByText("2 online")).toBeInTheDocument();
    expect(screen.getByText("gemma-live")).toBeInTheDocument();
    expect(screen.getByText("qwen-live")).toBeInTheDocument();
    expect(screen.getByText("qwen3.8-flash-next")).toBeInTheDocument();
    expect(screen.getByTestId("flash-inventory")).toHaveTextContent("Research candidate");
    expect(screen.getByTestId("flash-inventory")).toHaveTextContent("Evaluation only");
    expect(screen.getByTestId("flash-inventory")).toHaveTextContent(":8012");
    expect(screen.getByTestId("unobserved-flash-status")).toHaveTextContent("not serving");
  });

  it("does not present a partial inventory response as a complete model catalog", async () => {
    const http = await import("../src/api/http");
    (http.getServedModels as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      gemma: modelInventoryRow({ model: "gemma-live", configured_model: "gemma-live" }),
      qwen: modelInventoryRow({ model: "qwen-live", configured_model: "qwen-live" }),
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);

    expect(await screen.findByTestId("model-inventory-legacy")).toHaveTextContent(
      "Detailed endpoint inventory is unavailable",
    );
    expect(screen.queryByText("3 configured endpoints")).toBeNull();
    expect(screen.queryByText("2 configured endpoints")).toBeNull();
  });

  it("labels a controller-bound candidate window without claiming the lab is healthy", async () => {
    const http = await import("../src/api/http");
    D.connected = false;
    D.samples = D.samples.map((sample) => ({
      ...sample,
      vllm: null,
      read_errors: { psutil: "unavailable" },
    }));
    (http.getServedModels as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      gemma: modelInventoryRow({
        model: null,
        configured_model: "gemma-4-26b-a4b",
        service_status: "offline",
        models_endpoint_status: "unreachable",
        identity_status: "unknown",
        metrics_endpoint_status: "unreachable",
        activity_status: "unknown",
        metrics: null,
      }),
      qwen: modelInventoryRow({
        url: "http://127.0.0.1:8001",
        model: null,
        configured_model: "qwen3.8-27b-nvfp4-mtp",
        service_status: "offline",
        models_endpoint_status: "unreachable",
        identity_status: "unknown",
        metrics_endpoint_status: "unreachable",
        activity_status: "unknown",
        metrics: null,
      }),
      flash: modelInventoryRow({
        url: "http://127.0.0.1:8012",
        model: null,
        configured_model: "qwen3.8-flash-next",
        deployment_role: "research_candidate",
        benchmark_cohort: "flash",
        service_status: "offline",
        models_endpoint_status: "unreachable",
        identity_status: "unknown",
        metrics_endpoint_status: "unreachable",
        activity_status: "unknown",
        metrics: null,
      }),
    });
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1",
      observed_at: new Date().toISOString(),
      mode: "candidate_research",
      mode_source: "qualification_state",
      mode_source_sha256: "a".repeat(64),
      resident_services_expected: "stopped",
      nara_service_expected: "paused",
      run_id: "qfn-c0-001",
      phase: "readiness",
      source_error: null,
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);

    await waitFor(() =>
      expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "research"),
    );
    const verdict = screen.getByTestId("health-verdict");
    expect(verdict).toHaveTextContent("RESEARCH WINDOW");
    expect(verdict).toHaveTextContent("Resident model services are expected to be stopped");
    expect(verdict).toHaveTextContent("During this phase Nara is expected paused");
    expect(screen.getByTestId("runtime-observability-warning")).toHaveTextContent(
      "telemetry disconnected",
    );
    expect(screen.getByTestId("runtime-observability-warning")).toHaveTextContent(
      "read errors: psutil",
    );
    expect(screen.getByTestId("unobserved-gemma-status")).toHaveTextContent(
      "offline · expected during research",
    );
    expect(screen.getByTestId("unobserved-qwen-status")).toHaveTextContent(
      "offline · expected during research",
    );
    expect(screen.getByTestId("unobserved-flash-status")).toHaveTextContent("starting");
    expect(screen.getByTestId("unobserved-flash-status")).not.toHaveClass("text-red-400");
    expect(verdict).not.toHaveTextContent(/HEALTHY|telemetry fresh; Gemma metrics present|DOWN/);
  });

  it.each(["starting", "ready"])("recognizes the current personal SGLang session during %s", async (phase) => {
    const http = await import("../src/api/http");
    const paused = {
      model: null, service_status: "offline", models_endpoint_status: "unreachable",
      identity_status: "unknown", metrics_endpoint_status: "unreachable",
      activity_status: "unknown", metrics: null,
    } as const;
    (http.getServedModels as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      gemma: modelInventoryRow({ ...paused, configured_model: "gemma-4-26b-a4b" }),
      qwen: modelInventoryRow({ ...paused, url: "http://127.0.0.1:8001", configured_model: "qwen3.8-27b-nvfp4-mtp" }),
      flash: modelInventoryRow({
        ...(phase === "starting" ? paused : {}),
        url: "http://127.0.0.1:30080",
        model: phase === "ready" ? "nvidia/Qwen3.8-Flash-Next-NVFP4" : null,
        configured_model: "nvidia/Qwen3.8-Flash-Next-NVFP4",
        deployment_role: "research_candidate", benchmark_cohort: "flash",
      }),
    });
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "candidate_research", mode_source: "personal_session_state",
      mode_source_sha256: "a".repeat(64), resident_services_expected: "stopped",
      nara_service_expected: "paused", run_id: "session-s3-readiness-v5-001",
      phase, personal_endpoint: "sglang", candidate_id: "b".repeat(64),
      candidate_variant: null, source_error: null,
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("Personal Flash session active")).toBeInTheDocument());
    expect(screen.getByTestId("unobserved-gemma-status")).toHaveTextContent("expected during research");
    expect(screen.getByTestId("unobserved-qwen-status")).toHaveTextContent("expected during research");
    expect(screen.queryByText("Resident serving")).not.toBeInTheDocument();
    if (phase === "starting") {
      expect(screen.getByTestId("unobserved-flash-status")).toHaveTextContent("starting");
      expect(screen.getByText(/controller reports the starting phase/)).toBeInTheDocument();
    } else {
      expect(screen.getByTestId("nvidia/Qwen3.8-Flash-Next-NVFP4-status")).toHaveTextContent("online");
      expect(screen.getByText(/controller reports the ready phase/)).toBeInTheDocument();
      expect(screen.queryByText(/is available for research and coding/)).not.toBeInTheDocument();
    }
  });

  it("keeps a ready personal endpoint visibly offline when the matching probe is offline", async () => {
    const http = await import("../src/api/http");
    const offline = {
      model: null, service_status: "offline", models_endpoint_status: "unreachable",
      identity_status: "unknown", metrics_endpoint_status: "unreachable",
      activity_status: "unknown", metrics: null,
    } as const;
    (http.getServedModels as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      gemma: modelInventoryRow({ ...offline, configured_model: "gemma-4-26b-a4b" }),
      qwen: modelInventoryRow({ ...offline, url: "http://127.0.0.1:8001", configured_model: "qwen3.8-27b-nvfp4-mtp" }),
      flash: modelInventoryRow({
        ...offline, url: "http://127.0.0.1:30080",
        configured_model: "nvidia/Qwen3.8-Flash-Next-NVFP4",
        deployment_role: "research_candidate", benchmark_cohort: "flash",
      }),
    });
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "candidate_research", mode_source: "personal_session_state",
      mode_source_sha256: "a".repeat(64), resident_services_expected: "stopped",
      nara_service_expected: "paused", run_id: "session-s3-readiness-v5-001",
      phase: "ready", personal_endpoint: "sglang", candidate_id: "b".repeat(64),
      candidate_variant: null, source_error: null,
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText(/controller reports the ready phase/)).toBeInTheDocument());
    expect(screen.getByTestId("unobserved-flash-status")).toHaveTextContent("offline");
    expect(screen.queryByText(/is available for research and coding/)).not.toBeInTheDocument();
  });

  it("does not present retained Mia inventory as the selected personal SGLang endpoint", async () => {
    const http = await import("../src/api/http");
    (http.getServedModels as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      gemma: modelInventoryRow({ configured_model: "gemma-4-26b-a4b" }),
      qwen: modelInventoryRow({ url: "http://127.0.0.1:8001", configured_model: "qwen3.8-27b-nvfp4-mtp" }),
      flash: modelInventoryRow({
        url: "http://127.0.0.1:8012", model: "qwen3.8-flash-next-mia",
        configured_model: "qwen3.8-flash-next-mia",
        deployment_role: "research_candidate", benchmark_cohort: "flash",
      }),
    });
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "candidate_research", mode_source: "personal_session_state",
      mode_source_sha256: "a".repeat(64), resident_services_expected: "stopped",
      nara_service_expected: "paused", run_id: "session-s3-readiness-v5-001",
      phase: "ready", personal_endpoint: "sglang", candidate_id: "b".repeat(64),
      candidate_variant: null, source_error: null,
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    const awaiting = await screen.findByTestId("personal-flash-inventory-awaiting");
    expect(awaiting).toHaveTextContent("Awaiting a matching endpoint probe");
    expect(awaiting).toHaveTextContent("http://127.0.0.1:30080");
    expect(awaiting).toHaveTextContent("qwen3.8-flash-next-mia");
    expect(screen.queryByTestId("qwen3.8-flash-next-mia-status")).not.toBeInTheDocument();
  });

  it("requires complete active personal identity and accepts only the bounded unknown shape", () => {
    const base = {
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode_source: "personal_session_state", candidate_variant: null,
    };
    expect(isModelRuntime({
      ...base, mode: "candidate_research", mode_source_sha256: "a".repeat(64),
      resident_services_expected: "stopped", nara_service_expected: "paused",
      run_id: "session-s3-readiness-v5-001", phase: "ready",
      personal_endpoint: null, candidate_id: null, source_error: null,
    })).toBe(false);
    expect(isModelRuntime({
      ...base, mode: "unknown", mode_source_sha256: null,
      resident_services_expected: "unknown", nara_service_expected: "unknown",
      run_id: null, phase: null, personal_endpoint: null, candidate_id: null,
      source_error: "personal session projection is ambiguous",
    })).toBe(true);
  });

  it("renders a malformed active personal projection as unverified", async () => {
    const http = await import("../src/api/http");
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "candidate_research", mode_source: "personal_session_state",
      mode_source_sha256: "a".repeat(64), resident_services_expected: "stopped",
      nara_service_expected: "paused", run_id: "session-s3-readiness-v5-001",
      phase: "ready", personal_endpoint: null, candidate_id: null,
      candidate_variant: null, source_error: null,
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await waitFor(() => expect(http.getModelRuntime).toHaveBeenCalled());
    expect(await screen.findByRole("heading", { name: "Operating mode unverified" })).toBeInTheDocument();
    expect(screen.queryByText("Personal Flash session active")).not.toBeInTheDocument();
  });

  it("accepts a bounded unknown personal projection without claiming an active session", async () => {
    const http = await import("../src/api/http");
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "unknown", mode_source: "personal_session_state",
      mode_source_sha256: null, resident_services_expected: "unknown",
      nara_service_expected: "unknown", run_id: null, phase: null,
      personal_endpoint: null, candidate_id: null, candidate_variant: null,
      source_error: "personal session projection is ambiguous",
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await waitFor(() => expect(http.getModelRuntime).toHaveBeenCalled());
    expect(await screen.findByRole("heading", { name: "Operating mode unverified" })).toBeInTheDocument();
    expect(screen.queryByText("Personal Flash session active")).not.toBeInTheDocument();
  });

  it("starts a new Flash graph generation when candidate identity changes", () => {
    const row = modelInventoryRow({
      url: "http://127.0.0.1:30080",
      configured_model: "nvidia/Qwen3.8-Flash-Next-NVFP4",
    });
    const first = inventoryGenerationKey("flash", row, null, "session-current", "a".repeat(64));
    expect(inventoryGenerationKey("flash", row, null, "session-current", "a".repeat(64))).toBe(first);
    expect(inventoryGenerationKey("flash", row, null, "session-current", "b".repeat(64))).not.toBe(first);
  });

  it("labels controller setup as preparation without implying model services changed", async () => {
    const http = await import("../src/api/http");
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1",
      observed_at: new Date().toISOString(),
      mode: "transitioning",
      mode_source: "qualification_state",
      mode_source_sha256: "c".repeat(64),
      resident_services_expected: "unknown",
      nara_service_expected: "unknown",
      run_id: "qfn-c0-setup",
      phase: "preflight",
      source_error: null,
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);

    await waitFor(() =>
      expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "transitioning"),
    );
    expect(screen.getByRole("heading", { name: "Preparing research window" })).toBeInTheDocument();
    expect(screen.getByTestId("health-verdict")).toHaveTextContent("PREPARING");
    expect(screen.getByTestId("health-verdict")).toHaveTextContent(
      "model services have not been changed in this phase",
    );
    expect(screen.getByTestId("health-verdict")).not.toHaveTextContent(
      "Model runtime transition is recorded",
    );
  });

  it("shows an admitted active resident follow-on arm with Nara paused", async () => {
    const http = await import("../src/api/http");
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "resident", mode_source: "followon_resident_state",
      mode_source_sha256: "a".repeat(64),
      resident_services_expected: "online", nara_service_expected: "paused",
      run_id: "qfn-followon-c0-pilot-20260915-a.resident",
      phase: "evaluation", candidate_variant: null, source_error: null,
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Resident research window" })).toBeInTheDocument(),
    );
    const verdict = screen.getByTestId("health-verdict");
    expect(verdict).toHaveAttribute("data-level", "research");
    expect(verdict).toHaveTextContent("Nara is paused for this research arm");
    expect(verdict).not.toHaveTextContent("Mia candidate");
  });

  it("labels a fresh bound lab resident evaluation as active without turning its plan into a score", async () => {
    const http = await import("../src/api/http");
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "resident", mode_source: "lab_evaluation_state",
      mode_source_sha256: "a".repeat(64),
      resident_services_expected: "online", nara_service_expected: "paused",
      run_id: "qfn-ab-lab-primary-20260915-a.resident", phase: "evaluation",
      candidate_variant: null, source_error: null,
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Resident model evaluation active" })).toBeInTheDocument());
    expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "research");
    expect(screen.getByTestId("health-verdict")).toHaveTextContent("Nara is paused");
  });

  it("shows a source-bound stable benchmark resident phase without a candidate claim", async () => {
    const http = await import("../src/api/http");
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "resident", mode_source: "stable_benchmark_state",
      mode_source_sha256: "b".repeat(64),
      resident_services_expected: "online", nara_service_expected: "paused",
      run_id: "stable-benchmark-20260916-a.resident", phase: "evaluation",
      candidate_variant: null, source_error: null,
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Stable benchmark resident arm active" })).toBeInTheDocument());
    const verdict = screen.getByTestId("health-verdict");
    expect(verdict).toHaveAttribute("data-level", "research");
    expect(verdict).toHaveTextContent("BENCHMARK RUN");
    expect(verdict).toHaveTextContent("Phase: evaluation");
    expect(verdict).toHaveTextContent("Nara is expected paused");
    expect(within(verdict).getByRole("link", { name: /View benchmark progress/ })).toHaveAttribute("href", "/benchmarks");
    expect(screen.queryByText(/Mia candidate/)).toBeNull();
  });

  it("shows a fail-closed stable benchmark lifecycle without inferring runtime expectations", async () => {
    const http = await import("../src/api/http");
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "unknown", mode_source: "stable_benchmark_state",
      mode_source_sha256: null,
      resident_services_expected: "unknown", nara_service_expected: "unknown",
      run_id: null, phase: "unexpected_phase",
      candidate_variant: null, source_error: "stable restoration proof is unavailable",
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await waitFor(() => expect(http.getModelRuntime).toHaveBeenCalled());
    await screen.findByRole("heading", { name: "Stable benchmark lifecycle needs review" });
    const verdict = screen.getByTestId("health-verdict");
    expect(verdict).toHaveTextContent("BENCHMARK NEEDS REVIEW");
    expect(verdict).toHaveTextContent("Phase: unverified");
    expect(verdict).toHaveTextContent("Runtime expectations are unknown");
    expect(verdict).not.toHaveTextContent("Resident models are expected online");
  });

  it("retains a failed stable benchmark warning across a refresh failure until a verified successor arrives", async () => {
    const http = await import("../src/api/http");
    const getRuntime = http.getModelRuntime as unknown as ReturnType<typeof vi.fn>;
    getRuntime
      .mockResolvedValueOnce({
        schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
        mode: "unknown", mode_source: "stable_benchmark_state",
        mode_source_sha256: null,
        resident_services_expected: "unknown", nara_service_expected: "unknown",
        run_id: null, phase: null, candidate_variant: null,
        source_error: "stable release selection could not be verified",
      })
      .mockRejectedValueOnce(new Error("runtime endpoint unavailable"))
      .mockResolvedValueOnce({
        schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
        mode: "resident", mode_source: "stable_benchmark_state",
        mode_source_sha256: "b".repeat(64),
        resident_services_expected: "online", nara_service_expected: "running",
        run_id: "stable-benchmark-20260916-a.resident", phase: "complete",
        candidate_variant: null, source_error: null,
      });

    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Stable benchmark lifecycle needs review" });

    await act(async () => {
      refreshPoll("model_runtime");
      await Promise.resolve();
    });
    await waitFor(() => expect(getRuntime).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("health-verdict")).toHaveTextContent("BENCHMARK NEEDS REVIEW");
    expect(screen.getByTestId("health-verdict")).toHaveTextContent("Last observed phase: unverified");
    expect(screen.getByTestId("health-verdict")).toHaveTextContent("Current runtime expectations remain unknown");
    expect(screen.getByTestId("runtime-observability-warning")).toHaveTextContent("runtime projection refresh failed");
    expect(screen.getByText(/The last stable benchmark projection could not verify/)).toBeInTheDocument();

    await act(async () => {
      refreshPoll("model_runtime");
      await Promise.resolve();
    });
    await waitFor(() => expect(getRuntime).toHaveBeenCalledTimes(3));
    expect(await screen.findByRole("heading", { name: "Stable benchmark lifecycle complete" })).toBeInTheDocument();
    expect(screen.getByTestId("health-verdict")).toHaveTextContent("BENCHMARK COMPLETE");
    expect(screen.getByTestId("health-verdict")).toHaveTextContent("Phase: complete");
    expect(screen.getByTestId("health-verdict")).not.toHaveTextContent("BENCHMARK NEEDS REVIEW");
    expect(screen.queryByText(/The last stable benchmark projection could not verify/)).toBeNull();
  });

  it("keeps an aged fail-closed benchmark projection visible as last observed", async () => {
    const http = await import("../src/api/http");
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1",
      observed_at: new Date(Date.now() - 60_000).toISOString(),
      mode: "unknown", mode_source: "stable_benchmark_state",
      mode_source_sha256: null,
      resident_services_expected: "unknown", nara_service_expected: "unknown",
      run_id: null, phase: null, candidate_variant: null,
      source_error: "stable release selection could not be verified",
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Stable benchmark lifecycle needs review" });
    const verdict = screen.getByTestId("health-verdict");
    expect(verdict).toHaveTextContent("BENCHMARK NEEDS REVIEW");
    expect(verdict).toHaveTextContent("Last observed phase: unverified");
    expect(verdict).toHaveTextContent("Current runtime expectations remain unknown");
    expect(screen.getByTestId("runtime-observability-warning")).toHaveTextContent("runtime projection stale");
  });

  it("names a registered recovery-unknown phase without treating it as a resident claim", async () => {
    const http = await import("../src/api/http");
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "unknown", mode_source: "stable_benchmark_state",
      mode_source_sha256: null,
      resident_services_expected: "unknown", nara_service_expected: "unknown",
      run_id: "stable-benchmark-20260916-a.resident", phase: "recovery_unknown",
      candidate_variant: null, source_error: "stable restoration proof is unavailable",
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await waitFor(() => expect(http.getModelRuntime).toHaveBeenCalled());
    await screen.findByRole("heading", { name: "Stable benchmark lifecycle needs review" });
    const verdict = screen.getByTestId("health-verdict");
    expect(verdict).toHaveTextContent("Phase: recovery unknown");
    expect(verdict).toHaveTextContent("Runtime expectations are unknown");
    expect(screen.queryByText("Resident serving")).toBeNull();
  });

  it("rejects an unregistered stable benchmark run identity", async () => {
    const http = await import("../src/api/http");
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "resident", mode_source: "stable_benchmark_state",
      mode_source_sha256: "b".repeat(64),
      resident_services_expected: "online", nara_service_expected: "paused",
      run_id: "qfn-lookalike.resident", phase: "evaluation",
      candidate_variant: null, source_error: null,
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await waitFor(() => expect(http.getModelRuntime).toHaveBeenCalled());
    expect(await screen.findByRole("heading", { name: "Operating mode unverified" })).toBeInTheDocument();
    expect(screen.queryByText("BENCHMARK RUN")).toBeNull();
  });

  it("withholds a lab operating-mode claim with an unbound source", async () => {
    const http = await import("../src/api/http");
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "candidate_research", mode_source: "lab_evaluation_state",
      mode_source_sha256: "unbound", resident_services_expected: "stopped",
      nara_service_expected: "paused", run_id: "qfn-ab-lab-primary-20260915-a.flash",
      phase: "evaluation", candidate_variant: null, source_error: null,
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await waitFor(() => expect(http.getModelRuntime).toHaveBeenCalled());
    await new Promise(resolve => setTimeout(resolve, 100));
    expect(screen.getByRole("heading", { name: "Operating mode unverified" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Mia model evaluation active" })).not.toBeInTheDocument();
  });

  it("accepts a fresh restored resident receipt that arrives after the UI clock tick", async () => {
    const http = await import("../src/api/http");
    let publish!: (value: unknown) => void;
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () => new Promise(resolve => { publish = resolve; }),
    );
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await waitFor(() => expect(http.getModelRuntime).toHaveBeenCalled());
    // The component sampled its 5 s clock on the initial render. The server
    // receipt is timestamped only when the delayed poll settles.
    await new Promise(resolve => setTimeout(resolve, 120));
    publish({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "resident", mode_source: "followon_evaluation_state",
      mode_source_sha256: "9".repeat(64),
      resident_services_expected: "online", nara_service_expected: "running",
      run_id: "qfn-followon-coding-temp1-20260915-b.flash",
      phase: "complete", source_error: null,
      candidate_variant: {
        spec_id: "mia-925d7be6-mtp3-reduced47k-v2opt-v1",
        spec_sha256: "e71d3134f407cad3c288c21f9485c27352676dbb7de647c5b567777256702a50",
        repository: "Mia-AiLab/Qwen3.8-Flash-Next-NVFP4",
        revision: "925d7be6c14c6c9442ef83e8f05b5a3c39304f69",
        served_model: "qwen3.8-flash-next-mia",
        image_id: "sha256:29eab5a29b765eef8b6405bbe0f2d385fc1e7b5e3c7ae18ae70382a68a0a2201",
        model_artifact_sha256: "a40ce50173dd3aff54da88503894967e5248bbb927f9e4a91eff5a6a7270c168",
        profile: "MIA-MTP3-REDUCED47K-V2-FULL4-MODE0-32K",
        configured_max_context_tokens: 32768,
        configured_mtp_speculative_tokens: 3,
        configured_kv_cache_memory_bytes: 2147483648,
        source: "registered_plan_and_controller_state",
        image_evidence: "registered_source_only",
        promotion_authorized: false,
      },
    });
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Resident serving" })).toBeInTheDocument(),
      { timeout: 900 },
    );
  });

  it("withholds resident mode from a stale follow-on receipt", async () => {
    const http = await import("../src/api/http");
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1",
      observed_at: new Date(Date.now() - 60_000).toISOString(),
      mode: "resident", mode_source: "followon_evaluation_state",
      mode_source_sha256: "9".repeat(64),
      resident_services_expected: "online", nara_service_expected: "running",
      run_id: "qfn-followon-coding-temp1-20260915-b.flash",
      phase: "complete", candidate_variant: null, source_error: null,
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await waitFor(() => expect(http.getModelRuntime).toHaveBeenCalled());
    await new Promise(resolve => setTimeout(resolve, 100));
    expect(screen.getByRole("heading", { name: "Operating mode unverified" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Resident serving" })).not.toBeInTheDocument();
  });

  it("withholds resident mode when the follow-on source SHA is absent", async () => {
    const http = await import("../src/api/http");
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "resident", mode_source: "followon_evaluation_state",
      mode_source_sha256: null,
      resident_services_expected: "online", nara_service_expected: "running",
      run_id: "qfn-followon-coding-temp1-20260915-b.flash",
      phase: "complete", candidate_variant: null, source_error: null,
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await waitFor(() => expect(http.getModelRuntime).toHaveBeenCalled());
    await new Promise(resolve => setTimeout(resolve, 100));
    expect(screen.getByRole("heading", { name: "Operating mode unverified" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Resident serving" })).not.toBeInTheDocument();
  });

  it("does not trust a runtime receipt that carries a source error", async () => {
    const http = await import("../src/api/http");
    D.samples = D.samples.map((sample) => ({ ...sample, vllm: null }));
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1",
      observed_at: new Date().toISOString(),
      mode: "candidate_research",
      mode_source: "qualification_state",
      mode_source_sha256: "d".repeat(64),
      resident_services_expected: "stopped",
      nara_service_expected: "paused",
      run_id: "qfn-c0-error",
      phase: "probes",
      source_error: "projection failed",
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);

    await waitFor(() =>
      expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "down"),
    );
    expect(screen.getByTestId("health-verdict")).not.toHaveTextContent("RESEARCH WINDOW");
  });

  it("shows the controller-bound Mia variant during an extended evaluation window", async () => {
    const http = await import("../src/api/http");
    D.samples = D.samples.map((sample) => ({ ...sample, vllm: null }));
    const inventoryMock = http.getServedModels as unknown as ReturnType<typeof vi.fn>;
    inventoryMock.mockReset().mockResolvedValue({
      gemma: { url: "http://localhost:8000", model: "gemma-4-26b-a4b", error: null },
      qwen: { url: "http://localhost:8001", model: "qwen3.8-27b-nvfp4-mtp", error: null },
    });
    inventoryMock.mockResolvedValueOnce({
      gemma: modelInventoryRow({ model: null, deployment_role: "production_resident",
        service_status: "offline", models_endpoint_status: "unreachable", metrics_endpoint_status: "unreachable",
        activity_status: "unknown", identity_status: "unknown", metrics: null }),
      qwen: modelInventoryRow({ model: null, deployment_role: "production_resident",
        service_status: "offline", models_endpoint_status: "unreachable", metrics_endpoint_status: "unreachable",
        activity_status: "unknown", identity_status: "unknown", metrics: null }),
      flash: modelInventoryRow({ url: "http://127.0.0.1:8012", model: "qwen3.8-flash-next-mia",
        configured_model: "qwen3.8-flash-next", deployment_role: "research_candidate",
        benchmark_cohort: "flash", service_status: "online", identity_status: "match" }),
    });
    const runtimeMock = http.getModelRuntime as unknown as ReturnType<typeof vi.fn>;
    runtimeMock.mockReset().mockResolvedValue({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "unknown", mode_source: "none", mode_source_sha256: null,
      resident_services_expected: "unknown", nara_service_expected: "unknown",
      run_id: null, phase: null, source_error: null,
    });
    runtimeMock.mockResolvedValueOnce({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "candidate_research", mode_source: "extended_evaluation_state",
      mode_source_sha256: "a".repeat(64), resident_services_expected: "stopped",
      nara_service_expected: "paused", run_id: "qfn-ab-mia-control.flash",
      phase: "evaluation", source_error: null,
      candidate_variant: {
        spec_id: "mia-925d7be6-c0-s1",
        spec_sha256: "dde4fe1f72cf91de92089a95748cee1f6a8204e351d517aa0ae46d8d27122857",
        repository: "Mia-AiLab/Qwen3.8-Flash-Next-NVFP4",
        revision: "925d7be6c14c6c9442ef83e8f05b5a3c39304f69",
        served_model: "qwen3.8-flash-next-mia",
        image_id: "sha256:da68dd27a8ef1dadd0f380178a51f0a0671dc4235933ea1ae89fdaf66295ec72",
        model_artifact_sha256: "a40ce50173dd3aff54da88503894967e5248bbb927f9e4a91eff5a6a7270c168",
        profile: "C0-MIA-S1", source: "registered_plan_and_controller_state",
        image_evidence: "bound_live_container", promotion_authorized: false,
      },
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "research"),
    );
    expect(screen.getByRole("heading", { name: "Mia candidate research window" })).toBeInTheDocument();
    expect(screen.getByText("Mia-AiLab/Qwen3.8-Flash-Next-NVFP4")).toBeInTheDocument();
    expect(screen.getByTestId("flash-selected-variant")).toHaveTextContent("live cgroup-bind receipt");
  });

  it("rejects an extended mode claim with a qualification or malformed pair ID", async () => {
    const http = await import("../src/api/http");
    D.samples = D.samples.map((sample) => ({ ...sample, vllm: null }));
    const runtimeMock = http.getModelRuntime as unknown as ReturnType<typeof vi.fn>;
    runtimeMock.mockReset().mockResolvedValue({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "unknown", mode_source: "none", mode_source_sha256: null,
      resident_services_expected: "unknown", nara_service_expected: "unknown",
      run_id: null, phase: null, source_error: null,
    });
    runtimeMock.mockResolvedValueOnce({
      schema_version: "model-runtime/v1", observed_at: new Date().toISOString(),
      mode: "candidate_research", mode_source: "extended_evaluation_state",
      mode_source_sha256: "a".repeat(64), resident_services_expected: "stopped",
      nara_service_expected: "paused", run_id: "qfn-mia-c0-old",
      phase: "evaluation", source_error: null,
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "down"),
    );
    expect(screen.getByTestId("health-verdict")).not.toHaveTextContent("RESEARCH WINDOW");
  });

  it("does not excuse a resident outage from an unbound runtime payload", async () => {
    const http = await import("../src/api/http");
    D.samples = D.samples.map((sample) => ({ ...sample, vllm: null }));
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1",
      observed_at: new Date().toISOString(),
      mode: "candidate_research",
      mode_source: "none",
      mode_source_sha256: null,
      resident_services_expected: "stopped",
      nara_service_expected: "paused",
      run_id: null,
      phase: null,
      source_error: null,
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);

    await waitFor(() =>
      expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "down"),
    );
    const verdict = screen.getByTestId("health-verdict");
    expect(verdict).toHaveAttribute("data-level", "down");
    expect(verdict).toHaveTextContent("Gemma model server unreachable");
  });

  it("expires a formerly bound research-window receipt instead of retaining planned-stop semantics", async () => {
    const http = await import("../src/api/http");
    D.samples = D.samples.map((sample) => ({ ...sample, vllm: null }));
    (http.getModelRuntime as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      schema_version: "model-runtime/v1",
      observed_at: new Date(Date.now() - 60_000).toISOString(),
      mode: "candidate_research",
      mode_source: "qualification_state",
      mode_source_sha256: "b".repeat(64),
      resident_services_expected: "stopped",
      nara_service_expected: "paused",
      run_id: "qfn-c0-stale",
      phase: "probes",
      source_error: null,
    });
    render(<MemoryRouter><Pulse /></MemoryRouter>);

    await waitFor(() =>
      expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "down"),
    );
    const verdict = screen.getByTestId("health-verdict");
    expect(verdict).toHaveAttribute("data-level", "down");
    expect(verdict).not.toHaveTextContent("RESEARCH WINDOW");
  });
});


describe("Atlas Now intent boundary", () => {
  it("does not mount the potentially expensive queue on arrival, including a queue deep link", async () => {
    render(<MemoryRouter initialEntries={["/#lab-queue"]}><Pulse /></MemoryRouter>);
    await screen.findByTestId("now-board");
    expect(screen.getByRole("heading", { name: "Now", level: 1 })).toBeInTheDocument();
    expect(getLabTodo).not.toHaveBeenCalled();
    expect(screen.queryByTestId("lab-todo")).not.toBeInTheDocument();
    expect(screen.getByTestId("pulse-queue-not-read")).toHaveTextContent(/not been loaded/i);
    fireEvent.click(screen.getByRole("button", { name: "Load lab queue" }));
    await screen.findByTestId("lab-todo");
    await waitFor(() => expect(getLabTodo).toHaveBeenCalledTimes(1));
  });

  it("keeps research, engineering and human requests accessible as distinct choices", () => {
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "Explore research" })).toHaveAttribute("href", "/ladder");
    expect(screen.getByRole("link", { name: "Review delivery and readiness" })).toHaveAttribute("href", "/development");
    expect(screen.getByTestId("pulse-human-requests")).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Recorded human requests"));
    expect(screen.getByTestId("pulse-human-requests")).toHaveAttribute("open");
  });
});


describe("Pulse telemetry evidence boundary", () => {
  it.each([true, false])("zero samples with connected=%s is unknown, not a model outage", (connected) => {
    D.samples = [];
    D.connected = connected;
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    const page = screen.getByTestId("pulse-page");
    const verdict = screen.getByTestId("health-verdict");
    expect(verdict).toHaveAttribute("data-level", "unknown");
    expect(verdict).toHaveTextContent("UNKNOWN");
    expect(verdict).toHaveTextContent(connected ? "Awaiting telemetry" : "Telemetry disconnected");
    expect(verdict).not.toHaveTextContent(/DOWN|unreachable|telemetry fresh; Gemma metrics present/);
    expect(screen.getByTestId("gemma-4-26b-a4b-status")).toHaveTextContent("unknown");
    expect(screen.getByTestId("qwen3.6-27b-nvfp4-mtp-status")).toHaveTextContent("unknown");
    expect(page).toHaveTextContent(
      connected
        ? "Awaiting first telemetry sample — current model health not observed."
        : "Telemetry disconnected — model health not observed.",
    );
    expect(page).not.toHaveTextContent(
      /● (?:up|down)|\/metrics unavailable|endpoint unreachable|server may be down/i,
    );
  });

  it("a buffer containing only unsupported scalar/null/object entries is still unobserved", () => {
    D.samples = [null, 17, "bad", {}, []] as unknown as TelemetrySample[];
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "unknown");
    expect(screen.getByTestId("health-verdict")).not.toHaveTextContent(/DOWN|unreachable/);
    expect(screen.getByTestId("gemma-4-26b-a4b-status")).toHaveTextContent("unknown");
    expect(screen.getByTestId("pulse-page")).not.toHaveTextContent(
      /● (?:up|down)|\/metrics unavailable|endpoint unreachable|server may be down/i,
    );
  });

  it.each([true, false])("disconnection labels retained metrics-present=%s evidence as historical", (present) => {
    D.samples = baselineTelemetry.map((sample) => ({ ...sample, vllm: present ? sample.vllm : null }));
    D.connected = false;
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    const page = screen.getByTestId("pulse-page");
    const verdict = screen.getByTestId("health-verdict");
    expect(verdict).toHaveAttribute("data-level", "unknown");
    expect(verdict).toHaveTextContent("Telemetry disconnected");
    expect(verdict).toHaveTextContent(present ? "Last samples: Gemma metrics present" : "Last samples: Gemma metrics unavailable");
    expect(verdict).not.toHaveTextContent(/DOWN|Gemma model server unreachable/);
    expect(screen.getByTestId("gemma-4-26b-a4b-status")).toHaveTextContent("historical");
    expect(screen.getByTestId("qwen3.6-27b-nvfp4-mtp-status")).toHaveTextContent("historical");
    expect(page).toHaveTextContent(
      present
        ? "Historical telemetry — retained samples contained metrics."
        : "Historical telemetry — retained samples did not contain metrics.",
    );
    expect(page).not.toHaveTextContent(
      /● (?:up|down)|\/metrics unavailable|endpoint unreachable|server may be down/i,
    );
  });

  it("keeps a connected trailing scrape miss stale instead of inventing an outage", () => {
    D.samples = [
      baselineTelemetry[0],
      { ...baselineTelemetry[1], timestamp: new Date().toISOString(), vllm: null },
    ];
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    expect(screen.getByTestId("gemma-4-26b-a4b-status")).toHaveTextContent("stale");
    expect(screen.getByTestId("gemma-4-26b-a4b-stale-note")).toHaveTextContent(
      "stale telemetry",
    );
  });

  it("labels connected retained samples as historical once their timestamp is stale", () => {
    D.samples = baselineTelemetry.map((sample) => ({
      ...sample,
      timestamp: new Date(Date.now() - 30_000).toISOString(),
    }));
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    const page = screen.getByTestId("pulse-page");
    expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "unknown");
    expect(screen.getByTestId("health-verdict")).toHaveTextContent("Telemetry stale");
    expect(screen.getByTestId("gemma-4-26b-a4b-status")).toHaveTextContent("historical");
    expect(screen.getByTestId("qwen3.6-27b-nvfp4-mtp-status")).toHaveTextContent("historical");
    expect(page).not.toHaveTextContent(
      /● (?:up|down)|\/metrics unavailable|endpoint unreachable|server may be down/i,
    );
  });

  it.each(["not-a-timestamp", new Date(Date.now() + 60_000).toISOString()])(
    "does not present timestamp %s as fresh current model evidence",
    (timestamp) => {
      D.samples = baselineTelemetry.map((sample) => ({ ...sample, timestamp }));
      render(<MemoryRouter><Pulse /></MemoryRouter>);
      const page = screen.getByTestId("pulse-page");
      expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "unknown");
      expect(screen.getByTestId("health-verdict")).toHaveTextContent("Telemetry time unknown");
      expect(screen.getByTestId("gemma-4-26b-a4b-status")).toHaveTextContent("unknown");
      expect(page).not.toHaveTextContent(
        /● (?:up|down)|\/metrics unavailable|endpoint unreachable|server may be down/i,
      );
    },
  );

  it("preserves connected supplied missing-metrics failures", () => {
    D.samples = baselineTelemetry.map((sample) => ({ ...sample, timestamp: new Date().toISOString(), vllm: null }));
    render(<MemoryRouter><Pulse /></MemoryRouter>);
    expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "down");
    expect(screen.getByTestId("health-verdict")).toHaveTextContent("Gemma model server unreachable");
    expect(screen.getByTestId("gemma-4-26b-a4b-status")).toHaveTextContent("down");
    expect(screen.getByText(/\/metrics unavailable/)).toBeInTheDocument();
  });

  it("preserves connected supplied read errors and retains them historically on disconnection", () => {
    D.samples = baselineTelemetry.map((sample) => ({ ...sample, timestamp: new Date().toISOString(), read_errors: { psutil: "fixture failure" } }));
    const view = render(<MemoryRouter><Pulse /></MemoryRouter>);
    expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "degraded");
    expect(screen.getByTestId("health-verdict")).toHaveTextContent("read errors: psutil");
    D.connected = false;
    view.rerender(<MemoryRouter><Pulse /></MemoryRouter>);
    expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "unknown");
    expect(screen.getByTestId("health-verdict")).toHaveTextContent("Last read errors: psutil");
  });

  it("accepts a fresh frame arriving between coarse page-clock ticks", () => {
    const first = Date.now();
    const clock = vi.spyOn(Date, "now").mockReturnValue(first);
    try {
      D.samples = baselineTelemetry.map((sample) => ({ ...sample, timestamp: new Date(first).toISOString() }));
      const view = render(<MemoryRouter><Pulse /></MemoryRouter>);
      expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "healthy");
      // No interval advances: useNow still holds first, while a new frame arrives.
      clock.mockReturnValue(first + 1000);
      D.samples = baselineTelemetry.map((sample) => ({ ...sample, timestamp: new Date(first + 1000).toISOString(), vllm: null }));
      view.rerender(<MemoryRouter><Pulse /></MemoryRouter>);
      expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "down");
      expect(screen.getByTestId("gemma-4-26b-a4b-status")).toHaveTextContent("down");
    } finally { clock.mockRestore(); }
  });

  it("updates healthy to unobserved and then to a supplied failure without retaining a false status", () => {
    D.samples = baselineTelemetry.map((sample) => ({ ...sample, timestamp: new Date().toISOString() }));
    const view = render(<MemoryRouter><Pulse /></MemoryRouter>);
    expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "healthy");
    D.samples = [];
    view.rerender(<MemoryRouter><Pulse /></MemoryRouter>);
    expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "unknown");
    D.samples = baselineTelemetry.map((sample) => ({ ...sample, timestamp: new Date().toISOString(), vllm: null }));
    view.rerender(<MemoryRouter><Pulse /></MemoryRouter>);
    expect(screen.getByTestId("health-verdict")).toHaveAttribute("data-level", "down");
  });
});
