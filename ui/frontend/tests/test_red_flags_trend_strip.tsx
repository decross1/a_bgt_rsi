// RedFlagsTrendStrip renders the research program's standing self-checks as a
// compact percentage strip. The headline assertion: the suspected-false-novel
// tile reflects the 2026-06-09 false-novel fixture row (novel/survives on
// low/thin retrieval) — a non-zero rate, the key trust metric.
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import RedFlagsTrendStrip from "../src/components/RedFlagsTrendStrip";
import { ITERATIONS_COORD_FIXTURE } from "../src/fixtures/coordinator";

// Fixture (see src/fixtures/coordinator/index.ts), 3 rows:
//   [0] rediscovery / restated, relevance "ok"  — not novel, not suspect, on-domain
//   [1] novel / survives, relevance "low"        — THE false-novel: suspect + off-domain
//   [2] novel / survives, relevance "ok"         — novel but well-supported
// => novel 2/3 (67%), suspected-false-novel 1/3 (33%), off-domain 1/3 (33%).
describe("RedFlagsTrendStrip", () => {
  it("renders the three self-check labels", () => {
    render(<RedFlagsTrendStrip iterations={ITERATIONS_COORD_FIXTURE} />);
    expect(screen.getByTestId("red-flags-trend-strip")).toBeInTheDocument();
    expect(screen.getByText(/novel rate/i)).toBeInTheDocument();
    expect(screen.getByText(/suspected false-novel/i)).toBeInTheDocument();
    expect(screen.getByText(/off-domain retrieval/i)).toBeInTheDocument();
  });

  it("reflects the low-evidence fixture row in the suspected-false-novel tile (>0%)", () => {
    render(<RedFlagsTrendStrip iterations={ITERATIONS_COORD_FIXTURE} />);
    const tile = screen.getByTestId("red-flag-suspected-false-novel");
    // The one false-novel row out of three -> 33%, and emphasized (amber/red),
    // not the quiet zinc of a clean strip.
    expect(within(tile).getByText("33%")).toBeInTheDocument();
    expect(within(tile).getByText("1 of 3")).toBeInTheDocument();
    expect(tile.innerHTML).toMatch(/amber|red/);
  });

  it("computes novel and off-domain rates over the fixture", () => {
    render(<RedFlagsTrendStrip iterations={ITERATIONS_COORD_FIXTURE} />);
    expect(
      within(screen.getByTestId("red-flag-novel-rate")).getByText("67%"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("red-flag-off-domain")).getByText("33%"),
    ).toBeInTheDocument();
  });

  it("is safe on an empty iteration set (zero state)", () => {
    render(<RedFlagsTrendStrip iterations={[]} />);
    expect(screen.getByTestId("red-flags-trend-strip")).toBeInTheDocument();
    // No denominator -> em-dash tiles, and the suspect tile stays quiet (no
    // over-alarm on no data).
    const tile = screen.getByTestId("red-flag-suspected-false-novel");
    expect(within(tile).getByText("—")).toBeInTheDocument();
    expect(tile.innerHTML).not.toMatch(/amber|red/);
  });
});
