// Exp004Panel renders the combinatorial-auction per-mechanism summary
// (truthful fraction, efficiency, revenue, YES/NO verdict). The empty-state
// — results file absent / available:false — is a first-class expected
// display (experiment not yet run), so it gets its own test.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Exp004Panel from "../src/components/Exp004Panel";
import { EXP004_FIXTURE, EXP004_FIXTURE_EMPTY } from "../src/fixtures/loop_v0";

describe("Exp004Panel", () => {
  it("renders one row per mechanism with verdict chips and trial count", () => {
    render(<Exp004Panel initial={EXP004_FIXTURE} />);
    expect(screen.getByText("first_price")).toBeInTheDocument();
    expect(screen.getByText("sequential_second_price")).toBeInTheDocument();
    expect(screen.getByText("vcg")).toBeInTheDocument();
    // Three YES verdict chips, one per mechanism.
    expect(screen.getAllByText("YES")).toHaveLength(3);
    expect(screen.getByText(/n=150 trials/)).toBeInTheDocument();
    // Truthful fraction formatted as a percentage.
    expect(screen.getAllByText("96.5 %").length).toBeGreaterThan(0);
  });

  it("renders the empty-state when the results file is absent", () => {
    render(<Exp004Panel initial={EXP004_FIXTURE_EMPTY} />);
    expect(
      screen.getByText(/No exp004 results yet/),
    ).toBeInTheDocument();
  });
});
