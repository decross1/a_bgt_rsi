// FORWARD-COMPAT regression pin (announced additive contract, 2026-06-09).
//
// The primary session announced ADDITIVE-ONLY data-contract changes (join
// contract from 0fdb671 FROZEN — no renames). The shapes that touch this
// surface (LowEvidenceBadge + RedFlagsTrendStrip):
//   - retrieval.relevance keeps {relevance, low_confidence, reason} and gains
//     OPTIONAL anchor_cosine (float|null), curated_overlap (float|null),
//     neighbor_spread (float|null), category ("off_domain"|"thin"|
//     "no_sharp_match"|"empty"|"ok"), rule_fired (string|null).
//   - critique.verdict gains "undecidable" (fail-closed; never promotes), plus
//     optional siblings verdict_overridden_from / override_reason /
//     skeptic_verdict.
//   - novelty gains OPTIONAL novelty_axes — an OBJECT inside novelty. Legacy
//     novelty.class remains (derived).
//
// THE CONTRACT THIS FILE PINS: isLowEvidence keys ONLY on
// retrieval.relevance.low_confidence === true OR an explicitly-present, EMPTY
// neighbors array. The five new relevance siblings must NOT change its verdict
// in EITHER direction — category="off_domain" with low_confidence=false must
// NOT fire; category="ok" with low_confidence=true MUST fire. The strip's
// rates must stay NaN-free over announced-shape rows, "undecidable" must never
// count as novel/survives, and no tooltip/label may leak an object.
//
// Announced-shape rows are INLINE literals cast through unknown (per the
// hand-off: types/schemas.ts and src/fixtures/ stay untouched until the
// primary's close-out confirms the shapes). jsdom stand-in for "renders
// without console errors": spy on console.error/warn, assert not called —
// same idiom as the test_harden_* files.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import LowEvidenceBadge, {
  isLowEvidence,
} from "../src/components/LowEvidenceBadge";
import RedFlagsTrendStrip from "../src/components/RedFlagsTrendStrip";
import type { IterationRecord } from "../src/types/schemas";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function watchConsole() {
  return {
    error: vi.spyOn(console, "error").mockImplementation(() => {}),
    warn: vi.spyOn(console, "warn").mockImplementation(() => {}),
  };
}

// Build a minimal record carrying an arbitrary retrieval/critique/novelty
// block. Cast through unknown so the test expresses the ANNOUNCED runtime
// shapes the current compile-time type does not yet know about.
function recordWith(blocks: Record<string, unknown>): IterationRecord {
  return {
    iteration_id: "iter-fwdcompat",
    started_at: "2026-06-09T00:00:00Z",
    ended_at: "2026-06-09T00:01:00Z",
    journal_entry_path: "journal/iterations/fwdcompat.md",
    ...blocks,
  } as unknown as IterationRecord;
}

// The full announced relevance sibling set, well-formed.
const NEW_SIBLINGS = {
  anchor_cosine: 0.31,
  curated_overlap: 0.0,
  neighbor_spread: 0.42,
  rule_fired: "off_domain_anchor_below_floor",
};

describe("forward-compat — isLowEvidence verdict is INSENSITIVE to the five new relevance siblings", () => {
  it("category='off_domain' (+ all four other siblings) with low_confidence=false must NOT fire", () => {
    const c = watchConsole();
    const rec = recordWith({
      retrieval: {
        k: 8,
        neighbors: [{ id: "n1" }, { id: "n2" }], // non-empty → no structural trigger
        relevance: {
          relevance: 0.22,
          low_confidence: false, // the AUTHORITATIVE signal says fine
          reason: "anchor below floor but worker did not flag",
          ...NEW_SIBLINGS,
          category: "off_domain", // alarming-looking sibling must not promote
        },
      },
    });
    expect(isLowEvidence(rec)).toBe(false);
    const { container } = render(<LowEvidenceBadge record={rec} />);
    expect(container).toBeEmptyDOMElement();
    expect(c.error).not.toHaveBeenCalled();
    expect(c.warn).not.toHaveBeenCalled();
  });

  it("category='ok' (+ healthy-looking siblings) with low_confidence=true MUST still fire", () => {
    const c = watchConsole();
    const rec = recordWith({
      retrieval: {
        k: 8,
        neighbors: [{ id: "n1" }],
        relevance: {
          relevance: 0.81,
          low_confidence: true, // authoritative signal fires
          reason: "thin: only 1 sharp neighbor",
          anchor_cosine: 0.92,
          curated_overlap: 0.7,
          neighbor_spread: 0.05,
          category: "ok", // reassuring-looking sibling must not demote
          rule_fired: null,
        },
      },
    });
    expect(isLowEvidence(rec)).toBe(true);
    render(<LowEvidenceBadge record={rec} />);
    const badge = screen.getByTestId("low-evidence-badge");
    expect(badge).toHaveTextContent(/low-evidence/i);
    // The string reason still folds into the tooltip; the new siblings do not
    // leak into it (no rendering of category/rule_fired is gated for later).
    const title = badge.getAttribute("title") ?? "";
    expect(title).toContain("thin: only 1 sharp neighbor");
    expect(title).not.toContain("[object Object]");
    expect(c.error).not.toHaveBeenCalled();
    expect(c.warn).not.toHaveBeenCalled();
  });

  it("the structural empty-neighbors trigger still fires with all new siblings present", () => {
    const c = watchConsole();
    const rec = recordWith({
      retrieval: {
        k: 8,
        neighbors: [], // explicitly-present empty → structural trigger
        relevance: {
          relevance: 0.0,
          low_confidence: false,
          reason: null,
          ...NEW_SIBLINGS,
          category: "empty",
        },
      },
    });
    expect(isLowEvidence(rec)).toBe(true);
    render(<LowEvidenceBadge record={rec} />);
    const title =
      screen.getByTestId("low-evidence-badge").getAttribute("title") ?? "";
    expect(title).toContain("0 retrieved neighbors");
    expect(title).not.toContain("[object Object]");
    expect(c.error).not.toHaveBeenCalled();
    expect(c.warn).not.toHaveBeenCalled();
  });

  it("every announced category value, with low_confidence=false and non-empty neighbors, stays silent", () => {
    for (const category of [
      "off_domain",
      "thin",
      "no_sharp_match",
      "empty",
      "ok",
      "some_future_category", // an unknown enum value tomorrow's worker could add
    ]) {
      const rec = recordWith({
        retrieval: {
          neighbors: [{ id: "n1" }],
          relevance: {
            relevance: 0.5,
            low_confidence: false,
            reason: null,
            ...NEW_SIBLINGS,
            category,
          },
        },
      });
      expect(isLowEvidence(rec), `category=${category}`).toBe(false);
    }
  });
});

// Garbled variants of the NEW fields a buggy/partial producer write could
// emit: the wrong TYPE in each new slot. None is read by this surface, so the
// verdict must still key only on low_confidence / empty-neighbors, never
// throw, and never dump junk into the human-facing tooltip.
const GARBLED_SIBLINGS: Array<[string, Record<string, unknown>]> = [
  ["category as an OBJECT", { category: { kind: "off_domain", score: 0.1 } }],
  ["category as an array", { category: ["off_domain", "thin"] }],
  ["anchor_cosine as a string", { anchor_cosine: "0.31" }],
  ["neighbor_spread as NaN", { neighbor_spread: NaN }],
  ["curated_overlap as Infinity", { curated_overlap: Infinity }],
  ["rule_fired as a number", { rule_fired: 404 }],
  [
    "all five garbled at once",
    {
      category: { kind: "off_domain" },
      anchor_cosine: "high",
      curated_overlap: [],
      neighbor_spread: NaN,
      rule_fired: { rule: "x" },
    },
  ],
];

describe("forward-compat — garbled NEW-field variants never throw, flip the verdict, or leak into the tooltip", () => {
  it.each(GARBLED_SIBLINGS)(
    "%s with low_confidence=false stays silent",
    (_label, garbled) => {
      const c = watchConsole();
      const rec = recordWith({
        retrieval: {
          neighbors: [{ id: "n1" }],
          relevance: { relevance: 0.5, low_confidence: false, ...garbled },
        },
      });
      expect(() => isLowEvidence(rec)).not.toThrow();
      expect(isLowEvidence(rec)).toBe(false);
      const { container } = render(<LowEvidenceBadge record={rec} />);
      expect(container).toBeEmptyDOMElement();
      expect(c.error).not.toHaveBeenCalled();
      expect(c.warn).not.toHaveBeenCalled();
    },
  );

  it.each(GARBLED_SIBLINGS)(
    "%s with low_confidence=true still fires, tooltip clean",
    (_label, garbled) => {
      const c = watchConsole();
      const rec = recordWith({
        retrieval: {
          neighbors: [{ id: "n1" }],
          relevance: {
            relevance: 0.1,
            low_confidence: true,
            reason: "off-domain anchor",
            ...garbled,
          },
        },
      });
      expect(isLowEvidence(rec)).toBe(true);
      const { container } = render(<LowEvidenceBadge record={rec} />);
      const badge = screen.getByTestId("low-evidence-badge");
      const title = badge.getAttribute("title") ?? "";
      expect(title).toContain("off-domain anchor");
      expect(title).not.toContain("[object Object]");
      expect(title).not.toContain("NaN");
      expect(title).not.toContain("Infinity");
      expect(container.innerHTML).not.toContain("[object Object]");
      expect(c.error).not.toHaveBeenCalled();
      expect(c.warn).not.toHaveBeenCalled();
    },
  );
});

describe("forward-compat — RedFlagsTrendStrip over announced-shape rows", () => {
  // Four announced-shape rows exercising every new block at once:
  //   r1: novel + survives + low_confidence=true (+ siblings) → novel, suspect, off-domain.
  //   r2: undecidable (+ override siblings) + low evidence → off-domain ONLY —
  //       "undecidable" is fail-closed and must NEVER count as novel/survives,
  //       so it cannot enter the suspected-false-novel numerator.
  //   r3: novel via novelty_axes-carrying novelty + clean retrieval → novel only.
  //   r4: known + survives + clean retrieval (+ healthy siblings) → suspect-free.
  const ROWS = [
    recordWith({
      novelty: {
        class: "novel",
        novelty_axes: {
          phenomenon: "novel",
          substrate: "unstudied_llm",
          predicted_direction: "silent",
        },
      },
      critique: { verdict: "survives" },
      retrieval: {
        neighbors: [{ id: "n1" }],
        relevance: {
          relevance: 0.2,
          low_confidence: true,
          reason: "off-domain",
          ...NEW_SIBLINGS,
          category: "off_domain",
        },
      },
    }),
    recordWith({
      novelty: {
        class: "known",
        novelty_axes: {
          phenomenon: "known",
          substrate: "studied_llm",
          predicted_direction: "matches",
        },
      },
      critique: {
        verdict: "undecidable",
        verdict_overridden_from: "survives",
        override_reason: "skeptic gate: evidence insufficient",
        skeptic_verdict: "undecidable",
      },
      retrieval: {
        neighbors: [{ id: "n1" }],
        relevance: {
          relevance: 0.3,
          low_confidence: true,
          reason: "thin",
          ...NEW_SIBLINGS,
          category: "thin",
        },
      },
    }),
    recordWith({
      novelty: {
        class: "novel",
        novelty_axes: {
          phenomenon: "novel",
          substrate: "na",
          predicted_direction: "deviates",
        },
      },
      critique: { verdict: "falsified" },
      retrieval: {
        neighbors: [{ id: "n1" }, { id: "n2" }],
        relevance: {
          relevance: 0.85,
          low_confidence: false,
          reason: null,
          anchor_cosine: 0.9,
          curated_overlap: 0.6,
          neighbor_spread: 0.1,
          category: "ok",
          rule_fired: null,
        },
      },
    }),
    recordWith({
      novelty: { class: "known" },
      critique: {
        verdict: "survives",
        verdict_overridden_from: null,
        override_reason: null,
        skeptic_verdict: "survives",
      },
      retrieval: {
        neighbors: [{ id: "n1" }],
        relevance: {
          relevance: 0.9,
          low_confidence: false,
          reason: null,
          anchor_cosine: 0.95,
          curated_overlap: 0.8,
          neighbor_spread: 0.04,
          category: "ok",
          rule_fired: null,
        },
      },
    }),
  ];

  it("computes exact NaN-free rates: undecidable never enters suspect; novelty_axes rows still count as novel", () => {
    const c = watchConsole();
    expect(() =>
      render(<RedFlagsTrendStrip iterations={ROWS} />),
    ).not.toThrow();
    expect(screen.getByTestId("red-flags-trend-strip")).toBeInTheDocument();
    expect(
      screen.getByText(/self-checks over 4 iterations/i),
    ).toBeInTheDocument();

    // Novel rate: r1 + r3 (novelty_axes present alongside class) → 2 of 4.
    const novel = within(screen.getByTestId("red-flag-novel-rate"));
    expect(novel.getByText("50%")).toBeInTheDocument();
    expect(novel.getByText("2 of 4")).toBeInTheDocument();

    // Suspected false-novel: ONLY r1 (novel/survives on low evidence). r2 is
    // low-evidence too, but its verdict is "undecidable" — fail-closed, never
    // promotes, so it must NOT inflate the trust metric.
    const suspect = within(
      screen.getByTestId("red-flag-suspected-false-novel"),
    );
    expect(suspect.getByText("25%")).toBeInTheDocument();
    expect(suspect.getByText("1 of 4")).toBeInTheDocument();

    // Off-domain / thin: r1 + r2 carry low_confidence=true → 2 of 4. The new
    // category strings must not add r3/r4 (category="ok" + low_confidence=false).
    const offDomain = within(screen.getByTestId("red-flag-off-domain"));
    expect(offDomain.getByText("50%")).toBeInTheDocument();
    expect(offDomain.getByText("2 of 4")).toBeInTheDocument();

    // No NaN anywhere, and no object leaked into a label.
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(document.body.innerHTML).not.toContain("[object Object]");
    expect(c.error).not.toHaveBeenCalled();
    expect(c.warn).not.toHaveBeenCalled();
  });

  it("a batch mixing announced-shape rows with garbled new-field variants stays NaN-free and quiet", () => {
    const c = watchConsole();
    const garbled = GARBLED_SIBLINGS.map(([, g], i) =>
      recordWith({
        iteration_id: `iter-garbled-${i}`,
        novelty: { class: "novel", novelty_axes: "oops" }, // axes as a STRING
        critique: { verdict: "undecidable", skeptic_verdict: { deep: true } },
        retrieval: {
          neighbors: [{ id: "n1" }],
          relevance: { relevance: 0.4, low_confidence: false, ...g },
        },
      }),
    );
    const rows = [...ROWS, ...garbled];
    expect(() =>
      render(<RedFlagsTrendStrip iterations={rows} />),
    ).not.toThrow();
    expect(screen.getByTestId("red-flags-trend-strip")).toBeInTheDocument();
    expect(
      screen.getByText(new RegExp(`self-checks over ${rows.length} iterations`, "i")),
    ).toBeInTheDocument();
    // The garbled rows are all low_confidence=false + undecidable → they add to
    // the denominator and the novel numerator only; suspect stays at r1 alone.
    const suspect = within(
      screen.getByTestId("red-flag-suspected-false-novel"),
    );
    expect(suspect.getByText(`1 of ${rows.length}`)).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(document.body.innerHTML).not.toContain("[object Object]");
    expect(c.error).not.toHaveBeenCalled();
    expect(c.warn).not.toHaveBeenCalled();
  });
});
