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
import ActiveWorkersPanel from "../src/components/ActiveWorkersPanel";
import LiveCallsBanner from "../src/components/LiveCallsBanner";
import SyntheticInferencePanel from "../src/components/SyntheticInferencePanel";
import Activity from "../src/routes/Activity";
import {
  MONITOR_FIXTURE,
  MONITOR_FIXTURE_IDLE,
  MONITOR_FIXTURE_LIVE_CALLS,
  MONITOR_FIXTURE_UNAVAILABLE,
  GRAPH_FIXTURE,
} from "../src/fixtures/activity";
import { ACTIVE_FIXTURE } from "../src/fixtures/loop_v0";

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
    expect(screen.getByTestId("active-workers-empty")).toBeInTheDocument();
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
});

describe("LiveCallsBanner", () => {
  it("renders recent wrapper-call activity when active", () => {
    render(<LiveCallsBanner data={MONITOR_FIXTURE_LIVE_CALLS.live_calls!} />);
    const banner = screen.getByTestId("live-calls-banner");
    expect(banner).toHaveTextContent(/live/i);
    expect(banner).toHaveTextContent("nara.run_iteration");
    expect(banner).toHaveTextContent("fake-model");
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

describe("Activity layout (workers HERO, graph demoted)", () => {
  afterEach(() => vi.restoreAllMocks());

  // Inject all three fixtures (graph + monitor + iteration) so the page is
  // fully static — no self-polling — and the idle gate reads the injected
  // iteration. `iteration` defaults to null (idle) to match the prior
  // behavior where getActiveIteration was stubbed to null.
  function renderActivity(
    monitor = MONITOR_FIXTURE,
    iteration: typeof ACTIVE_FIXTURE | null = null,
  ) {
    return render(
      <MemoryRouter>
        <Activity
          initialGraph={GRAPH_FIXTURE}
          initialMonitor={monitor}
          initialIteration={iteration}
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
});
