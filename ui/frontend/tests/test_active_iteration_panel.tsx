// ActiveIterationPanel renders the current iteration's step + narration +
// tool-call list, or "idle" when no iteration is in flight.
import { render, screen } from "@testing-library/react";
import ActiveIterationPanel from "../src/components/ActiveIterationPanel";
import {
  ACTIVE_FIXTURE,
  ACTIVE_FIXTURE_DIVERGENT,
} from "../src/fixtures/loop_v0";
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

  it("shows the orchestrator backend chip prominently", () => {
    render(<ActiveIterationPanel initial={ACTIVE_FIXTURE} />);
    const chip = screen.getByTestId("orchestrator-chip");
    expect(chip).toHaveTextContent("vllm-gemma · gemma-4-26b-a4b");
    // Emerald accent calls out which model is in the chair.
    expect(chip.className).toMatch(/emerald/);
  });

  it("does NOT render per-tool backend chips when every tool inherits", () => {
    // Discipline check: in the uniform case (every tool's backend ==
    // orchestrator_backend) the per-tool chip MUST stay hidden. Showing
    // it everywhere would defeat the diagnostic purpose — the chip MEANS
    // "this step is on a different backend than the orchestrator."
    render(<ActiveIterationPanel initial={ACTIVE_FIXTURE} />);
    expect(screen.queryByTestId(/^tool-backend-chip-/)).toBeNull();
  });

  it("renders a per-tool backend chip ONLY on divergence", () => {
    // ACTIVE_FIXTURE_DIVERGENT: orchestrator=vllm-gemma, but
    // critic_loop_v0's subagent is on ollama-coder/qwen. The tool's own
    // backend still matches the orchestrator, so the divergent-tool chip
    // should NOT render on the critic step — but the subagent chip MUST.
    // No other tool diverges, so no other per-tool chip should appear.
    render(<ActiveIterationPanel initial={ACTIVE_FIXTURE_DIVERGENT} />);
    expect(screen.queryByTestId(/^tool-backend-chip-/)).toBeNull();
    const subagentChip = screen.getByTestId(/^tool-subagent-chip-/);
    expect(subagentChip).toHaveTextContent(
      "ollama-coder · qwen3.6-27b-nvfp4-mtp",
    );
    // Sky accent marks this as the Co-Scientist / critic-flip surface.
    expect(subagentChip.className).toMatch(/sky/);
  });
});
