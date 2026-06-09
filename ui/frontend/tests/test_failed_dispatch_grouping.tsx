// B2 — failed-dispatch GROUPING. The 2026-06-09 wall: 12 visually identical
// noop/boom failed-dispatch rows. Identical (topic, action, error) failures
// must collapse to ONE row carrying an xN badge + first/last timestamps;
// distinct errors stay distinct rows (most-recent last-timestamp first); a
// singleton renders exactly as before (no badge, one timestamp). The header
// count stays the TOTAL errored actions so grouping never under-reports.
//
// Render idiom: static injection via every initial* prop (Activity's `live`
// gates skip all polls) with console.error/warn spied quiet — the
// renderActivityQuietCycles helper from test_harden_Activity.tsx, verbatim.
import { render, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import Activity from "../src/routes/Activity";
import { GRAPH_FIXTURE, MONITOR_FIXTURE_IDLE } from "../src/fixtures/activity";
import { COORDINATOR_CYCLES_FIXTURE } from "../src/fixtures/coordinator";
import type { CoordinatorCycle } from "../src/types/schemas";

// ActivityGraph (react-flow) measures itself via ResizeObserver, which jsdom
// lacks — the same idempotent shim the other Activity suites hoist.
beforeAll(() => {
  if (!("ResizeObserver" in globalThis)) {
    class RO {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    (globalThis as Record<string, unknown>).ResizeObserver = RO;
  }
});

function renderActivityQuietCycles(cycles: unknown) {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  const handle = render(
    <MemoryRouter>
      <Activity
        initialGraph={GRAPH_FIXTURE}
        initialMonitor={MONITOR_FIXTURE_IDLE}
        initialIteration={null}
        initialActiveRun={null}
        initialCoordinatorActive={null}
        initialCoordinatorCycles={cycles as CoordinatorCycle[]}
      />
    </MemoryRouter>,
  );
  const calls = {
    error: errSpy.mock.calls.map((c) => String(c[0])),
    warn: warnSpy.mock.calls.map((c) => String(c[0])),
  };
  errSpy.mockRestore();
  warnSpy.mockRestore();
  return { handle, calls };
}

// A failed-dispatch cycle in the live noop/boom shape: one errored `noop`
// outcome per cycle, identical error text unless overridden.
function boomCycle(
  i: number,
  timestamp: string,
  error = "RuntimeError: boom",
): CoordinatorCycle {
  return {
    timestamp,
    run_id: `coordinator_w${i}`,
    agent: "coordinator",
    topic: "watchdog noop probe",
    topic_source: "coordinator",
    plan: [{ action: "noop" }],
    outcomes: [{ action: "noop", status: "errored", error }],
    promoted_finding_ids: [],
    bubble_run_ids: [],
  } as unknown as CoordinatorCycle;
}

describe("Activity failed-dispatch grouping", () => {
  afterEach(() => vi.restoreAllMocks());

  it("collapses 12 identical (topic, action, error) failures to ONE row with x12 + first/last", () => {
    // 12 boom cycles spread 07:17 → 19:44, fed newest-first (the API order) so
    // first/last must come from min/max timestamps, not encounter order.
    const stamps = [
      "2026-06-09T19:44:00Z", // last
      "2026-06-09T18:30:00Z",
      "2026-06-09T17:15:00Z",
      "2026-06-09T16:00:00Z",
      "2026-06-09T14:45:00Z",
      "2026-06-09T13:30:00Z",
      "2026-06-09T12:15:00Z",
      "2026-06-09T11:00:00Z",
      "2026-06-09T09:45:00Z",
      "2026-06-09T08:50:00Z",
      "2026-06-09T08:00:00Z",
      "2026-06-09T07:17:00Z", // first
    ];
    const WALL = stamps.map((ts, i) => boomCycle(i, ts));
    const { handle, calls } = renderActivityQuietCycles(WALL);

    const failed = handle.getByTestId("failed-dispatches");
    const rows = failed.querySelectorAll('[data-testid^="failed-dispatch-"]');
    expect(rows).toHaveLength(1);

    // The group row is keyed by its MOST RECENT member's run_id (w0 = 19:44).
    const row = within(failed).getByTestId("failed-dispatch-coordinator_w0");
    expect(within(row as HTMLElement).getByText("x12")).toBeInTheDocument();
    // First/last span via shortTimestamp (T→space, Z stripped).
    expect(row).toHaveTextContent("first 2026-06-09 07:17:00");
    expect(row).toHaveTextContent("last 2026-06-09 19:44:00");
    // The error string appears ONCE, not twelve times.
    expect(
      (row.textContent ?? "").split("RuntimeError: boom").length - 1,
    ).toBe(1);
    // The header count is still the TOTAL errored actions (12), so grouping
    // never under-reports failure volume.
    const header = failed.querySelector("h2")?.parentElement as HTMLElement;
    expect(within(header).getByText("12")).toBeInTheDocument();

    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });

  it("keeps DISTINCT errors as distinct rows, most-recent last-timestamp first", () => {
    const MIXED = [
      boomCycle(0, "2026-06-09T08:00:00Z", "RuntimeError: boom A"),
      boomCycle(1, "2026-06-09T12:00:00Z", "RuntimeError: boom B"),
      boomCycle(2, "2026-06-09T09:00:00Z", "RuntimeError: boom A"),
    ];
    const { handle, calls } = renderActivityQuietCycles(MIXED);

    const failed = handle.getByTestId("failed-dispatches");
    const rows = failed.querySelectorAll('[data-testid^="failed-dispatch-"]');
    expect(rows).toHaveLength(2);
    // boom B (last 12:00) outranks the boom-A group (last 09:00).
    expect(rows[0].textContent ?? "").toContain("RuntimeError: boom B");
    expect(rows[1].textContent ?? "").toContain("RuntimeError: boom A");
    // The boom-A group counts its 2 members; boom B is a singleton (no badge).
    expect(within(rows[1] as HTMLElement).getByText("x2")).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).queryByText(/^x\d+$/)).toBeNull();

    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });

  it("renders a singleton exactly as before: no xN badge, one timestamp, no first/last", () => {
    // The canonical fixture: exactly one errored action (run_loop_iteration).
    const { handle, calls } = renderActivityQuietCycles(
      COORDINATOR_CYCLES_FIXTURE,
    );

    const failed = handle.getByTestId("failed-dispatches");
    const rows = failed.querySelectorAll('[data-testid^="failed-dispatch-"]');
    expect(rows).toHaveLength(1);
    const row = within(failed).getByTestId(
      `failed-dispatch-${COORDINATOR_CYCLES_FIXTURE[0].run_id}`,
    );
    expect(row).toHaveTextContent("run_loop_iteration");
    expect(row).toHaveTextContent(/not a valid SeedSource/i);
    // Singleton: the plain timestamp, no repeat badge, no first/last span.
    expect(row).toHaveTextContent("2026-06-09 11:30:00");
    expect(within(row as HTMLElement).queryByText(/^x\d+$/)).toBeNull();
    expect(row.textContent ?? "").not.toContain("first ");
    expect(row.textContent ?? "").not.toContain("last ");

    expect(calls.error, `console.error: ${calls.error.join(" | ")}`).toHaveLength(0);
    expect(calls.warn, `console.warn: ${calls.warn.join(" | ")}`).toHaveLength(0);
  });
});
