// LastCycleLine — Pulse's one-line "what did the loop just do". Pins: renders
// cycles[0] (the backend sorts newest-first); no_valid_plan tints amber;
// errored outcomes count red; promoted findings count emerald; honest empty
// state; a malformed head row degrades instead of crashing.
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import LastCycleLine from "../src/components/LastCycleLine";
import type { CoordinatorCycle } from "../src/types/schemas";

function renderLine(cycles?: CoordinatorCycle[] | null) {
  return render(
    <MemoryRouter>
      <LastCycleLine initial={cycles} />
    </MemoryRouter>,
  );
}

const EXECUTED: CoordinatorCycle = {
  timestamp: "2026-08-14T09:30:00Z",
  run_id: "coordinator_001",
  agent: "coordinator",
  topic: "FASE: fast adaptive semantic entropy",
  topic_source: "arxiv_pick",
  status: "executed",
  plan: [{ action: "run_loop_iteration" }],
  outcomes: [
    { action: "run_loop_iteration", status: "passed" },
    { action: "noop", status: "errored", error: "RuntimeError: boom" },
    { action: "promote_findings", status: "errored", error: "x" },
  ],
  promoted_finding_ids: ["sf-001", "sf-002"],
  bubble_run_ids: [],
};

describe("LastCycleLine", () => {
  it("renders the newest cycle's topic, status, errored count and findings", () => {
    renderLine([EXECUTED, { ...EXECUTED, topic: "older cycle" }]);
    const line = screen.getByTestId("last-cycle-line");
    expect(line).toHaveTextContent("FASE: fast adaptive semantic entropy");
    expect(line.textContent).not.toContain("older cycle");
    expect(screen.getByTestId("last-cycle-status")).toHaveTextContent(
      "executed",
    );
    const errored = screen.getByTestId("last-cycle-errored");
    expect(errored).toHaveTextContent("2 errored");
    expect(errored.className).toContain("text-red-400");
    const findings = screen.getByTestId("last-cycle-findings");
    expect(findings).toHaveTextContent("+2 findings");
    expect(findings.className).toContain("text-emerald-400");
  });

  it("tints no_valid_plan amber", () => {
    renderLine([
      { ...EXECUTED, status: "no_valid_plan", outcomes: [], promoted_finding_ids: [] },
    ]);
    const status = screen.getByTestId("last-cycle-status");
    expect(status).toHaveTextContent("no_valid_plan");
    expect(status.className).toContain("text-amber-400");
  });

  it("omits the errored/findings chips at zero (quiet, not '0 errored')", () => {
    renderLine([
      { ...EXECUTED, outcomes: [{ action: "noop", status: "passed" }], promoted_finding_ids: [] },
    ]);
    expect(screen.queryByTestId("last-cycle-errored")).toBeNull();
    expect(screen.queryByTestId("last-cycle-findings")).toBeNull();
  });

  it("links into the coordinator narrative", () => {
    renderLine([EXECUTED]);
    expect(screen.getByRole("link", { name: /cycles/ })).toHaveAttribute(
      "href",
      "/coordinator",
    );
  });

  it("honest empty state when no cycles exist", () => {
    renderLine(null);
    expect(screen.getByTestId("last-cycle-empty")).toHaveTextContent(
      "no coordinator cycles yet",
    );
  });

  it("a malformed head row degrades to the empty state, never a crash", () => {
    renderLine(["garbage"] as unknown as CoordinatorCycle[]);
    expect(screen.getByTestId("last-cycle-empty")).toBeInTheDocument();
  });
});
