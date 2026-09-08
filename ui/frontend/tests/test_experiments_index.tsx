// Research index tests. Render the tier-grouped view from fixtures (network
// bypassed via `initial`) and assert the honest per-tier states: the three
// tier sections render in spectrum order; a YES verdict chip is emerald and a
// NO is red; a bridge badge names its iteration_id + metric; the applied
// design-only entry shows its "not run" state; an empty bridge reads "not yet
// bridged".
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Experiments from "../src/routes/Experiments";
import {
  RESEARCH_FIXTURE,
  RESEARCH_UNAVAILABLE,
} from "../src/fixtures/experiments";
import { COORDINATOR_CYCLES_FIXTURE } from "../src/fixtures/coordinator";
import type { CoordinatorCycle } from "../src/types/schemas";
import { describe, expect, it } from "vitest";

function renderPage(
  initial: typeof RESEARCH_FIXTURE,
  coordinatorCycles: CoordinatorCycle[] = [],
) {
  return render(
    <MemoryRouter>
      <Experiments
        initial={initial}
        initialCoordinatorCycles={coordinatorCycles}
      />
    </MemoryRouter>,
  );
}

describe("Research index (tier-grouped)", () => {
  it("renders the three tier sections in spectrum order", () => {
    const { container } = renderPage(RESEARCH_FIXTURE);
    const sections = Array.from(
      container.querySelectorAll('[data-testid^="tier-section-"]'),
    ).map((el) => el.getAttribute("data-testid"));
    // Untiered may trail; the first three are the spectrum tiers in order.
    expect(sections.slice(0, 3)).toEqual([
      "tier-section-synthetic",
      "tier-section-semi_synthetic",
      "tier-section-applied",
    ]);
  });

  it("colors a YES verdict emerald and a NO verdict red", () => {
    renderPage(RESEARCH_FIXTURE);
    const yes = screen.getByTestId("verdict-exp003_vickrey_rediscovery");
    expect(yes.className).toContain("emerald");
    const no = screen.getByTestId("verdict-exp001_repeated_pd");
    expect(no.className).toContain("red");
  });

  it("renders a bridge badge with its iteration_id + metric", () => {
    renderPage(RESEARCH_FIXTURE);
    const bridge = screen.getByTestId("bridge-exp003_vickrey_rediscovery");
    expect(bridge).toHaveTextContent("iter-2026-05-27-028");
    expect(bridge).toHaveTextContent("truthful_bid_fraction=1");
  });

  it("attaches the exp006 semi_synthetic bridge", () => {
    renderPage(RESEARCH_FIXTURE);
    const bridge = screen.getByTestId("bridge-exp006_mechanism_design");
    expect(bridge).toHaveTextContent("iter-2026-06-05-006");
    expect(bridge).toHaveTextContent("designer_mean_efficiency");
  });

  it("shows the applied design-only entry's not-run state + no verdict", () => {
    renderPage(RESEARCH_FIXTURE);
    const card = screen.getByTestId("research-card-exp007_polymarket");
    expect(card).toHaveTextContent("design-only — not run");
    expect(
      within(card).getByTestId("verdict-exp007_polymarket"),
    ).toHaveTextContent("no verdict");
  });

  it("reads 'not yet bridged' for an experiment with an empty bridge", () => {
    renderPage(RESEARCH_FIXTURE);
    const bridge = screen.getByTestId("bridge-exp001_repeated_pd");
    expect(bridge).toHaveTextContent("not yet bridged into the loop");
  });

  it("renders an untiered section for an unmapped on-disk dir", () => {
    renderPage(RESEARCH_FIXTURE);
    expect(screen.getByTestId("tier-section-untiered")).toBeInTheDocument();
    expect(
      screen.getByTestId("research-card-exp002_loop_v0_robustness"),
    ).toBeInTheDocument();
  });

  it("degrades to an unavailable notice when the dir is absent", () => {
    renderPage(RESEARCH_UNAVAILABLE);
    expect(screen.getByTestId("experiments-unavailable")).toBeInTheDocument();
    expect(
      screen.getByTestId("experiments-unavailable"),
    ).toHaveTextContent(/not available/);
  });

  it("renders coordinator cycles as auditable units (incl. the errored one)", () => {
    renderPage(RESEARCH_FIXTURE, COORDINATOR_CYCLES_FIXTURE);
    const section = within(screen.getByTestId("coordinator-cycles-section"));
    // One card per cycle.
    expect(section.getAllByTestId("coordinator-cycle-card")).toHaveLength(
      COORDINATOR_CYCLES_FIXTURE.length,
    );
    // The failed dispatch's plan→outcome chain is visible (the errored action
    // with its error string), so a coordinator verdict can be doubted here.
    expect(
      section.getByTestId("coordinator-action-error-run_loop_iteration"),
    ).toHaveTextContent(/not a valid SeedSource/i);
  });

  it("shows an empty coordinator-cycles state when there are none", () => {
    renderPage(RESEARCH_FIXTURE);
    expect(
      screen.getByTestId("coordinator-cycles-empty"),
    ).toHaveTextContent(/No coordinator cycles yet/i);
  });
});
