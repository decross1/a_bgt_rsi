// TopicalityAdvisoryBadge surfaces D-052's NON-GATING topicality dissent: a
// quiet zinc hint that fires ONLY for retrieval.relevance.topicality_advisory
// === "off". It must NOT reuse the amber low-evidence styling (it is not a
// low-evidence flag, not a gate), and it stays silent for every other value
// (absent / "on" / "unsure" / null / a non-object row / a garbled value). These
// tests cover the render and the exported hasTopicalityDissent rule.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import TopicalityAdvisoryBadge, {
  hasTopicalityDissent,
} from "../src/components/TopicalityAdvisoryBadge";
import type { IterationRecord } from "../src/types/schemas";

// Build a minimal record carrying just the relevance block under test —
// recordWith idiom from tests/test_low_evidence_badge.tsx.
function recordWith(
  relevance: NonNullable<IterationRecord["retrieval"]>["relevance"],
): IterationRecord {
  return {
    iteration_id: "iter-test",
    started_at: "2026-06-14T00:00:00Z",
    ended_at: "2026-06-14T00:01:00Z",
    journal_entry_path: "journal/iterations/test.md",
    retrieval: { relevance },
  };
}

const DISSENT_ROW = recordWith({ topicality_advisory: "off" });

describe("TopicalityAdvisoryBadge", () => {
  it("renders the quiet topicality-dissent badge for an explicit 'off'", () => {
    render(<TopicalityAdvisoryBadge record={DISSENT_ROW} />);
    const badge = screen.getByTestId("topicality-advisory-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent(/topicality dissent/i);
  });

  it("uses ZINC styling, never amber — it is not a low-evidence flag", () => {
    render(<TopicalityAdvisoryBadge record={DISSENT_ROW} />);
    const badge = screen.getByTestId("topicality-advisory-badge");
    expect(badge.className).toContain("zinc");
    expect(badge.className).not.toContain("amber");
  });

  it("titles the badge as an advisory, citing D-052 and that it is not a gate", () => {
    render(<TopicalityAdvisoryBadge record={DISSENT_ROW} />);
    const title = screen
      .getByTestId("topicality-advisory-badge")
      .getAttribute("title");
    expect(title).toMatch(/advisory/i);
    expect(title).toMatch(/D-052/);
    expect(title).toMatch(/not a gate/i);
  });

  it("renders nothing for absent / 'on' / 'unsure' / null advisory values", () => {
    for (const value of [undefined, "on", "unsure", null] as const) {
      const { container } = render(
        <TopicalityAdvisoryBadge record={recordWith({ topicality_advisory: value })} />,
      );
      expect(screen.queryByTestId("topicality-advisory-badge")).toBeNull();
      expect(container).toBeEmptyDOMElement();
    }
  });

  it("renders nothing when the relevance/retrieval block is wholly absent", () => {
    const bare: IterationRecord = {
      iteration_id: "iter-bare",
      started_at: "2026-06-14T00:00:00Z",
      ended_at: "2026-06-14T00:01:00Z",
      journal_entry_path: "journal/iterations/bare.md",
    };
    const { container } = render(<TopicalityAdvisoryBadge record={bare} />);
    expect(screen.queryByTestId("topicality-advisory-badge")).toBeNull();
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a non-object row or a garbled advisory value", () => {
    // A bare-null row round-trips from the append-only log as a primitive.
    const nullRow = null as unknown as IterationRecord;
    const { container: c1 } = render(<TopicalityAdvisoryBadge record={nullRow} />);
    expect(c1).toBeEmptyDOMElement();

    // Garbled producer writes: an object or a number where a string is expected
    // must surface nothing (never "[object Object]").
    const objVal = recordWith({
      topicality_advisory: {} as unknown as string,
    });
    const { container: c2 } = render(<TopicalityAdvisoryBadge record={objVal} />);
    expect(c2).toBeEmptyDOMElement();

    const numVal = recordWith({
      topicality_advisory: 1 as unknown as string,
    });
    const { container: c3 } = render(<TopicalityAdvisoryBadge record={numVal} />);
    expect(c3).toBeEmptyDOMElement();
  });
});

describe("hasTopicalityDissent", () => {
  it("is true ONLY for an explicit 'off' (case-insensitive)", () => {
    expect(hasTopicalityDissent(recordWith({ topicality_advisory: "off" }))).toBe(true);
    expect(hasTopicalityDissent(recordWith({ topicality_advisory: "OFF" }))).toBe(true);
    expect(hasTopicalityDissent(recordWith({ topicality_advisory: " off " }))).toBe(true);
  });

  it("is false for absent / 'on' / 'unsure' / null / garbled / non-object", () => {
    expect(hasTopicalityDissent(recordWith({ topicality_advisory: undefined }))).toBe(false);
    expect(hasTopicalityDissent(recordWith({ topicality_advisory: "on" }))).toBe(false);
    expect(hasTopicalityDissent(recordWith({ topicality_advisory: "unsure" }))).toBe(false);
    expect(hasTopicalityDissent(recordWith({ topicality_advisory: null }))).toBe(false);
    expect(hasTopicalityDissent(recordWith(null))).toBe(false);
    expect(
      hasTopicalityDissent(recordWith({ topicality_advisory: {} as unknown as string })),
    ).toBe(false);
    expect(hasTopicalityDissent(null as unknown as IterationRecord)).toBe(false);
  });
});
