// LowEvidenceBadge flags the 2026-06-09 false `novel/survives` bug: a verdict
// resting on thin / off-domain retrieval. These tests cover the component
// render (fires on the low-evidence fixture row, renders nothing on a clean
// row) and unit-test the pure isLowEvidence rule across its triggers
// (low_confidence + empty-neighbors) plus the conservative no-signal default.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import LowEvidenceBadge, {
  isLowEvidence,
} from "../src/components/LowEvidenceBadge";
import { ITERATIONS_COORD_FIXTURE } from "../src/fixtures/coordinator";
import type { IterationRecord } from "../src/types/schemas";

// Fixture rows (see src/fixtures/coordinator/index.ts):
//   [0] clean coordinator row  — relevance.low_confidence false (score 0.81)
//   [1] the false-novel bug    — relevance.low_confidence true  (score 0.04)
//   [2] clean human row        — relevance.low_confidence false (score 0.74)
const LOW_EVIDENCE_ROW = ITERATIONS_COORD_FIXTURE[1];
const CLEAN_ROW = ITERATIONS_COORD_FIXTURE[0];

describe("LowEvidenceBadge", () => {
  it("renders the amber badge for a verdict on thin/off-domain retrieval", () => {
    render(<LowEvidenceBadge record={LOW_EVIDENCE_ROW} />);
    const badge = screen.getByTestId("low-evidence-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent(/low-evidence/i);
    // Amber, not red — suspect, not broken.
    expect(badge.className).toContain("amber");
    // The tooltip explains *why* the verdict is suspect.
    expect(badge.getAttribute("title")).toMatch(/thin|off-domain|relevance/i);
  });

  it("renders nothing for a clean, well-supported row", () => {
    const { container } = render(<LowEvidenceBadge record={CLEAN_ROW} />);
    expect(screen.queryByTestId("low-evidence-badge")).toBeNull();
    expect(container).toBeEmptyDOMElement();
  });
});

// Build a minimal record carrying just the retrieval block under test.
function recordWith(
  retrieval: IterationRecord["retrieval"],
): IterationRecord {
  return {
    iteration_id: "iter-test",
    started_at: "2026-06-09T00:00:00Z",
    ended_at: "2026-06-09T00:01:00Z",
    journal_entry_path: "journal/iterations/test.md",
    retrieval,
  };
}

describe("isLowEvidence", () => {
  it("is true on the false-novel fixture row and false on the clean rows", () => {
    expect(isLowEvidence(LOW_EVIDENCE_ROW)).toBe(true);
    expect(isLowEvidence(ITERATIONS_COORD_FIXTURE[0])).toBe(false);
    expect(isLowEvidence(ITERATIONS_COORD_FIXTURE[2])).toBe(false);
  });

  it("is true when retrieval.relevance.low_confidence is set", () => {
    expect(
      isLowEvidence(recordWith({ relevance: { low_confidence: true } })),
    ).toBe(true);
  });

  it("is true when retrieval has an explicitly-empty neighbor list", () => {
    expect(isLowEvidence(recordWith({ k: 8, neighbors: [] }))).toBe(true);
  });

  it("trusts the worker: a low numeric score it did NOT flag is not low-evidence", () => {
    // The retrieval-relevance worker owns the calibrated cutoff; we don't
    // re-derive one, so a low blended score with low_confidence false is trusted.
    expect(
      isLowEvidence(
        recordWith({ relevance: { relevance: 0.07, low_confidence: false } }),
      ),
    ).toBe(false);
  });

  it("defaults to false when there is no retrieval signal (conservative)", () => {
    // Absent retrieval block (pre-coordinator row).
    expect(isLowEvidence(recordWith(null))).toBe(false);
    // Retrieval present but no relevance and neighbors absent (not empty).
    expect(isLowEvidence(recordWith({ k: 8 }))).toBe(false);
    // Relevance present but low_confidence absent/false is a benign value.
    expect(
      isLowEvidence(recordWith({ relevance: { relevance: 0.81 } })),
    ).toBe(false);
  });
});
