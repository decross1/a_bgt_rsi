// Page B index tests. Render the list from fixtures (network bypassed via
// `initial`) and assert the honest per-shape states: json summary card,
// markdown badge, "no results yet", and the unavailable degrade.
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Experiments from "../src/routes/Experiments";
import {
  EXPERIMENTS_LIST_FIXTURE,
  EXPERIMENTS_LIST_UNAVAILABLE,
} from "../src/fixtures/experiments";
import { describe, expect, it } from "vitest";

function renderPage(initial: typeof EXPERIMENTS_LIST_FIXTURE) {
  return render(
    <MemoryRouter>
      <Experiments initial={initial} />
    </MemoryRouter>,
  );
}

describe("Experiments index", () => {
  it("renders a card per experiment", () => {
    renderPage(EXPERIMENTS_LIST_FIXTURE);
    expect(screen.getByTestId("exp-card-exp001_repeated_pd")).toBeInTheDocument();
    expect(
      screen.getByTestId("exp-card-exp003_vickrey_rediscovery"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("exp-card-exp002_loop_v0_robustness"),
    ).toBeInTheDocument();
  });

  it("shows json + per-round badges for the json-shaped experiment", () => {
    renderPage(EXPERIMENTS_LIST_FIXTURE);
    const card = screen.getByTestId("exp-card-exp001_repeated_pd");
    expect(card).toHaveTextContent("json summary");
    expect(card).toHaveTextContent("per-round");
  });

  it("shows a markdown summary badge for the md-shaped experiment", () => {
    renderPage(EXPERIMENTS_LIST_FIXTURE);
    const card = screen.getByTestId("exp-card-exp003_vickrey_rediscovery");
    expect(card).toHaveTextContent("markdown summary");
    expect(card).toHaveTextContent("trials");
  });

  it("marks the no-results experiment honestly", () => {
    renderPage(EXPERIMENTS_LIST_FIXTURE);
    const card = screen.getByTestId("exp-card-exp002_loop_v0_robustness");
    expect(card).toHaveTextContent("no results yet");
  });

  it("degrades to an unavailable notice when the dir is absent", () => {
    renderPage(EXPERIMENTS_LIST_UNAVAILABLE);
    expect(screen.getByTestId("experiments-unavailable")).toBeInTheDocument();
    expect(
      screen.getByTestId("experiments-unavailable"),
    ).toHaveTextContent(/not available/);
  });
});
