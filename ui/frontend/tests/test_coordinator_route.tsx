// /coordinator route tests. Render newest-first from the fixture via `initial`
// (network bypassed, the ResolvedIterationsList idiom) and assert the page is
// the cycle-narrative surface: a card per cycle — INCLUDING the failed-dispatch
// cycle, whose errored action is an explicit row, never a silent gap. An empty
// cycle log renders a clean empty state.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Coordinator from "../src/routes/Coordinator";
import { COORDINATOR_CYCLES_FIXTURE } from "../src/fixtures/coordinator";

describe("Coordinator route", () => {
  it("renders a card per cycle, including the errored one", () => {
    render(<Coordinator initial={COORDINATOR_CYCLES_FIXTURE} />);

    expect(screen.getByTestId("coordinator-page")).toBeInTheDocument();

    // One card per fixture cycle (the clean dispatch + the failed dispatch).
    const cards = screen.getAllByTestId("coordinator-cycle-card");
    expect(cards).toHaveLength(COORDINATOR_CYCLES_FIXTURE.length);

    // Both topics are on screen.
    for (const cycle of COORDINATOR_CYCLES_FIXTURE) {
      expect(screen.getByText(cycle.topic)).toBeInTheDocument();
    }

    // The failed dispatch is a visible row carrying its error inline — the
    // headline "make absence legible" case.
    const errored = screen.getByTestId(
      "coordinator-action-error-run_loop_iteration",
    );
    expect(errored).toHaveTextContent(/not a valid SeedSource/i);
    expect(errored.className).toContain("red");
  });

  it("renders the cycles newest-first", () => {
    render(<Coordinator initial={COORDINATOR_CYCLES_FIXTURE} />);
    const cards = screen.getAllByTestId("coordinator-cycle-card");
    // Fixture[0] (11:30, the errored arxiv_pick cycle) is newer than
    // fixture[1] (10:00); the route sorts/renders newest-first, so the first
    // card carries the newer cycle's topic.
    expect(cards[0]).toHaveTextContent(COORDINATOR_CYCLES_FIXTURE[0].topic);
  });

  it("shows a clean empty state when there are no cycles", () => {
    render(<Coordinator initial={[]} />);
    expect(screen.getByTestId("coordinator-empty")).toHaveTextContent(
      /No coordinator cycles yet/i,
    );
    expect(screen.queryByTestId("coordinator-cycle-card")).toBeNull();
  });
});
