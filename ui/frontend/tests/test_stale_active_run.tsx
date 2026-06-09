// Stale-active-run legibility for CoordinatorPhases — the dual of "make
// absence legible": phantom PRESENCE. A confirmed producer bug (a lock-leak
// past a finally-block clear) can leave run_state/active_run.json behind after
// the iteration completed, which would paint a "running" stepper forever.
// When the run's freshest timestamp (step_started_at ?? started_at) is older
// than ~30 minutes the panel now renders a small AMBER hint
// (data-testid="coordinator-stale-hint") WHILE STILL rendering the stepper —
// annotate the state, don't hide it.
//
// Guard contract (mirrors Dashboard's Number.isFinite ageMs guard): a
// malformed / non-string / unparseable timestamp means "freshness unknown" →
// NO hint (never a false-stale), and absent timestamps / the idle state are
// unchanged. jsdom + console.error/warn spies stand in for the "renders
// without console errors" gate, as in test_harden_CoordinatorPhases.tsx.
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CoordinatorPhases from "../src/components/CoordinatorPhases";
import type { CoordinatorActiveRun } from "../src/types/schemas";

// Cast helper for deliberately-malformed producer rows (same idiom as
// test_harden_CoordinatorPhases.tsx): the UI gets any-shaped JSON at run time.
const bad = (row: unknown) => row as CoordinatorActiveRun;

// Timestamps relative to the real clock — useNow() seeds from Date.now(), so
// "fresh" / "stale" are offsets from now, not fixed dates.
const minutesAgoIso = (m: number) => new Date(Date.now() - m * 60_000).toISOString();

const baseRun: CoordinatorActiveRun = {
  kind: "coordinator",
  run_id: "coordinator-2026-06-09T12:00:00",
  label: "coordinator_cycle",
  current_step: "plan",
  narration: "Chose topic Z (topic_source=coordinator).",
};

describe("CoordinatorPhases — stale active_run hint", () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("a FRESH run (recent step_started_at) renders the stepper with NO stale hint", () => {
    render(
      <CoordinatorPhases
        activeRun={{
          ...baseRun,
          started_at: minutesAgoIso(5),
          step_started_at: minutesAgoIso(1),
        }}
      />,
    );
    expect(screen.getByTestId("coordinator-stepper")).toBeInTheDocument();
    expect(screen.queryByTestId("coordinator-stale-hint")).toBeNull();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a >30min-old step_started_at shows the amber hint AND still renders the stepper", () => {
    render(
      <CoordinatorPhases
        activeRun={{
          ...baseRun,
          started_at: minutesAgoIso(50),
          step_started_at: minutesAgoIso(45),
        }}
      />,
    );

    const hint = screen.getByTestId("coordinator-stale-hint");
    expect(hint).toHaveTextContent("possibly stale");
    expect(hint).toHaveTextContent("failed to clear active_run.json");
    // Relative age is rendered ("45m ..."), not a raw timestamp.
    expect(hint).toHaveTextContent(/45m/);
    expect(hint.className).toContain("amber");

    // Annotate, don't hide: the stepper + narration still render normally.
    expect(screen.getByTestId("coordinator-stepper")).toBeInTheDocument();
    expect(screen.getByTestId("phase-plan")).toHaveAttribute(
      "data-state",
      "active",
    );
    expect(screen.getByTestId("coordinator-narration")).toBeInTheDocument();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("falls back to started_at when step_started_at is absent (old run → hint)", () => {
    render(
      <CoordinatorPhases
        activeRun={{ ...baseRun, started_at: minutesAgoIso(90) }}
      />,
    );
    expect(screen.getByTestId("coordinator-stale-hint")).toBeInTheDocument();
    expect(screen.getByTestId("coordinator-stepper")).toBeInTheDocument();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a GARBAGE step_started_at string parses to NaN → NO hint (freshness unknown ≠ stale), no crash", () => {
    expect(() =>
      render(
        <CoordinatorPhases
          activeRun={bad({
            ...baseRun,
            step_started_at: "not-a-timestamp",
            started_at: undefined,
          })}
        />,
      ),
    ).not.toThrow();
    expect(screen.getByTestId("coordinator-stepper")).toBeInTheDocument();
    expect(screen.queryByTestId("coordinator-stale-hint")).toBeNull();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("NON-STRING timestamps (object / array) from a malformed row → NO hint, no crash", () => {
    // Date.parse coerces arrays to strings — an array-wrapped old ISO date
    // would parse "successfully" without the typeof-string guard and paint a
    // false-stale. Both shapes must be dropped.
    expect(() =>
      render(
        <CoordinatorPhases
          activeRun={bad({
            ...baseRun,
            step_started_at: { at: minutesAgoIso(90) },
            started_at: [minutesAgoIso(90)],
          })}
        />,
      ),
    ).not.toThrow();
    expect(screen.getByTestId("coordinator-stepper")).toBeInTheDocument();
    expect(screen.queryByTestId("coordinator-stale-hint")).toBeNull();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("timestamps entirely ABSENT (null) → NO hint (no false-stale on a sparse row)", () => {
    render(
      <CoordinatorPhases
        activeRun={{ ...baseRun, step_started_at: null, started_at: null }}
      />,
    );
    expect(screen.getByTestId("coordinator-stepper")).toBeInTheDocument();
    expect(screen.queryByTestId("coordinator-stale-hint")).toBeNull();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("idle (activeRun null) is unchanged: quiet idle state, no hint, no stepper", () => {
    render(<CoordinatorPhases activeRun={null} />);
    expect(screen.getByTestId("coordinator-idle")).toHaveTextContent(
      "coordinator idle",
    );
    expect(screen.queryByTestId("coordinator-stale-hint")).toBeNull();
    expect(screen.queryByTestId("coordinator-stepper")).toBeNull();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});
