// InFlightRollup (FE5) — the Dashboard's compact "what is RUNNING + what's
// next" rollup. The component is purely prop-driven (no fetching), so these
// tests render it directly with constructed inputs. They cover each feed (the
// active loop iteration, the coordinator cycle, running subprocesses), the
// human-owned next-step lines (experiment-bridging placeholder + findings
// awaiting sign-off), the calm empty state, and — the house doctrine — hostile
// producer fields that must coerce/drop rather than crash the Dashboard.
//
// No-headless-browser stand-in for "renders without console errors": a jsdom
// render plus a console.error/warn spy asserted not-called (a render-time
// throw — e.g. an object reaching React as a child — lands on console.error).
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import InFlightRollup from "../src/components/InFlightRollup";
import type {
  ActiveIteration,
  CoordinatorActiveRun,
  ProcessRow,
} from "../src/types/schemas";

afterEach(cleanup);

function iteration(overrides: Partial<ActiveIteration> = {}): ActiveIteration {
  return {
    iteration_id: "iter-2026-06-16-001",
    topic: "spectral gap of attention",
    started_at: "2026-06-16T10:00:00.000000Z",
    current_step: "query_chroma",
    ...overrides,
  } as ActiveIteration;
}

function coordinator(
  overrides: Partial<CoordinatorActiveRun> = {},
): CoordinatorActiveRun {
  return {
    kind: "coordinator",
    run_id: "coord-2026-06-16-001",
    label: "auto-topic: emergent calibration",
    current_step: "plan",
    narration: "chose emergent calibration because …",
    started_at: "2026-06-16T10:05:00.000000Z",
    ...overrides,
  } as CoordinatorActiveRun;
}

function proc(overrides: Partial<ProcessRow> = {}): ProcessRow {
  return {
    pid: 4242,
    topic: "running loop iteration",
    status: "running",
    started_at: "2026-06-16T10:01:00.000000Z",
    ...overrides,
  } as ProcessRow;
}

describe("InFlightRollup feeds", () => {
  it("renders the active loop iteration (topic + current step)", () => {
    render(
      <InFlightRollup
        activeIteration={iteration()}
        coordinatorActive={null}
        processes={[]}
        findingsAwaiting={0}
      />,
    );
    const row = screen.getByTestId("in-flight-iteration");
    expect(row).toHaveTextContent("spectral gap of attention");
    expect(row).toHaveTextContent("query_chroma");
    expect(screen.queryByTestId("in-flight-empty")).toBeNull();
  });

  it("renders the coordinator run from label/narration (it has NO .topic)", () => {
    render(
      <InFlightRollup
        activeIteration={null}
        coordinatorActive={coordinator()}
        processes={[]}
        findingsAwaiting={0}
      />,
    );
    const row = screen.getByTestId("in-flight-coordinator");
    expect(row).toHaveTextContent("auto-topic: emergent calibration");
    expect(row).toHaveTextContent("plan");
  });

  it("falls back to coordinator narration when label is empty", () => {
    render(
      <InFlightRollup
        activeIteration={null}
        coordinatorActive={coordinator({ label: "" })}
        processes={[]}
        findingsAwaiting={0}
      />,
    );
    expect(screen.getByTestId("in-flight-coordinator")).toHaveTextContent(
      "chose emergent calibration",
    );
  });

  it("renders only running-status processes (drops exited rows)", () => {
    render(
      <InFlightRollup
        activeIteration={null}
        coordinatorActive={null}
        processes={[
          proc({ pid: 100 }),
          proc({ pid: 200, status: "exited_clean" }),
          proc({ pid: 300, status: "exited_error_1" }),
        ]}
        findingsAwaiting={0}
      />,
    );
    expect(screen.getByTestId("in-flight-process-100")).toHaveTextContent(
      "pid 100",
    );
    expect(screen.queryByTestId("in-flight-process-200")).toBeNull();
    expect(screen.queryByTestId("in-flight-process-300")).toBeNull();
  });

  it("renders the findings-awaiting next-step line when N > 0", () => {
    render(
      <InFlightRollup
        activeIteration={iteration()}
        coordinatorActive={null}
        processes={[]}
        findingsAwaiting={3}
      />,
    );
    expect(
      screen.getByTestId("in-flight-findings-awaiting"),
    ).toHaveTextContent("3 findings awaiting your applied sign-off");
  });

  it("singularizes the findings-awaiting line at N = 1", () => {
    render(
      <InFlightRollup
        activeIteration={iteration()}
        coordinatorActive={null}
        processes={[]}
        findingsAwaiting={1}
      />,
    );
    expect(
      screen.getByTestId("in-flight-findings-awaiting"),
    ).toHaveTextContent("1 finding awaiting your applied sign-off");
  });

  it("renders experiment-bridging as a greyed Phase-2 placeholder by default", () => {
    render(
      <InFlightRollup
        activeIteration={iteration()}
        coordinatorActive={null}
        processes={[]}
        findingsAwaiting={0}
      />,
    );
    const bridging = screen.getByTestId("in-flight-experiment-bridging");
    expect(bridging).toHaveTextContent("Experiment bridging");
    expect(bridging).toHaveTextContent("Phase 2 — not wired");
    // GREYED: the placeholder carries the muted zinc-600 tone, NOT an alarm/amber.
    expect(bridging.className).toContain("text-zinc-600");
  });

  it("marks experiment-bridging as dispatching when the coordinator is on dispatch", () => {
    render(
      <InFlightRollup
        activeIteration={null}
        coordinatorActive={coordinator({ current_step: "dispatch" })}
        processes={[]}
        findingsAwaiting={0}
      />,
    );
    expect(
      screen.getByTestId("in-flight-experiment-bridging"),
    ).toHaveTextContent("dispatching");
  });
});

describe("InFlightRollup empty state", () => {
  it("shows the calm 'nothing in flight' state with no feeds and no findings", () => {
    render(
      <InFlightRollup
        activeIteration={null}
        coordinatorActive={null}
        processes={[]}
        findingsAwaiting={0}
      />,
    );
    expect(screen.getByTestId("in-flight-empty")).toHaveTextContent(
      "Nothing in flight",
    );
    expect(screen.queryByTestId("in-flight-iteration")).toBeNull();
    expect(screen.queryByTestId("in-flight-coordinator")).toBeNull();
    expect(screen.queryByTestId("in-flight-findings-awaiting")).toBeNull();
    // The experiment-bridging next-step placeholder still renders (it is the
    // standing "Phase 2" note, present even when nothing is in flight).
    expect(screen.getByTestId("in-flight-experiment-bridging")).toBeTruthy();
  });

  it("treats all-omitted props as the empty state without throwing", () => {
    expect(() => render(<InFlightRollup />)).not.toThrow();
    expect(screen.getByTestId("in-flight-empty")).toBeTruthy();
  });
});

describe("InFlightRollup hostile-field coercion (house doctrine)", () => {
  // The no-browser stand-in: a render-time throw (e.g. an object reaching React
  // as a child) lands on console.error in jsdom. Spy and assert silence.
  function renderQuiet(node: React.ReactElement) {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(() => render(node)).not.toThrow();
    expect(err).not.toHaveBeenCalled();
    expect(warn).not.toHaveBeenCalled();
    err.mockRestore();
    warn.mockRestore();
  }

  it("drops an object-typed iteration topic instead of crashing", () => {
    renderQuiet(
      <InFlightRollup
        activeIteration={
          iteration({
            topic: { evil: "object" } as unknown as string,
            current_step: "query_chroma",
          })
        }
        coordinatorActive={null}
        processes={[]}
        findingsAwaiting={0}
      />,
    );
    // The object topic is dropped, but the iteration row still renders from its
    // current_step (the row mounts when EITHER topic or step is legible).
    expect(screen.getByTestId("in-flight-iteration")).toHaveTextContent(
      "query_chroma",
    );
  });

  it("drops an object-typed coordinator label/narration instead of crashing", () => {
    renderQuiet(
      <InFlightRollup
        activeIteration={null}
        coordinatorActive={
          coordinator({
            label: { x: 1 } as unknown as string,
            narration: ["bad"] as unknown as string,
            run_id: "coord-fallback",
          })
        }
        processes={[]}
        findingsAwaiting={0}
      />,
    );
    // label + narration are non-scalar and dropped; run_id is the legible
    // fallback so the coordinator row still names the run.
    expect(screen.getByTestId("in-flight-coordinator")).toHaveTextContent(
      "coord-fallback",
    );
  });

  it("coerces a non-array processes payload to empty without throwing", () => {
    renderQuiet(
      <InFlightRollup
        activeIteration={null}
        coordinatorActive={null}
        processes={null as unknown as ProcessRow[]}
        findingsAwaiting={0}
      />,
    );
    expect(screen.getByTestId("in-flight-empty")).toBeTruthy();
  });

  it("coerces a negative / fractional / non-finite findingsAwaiting", () => {
    // Negative -> clamped to 0 -> line suppressed.
    renderQuiet(
      <InFlightRollup
        activeIteration={iteration()}
        coordinatorActive={null}
        processes={[]}
        findingsAwaiting={-5 as number}
      />,
    );
    expect(screen.queryByTestId("in-flight-findings-awaiting")).toBeNull();
    cleanup();

    // Fractional -> floored to an integer.
    renderQuiet(
      <InFlightRollup
        activeIteration={iteration()}
        coordinatorActive={null}
        processes={[]}
        findingsAwaiting={2.7 as number}
      />,
    );
    expect(
      screen.getByTestId("in-flight-findings-awaiting"),
    ).toHaveTextContent("2 findings awaiting your applied sign-off");
    cleanup();

    // NaN -> 0 -> line suppressed.
    renderQuiet(
      <InFlightRollup
        activeIteration={iteration()}
        coordinatorActive={null}
        processes={[]}
        findingsAwaiting={NaN as number}
      />,
    );
    expect(screen.queryByTestId("in-flight-findings-awaiting")).toBeNull();
  });

  it("drops an object-typed process topic but still renders the running row", () => {
    renderQuiet(
      <InFlightRollup
        activeIteration={null}
        coordinatorActive={null}
        processes={[
          proc({ pid: 777, topic: { bad: true } as unknown as string }),
        ]}
        findingsAwaiting={0}
      />,
    );
    expect(screen.getByTestId("in-flight-process-777")).toHaveTextContent(
      "pid 777",
    );
  });
});
