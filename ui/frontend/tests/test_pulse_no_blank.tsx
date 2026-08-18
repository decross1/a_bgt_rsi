// NO-BLANK-ON-REFETCH (perf work 2026-08-18, owner: "it keeps refreshing").
//
// The old failure mode: every Pulse panel polled on a bare setInterval and
// swapped its rendered content for an error line the moment one refetch
// failed — which, against a drowning backend, happened constantly, so panels
// flickered between content and error. These tests pin the SWR replacement
// at the COMPONENT level, against the three panels that did the flickering:
//
//   - a refetch that FAILS keeps the rendered content and adds an honest
//     muted "refresh failing — as of Xs ago" note (never a blank, never a
//     silent fake-fresh);
//   - a refetch with a CHANGED payload updates the content in place;
//   - recovery clears the stale note.
import { cleanup, render, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetPollHub } from "../src/api/pollhub";

const M = vi.hoisted(() => ({
  humanTodo: vi.fn(),
  labTodo: vi.fn(),
  activeRuns: vi.fn(),
}));

vi.mock("../src/api/http", () => ({
  HttpError: class HttpError extends Error {
    status: number;
    detail: string;
    constructor(status: number, detail: string) {
      super(`${status} ${detail}`);
      this.status = status;
      this.detail = detail;
    }
  },
  getHumanTodo: M.humanTodo,
  getLabTodo: M.labTodo,
  getActiveRuns: M.activeRuns,
  // EndpointMissingNote's version stamp — irrelevant here, must not throw.
  getHealth: vi.fn().mockResolvedValue({ version: "sha" }),
}));

import LabTodo from "../src/components/LabTodo";
import NowBoard from "../src/components/NowBoard";
import OweStrip from "../src/components/OweStrip";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  resetPollHub();
  vi.useRealTimers();
  vi.clearAllMocks();
});

const tickAsync = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

const owedItem = (id: string) => ({
  kind: "gate_verdict",
  id,
  title: `${id} awaiting verdict`,
  since: new Date().toISOString(),
});

describe("OweStrip (hero) never blanks on a failed refetch", () => {
  it("keeps rows + adds the honest stale note, then updates in place on recovery", async () => {
    M.humanTodo.mockResolvedValue({ items: [owedItem("iter-A")] });
    render(
      <MemoryRouter>
        <OweStrip pollMs={5000} />
      </MemoryRouter>,
    );
    await tickAsync(0);
    expect(screen.getByText("iter-A awaiting verdict")).toBeInTheDocument();
    expect(screen.queryByTestId("owe-stale")).toBeNull();

    // Refetch FAILS: the rendered queue stays, the failure is named.
    M.humanTodo.mockRejectedValue(new Error("backend drowned"));
    await tickAsync(6_000);
    expect(screen.getByText("iter-A awaiting verdict")).toBeInTheDocument();
    expect(screen.queryByTestId("owe-error")).toBeNull(); // no red swap
    expect(screen.getByTestId("owe-stale").textContent).toContain(
      "refresh failing",
    );

    // Recovery with a CHANGED payload: in-place update, stale note gone.
    M.humanTodo.mockResolvedValue({ items: [owedItem("iter-B")] });
    await tickAsync(6_000);
    expect(screen.getByText("iter-B awaiting verdict")).toBeInTheDocument();
    expect(screen.queryByText("iter-A awaiting verdict")).toBeNull();
    expect(screen.queryByTestId("owe-stale")).toBeNull();
  });

  it("still reports honestly when the FIRST load fails (no data to keep)", async () => {
    M.humanTodo.mockRejectedValue(new Error("500 kaput"));
    render(
      <MemoryRouter>
        <OweStrip pollMs={5000} />
      </MemoryRouter>,
    );
    await tickAsync(0);
    expect(screen.getByTestId("owe-error")).toHaveTextContent("kaput");
    expect(screen.queryByTestId("owe-empty")).toBeNull();
  });
});

describe("LabTodo never blanks on a failed refetch", () => {
  const labPayload = (gap: string) => ({
    agent_gaps: [gap],
    human_gaps: [],
    gaps_source: "last_cycle",
    gaps_as_of: null,
    owed: [],
    agenda: [],
    refine_candidates: [],
    generated_at: new Date().toISOString(),
  });

  it("keeps sections + adds the stale note; changed payload updates in place", async () => {
    M.labTodo.mockResolvedValue(labPayload("gap ONE"));
    render(
      <MemoryRouter>
        <LabTodo pollMs={5000} />
      </MemoryRouter>,
    );
    await tickAsync(500); // covers the initial stagger
    expect(screen.getByText("gap ONE")).toBeInTheDocument();

    M.labTodo.mockRejectedValue(new Error("lab_todo timed out"));
    await tickAsync(6_000);
    // The old behavior swapped the whole panel for lab-todo-error. Now: the
    // content stays and the staleness is NAMED.
    expect(screen.getByText("gap ONE")).toBeInTheDocument();
    expect(screen.queryByTestId("lab-todo-error")).toBeNull();
    expect(screen.getByTestId("lab-todo-stale").textContent).toContain(
      "refresh failing",
    );

    M.labTodo.mockResolvedValue(labPayload("gap TWO"));
    await tickAsync(6_000);
    expect(screen.getByText("gap TWO")).toBeInTheDocument();
    expect(screen.queryByText("gap ONE")).toBeNull();
    expect(screen.queryByTestId("lab-todo-stale")).toBeNull();
  });
});

describe("NowBoard never blanks on a failed refetch", () => {
  const runsPayload = (label: string) => ({
    runs: [
      {
        run_id: "run-1",
        kind: "coordinator",
        label,
        current_step: "planning",
        started_at: new Date().toISOString(),
        heartbeat_at: new Date().toISOString(),
      },
    ],
    skipped: 0,
  });

  it("keeps the board + adds the stale note instead of the red swap", async () => {
    M.activeRuns.mockResolvedValue(runsPayload("refine cycle"));
    render(<NowBoard live />);
    await tickAsync(0);
    expect(screen.getByText("refine cycle")).toBeInTheDocument();

    M.activeRuns.mockRejectedValue(new Error("connection refused"));
    await tickAsync(11_000);
    expect(screen.getByText("refine cycle")).toBeInTheDocument();
    expect(screen.queryByTestId("now-board-error")).toBeNull();
    expect(screen.getByTestId("now-board-stale").textContent).toContain(
      "refresh failing",
    );

    M.activeRuns.mockResolvedValue({ runs: [], skipped: 0 });
    await tickAsync(11_000);
    expect(screen.getByTestId("now-board-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("now-board-stale")).toBeNull();
  });
});
