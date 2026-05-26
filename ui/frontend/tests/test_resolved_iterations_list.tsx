// ResolvedIterationsList renders past iterations newest-first with
// novelty/critique badges, the topic, and a click handler that surfaces
// the selected iteration id to the parent so JournalScroll can load it.
import { fireEvent, render, screen } from "@testing-library/react";
import ResolvedIterationsList from "../src/components/ResolvedIterationsList";
import { ITERATIONS_FIXTURE } from "../src/fixtures/loop_v0";
import { describe, expect, it, vi } from "vitest";

describe("ResolvedIterationsList", () => {
  it("renders all rows with id, topic, novelty and verdict badges", () => {
    render(<ResolvedIterationsList initial={ITERATIONS_FIXTURE} />);
    for (const row of ITERATIONS_FIXTURE) {
      expect(screen.getByText(row.iteration_id)).toBeInTheDocument();
      if (row.seed?.topic) {
        expect(screen.getByText(row.seed.topic)).toBeInTheDocument();
      }
    }
    expect(screen.getByText("rediscovery")).toBeInTheDocument();
    expect(screen.getByText("novel")).toBeInTheDocument();
    expect(screen.getByText("nonsense")).toBeInTheDocument();
    expect(screen.getByText("survives")).toBeInTheDocument();
    expect(screen.getByText("restated")).toBeInTheDocument();
  });

  it("invokes onSelect with the iteration id when a row is clicked", () => {
    const onSelect = vi.fn();
    render(
      <ResolvedIterationsList
        initial={ITERATIONS_FIXTURE}
        onSelect={onSelect}
      />,
    );
    const button = screen.getByLabelText(/load journal iter-2026-05-26-001/);
    fireEvent.click(button);
    expect(onSelect).toHaveBeenCalledWith("iter-2026-05-26-001");
  });

  it("shows the empty-state message when no iterations have completed yet", () => {
    render(<ResolvedIterationsList initial={[]} />);
    expect(screen.getByText(/No iterations yet/)).toBeInTheDocument();
  });
});
