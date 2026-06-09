// Consolidated edge-case + property-fuzz hardening for LowEvidenceBadge (merged from per-round files).
//
// ---------------------------------------------------------------------------
// Round 2 (malformed value-TYPES) provenance:
//
// memory/loop_memory.jsonl is producer-owned: a buggy/legacy/partial row can
// emit the retrieval block with the wrong value TYPE for a field (a string
// where an object is expected, an array where a scalar is, null inside an
// array, NaN/Infinity, a garbage timestamp). The badge must NEVER throw, print
// "NaN", blank, or dump garbage into the human-facing tooltip on one bad row.
//
// The real bug this pins: `retrieval.relevance.reason` arriving as an OBJECT
// (or array/number) instead of a string. The tooltip builder used a template
// literal, so an object stringified to "[object Object]" and that landed in the
// `title` — the very text meant to explain *why* the verdict is suspect. The
// fix folds in `reason` only when it is a non-empty string (mirroring
// ResolvedIterationsList's seedTopic / conditioningBullets guards); otherwise
// it falls back to the bare "retrieval flagged low-confidence" phrase.
//
// ---------------------------------------------------------------------------
// Round 4 (unknown / forward-compatible + bad-row category) provenance:
//
// memory/loop_memory.jsonl is producer-owned and the backend forwards each row
// as-is: a bare `null` JSONL line round-trips to a `null` array element
// (backend/loop_v0.py _read_jsonl does NOT drop None — RedFlagsTrendStrip's own
// guard documents this). The `record: IterationRecord` type is a compile-time
// fiction over that unchecked stream; a `null`/`undefined`/primitive row reached
// both `isLowEvidence(record)` and `<LowEvidenceBadge record={...}>` and threw
// "Cannot read properties of null (reading 'retrieval')" — taking down whatever
// maps the badge/score over rows (the Dashboard's Red-flags strip, the resolved
// list). `isLowEvidence` is EXPORTED and consumed by RedFlagsTrendStrip; the
// only prior protection was every caller remembering to pre-filter non-objects,
// so the fix guards the source: a non-object row carries no retrieval signal →
// conservative false (no throw, no badge), matching AgentBadge / SourceBadge's
// "treat a wrong type as absent" stance.
//
// This is the gap round-2 (malformed value-TYPES) missed: round-2 always wrapped
// a real record object, so it never exercised a null/primitive RECORD. Pairs
// with the round-4 forward-compat sweep — an unknown enum value or a partial row
// must render generically, never crash the page on one bad row.
//
// No headless browser in this stack, so "renders without console errors" is the
// jsdom stand-in: render and assert console.error / console.warn were not called.
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
    iteration_id: "iter-harden-r2",
    started_at: "2026-06-09T00:00:00Z",
    ended_at: "2026-06-09T00:01:00Z",
    journal_entry_path: "journal/iterations/harden-r2.md",
    retrieval,
  } as unknown as IterationRecord;
}

// Bad ROWS a real JSONL producer can hand the UI but the IterationRecord type
// forbids at compile time. Cast through unknown so the test can express them.
// A null line is the headline case; the primitives/array cover the rest of the
// "row is not an object" surface so the source guard is proven broadly.
const BAD_ROWS: Array<[string, unknown]> = [
  ["null (a bare `null` JSONL line)", null],
  ["undefined", undefined],
  ["a string row", "garbage-row"],
  ["a number row", 42],
  ["a boolean row", true],
  ["NaN", NaN],
  ["an array row", [1, 2, 3]],
];

describe("LowEvidenceBadge hardening — malformed value TYPES (round-2)", () => {
  describe("LowEvidenceBadge — malformed value TYPES (round-2 hardening)", () => {
    it("the regression: an OBJECT reason does not leak [object Object] into the tooltip", () => {
      const c = watchConsole();
      // low_confidence is correctly true (the badge fires), but `reason` is an
      // object — the exact shape that used to dump "[object Object]" into title.
      const { container } = render(
        <LowEvidenceBadge
          record={recordWith({ relevance: { low_confidence: true, reason: { x: 1 } } })}
        />,
      );
      const badge = screen.getByTestId("low-evidence-badge");
      // Still fires (the verdict IS low-evidence) …
      expect(badge).toHaveTextContent(/low-evidence/i);
      // … but the tooltip degrades cleanly to the bare phrase, never garbage.
      const title = badge.getAttribute("title") ?? "";
      expect(title).not.toContain("[object Object]");
      expect(title).toContain("retrieval flagged low-confidence");
      expect(container.innerHTML).not.toContain("[object Object]");
      expect(c.error).not.toHaveBeenCalled();
      expect(c.warn).not.toHaveBeenCalled();
    });

    it("array / number / NaN / Infinity reasons also degrade to the bare phrase (no junk in title)", () => {
      for (const reason of [
        ["off-domain", null, 3] as unknown,
        12345,
        NaN,
        Infinity,
        { nested: { deep: true } },
      ]) {
        const c = watchConsole();
        const { unmount } = render(
          <LowEvidenceBadge
            record={recordWith({ relevance: { low_confidence: true, reason } })}
          />,
        );
        const title =
          screen.getByTestId("low-evidence-badge").getAttribute("title") ?? "";
        expect(title).toContain("retrieval flagged low-confidence");
        // No "[object Object]", no stray "NaN"/"Infinity" leaking from a coerced
        // non-string reason.
        expect(title).not.toContain("[object Object]");
        expect(title).not.toContain("NaN");
        expect(title).not.toContain("Infinity");
        expect(c.error).not.toHaveBeenCalled();
        expect(c.warn).not.toHaveBeenCalled();
        unmount();
      }
    });

    it("a legitimate string reason is STILL folded into the tooltip (fix didn't over-suppress)", () => {
      watchConsole();
      render(
        <LowEvidenceBadge
          record={recordWith({
            relevance: {
              low_confidence: true,
              reason: "off-domain: code-quality vs game-theory corpus",
            },
          })}
        />,
      );
      const title =
        screen.getByTestId("low-evidence-badge").getAttribute("title") ?? "";
      expect(title).toContain("off-domain: code-quality vs game-theory corpus");
    });

    it("wrong-TYPE retrieval / relevance / neighbors never throw and render no badge", () => {
      // retrieval or relevance arriving as a string/number/array/boolean (object
      // expected), neighbors as a non-array, low_confidence as a stringy/number
      // truthy. None of these is a genuine low_confidence===true signal, so the
      // conservative guard renders nothing — and crucially never throws.
      const malformed: unknown[] = [
        "thin", // retrieval is a string
        42, // retrieval is a number
        [], // retrieval is an array
        [1, 2, 3], // retrieval is a populated array
        true, // retrieval is a boolean
        NaN, // retrieval is NaN
        { relevance: "low" }, // relevance is a string
        { relevance: [1, 2] }, // relevance is an array
        { relevance: 0.04 }, // relevance is a number
        { relevance: { low_confidence: "true" } }, // stringy boolean — NOT === true
        { relevance: { low_confidence: 1 } }, // numeric truthy — NOT === true
        { relevance: { low_confidence: NaN } }, // NaN — NOT === true
        { relevance: null }, // explicit null relevance
        { neighbors: "none" }, // neighbors is a string
        { neighbors: {} }, // neighbors is an object
        { neighbors: 0 }, // neighbors is a number
      ];
      for (const retrieval of malformed) {
        const c = watchConsole();
        const rec = recordWith(retrieval);
        expect(() => isLowEvidence(rec)).not.toThrow();
        // None of these is a real low-evidence signal → conservative false → no badge.
        expect(isLowEvidence(rec)).toBe(false);
        const { container, unmount } = render(<LowEvidenceBadge record={rec} />);
        expect(container).toBeEmptyDOMElement();
        expect(container.innerHTML).not.toContain("NaN");
        expect(c.error).not.toHaveBeenCalled();
        expect(c.warn).not.toHaveBeenCalled();
        unmount();
      }
    });

    it("null inside the neighbors array and a garbage timestamp still render the badge cleanly", () => {
      const c = watchConsole();
      // neighbors is a present-but-empty array (the structural empty-retrieval
      // trigger) carried on a row with garbage ISO timestamps the badge never
      // parses — must fire the badge and not throw / print NaN.
      const rec = recordWith({ k: 8, neighbors: [] });
      (rec as { started_at: string }).started_at = "not-a-real-date";
      (rec as { ended_at: string }).ended_at = "🙃garbage🙃";
      expect(isLowEvidence(rec)).toBe(true);
      const { container } = render(<LowEvidenceBadge record={rec} />);
      expect(screen.getByTestId("low-evidence-badge")).toHaveTextContent(
        /low-evidence/i,
      );
      expect(container.innerHTML).not.toContain("NaN");
      expect(c.error).not.toHaveBeenCalled();
      expect(c.warn).not.toHaveBeenCalled();
    });
  });
});

describe("LowEvidenceBadge hardening — non-object / null RECORD (round-4)", () => {
  describe("LowEvidenceBadge — non-object / null RECORD (round-4 hardening)", () => {
    it("the regression: isLowEvidence does NOT throw on a null/undefined/primitive row", () => {
      for (const [name, row] of BAD_ROWS) {
        expect(
          () => isLowEvidence(row as unknown as IterationRecord),
          name,
        ).not.toThrow();
        // No retrieval signal can exist on a non-object → conservative false.
        expect(isLowEvidence(row as unknown as IterationRecord), name).toBe(false);
      }
    });

    it("renders nothing (no badge, no throw, no console.error) for every bad row", () => {
      for (const [name, row] of BAD_ROWS) {
        const c = watchConsole();
        const { container, unmount } = render(
          <LowEvidenceBadge record={row as unknown as IterationRecord} />,
        );
        // A bad row is not a low-evidence verdict → the badge stays silent rather
        // than crashing the surface that maps over rows.
        expect(container, name).toBeEmptyDOMElement();
        expect(container.innerHTML, name).not.toContain("[object Object]");
        expect(container.innerHTML, name).not.toContain("NaN");
        expect(c.error, name).not.toHaveBeenCalled();
        expect(c.warn, name).not.toHaveBeenCalled();
        unmount();
      }
    });

    it("the fix did not over-suppress: a real low-evidence row still fires and a clean one still stays silent", () => {
      const c = watchConsole();
      // A genuine low_confidence:true row must STILL produce the amber badge — the
      // guard only neutralizes non-object rows, it does not blunt a real signal.
      const lowEvidence = {
        iteration_id: "iter-harden-r4-live",
        started_at: "2026-06-09T00:00:00Z",
        ended_at: "2026-06-09T00:01:00Z",
        journal_entry_path: "journal/iterations/harden-r4.md",
        retrieval: { relevance: { low_confidence: true, reason: "off-domain" } },
      } as unknown as IterationRecord;
      const { unmount } = render(<LowEvidenceBadge record={lowEvidence} />);
      expect(screen.getByTestId("low-evidence-badge")).toHaveTextContent(
        /low-evidence/i,
      );
      expect(c.error).not.toHaveBeenCalled();
      expect(c.warn).not.toHaveBeenCalled();
      unmount();

      // And a clean object row (no signal) still renders nothing.
      const clean = {
        iteration_id: "iter-harden-r4-clean",
        started_at: "2026-06-09T00:00:00Z",
        ended_at: "2026-06-09T00:01:00Z",
        journal_entry_path: "journal/iterations/clean-r4.md",
        retrieval: { relevance: { relevance: 0.81, low_confidence: false } },
      } as unknown as IterationRecord;
      const { container } = render(<LowEvidenceBadge record={clean} />);
      expect(screen.queryByTestId("low-evidence-badge")).toBeNull();
      expect(container).toBeEmptyDOMElement();
    });
  });
});
