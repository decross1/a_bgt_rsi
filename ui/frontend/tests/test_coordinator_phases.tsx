// CoordinatorPhases renders the four coordinator phases (assess → plan →
// validate → dispatch) as a stepper, highlights current_step, walks prior
// steps to "done", shows the chosen-topic narration, and falls back to a quiet
// idle state when no coordinator cycle is live.
import { render, screen } from "@testing-library/react";
import CoordinatorPhases from "../src/components/CoordinatorPhases";
import { ACTIVE_RUN_FIXTURE } from "../src/fixtures/coordinator";
import type { CoordinatorActiveRun } from "../src/types/schemas";

describe("CoordinatorPhases", () => {
  it("renders the four phases and highlights the current step", () => {
    // ACTIVE_RUN_FIXTURE.current_step === "dispatch" (the last phase).
    render(<CoordinatorPhases activeRun={ACTIVE_RUN_FIXTURE} />);

    expect(screen.getByTestId("coordinator-phases")).toBeInTheDocument();
    for (const phase of ["assess", "plan", "validate", "dispatch"]) {
      expect(screen.getByTestId(`phase-${phase}`)).toHaveTextContent(phase);
    }

    // dispatch is current → active + emerald; the three before it are done.
    const dispatch = screen.getByTestId("phase-dispatch");
    expect(dispatch).toHaveAttribute("data-state", "active");
    expect(dispatch).toHaveAttribute("aria-current", "step");
    expect(dispatch.className).toContain("emerald");
    for (const prior of ["assess", "plan", "validate"]) {
      expect(screen.getByTestId(`phase-${prior}`)).toHaveAttribute(
        "data-state",
        "done",
      );
    }
  });

  it("shows the narration (chosen topic + why) below the stepper", () => {
    render(<CoordinatorPhases activeRun={ACTIVE_RUN_FIXTURE} />);
    const narration = screen.getByTestId("coordinator-narration");
    expect(narration).toHaveTextContent(
      "Truthfulness of VCG in combinatorial auctions",
    );
    expect(narration).toHaveTextContent("topic_source=coordinator");
  });

  it("marks an early current_step active with later phases still future", () => {
    const run: CoordinatorActiveRun = {
      ...ACTIVE_RUN_FIXTURE,
      current_step: "plan",
    };
    render(<CoordinatorPhases activeRun={run} />);
    expect(screen.getByTestId("phase-assess")).toHaveAttribute(
      "data-state",
      "done",
    );
    expect(screen.getByTestId("phase-plan")).toHaveAttribute(
      "data-state",
      "active",
    );
    for (const future of ["validate", "dispatch"]) {
      expect(screen.getByTestId(`phase-${future}`)).toHaveAttribute(
        "data-state",
        "future",
      );
    }
  });

  it("renders the quiet idle state when activeRun is null", () => {
    render(<CoordinatorPhases activeRun={null} />);
    expect(screen.getByTestId("coordinator-phases")).toBeInTheDocument();
    expect(screen.getByTestId("coordinator-idle")).toHaveTextContent(
      "coordinator idle",
    );
    // No stepper / no phase chips in the idle state.
    expect(screen.queryByTestId("coordinator-stepper")).toBeNull();
    expect(screen.queryByTestId("phase-assess")).toBeNull();
  });

  it("renders idle when a non-coordinator run is active (kind !== coordinator)", () => {
    const adHoc: CoordinatorActiveRun = {
      ...ACTIVE_RUN_FIXTURE,
      kind: "ad_hoc",
    };
    render(<CoordinatorPhases activeRun={adHoc} />);
    expect(screen.getByTestId("coordinator-idle")).toBeInTheDocument();
    expect(screen.queryByTestId("coordinator-stepper")).toBeNull();
  });
});
