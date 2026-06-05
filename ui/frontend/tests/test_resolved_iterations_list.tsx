// ResolvedIterationsList renders past iterations newest-first with
// novelty/critique badges, the topic, and a click handler that surfaces
// the selected iteration id to the parent so JournalScroll can load it.
import { fireEvent, render, screen } from "@testing-library/react";
import ResolvedIterationsList from "../src/components/ResolvedIterationsList";
import {
  ITERATIONS_FIXTURE,
  ITERATIONS_FIXTURE_V1,
} from "../src/fixtures/loop_v0";
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

  it("does NOT render Loop v1 surfaces on pre-v1 rows", () => {
    // ITERATIONS_FIXTURE rows carry no meta_review/redteam/gate_status —
    // the v1 chips and conditioning block must stay hidden.
    render(<ResolvedIterationsList initial={ITERATIONS_FIXTURE} />);
    expect(screen.queryByTestId("redteam-chip")).toBeNull();
    expect(screen.queryByTestId(/^conditioning-/)).toBeNull();
  });

  it("renders Loop v1 conditioning bullets, red-team chip and gate badge", () => {
    render(<ResolvedIterationsList initial={ITERATIONS_FIXTURE_V1} />);
    // Conditioning bullets from meta_review on both rows.
    expect(
      screen.getByText(/exp004 showed VCG elicits 96.5% truthful bids/),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("conditioning-iter-2026-06-04-001"),
    ).toBeInTheDocument();
    // Gate badges.
    expect(screen.getByText("valid")).toBeInTheDocument();
    expect(screen.getByText("needs_revision")).toBeInTheDocument();
    // Two red-team chips; the fatal_flaw + 2-retry one is highlighted red.
    const chips = screen.getAllByTestId("redteam-chip");
    expect(chips).toHaveLength(2);
    const fatal = chips.find((c) => /fatal_flaw/.test(c.textContent ?? ""));
    expect(fatal).toBeDefined();
    expect(fatal!).toHaveTextContent(/2 retries/);
    expect(fatal!.className).toMatch(/red/);
    // The clean "proceed / 0 retries" chip stays quiet (zinc, not red).
    const proceed = chips.find((c) => /proceed/.test(c.textContent ?? ""));
    expect(proceed).toBeDefined();
    expect(proceed!.className).not.toMatch(/red/);
  });
});
