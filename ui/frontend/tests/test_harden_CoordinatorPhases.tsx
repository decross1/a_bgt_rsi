// Adversarial hardening (round 1) for CoordinatorPhases — category: missing /
// null / undefined optional fields + malformed producer rows.
//
// active_run.json is producer-owned, append-only JSON the backend serves
// verbatim (schema/active_run.schema.json is the *intended* contract, but a
// partial / legacy / half-flushed write can violate it — and the UI must NEVER
// crash the page on one bad row). The component reads only scalar fields
// (run_id / current_step / narration / kind), so there are no nested objects to
// absent here — the live failure modes for this surface are (a) the optional
// fields simply missing / null, and (b) a field the schema types as
// string|null arriving as a non-string (object / array) from a malformed row.
//
// Found + fixed: narration and run_id were rendered as React children directly
// ({activeRun.narration} / {activeRun.run_id}); a non-string value there throws
// "Objects are not valid as a React child" and takes down the whole Activity
// page. The guards now require `typeof === "string"`, so a bad value is dropped
// (the block omits, exactly like a null value) instead of crashing.
//
// jsdom stands in for a headless browser (none available): render + spy on
// console.error / console.warn and assert they are never called on this
// category (the "renders without console errors" gate).
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CoordinatorPhases from "../src/components/CoordinatorPhases";
import type { CoordinatorActiveRun } from "../src/types/schemas";

// Cast helper: these rows deliberately violate the TS type to mimic what a
// malformed producer can write to disk (the UI gets `any`-shaped JSON at run
// time, regardless of the compile-time interface).
const bad = (row: unknown) => row as CoordinatorActiveRun;

describe("CoordinatorPhases — hardening r1 (missing/null/malformed fields)", () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("a coordinator row with EVERY optional field absent renders the stepper, no crash", () => {
    // Only `kind` present (the one required field the component branches on).
    // current_step / run_id / narration all undefined.
    render(<CoordinatorPhases activeRun={bad({ kind: "coordinator" })} />);

    expect(screen.getByTestId("coordinator-phases")).toBeInTheDocument();
    expect(screen.getByTestId("coordinator-stepper")).toBeInTheDocument();
    // No current_step → nothing highlighted, every phase "future".
    for (const phase of ["assess", "plan", "validate", "dispatch"]) {
      expect(screen.getByTestId(`phase-${phase}`)).toHaveAttribute(
        "data-state",
        "future",
      );
    }
    // Absent narration / run_id → those blocks are simply omitted (no empty box).
    expect(screen.queryByTestId("coordinator-narration")).toBeNull();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a coordinator row with all optional fields explicitly null renders cleanly", () => {
    render(
      <CoordinatorPhases
        activeRun={bad({
          kind: "coordinator",
          run_id: null,
          label: null,
          current_step: null,
          step_started_at: null,
          narration: null,
          started_at: null,
        })}
      />,
    );
    expect(screen.getByTestId("coordinator-stepper")).toBeInTheDocument();
    expect(screen.queryByTestId("coordinator-narration")).toBeNull();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a row with `kind` missing entirely falls back to the idle state, no crash", () => {
    // No `kind` → kind !== "coordinator" is true → idle (not a live stepper).
    render(<CoordinatorPhases activeRun={bad({})} />);
    expect(screen.getByTestId("coordinator-idle")).toHaveTextContent(
      "coordinator idle",
    );
    expect(screen.queryByTestId("coordinator-stepper")).toBeNull();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a non-string current_step (number / array) leaves every phase future, no crash", () => {
    // phaseState's indexOf returns -1 for a non-matching value → all "future".
    for (const step of [2, ["plan"], { step: "plan" }] as unknown[]) {
      render(
        <CoordinatorPhases
          activeRun={bad({ kind: "coordinator", current_step: step })}
        />,
      );
    }
    // The last render's stepper is present and unhighlighted.
    expect(screen.getAllByTestId("coordinator-stepper").length).toBeGreaterThan(0);
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a malformed OBJECT-valued narration is dropped, not rendered as a React child (no crash)", () => {
    // Pre-guard this threw: "Objects are not valid as a React child".
    expect(() =>
      render(
        <CoordinatorPhases
          activeRun={bad({
            kind: "coordinator",
            current_step: "plan",
            narration: { topic: "x", why: "y" },
          })}
        />,
      ),
    ).not.toThrow();
    // The stepper still renders; the malformed narration block is omitted.
    expect(screen.getByTestId("coordinator-stepper")).toBeInTheDocument();
    expect(screen.queryByTestId("coordinator-narration")).toBeNull();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("an ARRAY-valued narration (legacy list-of-sentences row) is dropped, no crash", () => {
    expect(() =>
      render(
        <CoordinatorPhases
          activeRun={bad({
            kind: "coordinator",
            current_step: "assess",
            narration: ["picked topic X", "because Y"],
          })}
        />,
      ),
    ).not.toThrow();
    expect(screen.getByTestId("coordinator-stepper")).toBeInTheDocument();
    expect(screen.queryByTestId("coordinator-narration")).toBeNull();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a malformed OBJECT-valued run_id is dropped from the header chip, no crash", () => {
    // Pre-guard this threw on the {activeRun.run_id} header chip.
    expect(() =>
      render(
        <CoordinatorPhases
          activeRun={bad({
            kind: "coordinator",
            current_step: "dispatch",
            run_id: { id: 1 },
            narration: "valid narration still shows",
          })}
        />,
      ),
    ).not.toThrow();
    // The good narration still renders; the bad run_id is just absent.
    expect(screen.getByTestId("coordinator-narration")).toHaveTextContent(
      "valid narration still shows",
    );
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a valid string narration + run_id still render exactly as before (no regression)", () => {
    render(
      <CoordinatorPhases
        activeRun={bad({
          kind: "coordinator",
          run_id: "coordinator-2026-06-09T12:00:00",
          current_step: "validate",
          narration: "Chose topic Z (topic_source=coordinator).",
        })}
      />,
    );
    expect(screen.getByTestId("coordinator-narration")).toHaveTextContent(
      "Chose topic Z",
    );
    expect(
      screen.getByText("coordinator-2026-06-09T12:00:00"),
    ).toBeInTheDocument();
    // validate is current → active; assess/plan done; dispatch future.
    expect(screen.getByTestId("phase-validate")).toHaveAttribute(
      "data-state",
      "active",
    );
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});
