// B2b — relevance.category / rule_fired DETAIL on the low-evidence tooltip.
//
// The close-out (docs/ui_validation_handoff.md, 2026-06-09 evening additions)
// confirmed retrieval.relevance gains additive {category, rule_fired} (plus
// three numeric diagnostics this surface ignores). When isLowEvidence fires
// AND those keys are present, the badge's title-tooltip is ENRICHED with
// "category: <category>; rule: <rule_fired>" — detail only. The five new keys
// never decide the verdict (test_forwardcompat_lowevidence_strip pins that);
// this file pins the tooltip side: present → enriched, absent → the old
// tooltip unchanged, garbled (object) → dropped without a crash.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import LowEvidenceBadge, {
  isLowEvidence,
} from "../src/components/LowEvidenceBadge";
import type { IterationRecord } from "../src/types/schemas";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// Build a minimal record carrying just the retrieval block under test. Cast
// through unknown so a test can express garbled producer shapes the declared
// type does not admit (same idiom as test_forwardcompat_lowevidence_strip).
function recordWith(retrieval: unknown): IterationRecord {
  return {
    iteration_id: "iter-category-detail",
    started_at: "2026-06-09T00:00:00Z",
    ended_at: "2026-06-09T00:01:00Z",
    journal_entry_path: "journal/iterations/category-detail.md",
    retrieval,
  } as unknown as IterationRecord;
}

function renderTitle(rec: IterationRecord): string {
  render(<LowEvidenceBadge record={rec} />);
  return screen.getByTestId("low-evidence-badge").getAttribute("title") ?? "";
}

describe("LowEvidenceBadge — category/rule_fired tooltip detail", () => {
  it("folds category + rule into the tooltip when both are present", () => {
    const title = renderTitle(
      recordWith({
        neighbors: [{ id: "n1" }],
        relevance: {
          relevance: 0.04,
          low_confidence: true,
          reason: "off-domain anchor",
          category: "off_domain",
          rule_fired: "off_domain_anchor_below_floor",
        },
      }),
    );
    // The exact confirmed format, riding the existing "; "-joined parts.
    expect(title).toContain(
      "category: off_domain; rule: off_domain_anchor_below_floor",
    );
    // The pre-existing reason text still leads — enrichment, not replacement.
    expect(title).toContain("retrieval flagged low-confidence — off-domain anchor");
  });

  it("an unknown category value passes through raw (no enum gate)", () => {
    const title = renderTitle(
      recordWith({
        neighbors: [{ id: "n1" }],
        relevance: {
          low_confidence: true,
          category: "some_future_category",
        },
      }),
    );
    expect(title).toContain("category: some_future_category");
    // rule_fired absent → no dangling "rule:" fragment.
    expect(title).not.toContain("rule:");
  });

  it("enriches the structural empty-neighbors tooltip too", () => {
    const title = renderTitle(
      recordWith({
        neighbors: [],
        relevance: {
          relevance: 0.0,
          low_confidence: false,
          category: "empty",
          rule_fired: "empty_neighbors",
        },
      }),
    );
    expect(title).toContain("0 retrieved neighbors");
    expect(title).toContain("category: empty; rule: empty_neighbors");
  });

  it("absent category/rule_fired → the old tooltip, byte-identical", () => {
    const retrieval = {
      neighbors: [{ id: "n1" }],
      relevance: {
        relevance: 0.04,
        low_confidence: true,
        reason: "off-domain anchor",
      },
    };
    const title = renderTitle(recordWith(retrieval));
    expect(title).toBe(
      "Low-evidence verdict: retrieval flagged low-confidence — off-domain anchor. The verdict rests on thin or off-domain retrieval — eyeball before trusting.",
    );
    expect(title).not.toContain("category:");
    expect(title).not.toContain("rule:");
  });

  it("garbled category (object) is dropped — no crash, no junk in the tooltip", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const rec = recordWith({
      neighbors: [{ id: "n1" }],
      relevance: {
        low_confidence: true,
        reason: "thin",
        category: { kind: "off_domain", score: 0.1 }, // object → no scalar form
        rule_fired: ["r1", "r2"], // array → also dropped
      },
    });
    expect(() => isLowEvidence(rec)).not.toThrow();
    expect(isLowEvidence(rec)).toBe(true); // verdict untouched by garble
    let title = "";
    expect(() => {
      title = renderTitle(rec);
    }).not.toThrow();
    expect(title).toContain("retrieval flagged low-confidence — thin");
    expect(title).not.toContain("category:");
    expect(title).not.toContain("rule:");
    expect(title).not.toContain("[object Object]");
    expect(error).not.toHaveBeenCalled();
  });

  it("detail never makes the badge appear: category/rule on a CLEAN row stays silent", () => {
    const rec = recordWith({
      neighbors: [{ id: "n1" }],
      relevance: {
        relevance: 0.81,
        low_confidence: false,
        category: "off_domain", // alarming-looking detail must not promote
        rule_fired: "off_domain_anchor_below_floor",
      },
    });
    expect(isLowEvidence(rec)).toBe(false);
    const { container } = render(<LowEvidenceBadge record={rec} />);
    expect(container).toBeEmptyDOMElement();
  });
});
