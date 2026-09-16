import { describe, expect, it } from "vitest";

import {
  collectionDisplayTitle,
  iterationDisplayTitle,
  iterationQuestion,
} from "../src/researchLabels";

const current = [
  {
    iteration_id: "iter-2026-09-15-007",
    hypothesis: { text: JSON.stringify({ chosen: "Exact focal and pooled payoffs should imply oracle-consistent actions in every seat." }) },
  },
  {
    iteration_id: "iter-2026-09-15-008",
    hypothesis: { text: "A seat-indexed action table is more strategically consistent than a word-list representation." },
  },
  {
    iteration_id: "iter-2026-09-15-009",
    hypothesis: { text: "Future retaliation changes attention under a joint-payoff objective." },
  },
];

describe("evidence-bound research labels", () => {
  it("unwraps a serialized candidate envelope instead of showing JSON", () => {
    expect(iterationQuestion(current[0])).toBe(
      "Exact focal and pooled payoffs should imply oracle-consistent actions in every seat.",
    );
  });

  it("recovers the selected candidate when an earlier candidate has a malformed escape", () => {
    expect(iterationQuestion({
      hypothesis: {
        text: '{"candidates":["high learning rate $\\alpha$"],"chosen":"Exact focal and pooled payoffs predict oracle-consistent actions."}',
      },
    })).toBe("Exact focal and pooled payoffs predict oracle-consistent actions.");
  });

  it("uses informative current titles while keeping the exact ids out of the headline", () => {
    expect(current.map(iterationDisplayTitle)).toEqual([
      "Payoff arithmetic and strategic consistency",
      "Seat-indexed action tables",
      "Future retaliation and joint payoff",
    ]);
    expect(collectionDisplayTitle(current)).toBe(
      "Strategic consistency: arithmetic, action tables, and retaliation",
    );
  });

  it("falls back to the changed source question when a guarded claim drifts", () => {
    expect(iterationDisplayTitle({
      ...current[2],
      hypothesis: { text: "A new question about liquidity and settlement." },
    })).toBe("A new question about liquidity and settlement");
  });
});
