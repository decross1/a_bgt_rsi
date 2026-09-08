// Pulse (/) — the S1 home page: HealthVerdict hero + the ONE merged now-card
// (NowBoard + headline strip) + OweStrip + LastCycleLine + HealthStrip + the
// two ModelServerCards + the launch disclosure. Route-level smoke against
// mocked feeds: every surface mounts, the owed row links into the dossier
// reader, and the render stays console-clean (the route-sweep bar).
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
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

import Pulse, { stripMonitorChurn } from "../src/routes/Pulse";
import { getLabTodo } from "../src/api/http";
import type { MonitorResponse } from "../src/types/activity";

const baselineTelemetry = D.samples;

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

    fireEvent.click(screen.getByText("Review recorded requests"));
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

    // The demoted mass is INFORMATION, not a queue: one muted line, and the
    // owed count stays at the one real gate item.
    await waitFor(() =>
      expect(screen.getByTestId("owe-below-bar")).toHaveTextContent(
        "1 below-bar finding demoted to the ladder",
      ),
    );
    expect(screen.getByTestId("owe-count")).toHaveTextContent("1");

    expect(getLabTodo).not.toHaveBeenCalled();
    const labQueue = screen.getByTestId("pulse-lab-queue");
    fireEvent.click(within(labQueue).getByText("Lab queue"));
    fireEvent.click(
      within(labQueue).getByRole("button", { name: "Load lab queue" }),
    );
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
      <MemoryRouter>
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
      <MemoryRouter>
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

  it("malformed history rows stay incomplete instead of becoming an empty history claim", async () => {
    const http = await import("../src/api/http");
    vi.mocked(http.getCoordinatorCycles).mockResolvedValueOnce({
      cycles: [null] as never,
    });
    vi.mocked(http.getIterations).mockResolvedValueOnce({
      iterations: [42] as never,
    });
    render(
      <MemoryRouter>
        <Pulse />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("pulse-cycles-malformed")).toHaveTextContent(
        /last recorded cycle is unknown/i,
      ),
    );
    await waitFor(() =>
      expect(screen.getByTestId("pulse-iterations-malformed")).toHaveTextContent(
        /distribution is incomplete/i,
      ),
    );
    expect(screen.getByTestId("pulse-history-summary")).toHaveTextContent(
      /recorded history is incomplete/i,
    );
    expect(screen.queryByTestId("last-cycle-empty")).toBeNull();
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
    await waitFor(() =>
      expect(
        within(screen.getByTestId("pulse-runtime-evidence")).getAllByText(
          "unknown",
          { selector: "h2" },
        ),
      ).toHaveLength(2),
    );
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
    fireEvent.click(screen.getByText("Review recorded requests"));
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
    expect(verdict).not.toHaveTextContent(/DOWN|unreachable|all systems nominal/);
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
