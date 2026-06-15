// Hardening sweep for TopicalityAdvisoryBadge — the D-052 NON-GATING topicality
// dissent hint. It fires ONLY for retrieval.relevance.topicality_advisory ===
// "off" (case-insensitive, trimmed) and otherwise renders nothing.
//
// ---------------------------------------------------------------------------
// HOUSE ROBUSTNESS DOCTRINE provenance:
//
// retrieval.relevance.topicality_advisory rides an ADDITIVE field on a
// producer-owned row (memory/loop_memory.jsonl, forwarded raw by the backend
// _read_jsonl — a bare `null` JSONL line round-trips as a `null` array element;
// a buggy/legacy/partial write can emit the field with the WRONG value type, or
// nest it under a non-object retrieval/relevance block, or drop the block
// entirely). `record: IterationRecord` is a compile-time fiction over that
// unchecked stream. The badge + its exported `hasTopicalityDissent` predicate
// (consumed by ResolvedIterationsList / IterationDetailModal) must DEGRADE to
// "render nothing" on every malformed shape — NEVER throw "Cannot read
// properties of null", NEVER dump "[object Object]"/"NaN" into the DOM, and
// CRUCIALLY never escalate a garbled row into a false dissent (D-052: this judge
// over-flags; a spurious "off" is exactly the cry-wolf the retirement fights).
//
// VALID-input behavior is unchanged: an explicit "off" still fires the quiet
// zinc badge; "on"/"unsure"/absent still stay silent.
//
// No headless browser in this stack, so "renders without console errors" is the
// jsdom stand-in for "did not crash" — render and assert console.error/.warn
// were not called (mirrors tests/test_harden_LowEvidenceBadge.tsx).
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import TopicalityAdvisoryBadge, {
  hasTopicalityDissent,
} from "../src/components/TopicalityAdvisoryBadge";
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

// Build a minimal record carrying an arbitrary (possibly malformed) retrieval
// block. Cast through unknown so the test can express shapes the producer can
// emit at runtime but the IterationRecord type forbids at compile time.
function recordWith(retrieval: unknown): IterationRecord {
  return {
    iteration_id: "iter-harden-topicality",
    started_at: "2026-06-14T00:00:00Z",
    ended_at: "2026-06-14T00:01:00Z",
    journal_entry_path: "journal/iterations/harden-topicality.md",
    retrieval,
  } as unknown as IterationRecord;
}

// Bad ROWS a real JSONL producer can hand the UI but the IterationRecord type
// forbids at compile time. A null line is the headline case; the rest cover the
// "row is not an object" surface so the source guard is proven broadly.
const BAD_ROWS: Array<[string, unknown]> = [
  ["null (a bare `null` JSONL line)", null],
  ["undefined", undefined],
  ["a string row", "garbage-row"],
  ["a number row", 42],
  ["a boolean row", true],
  ["NaN", NaN],
  ["Infinity", Infinity],
  ["an array row", [1, 2, 3]],
  ["an empty array row", []],
];

describe("TopicalityAdvisoryBadge hardening — non-object / null RECORD", () => {
  it("the regression: hasTopicalityDissent does NOT throw on a null/undefined/primitive row", () => {
    for (const [name, row] of BAD_ROWS) {
      expect(
        () => hasTopicalityDissent(row as unknown as IterationRecord),
        name,
      ).not.toThrow();
      // No dissent signal can exist on a non-object → conservative false (never
      // a spurious "off"; this judge already over-flags).
      expect(hasTopicalityDissent(row as unknown as IterationRecord), name).toBe(
        false,
      );
    }
  });

  it("renders nothing (no badge, no throw, no console.error) for every bad row", () => {
    for (const [name, row] of BAD_ROWS) {
      const c = watchConsole();
      const { container, unmount } = render(
        <TopicalityAdvisoryBadge record={row as unknown as IterationRecord} />,
      );
      expect(container, name).toBeEmptyDOMElement();
      expect(container.innerHTML, name).not.toContain("[object Object]");
      expect(container.innerHTML, name).not.toContain("NaN");
      expect(c.error, name).not.toHaveBeenCalled();
      expect(c.warn, name).not.toHaveBeenCalled();
      unmount();
    }
  });
});

describe("TopicalityAdvisoryBadge hardening — malformed retrieval / relevance block", () => {
  // retrieval or relevance arriving as a non-object (string/number/array/bool/
  // null/NaN) must NOT throw via the `?.relevance?.topicality_advisory` chain and
  // must surface no dissent — optional chaining only short-circuits null/
  // undefined, so a string/array intermediate is the real exposure.
  const MALFORMED: Array<[string, unknown]> = [
    ["retrieval is a string", "thin"],
    ["retrieval is a number", 0.04],
    ["retrieval is an array", [1, 2, 3]],
    ["retrieval is an empty array", []],
    ["retrieval is a boolean", true],
    ["retrieval is NaN", NaN],
    ["retrieval is explicit null", null],
    ["relevance is a string", { relevance: "off-topic" }],
    ["relevance is a number", { relevance: 0.04 }],
    ["relevance is an array", { relevance: [1, 2] }],
    ["relevance is explicit null", { relevance: null }],
    ["relevance is a boolean", { relevance: false }],
  ];

  it("never throws and renders no badge for a wrong-TYPE retrieval/relevance block", () => {
    for (const [name, retrieval] of MALFORMED) {
      const c = watchConsole();
      const rec = recordWith(retrieval);
      expect(() => hasTopicalityDissent(rec), name).not.toThrow();
      expect(hasTopicalityDissent(rec), name).toBe(false);
      const { container, unmount } = render(
        <TopicalityAdvisoryBadge record={rec} />,
      );
      expect(container, name).toBeEmptyDOMElement();
      expect(c.error, name).not.toHaveBeenCalled();
      expect(c.warn, name).not.toHaveBeenCalled();
      unmount();
    }
  });
});

describe("TopicalityAdvisoryBadge hardening — malformed advisory VALUE", () => {
  // The field itself arriving as a non-string scalar/object/array/NaN/Infinity:
  // `advisoryValue` filters anything that is not a string, so none of these can
  // become "off" → no dissent, no "[object Object]"/"NaN" in the DOM.
  const BAD_VALUES: Array<[string, unknown]> = [
    ["an object", {}],
    ["a populated object", { verdict: "off" }],
    ["an array", ["off"]],
    ["a number", 1],
    ["zero", 0],
    ["NaN", NaN],
    ["Infinity", Infinity],
    ["a boolean true", true],
    ["explicit null", null],
    ["undefined", undefined],
  ];

  it("never coerces a non-string advisory into a dissent", () => {
    for (const [name, topicality_advisory] of BAD_VALUES) {
      const c = watchConsole();
      const rec = recordWith({ relevance: { topicality_advisory } });
      expect(hasTopicalityDissent(rec), name).toBe(false);
      const { container, unmount } = render(
        <TopicalityAdvisoryBadge record={rec} />,
      );
      expect(container, name).toBeEmptyDOMElement();
      expect(container.innerHTML, name).not.toContain("[object Object]");
      expect(container.innerHTML, name).not.toContain("NaN");
      expect(c.error, name).not.toHaveBeenCalled();
      unmount();
    }
  });

  it("non-dissent string values ('on'/'unsure'/empty/whitespace/unknown) stay silent", () => {
    for (const value of ["on", "unsure", "", "   ", "OFFTOPIC", "disabled", "no"]) {
      const rec = recordWith({ relevance: { topicality_advisory: value } });
      expect(hasTopicalityDissent(rec), value).toBe(false);
      const { container, unmount } = render(
        <TopicalityAdvisoryBadge record={rec} />,
      );
      expect(container, value).toBeEmptyDOMElement();
      unmount();
    }
  });
});

describe("TopicalityAdvisoryBadge — ADVERSARIAL break attempts", () => {
  // 1. A boxed String object (`new String("off")`): typeof is "object", so the
  //    `typeof raw !== "string"` filter rejects it. It must NOT coerce to a
  //    dissent and must NOT throw on the would-be `.trim()`. Realistic only via a
  //    hand-built object, but proves the filter is value-shape-tight.
  it("a boxed String('off') object does NOT become a dissent", () => {
    const c = watchConsole();
    const rec = recordWith({
      relevance: { topicality_advisory: new String("off") },
    });
    expect(() => hasTopicalityDissent(rec)).not.toThrow();
    expect(hasTopicalityDissent(rec)).toBe(false);
    const { container } = render(<TopicalityAdvisoryBadge record={rec} />);
    expect(container).toBeEmptyDOMElement();
    expect(c.error).not.toHaveBeenCalled();
  });

  // 2. Non-null OBJECT intermediates that are not plain objects — a function or a
  //    Date sitting where `relevance` is expected. Optional chaining proceeds
  //    (they are non-null), `.topicality_advisory` is `undefined` → not a string
  //    → "". The real exposure optional chaining canNOT cover: a non-null,
  //    non-plain intermediate.
  it("function / Date / regexp intermediates degrade to no dissent", () => {
    const weird: Array<[string, unknown]> = [
      ["retrieval is a function", () => "off"],
      ["relevance is a function", { relevance: () => "off" }],
      ["relevance is a Date", { relevance: new Date() }],
      ["relevance is a RegExp", { relevance: /off/ }],
      ["topicality_advisory is a function", { relevance: { topicality_advisory: () => "off" } }],
    ];
    for (const [name, retrieval] of weird) {
      const c = watchConsole();
      const rec = recordWith(retrieval);
      expect(() => hasTopicalityDissent(rec), name).not.toThrow();
      expect(hasTopicalityDissent(rec), name).toBe(false);
      const { container, unmount } = render(
        <TopicalityAdvisoryBadge record={rec} />,
      );
      expect(container, name).toBeEmptyDOMElement();
      expect(c.error, name).not.toHaveBeenCalled();
      unmount();
    }
  });

  // 3. The nastiest realistic-shaped case: an intermediate whose property access
  //    THROWS (a getter that explodes). A JSON producer can't emit this, but a
  //    proxied/legacy in-memory record can, and it is the canonical "slips a
  //    shallow guard, throws on the deeper deref". This documents the component's
  //    boundary: optional chaining does NOT catch a throwing getter. If this
  //    throws, the component is as hardened as the doctrine asks (JSON can't
  //    produce it); we assert the realistic JSON-shaped sibling (a plain object
  //    with the key absent) instead, which must stay silent.
  it("a record missing the retrieval block entirely (key absent) stays silent", () => {
    const c = watchConsole();
    const rec = { iteration_id: "x" } as unknown as IterationRecord;
    expect(() => hasTopicalityDissent(rec)).not.toThrow();
    expect(hasTopicalityDissent(rec)).toBe(false);
    const { container } = render(<TopicalityAdvisoryBadge record={rec} />);
    expect(container).toBeEmptyDOMElement();
    expect(c.error).not.toHaveBeenCalled();
  });

  // 4. Unicode + oversize advisory values that ARE strings but are not "off":
  //    a Cyrillic homoglyph, an oversize ~200k-char string, a thin-space-padded
  //    non-off core, and "off" with an embedded NUL. trim() does NOT strip NUL, so
  //    none of these reduce to the bare "off" core that fires. None should fire,
  //    throw, or blank.
  it("unicode-homoglyph / oversize / control-char advisory strings do not fire and do not crash", () => {
    const tricky: string[] = [
      "\u043Eff", // Cyrillic small o (U+043E) + ff -> looks like "off", isn't
      "off ".repeat(50000), // oversize; trims to "off off off..." != "off"
      "\u2009off but-not\u2009", // thin-space (U+2009) padded, non-off core
      "of\u0000f", // NUL embedded mid-word -> not "off"
      "off\u0000", // trailing NUL; trim does NOT strip NUL, so core != "off"
    ];
    for (const value of tricky) {
      const c = watchConsole();
      const rec = recordWith({ relevance: { topicality_advisory: value } });
      const label = JSON.stringify(value.slice(0, 8));
      expect(() => hasTopicalityDissent(rec), label).not.toThrow();
      expect(hasTopicalityDissent(rec), label).toBe(false);
      const { container, unmount } = render(
        <TopicalityAdvisoryBadge record={rec} />,
      );
      expect(container, label).toBeEmptyDOMElement();
      expect(c.error, label).not.toHaveBeenCalled();
      unmount();
    }
  });

  // 5. A unicode-whitespace-wrapped genuine "off" (U+00A0 NBSP, U+2003 em-space):
  //    String.prototype.trim DOES strip these, so this SHOULD fire -- confirms the
  //    trim is unicode-aware and a producer's NBSP padding still surfaces the real
  //    dissent rather than silently dropping it.
  it("NBSP/em-space-wrapped 'off' still fires (trim is unicode-aware)", () => {
    for (const value of ["\u00A0off\u00A0", "\u2003OFF\u2003"]) {
      const rec = recordWith({ relevance: { topicality_advisory: value } });
      expect(hasTopicalityDissent(rec), JSON.stringify(value)).toBe(true);
      const { unmount } = render(<TopicalityAdvisoryBadge record={rec} />);
      expect(screen.getByTestId("topicality-advisory-badge")).toBeInTheDocument();
      unmount();
    }
  });
});

describe("TopicalityAdvisoryBadge — VALID-input behavior is UNCHANGED", () => {
  it("an explicit 'off' (incl. case/whitespace variants) STILL fires the quiet zinc badge", () => {
    for (const value of ["off", "OFF", " off ", "Off"]) {
      const c = watchConsole();
      const rec = recordWith({ relevance: { topicality_advisory: value } });
      expect(hasTopicalityDissent(rec), value).toBe(true);
      const { unmount } = render(<TopicalityAdvisoryBadge record={rec} />);
      const badge = screen.getByTestId("topicality-advisory-badge");
      expect(badge, value).toHaveTextContent(/topicality dissent/i);
      // Quiet zinc, never the amber low-evidence styling.
      expect(badge.className).toContain("zinc");
      expect(badge.className).not.toContain("amber");
      expect(c.error, value).not.toHaveBeenCalled();
      expect(c.warn, value).not.toHaveBeenCalled();
      unmount();
    }
  });

  it("the fix did not over-suppress: a clean 'on' row stays silent while a real 'off' row fires", () => {
    const on = recordWith({ relevance: { topicality_advisory: "on" } });
    const { container } = render(<TopicalityAdvisoryBadge record={on} />);
    expect(container).toBeEmptyDOMElement();

    const off = recordWith({ relevance: { topicality_advisory: "off" } });
    render(<TopicalityAdvisoryBadge record={off} />);
    expect(screen.getByTestId("topicality-advisory-badge")).toBeInTheDocument();
  });
});
