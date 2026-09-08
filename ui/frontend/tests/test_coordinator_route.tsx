// /cycles route tests (the S3 rename of /coordinator). Render newest-first
// from the fixture via `initial` (network bypassed, the historical
// ResolvedIterationsList idiom) and assert the page is the cycle-narrative
// surface: the CoordinatorPhases stepper at the top (idle when no live run),
// then a card per cycle — INCLUDING the failed-dispatch cycle, whose errored
// action is an explicit row, never a silent gap. An empty cycle log renders a
// clean empty state. `initialPhasesRun` is injected (null = idle) so the page
// never polls the D-047 registry in tests.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Cycles from "../src/routes/Cycles";
import * as http from "../src/api/http";
afterEach(() => vi.restoreAllMocks());
import {
  ACTIVE_RUN_FIXTURE,
  COORDINATOR_CYCLES_FIXTURE,
} from "../src/fixtures/coordinator";
import type { CoordinatorCycle } from "../src/types/schemas";

describe("Cycles route", () => {
  it("renders a compact row per cycle and discloses the frozen full record", () => {
    render(
      <Cycles initial={COORDINATOR_CYCLES_FIXTURE} initialPhasesRun={null} />,
    );

    expect(screen.getByTestId("coordinator-page")).toBeInTheDocument();

    const rows = screen.getAllByTestId("coordinator-cycle-row");
    expect(rows).toHaveLength(COORDINATOR_CYCLES_FIXTURE.length);
    expect(screen.queryByTestId("coordinator-cycle-card")).toBeNull();

    // Both topics are on screen.
    for (const cycle of COORDINATOR_CYCLES_FIXTURE) {
      expect(screen.getByText(cycle.topic)).toBeInTheDocument();
    }

    // The failed dispatch is a visible row carrying its error inline — the
    // headline "make absence legible" case.
    const erroredRow = rows.find((row) => row.getAttribute("data-outcome") === "errored");
    expect(erroredRow).toBeDefined();
    fireEvent.click(erroredRow!);
    fireEvent.click(screen.getByText("Complete recorded cycle evidence"));
    const errored = screen.getByTestId("coordinator-action-error-run_loop_iteration");
    expect(errored).toHaveTextContent(/not a valid SeedSource/i);
    expect(errored.className).toContain("red");
  });

  it("renders the cycles newest-first", () => {
    render(
      <Cycles initial={COORDINATOR_CYCLES_FIXTURE} initialPhasesRun={null} />,
    );
    const cards = screen.getAllByTestId("coordinator-cycle-row");
    // Fixture[0] (11:30, the errored arxiv_pick cycle) is newer than
    // fixture[1] (10:00); the route sorts/renders newest-first, so the first
    // card carries the newer cycle's topic.
    expect(cards[0]).toHaveTextContent(COORDINATOR_CYCLES_FIXTURE[0].topic);
  });

  it("groups no-ops only when every supplied non-identity field is equal", () => {
    const noop = (runId: string, timestamp: string, reason: string): CoordinatorCycle => ({
      timestamp,
      run_id: runId,
      agent: "coordinator",
      topic: "Budget check",
      topic_source: "coordinator_propose",
      status: "executed",
      plan: [{ action: "noop", args: { reason } }],
      outcomes: [{ action: "noop", status: "passed" }],
      promoted_finding_ids: [],
      bubble_run_ids: [],
    });
    render(
      <Cycles
        initial={[
          noop("same-a", "2026-09-08T03:00:00Z", "exact reason"),
          noop("same-b", "2026-09-08T02:00:00Z", "exact reason"),
          noop("different", "2026-09-08T01:00:00Z", "different recorded reason"),
        ]}
        initialPhasesRun={null}
      />,
    );

    expect(screen.getByText(/2 equivalent recorded no-ops/)).toBeInTheDocument();
    expect(screen.queryByText(/3 equivalent recorded no-ops/)).toBeNull();
    expect(screen.getAllByTestId("coordinator-cycle-row")).toHaveLength(3);
  });

  it("shows a clean empty state when there are no cycles", () => {
    render(<Cycles initial={[]} initialPhasesRun={null} />);
    expect(screen.getByTestId("coordinator-empty")).toHaveTextContent(
      /No coordinator cycles are recorded/i,
    );
    expect(screen.queryByTestId("coordinator-cycle-card")).toBeNull();
  });

  it("mounts CoordinatorPhases at the top — idle when no live run, live stepper when injected", () => {
    // Idle: the quiet phases panel renders above the narrative (moved here
    // from the deleted /activity page in S3).
    const { unmount } = render(
      <Cycles initial={COORDINATOR_CYCLES_FIXTURE} initialPhasesRun={null} />,
    );
    expect(screen.getByTestId("coordinator-phases")).toBeInTheDocument();
    expect(screen.getByTestId("coordinator-idle")).toBeInTheDocument();
    unmount();

    // Live: the injected coordinator run lights the stepper + narration.
    render(
      <Cycles
        initial={COORDINATOR_CYCLES_FIXTURE}
        initialPhasesRun={ACTIVE_RUN_FIXTURE}
      />,
    );
    expect(screen.queryByTestId("coordinator-idle")).toBeNull();
    expect(screen.getByTestId("phase-dispatch").getAttribute("data-state")).toBe(
      "active",
    );
    expect(screen.getByTestId("coordinator-narration")).toHaveTextContent(
      /Truthfulness of VCG/,
    );
  });
});


describe("trace response integrity and exact row selection", () => {
  it("keeps unreadable history and active envelopes unknown instead of empty or idle", async () => {
    vi.spyOn(http, "getCoordinatorCycles").mockResolvedValue({} as never);
    vi.spyOn(http, "getActiveRuns").mockResolvedValue({} as never);
    render(<Cycles />);
    expect(screen.queryByTestId("coordinator-idle")).toBeNull();
    await waitFor(() => expect(screen.getByTestId("coordinator-error")).toHaveTextContent("unavailable"));
    expect(screen.getByTestId("coordinator-phases")).toHaveTextContent("unavailable");
    expect(screen.queryByTestId("coordinator-empty")).toBeNull();
    expect(screen.queryByText(/0 readable of 0 loaded/)).toBeNull();
  });

  it("retains exact last-good history after a malformed refresh", async () => {
    vi.spyOn(http, "getCoordinatorCycles")
      .mockResolvedValueOnce({ cycles: COORDINATOR_CYCLES_FIXTURE } as never)
      .mockResolvedValue({ cycles: null } as never);
    render(<Cycles pollMs={20} initialPhasesRun={null} />);
    await screen.findAllByTestId("coordinator-cycle-row");
    await waitFor(() => expect(screen.getByTestId("coordinator-error")).toHaveTextContent("History refresh failed"));
    expect(screen.getAllByTestId("coordinator-cycle-row")).toHaveLength(COORDINATOR_CYCLES_FIXTURE.length);
    expect(screen.queryByTestId("coordinator-empty")).toBeNull();
  });

  it("selects the clicked evidence when displayed identity fields collide", () => {
    const first = { ...COORDINATOR_CYCLES_FIXTURE[0], outcomes: [{ action: "noop", status: "passed" }] } as CoordinatorCycle;
    const second = { ...first, outcomes: [{ action: "noop", status: "errored", error: "second exact row failure" }] } as CoordinatorCycle;
    render(<Cycles initial={[first, second]} initialPhasesRun={null} />);
    fireEvent.click(screen.getAllByTestId("coordinator-cycle-row")[1]);
    fireEvent.click(screen.getByRole("button", { name: "Complete recorded cycle evidence" }));
    expect(screen.getByTestId("coordinator-cycle-card")).toHaveTextContent("second exact row failure");
    expect(screen.getAllByTestId("coordinator-cycle-row")[1]).toHaveAttribute("aria-pressed", "true");
  });

  it("does not label mixed passed and unknown outcomes as a passed cycle", () => {
    const mixed = { ...COORDINATOR_CYCLES_FIXTURE[0], outcomes: [{action: "one", status: "passed"}, {action: "two", status: "unreported"}] } as CoordinatorCycle;
    render(<Cycles initial={[mixed]} initialPhasesRun={null} />);
    expect(screen.getByTestId("coordinator-cycle-row")).not.toHaveAttribute("data-outcome", "passed");
  });
});
