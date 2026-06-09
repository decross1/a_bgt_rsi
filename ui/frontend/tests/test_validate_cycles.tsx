// VALIDATE CoordinatorCycleCard against the REAL run_state/coordinator_cycles.jsonl
// rows (13 live rows, 2026-06-09), not just the happy-path fixtures. The real
// data exercises shapes the fixtures never do — most importantly a
// `status:"planned"` cycle that carries a non-empty `plan` with EMPTY
// `outcomes`. The existing fixtures always have plan.length === outcomes.length,
// so the "planned, not yet run" case (proposed actions with no outcome rows)
// went untested; the card mapped `outcomes` only, so those proposed actions
// rendered as a blank section — "nothing happened" when the truth was "planned"
// (the exact dark-loop failure this view exists to fix). These rows are pasted
// verbatim from the live file (subset incl. an errored, a planned-with-plan, a
// no_valid_plan, and a clean executed row).
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CoordinatorCycleCard from "../src/components/CoordinatorCycleCard";
import type { CoordinatorCycle } from "../src/types/schemas";

// Verbatim subset of run_state/coordinator_cycles.jsonl (live 2026-06-09). All
// topic_source="arxiv_pick"; agent="coordinator"; none carries
// dispatched_iteration_id (the live cycles never wrote one).
const REAL_CYCLES: CoordinatorCycle[] = [
  // (a) ERRORED: a noop action errored with a real error string. Must render an
  // explicit red row carrying the error, never a silent gap.
  {
    timestamp: "2026-06-09T07:17:53.411655Z",
    run_id: "coordinator_696791e2",
    agent: "coordinator",
    topic: "FASE: Fast Adaptive Semantic Entropy for Code Quality",
    topic_source: "arxiv_pick",
    status: "executed",
    plan: [{ action: "noop", args: { reason: "x" } }],
    outcomes: [{ action: "noop", status: "errored", error: "RuntimeError: boom" }],
    promoted_finding_ids: [],
    bubble_run_ids: [],
  },
  // (b) PLANNED with a real plan but NO outcomes — the previously-invisible case.
  // Two proposed actions (run_loop_iteration, bubble_up) and an empty outcomes
  // array. Each proposed action MUST still be a visible row.
  {
    timestamp: "2026-06-09T07:17:53.375723Z",
    run_id: "coordinator_df4eecc8",
    agent: "coordinator",
    topic: "noisy PD",
    topic_source: "arxiv_pick",
    status: "planned",
    plan: [
      { action: "run_loop_iteration", args: { topic: "noisy PD" } },
      {
        action: "bubble_up",
        args: { finding_ids: ["sf-iter-2026-06-05-099"], note: "look" },
      },
    ],
    outcomes: [],
    promoted_finding_ids: [],
    bubble_run_ids: ["coordinator_df4eecc8"],
  },
  // (c) NO_VALID_PLAN: empty plan AND empty outcomes. Must render an explicit
  // "no valid plan" note, never a blank plan section.
  {
    timestamp: "2026-06-09T07:17:53.427909Z",
    run_id: "coordinator_8a997bf1",
    agent: "coordinator",
    topic: "FASE: Fast Adaptive Semantic Entropy for Code Quality",
    topic_source: "arxiv_pick",
    status: "no_valid_plan",
    plan: [],
    outcomes: [],
    promoted_finding_ids: [],
    bubble_run_ids: [],
  },
  // (d) CLEAN executed: 3 actions all passed (the happy path, for contrast).
  {
    timestamp: "2026-06-09T07:19:25.373451Z",
    run_id: "coordinator_ed54e262",
    agent: "coordinator",
    topic: "noisy PD",
    topic_source: "arxiv_pick",
    status: "executed",
    plan: [
      { action: "run_loop_iteration", args: { topic: "noisy PD" } },
      { action: "promote_findings", args: { max_candidates: 2 } },
      { action: "noop", args: { reason: "done" } },
    ],
    outcomes: [
      { action: "run_loop_iteration", status: "passed" },
      { action: "promote_findings", status: "passed" },
      { action: "noop", status: "passed" },
    ],
    promoted_finding_ids: [],
    bubble_run_ids: [],
  },
];

const ERRORED = REAL_CYCLES[0];
const PLANNED = REAL_CYCLES[1];
const NO_VALID_PLAN = REAL_CYCLES[2];
const CLEAN = REAL_CYCLES[3];

describe("CoordinatorCycleCard against real coordinator_cycles.jsonl rows", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders every real row without throwing and without console errors", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    for (const cycle of REAL_CYCLES) {
      const { unmount } = render(<CoordinatorCycleCard cycle={cycle} />);
      expect(screen.getByTestId("coordinator-cycle-card")).toBeInTheDocument();
      unmount();
    }

    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("renders the errored real row as an explicit row carrying the error string", () => {
    render(<CoordinatorCycleCard cycle={ERRORED} />);
    const action = screen.getByTestId("coordinator-action-noop");
    expect(action).toHaveTextContent(/errored/i);
    const errorText = screen.getByTestId("coordinator-action-error-noop");
    expect(errorText).toHaveTextContent("RuntimeError: boom");
    expect(errorText.className).toContain("red");
  });

  it("badges the real topic_source as arxiv_pick (never blank) and the agent", () => {
    render(<CoordinatorCycleCard cycle={ERRORED} />);
    expect(screen.getByTestId("coordinator-topic-source")).toHaveTextContent(
      /arxiv_pick/i,
    );
    expect(screen.getByTestId("agent-badge")).toHaveTextContent(/coordinator/i);
    expect(screen.getByText(ERRORED.topic)).toBeInTheDocument();
  });

  it("makes a planned-but-not-run cycle's proposed actions legible (the regression)", () => {
    // A status:"planned" cycle has a non-empty plan and empty outcomes. Each
    // proposed action must STILL render as a visible row (pending), not vanish.
    const { container } = render(<CoordinatorCycleCard cycle={PLANNED} />);
    const card = screen.getByTestId("coordinator-cycle-card");

    const runChip = within(card).getByTestId(
      "coordinator-action-run_loop_iteration",
    );
    const bubbleChip = within(card).getByTestId("coordinator-action-bubble_up");
    expect(runChip).toHaveTextContent(/pending/i);
    expect(bubbleChip).toHaveTextContent(/pending/i);

    // The plan section is not empty (the bug was a blank <ul>).
    expect(
      container.querySelectorAll('[data-testid^="coordinator-action-"]').length,
    ).toBe(2);
    // No error chip on a pending action.
    expect(
      within(card).queryByTestId("coordinator-action-error-run_loop_iteration"),
    ).toBeNull();
  });

  it("renders an explicit no-valid-plan note for an empty-plan cycle (never a blank gap)", () => {
    render(<CoordinatorCycleCard cycle={NO_VALID_PLAN} />);
    const note = screen.getByTestId("coordinator-no-plan");
    expect(note).toHaveTextContent(/no valid plan/i);
    // Surfaces the cycle status so "no plan formed" reads distinctly.
    expect(note).toHaveTextContent(/no_valid_plan/);
  });

  it("renders a clean executed cycle's actions as passed with no error rows", () => {
    render(<CoordinatorCycleCard cycle={CLEAN} />);
    const card = screen.getByTestId("coordinator-cycle-card");
    for (const a of ["run_loop_iteration", "promote_findings", "noop"]) {
      expect(within(card).getByTestId(`coordinator-action-${a}`)).toHaveTextContent(
        /passed/i,
      );
    }
    expect(
      within(card).queryByTestId("coordinator-action-error-run_loop_iteration"),
    ).toBeNull();
  });
});
