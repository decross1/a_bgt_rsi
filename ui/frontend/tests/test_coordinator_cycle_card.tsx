// CoordinatorCycleCard renders one cycle as one narrative. The load-bearing
// case is the FAILED dispatch (make absence legible): an errored action must be
// a visible red chip carrying its error string inline, never a silent gap.
// Fixture [0] is exactly that case (arxiv_pick topic whose run_loop_iteration
// errored on a schema-enum gap); fixture [1] is the clean coordinator dispatch.
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import CoordinatorCycleCard from "../src/components/CoordinatorCycleCard";
import { COORDINATOR_CYCLES_FIXTURE } from "../src/fixtures/coordinator";

const ERRORED_CYCLE = COORDINATOR_CYCLES_FIXTURE[0]; // failed dispatch
const CLEAN_CYCLE = COORDINATOR_CYCLES_FIXTURE[1]; // all passed

describe("CoordinatorCycleCard", () => {
  it("renders the errored action as a visible row with its error text inline", () => {
    render(<CoordinatorCycleCard cycle={ERRORED_CYCLE} />);

    expect(screen.getByTestId("coordinator-cycle-card")).toBeInTheDocument();

    // The failed dispatch is an explicit chip — not a silent gap.
    const erroredAction = screen.getByTestId(
      "coordinator-action-run_loop_iteration",
    );
    expect(erroredAction).toHaveTextContent(/errored/i);

    // And it shows the error string inline (red), so a human can see WHY.
    const errorText = screen.getByTestId(
      "coordinator-action-error-run_loop_iteration",
    );
    expect(errorText).toBeInTheDocument();
    expect(errorText).toHaveTextContent(/not a valid SeedSource/i);
    expect(errorText.className).toContain("red");
  });

  it("badges provenance: the agent and the topic_source", () => {
    render(<CoordinatorCycleCard cycle={ERRORED_CYCLE} />);

    // Agent badge (coordinator) on the header.
    expect(screen.getByTestId("agent-badge")).toHaveTextContent(/coordinator/i);

    // topic_source badge renders the cycle's source (arxiv_pick here).
    expect(screen.getByTestId("coordinator-topic-source")).toHaveTextContent(
      /arxiv_pick/i,
    );

    // The topic itself is shown.
    expect(screen.getByText(ERRORED_CYCLE.topic)).toBeInTheDocument();
  });

  it("renders the linked iteration, promoted-finding count, and bubble count", () => {
    render(<CoordinatorCycleCard cycle={ERRORED_CYCLE} />);

    expect(
      screen.getByTestId("coordinator-dispatched-iteration"),
    ).toHaveTextContent(ERRORED_CYCLE.dispatched_iteration_id!);
    // The errored cycle promoted nothing and raised one bubble.
    expect(screen.getByTestId("coordinator-promoted-count")).toHaveTextContent(
      "0 findings promoted",
    );
    expect(screen.getByTestId("coordinator-bubble-count")).toHaveTextContent(
      "1 bubble",
    );
  });

  it("renders a clean cycle's actions as passed, with no error rows", () => {
    render(<CoordinatorCycleCard cycle={CLEAN_CYCLE} />);

    const card = screen.getByTestId("coordinator-cycle-card");
    expect(
      within(card).getByTestId("coordinator-action-run_loop_iteration"),
    ).toHaveTextContent(/passed/i);
    // No inline error row anywhere on a clean cycle.
    expect(
      within(card).queryByTestId(
        "coordinator-action-error-run_loop_iteration",
      ),
    ).toBeNull();
    expect(screen.getByTestId("coordinator-promoted-count")).toHaveTextContent(
      "1 finding promoted",
    );
  });
});
