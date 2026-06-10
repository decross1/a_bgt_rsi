// PAGE A — active-worker + synthetic-inference + /activity layout tests.
// The old AgentMonitorPanel is split: ActiveWorkersPanel is the HERO live
// view (rich rows w/ `detail` + live elapsed + cpu/rss), SyntheticInferencePanel
// is a subordinate <details> disclosure that still carries the amber
// "synthetic — needs worker_activity.jsonl" marker so its numbers are never
// read as measured. Activity.tsx inverts the page: workers HERO, history graph
// demoted into a collapsible disclosure.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import ActiveRunCard from "../src/components/ActiveRunCard";
import ActiveWorkersPanel from "../src/components/ActiveWorkersPanel";
import LiveCallsBanner from "../src/components/LiveCallsBanner";
import SyntheticInferencePanel from "../src/components/SyntheticInferencePanel";
import { getActiveRun } from "../src/api/activity";
import Activity from "../src/routes/Activity";
import {
  ACTIVE_RUN_FIXTURE,
  MONITOR_FIXTURE,
  MONITOR_FIXTURE_IDLE,
  MONITOR_FIXTURE_LIVE_CALLS,
  MONITOR_FIXTURE_REAL_INFERENCE,
  MONITOR_FIXTURE_REAL_INFERENCE_NULL_ETA,
  MONITOR_FIXTURE_UNAVAILABLE,
  GRAPH_FIXTURE,
} from "../src/fixtures/activity";
import { ACTIVE_FIXTURE } from "../src/fixtures/loop_v0";
import {
  ACTIVE_RUN_FIXTURE as COORDINATOR_ACTIVE_FIXTURE,
  COORDINATOR_CYCLES_FIXTURE,
} from "../src/fixtures/coordinator";
import type { ActiveRunsResponse, LiveCalls } from "../src/types/activity";
import type {
  CoordinatorActiveRun,
  CoordinatorCycle,
} from "../src/types/schemas";

// Grouped live-calls payload — CONSTRUCTED (explicitly synthetic counts/ids;
// the tag/model/backend strings are the live names: skeptic_attack /
// subagent.* tags, qwen3.6-27b-nvfp4-mtp + gemma-4-26b-a4b served models,
// vllm-qwen/vllm-gemma registry names). Mirrors _live_calls()'s additive
// groups[]: backend/run_id are PASSTHROUGH and null on pre-EMIT rows.
const GROUPED_LIVE_CALLS: LiveCalls = {
  active: true,
  count: 19,
  window_s: 60,
  calls_per_s: 0.32,
  last_call_at: "2026-06-10T08:00:06.4Z",
  caller_tags: [
    { tag: "skeptic_attack", count: 12 },
    { tag: "hypothesize", count: 4 },
  ],
  model: "qwen3.6-27b-nvfp4-mtp",
  groups: [
    {
      tag: "skeptic_attack",
      model: "qwen3.6-27b-nvfp4-mtp",
      backend: "vllm-qwen",
      run_id: null,
      count: 12,
      last_call_at: "2026-06-10T08:00:06.4Z",
    },
    {
      tag: "hypothesize",
      model: "gemma-4-26b-a4b",
      backend: "vllm-gemma",
      run_id: "loop_v0_2026-06-10_001",
      count: 4,
      last_call_at: "2026-06-10T08:00:05.0Z",
    },
    {
      // Pre-EMIT row: backend null (passthrough) — the row must render NO
      // backend chip, never one guessed from the model name.
      tag: "nara.run_iteration",
      model: "gemma-4-26b-a4b",
      backend: null,
      run_id: null,
      count: 3,
      last_call_at: "2026-06-10T08:00:01.0Z",
    },
  ],
  groups_truncated: true,
  other_count: 7,
};

// @xyflow/react reaches for ResizeObserver on mount; jsdom lacks it.
beforeAll(() => {
  if (typeof globalThis.ResizeObserver === "undefined") {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  }
});

describe("ActiveWorkersPanel (HERO)", () => {
  it("renders rich active-worker rows with detail and live elapsed", () => {
    render(<ActiveWorkersPanel data={MONITOR_FIXTURE} />);
    const row = screen.getByTestId("worker-seq-1");
    expect(row).toHaveTextContent("summarize_paper");
    expect(row).toHaveTextContent("12.5%");
    expect(row).toHaveTextContent("660 MB");
    // "what it's doing" — the human-readable orchestrator detail.
    expect(screen.getByTestId("worker-detail-seq-1")).toHaveTextContent(
      "spawning worker process for 2605.21448",
    );
    // LIVE elapsed cell is present and formatted (the row carries a 2026-05
    // timestamp, so elapsed is a large but well-formed value, never "—").
    const el = screen.getByTestId("worker-elapsed-seq-1");
    expect(el.textContent).not.toBe("—");
  });

  it("renders an empty state when no workers are in flight", () => {
    render(<ActiveWorkersPanel data={MONITOR_FIXTURE_IDLE} />);
    const empty = screen.getByTestId("active-workers-empty");
    expect(empty).toHaveTextContent("No workers in flight.");
  });

  it("empty state names live sub-agent call groups instead of reading quiet", () => {
    // Sub-agents (caller_tag "subagent.*") bypass orchestrator worker
    // dispatch — zero rows in this table while they call is "no ORCHESTRATOR
    // workers", not "nothing running". CONSTRUCTED groups; the tags are the
    // live sub-agent tags (subagent.finding_skeptic_1/2).
    render(
      <ActiveWorkersPanel
        data={{
          ...MONITOR_FIXTURE_IDLE,
          live_calls: {
            active: true,
            count: 9,
            window_s: 60,
            calls_per_s: 0.15,
            last_call_at: "2026-06-10T08:00:06.4Z",
            caller_tags: [{ tag: "subagent.finding_skeptic_1", count: 5 }],
            model: "qwen3.6-27b-nvfp4-mtp",
            groups: [
              {
                tag: "subagent.finding_skeptic_1",
                model: "qwen3.6-27b-nvfp4-mtp",
                backend: "vllm-qwen",
                run_id: null,
                count: 5,
                last_call_at: "2026-06-10T08:00:06.4Z",
              },
              {
                tag: "subagent.finding_skeptic_2",
                model: "qwen3.6-27b-nvfp4-mtp",
                backend: "vllm-qwen",
                run_id: null,
                count: 3,
                last_call_at: "2026-06-10T08:00:05.0Z",
              },
              {
                // NOT a sub-agent group — must not inflate the count.
                tag: "skeptic_attack",
                model: "qwen3.6-27b-nvfp4-mtp",
                backend: "vllm-qwen",
                run_id: null,
                count: 1,
                last_call_at: "2026-06-10T08:00:04.0Z",
              },
            ],
          },
        }}
      />,
    );
    expect(screen.getByTestId("active-workers-empty")).toHaveTextContent(
      "No orchestrator workers in flight — 2 sub-agent call groups active (see live calls)",
    );
  });

  it("renders an unavailable notice when the monitor is absent", () => {
    render(<ActiveWorkersPanel data={MONITOR_FIXTURE_UNAVAILABLE} />);
    expect(screen.getByTestId("active-workers-unavailable")).toHaveTextContent(
      /unavailable/i,
    );
  });
});

describe("SyntheticInferencePanel (subordinate)", () => {
  it("keeps the synthetic marker behind a disclosure", () => {
    render(<SyntheticInferencePanel data={MONITOR_FIXTURE} />);
    const block = screen.getByTestId("synthetic-inference");
    // It is a <details> disclosure — subordinate, not co-equal.
    expect(block.tagName.toLowerCase()).toBe("details");
    // The amber not-measured marker is preserved verbatim.
    const marker = screen.getByTestId("synthetic-marker");
    expect(marker).toHaveTextContent(/synthetic/i);
    expect(marker).toHaveTextContent(/worker_activity\.jsonl/);
    expect(marker).toHaveTextContent(/primary-session/);
    // The synthetic numbers live inside the flagged block.
    expect(block).toHaveTextContent("312/512");
    expect(screen.getByTestId("synthetic-worker-seq-1")).toBeInTheDocument();
  });

  it("renders REAL inference with NO synthetic marker when synthetic:false", () => {
    // worker_activity.jsonl had recent rows -> synthetic:false. The amber
    // marker must NOT appear over real measured data (CLAUDE.md rule 4).
    render(<SyntheticInferencePanel data={MONITOR_FIXTURE_REAL_INFERENCE} />);
    const block = screen.getByTestId("synthetic-inference");
    expect(block).toHaveAttribute("data-synthetic", "false");
    // No amber "synthetic — needs ..." marker over real data.
    expect(screen.queryByTestId("synthetic-marker")).toBeNull();
    // The live measured row + tok/s are rendered.
    expect(screen.getByTestId("live-worker-t/a")).toHaveTextContent("220/512");
    expect(block).toHaveTextContent("44.0");
  });

  it("renders a bare dash (not 'n/as') when a real row's eta_s is null", () => {
    // Producer writes eta_s=null when tok_per_s is 0. The live panel must show a
    // bare "—" for that cell, never "n/as" (fmt(null)+"s").
    render(
      <SyntheticInferencePanel data={MONITOR_FIXTURE_REAL_INFERENCE_NULL_ETA} />,
    );
    const row = screen.getByTestId("live-worker-t/z");
    expect(row).toHaveTextContent("0/512");
    expect(row.textContent).toContain("—");
    expect(row.textContent).not.toContain("n/as");
  });

  it("KEEPS the synthetic marker when synthetic:true (fixture)", () => {
    render(<SyntheticInferencePanel data={MONITOR_FIXTURE} />);
    expect(screen.getByTestId("synthetic-inference")).toHaveAttribute(
      "data-synthetic",
      "true",
    );
    expect(screen.getByTestId("synthetic-marker")).toBeInTheDocument();
  });
});

describe("ActiveRunCard (HERO)", () => {
  it("renders nothing when data is null (no run in flight)", () => {
    const { container } = render(<ActiveRunCard data={null} />);
    expect(
      container.querySelector('[data-testid="active-run-card"]'),
    ).toBeNull();
  });

  it("renders label, kind, step and progress when a run is present", () => {
    render(<ActiveRunCard data={ACTIVE_RUN_FIXTURE} />);
    const card = screen.getByTestId("active-run-card");
    expect(card).toHaveTextContent("exp003 paraphrase probe");
    expect(card).toHaveTextContent("experiment");
    expect(screen.getByTestId("active-run-step")).toHaveTextContent(
      "retrieve_literature",
    );
    expect(screen.getByTestId("active-run-progress")).toHaveTextContent(
      "3/10 papers",
    );
    // The narration + model surface too.
    expect(screen.getByTestId("active-run-narration")).toHaveTextContent(
      /scoring candidate seeds/i,
    );
    expect(screen.getByTestId("active-run-model")).toHaveTextContent(
      "gemma-4-26b-a4b",
    );
    // Live elapsed cell is present and formatted (well-formed, never "—").
    expect(screen.getByTestId("active-run-elapsed").textContent).not.toBe("—");
  });
});

describe("LiveCallsBanner", () => {
  it("renders recent wrapper-call activity when active", () => {
    render(<LiveCallsBanner data={MONITOR_FIXTURE_LIVE_CALLS.live_calls!} />);
    const banner = screen.getByTestId("live-calls-banner");
    expect(banner).toHaveTextContent(/live/i);
    expect(banner).toHaveTextContent("nara.run_iteration");
    expect(banner).toHaveTextContent("fake-model");
  });

  it("FALLBACK: groups absent (older backend) keeps the aggregate line, no rows", () => {
    // MONITOR_FIXTURE_LIVE_CALLS predates the 2026-06-10 EMIT — no groups[].
    render(<LiveCallsBanner data={MONITOR_FIXTURE_LIVE_CALLS.live_calls!} />);
    expect(screen.queryByTestId("live-call-groups")).toBeNull();
    expect(screen.queryByTestId("live-call-groups-truncated")).toBeNull();
  });

  it("renders one row per group: tag · ×count · model", () => {
    render(<LiveCallsBanner data={GROUPED_LIVE_CALLS} />);
    const rows = screen.getByTestId("live-call-groups");
    const row0 = screen.getByTestId("live-call-group-0");
    expect(row0).toHaveTextContent("skeptic_attack");
    expect(row0).toHaveTextContent("×12");
    expect(row0).toHaveTextContent("qwen3.6-27b-nvfp4-mtp");
    const row1 = screen.getByTestId("live-call-group-1");
    expect(row1).toHaveTextContent("hypothesize");
    expect(row1).toHaveTextContent("×4");
    expect(row1).toHaveTextContent("gemma-4-26b-a4b");
    expect(rows.querySelectorAll('[data-testid^="live-call-group-"]').length)
      .toBeGreaterThanOrEqual(3);
    // The grouped render replaces the aggregate top-model label (the
    // one-model-label bug this fixes), but the live header line stays.
    expect(screen.getByTestId("live-calls-banner")).toHaveTextContent(
      "19 calls in last 60s",
    );
  });

  it("backend chip takes its tone from roles.ts and is ABSENT on a null backend", () => {
    render(<LiveCallsBanner data={GROUPED_LIVE_CALLS} />);
    // vllm-qwen -> sky; vllm-gemma -> emerald.
    expect(
      screen.getByTestId("live-call-group-backend-0").className,
    ).toContain("sky");
    expect(screen.getByTestId("live-call-group-backend-0")).toHaveTextContent(
      "vllm-qwen",
    );
    expect(
      screen.getByTestId("live-call-group-backend-1").className,
    ).toContain("emerald");
    // Group 2 carried backend:null (pre-EMIT row) — no chip, never a guess
    // from the model name.
    expect(screen.queryByTestId("live-call-group-backend-2")).toBeNull();
  });

  it("run chip links a present run_id; null run_id reads quiet 'unregistered'", () => {
    render(<LiveCallsBanner data={GROUPED_LIVE_CALLS} />);
    const link = screen.getByTestId("live-call-group-run-1");
    expect(link.tagName.toLowerCase()).toBe("a");
    expect(link).toHaveAttribute("href", "#run-loop_v0_2026-06-10_001");
    expect(link).toHaveTextContent("loop_v0_2026-06-10_001");
    // Unregistered rows: quiet zinc chip, not red, not a link.
    const unreg = screen.getByTestId("live-call-group-unregistered-0");
    expect(unreg).toHaveTextContent(/unregistered/i);
    expect(unreg.className).toContain("zinc");
    expect(unreg.className).not.toContain("red");
  });

  it("shows '+N more calls' when groups_truncated", () => {
    render(<LiveCallsBanner data={GROUPED_LIVE_CALLS} />);
    expect(screen.getByTestId("live-call-groups-truncated")).toHaveTextContent(
      "+7 more calls",
    );
  });

  it("omits the truncation line when groups_truncated is false", () => {
    render(
      <LiveCallsBanner
        data={{
          ...GROUPED_LIVE_CALLS,
          groups_truncated: false,
          other_count: 0,
        }}
      />,
    );
    expect(screen.queryByTestId("live-call-groups-truncated")).toBeNull();
  });

  it("renders nothing when not active", () => {
    const { container } = render(
      <LiveCallsBanner
        data={{
          active: false,
          count: 0,
          window_s: 15,
          calls_per_s: 0,
          last_call_at: null,
          caller_tags: [],
          model: null,
        }}
      />,
    );
    expect(
      container.querySelector('[data-testid="live-calls-banner"]'),
    ).toBeNull();
  });
});

describe("getActiveRun (api)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("returns null on 204 (no run in flight)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ status: 204, ok: false } as Response),
    );
    await expect(getActiveRun()).resolves.toBeNull();
    vi.unstubAllGlobals();
  });

  it("returns the parsed object on 200", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 200,
        ok: true,
        json: async () => ACTIVE_RUN_FIXTURE,
      } as Response),
    );
    await expect(getActiveRun()).resolves.toMatchObject({
      run_id: ACTIVE_RUN_FIXTURE.run_id,
    });
    vi.unstubAllGlobals();
  });

  it("throws on a 500 error path (corrupt active_run.json)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 500,
        ok: false,
        statusText: "Internal Server Error",
        json: async () => ({ detail: "active_run unreadable: ..." }),
      } as Response),
    );
    await expect(getActiveRun()).rejects.toThrow(/500/);
    vi.unstubAllGlobals();
  });
});

describe("Activity layout (workers HERO, graph demoted)", () => {
  afterEach(() => vi.restoreAllMocks());

  // Inject all three fixtures (graph + monitor + iteration) so the page is
  // fully static — no self-polling — and the idle gate reads the injected
  // iteration. `iteration` defaults to null (idle) to match the prior
  // behavior where getActiveIteration was stubbed to null.
  function renderActivity(
    monitor = MONITOR_FIXTURE,
    iteration: typeof ACTIVE_FIXTURE | null = null,
    activeRun: typeof ACTIVE_RUN_FIXTURE | null = null,
    coordinatorActive: CoordinatorActiveRun | null = null,
    coordinatorCycles: CoordinatorCycle[] = [],
    activeRuns: ActiveRunsResponse | null = null,
  ) {
    return render(
      <MemoryRouter>
        <Activity
          initialGraph={GRAPH_FIXTURE}
          initialMonitor={monitor}
          initialIteration={iteration}
          initialActiveRun={activeRun}
          initialActiveRuns={activeRuns}
          initialCoordinatorActive={coordinatorActive}
          initialCoordinatorCycles={coordinatorCycles}
        />
      </MemoryRouter>,
    );
  }

  it("renders the HERO active-now section with the worker panel", () => {
    renderActivity();
    const hero = screen.getByTestId("active-now");
    expect(within(hero).getByTestId("active-workers-panel")).toBeInTheDocument();
    // No idle empty-state while a worker is in flight.
    expect(screen.queryByTestId("activity-idle-empty")).toBeNull();
  });

  it("shows the idle empty-state with last-activity when no workers run", () => {
    renderActivity(MONITOR_FIXTURE_IDLE);
    const idle = screen.getByTestId("activity-idle-empty");
    expect(idle).toHaveTextContent(/No agents active/i);
    expect(idle).toHaveTextContent(/last activity/i);
  });

  it("hides the idle empty-state while an iteration runs with zero workers", () => {
    // The false-idle case: an orchestrator iteration IS in flight (e.g.
    // nara_thinking / query_chroma / between worker dispatches) but no worker
    // is in flight at this instant. The page must NOT claim "No agents active".
    renderActivity(MONITOR_FIXTURE_IDLE, ACTIVE_FIXTURE);
    expect(screen.queryByTestId("activity-idle-empty")).toBeNull();
    // And the active-iteration panel shows running.
    expect(screen.getByTestId("active-iteration-panel")).toHaveTextContent(
      /running/i,
    );
    // The status strip still reflects idle workers (it is worker-scoped), but
    // the contradictory "No agents active" empty-state is gone.
    expect(screen.getByTestId("activity-status")).toBeInTheDocument();
  });

  it("on the unavailable degrade path shows ONLY the unavailable notice", () => {
    // {available:false}: active[] is empty for want of data, not because the
    // apparatus is quiescent. The old single panel showed one clean
    // "unavailable" card; the page must not also emit a misleading "Idle"
    // status strip or a "No agents active" empty-state.
    renderActivity(MONITOR_FIXTURE_UNAVAILABLE);
    expect(screen.getByTestId("active-workers-unavailable")).toHaveTextContent(
      /unavailable/i,
    );
    // No status strip and no idle empty-state on the unavailable path.
    expect(screen.queryByTestId("activity-status")).toBeNull();
    expect(screen.queryByTestId("activity-idle-empty")).toBeNull();
  });

  it("lights the hero via the live-calls banner when calls flow with no workers or iteration", () => {
    // The exp-run blind spot: no orchestrator task, no loop iteration, but the
    // wrapper call log shows recent activity. The page must NOT read idle.
    renderActivity(MONITOR_FIXTURE_LIVE_CALLS, null);
    expect(screen.getByTestId("live-calls-banner")).toHaveTextContent(
      "nara.run_iteration",
    );
    expect(screen.queryByTestId("activity-idle-empty")).toBeNull();
    expect(screen.getByTestId("activity-status")).toHaveTextContent(/live/i);
  });

  it("renders the Now board in the hero with one card per registered run", () => {
    // NowBoard takes over the old single-run ActiveRunCard slot (2026-06-10
    // handoff Task 1): the injected registry payload wraps the same fixture
    // run the old card test used.
    renderActivity(MONITOR_FIXTURE_IDLE, null, ACTIVE_RUN_FIXTURE, null, [], {
      runs: [ACTIVE_RUN_FIXTURE],
      skipped: 0,
    });
    const hero = screen.getByTestId("active-now");
    const board = within(hero).getByTestId("now-board");
    const card = within(board).getByTestId(
      `now-run-${ACTIVE_RUN_FIXTURE.run_id}`,
    );
    expect(card).toHaveTextContent("exp003 paraphrase probe");
    expect(card).toHaveTextContent("experiment");
    expect(card).toHaveTextContent("retrieve_literature");
    expect(card).toHaveTextContent("3/10 papers");
  });

  it("Now board renders the honest empty state — never invents a run", () => {
    renderActivity(MONITOR_FIXTURE_IDLE, null, null, null, [], {
      runs: [],
      skipped: 0,
    });
    expect(screen.getByTestId("now-board-empty")).toHaveTextContent(
      /no registered runs/i,
    );
    expect(
      document.querySelectorAll('[data-testid^="now-run-"]'),
    ).toHaveLength(0);
  });

  it("suppresses the idle empty-state when an active_run is present", () => {
    // The monitor reports zero workers (idle), but a run IS registered in
    // run_state/active_run.json — the page must NOT claim "No agents active".
    renderActivity(MONITOR_FIXTURE_IDLE, null, ACTIVE_RUN_FIXTURE);
    expect(screen.queryByTestId("activity-idle-empty")).toBeNull();
    // And the status strip reads Live.
    expect(screen.getByTestId("activity-status")).toHaveTextContent(/live/i);
  });

  it("renders no run card when none is in flight (board un-injected)", () => {
    renderActivity(MONITOR_FIXTURE_IDLE, null, null);
    // The legacy single-run card is gone from the page, and the NowBoard
    // (injected as null = no payload) claims nothing.
    expect(screen.queryByTestId("active-run-card")).toBeNull();
    expect(document.querySelectorAll('[data-testid^="now-run-"]')).toHaveLength(0);
  });

  it("renders REAL inference (no synthetic marker) when monitor synthetic:false", () => {
    renderActivity(MONITOR_FIXTURE_REAL_INFERENCE, null, null);
    expect(screen.getByTestId("synthetic-inference")).toHaveAttribute(
      "data-synthetic",
      "false",
    );
    expect(screen.queryByTestId("synthetic-marker")).toBeNull();
  });

  it("renders the synthetic block subordinate (a disclosure)", () => {
    renderActivity();
    expect(screen.getByTestId("synthetic-inference").tagName.toLowerCase()).toBe(
      "details",
    );
  });

  it("keeps the synthetic marker visible while the disclosure is collapsed", () => {
    renderActivity();
    const details = screen.getByTestId("synthetic-inference");
    // Default-collapsed: the <details> is not open, yet the amber marker lives
    // in the always-visible <summary> so the not-measured flag survives the
    // collapsed state production users see first.
    expect(details).not.toHaveAttribute("open");
    const marker = screen.getByTestId("synthetic-marker");
    expect(marker).toHaveTextContent(/synthetic/i);
    expect(details.querySelector("summary")).toContainElement(marker);
  });

  it("demotes the history graph into a collapsible disclosure", () => {
    renderActivity();
    const disclosure = screen.getByTestId("recent-history-disclosure");
    expect(disclosure.tagName.toLowerCase()).toBe("details");
    // The graph renders inside the disclosure (its sr-only node list is the
    // test-visible node surface).
    expect(
      within(disclosure).getByTestId("activity-graph-nodes"),
    ).toBeInTheDocument();
  });

  it("detail toggle switches level WITHOUT opening the history disclosure", () => {
    renderActivity();
    const disclosure = screen.getByTestId("recent-history-disclosure");
    expect(disclosure).not.toHaveAttribute("open");
    const toggle = screen.getByTestId("detail-toggle");
    const fullBtn = within(toggle).getByText("full chain");
    // Clicking a toggle button inside the <summary> must call its onChange but
    // NOT toggle the <details> open/closed (preventDefault contract).
    fireEvent.click(fullBtn);
    expect(disclosure).not.toHaveAttribute("open");
  });

  it("renders the coordinator phases stepper when a coordinator cycle is live", () => {
    renderActivity(MONITOR_FIXTURE, null, null, COORDINATOR_ACTIVE_FIXTURE);
    const section = screen.getByTestId("coordinator-activity");
    // The live cycle's current step (dispatch) is highlighted active.
    expect(within(section).getByTestId("phase-dispatch")).toHaveAttribute(
      "data-state",
      "active",
    );
    // Narration (chosen topic + why) is shown.
    expect(within(section).getByTestId("coordinator-narration")).toHaveTextContent(
      /Truthfulness of VCG/i,
    );
  });

  it("renders the coordinator idle state when no cycle is live", () => {
    renderActivity();
    const section = screen.getByTestId("coordinator-activity");
    expect(within(section).getByTestId("coordinator-idle")).toBeInTheDocument();
    // No failed-dispatch surface when there are no cycles.
    expect(screen.queryByTestId("failed-dispatches")).toBeNull();
  });

  it("surfaces a failed dispatch as an explicit red row with its error", () => {
    // COORDINATOR_CYCLES_FIXTURE[0] has an errored run_loop_iteration action.
    renderActivity(
      MONITOR_FIXTURE,
      null,
      null,
      null,
      COORDINATOR_CYCLES_FIXTURE,
    );
    const failed = screen.getByTestId("failed-dispatches");
    expect(failed.className).toContain("red");
    const row = screen.getByTestId(
      `failed-dispatch-${COORDINATOR_CYCLES_FIXTURE[0].run_id}`,
    );
    expect(row).toHaveTextContent("run_loop_iteration");
    expect(row).toHaveTextContent(/not a valid SeedSource/i);
  });
});
