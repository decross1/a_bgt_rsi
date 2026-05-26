// ActiveIterationPanel renders the current iteration's step + narration +
// tool-call list, or "idle" when no iteration is in flight.
import { render, screen } from "@testing-library/react";
import ActiveIterationPanel from "../src/components/ActiveIterationPanel";
import { ACTIVE_FIXTURE } from "../src/fixtures/loop_v0";
import { describe, expect, it } from "vitest";

describe("ActiveIterationPanel", () => {
  it("renders the iteration id, topic, narration and tool calls", () => {
    render(<ActiveIterationPanel initial={ACTIVE_FIXTURE} />);
    expect(screen.getByText("iter-2026-05-26-001")).toBeInTheDocument();
    expect(
      screen.getByText("Tit-for-Tat dominance in repeated PD"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Nara: querying Chroma/)).toBeInTheDocument();
    expect(screen.getByText("summarize_paper")).toBeInTheDocument();
    expect(screen.getByText("query_chroma")).toBeInTheDocument();
    expect(screen.getByText(/● running/)).toBeInTheDocument();
  });

  it("highlights the current step in the strip", () => {
    render(<ActiveIterationPanel initial={ACTIVE_FIXTURE} />);
    // The strip step matching ACTIVE_FIXTURE.current_step (query_chroma)
    // gets the emerald active class; other steps get the muted class.
    const activeStep = screen.getByTestId("step-query_chroma");
    expect(activeStep.className).toMatch(/emerald/);
    const otherStep = screen.getByTestId("step-summarize_paper");
    expect(otherStep.className).not.toMatch(/emerald/);
  });

  it("renders the idle state when no iteration is in flight", () => {
    render(<ActiveIterationPanel initial={null} />);
    expect(screen.getByText(/idle/)).toBeInTheDocument();
    expect(screen.getByText(/No iteration in flight/)).toBeInTheDocument();
  });
});
