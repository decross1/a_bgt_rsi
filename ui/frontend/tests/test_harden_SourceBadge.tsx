// Consolidated edge-case + property-fuzz hardening for SourceBadge (merged from per-round files).
//
// ── round 1 (wrong-TYPE) ─────────────────────────────────────────────────────
// Adversarial hardening (round 1) — SourceBadge against a MALFORMED, producer-
// owned `source`. seed.source / topic_source are parsed straight from a
// gitignored, producer-owned JSONL file; the `string | null` type is a
// compile-time fiction. A legacy or buggy row can put a number, boolean,
// object, or array where a string was meant. Before this guard, the
// optional-chained `source?.trim()` only covered null/undefined — a non-null
// non-string hit `.trim()` (undefined) and threw `TypeError: source?.trim is
// not a function`, crashing the WHOLE CoordinatorCycleCard / ResolvedIterations
// list on a single bad row (the page goes blank — exactly the failure mode the
// "make absence legible" view exists to prevent).
//
// These tests pin: (1) the component never throws / NaNs on any non-string;
// (2) sourceTone (exported) is equally guarded; (3) a real card with a
// malformed topic_source still renders, without a React console.error/warn
// (no headless browser — jsdom + a console spy is the stand-in for "renders
// clean"). The happy-path tones live in test_source_badge.tsx; this file is
// the malformed-input regression only.
//
// ── round 3 (SCALE + CONTENT) ────────────────────────────────────────────────
// Adversarial hardening (round 3) — SourceBadge against the SCALE + CONTENT
// category of producer-owned `source` values. seed.source / topic_source are
// freeform strings parsed straight from a gitignored, producer-owned JSONL
// file, so beyond the wrong-TYPE cases (round 1) the *content* of a string can
// itself be hostile: a value that collides with an inherited Object.prototype
// member name, an enormous unbroken token, or unicode/emoji/RTL/newlines/
// HTML-looking text.
//
// The real bug this file pins (and fixes): a `source` of "toString" /
// "constructor" / "__proto__" / "valueOf" / "hasOwnProperty" is a plausible
// freeform string a producer could emit. Before the guard, `TONE[value]` and
// `LABEL[value]` resolved to a FUNCTION via the prototype chain instead of
// undefined, so the `?? QUIET` / `?? source` fallbacks never fired:
//   - the tone function interpolated into className as
//     "function toString() { [native code] }" (broken styling), and
//   - the label function reached the DOM as a React child, which React rejects
//     with a console.error ("Functions are not valid as a React child") while
//     the provenance label silently vanished.
// One such row in `loop_memory.jsonl` / `coordinator_cycles.jsonl` would log a
// React error and blank the badge — the exact "one bad row degrades the page"
// failure the autonomy views exist to prevent. AgentBadge already guards this;
// SourceBadge now does too (own-key lookup). The happy-path tones live in
// test_source_badge.tsx; the wrong-type cases in the round-1 describe below;
// this round is the scale + content regression only.
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SourceBadge, { sourceTone } from "../src/components/SourceBadge";
import CoordinatorCycleCard from "../src/components/CoordinatorCycleCard";
import { COORDINATOR_CYCLES_FIXTURE } from "../src/fixtures/coordinator";
import type { CoordinatorCycle } from "../src/types/schemas";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SourceBadge hardening — round 1 (malformed / wrong-type source)", () => {
  // Cast helper — these values are illegal per the prop type but legal in the
  // JSONL the producer actually writes; the runtime must survive them.
  const bad = (v: unknown) => v as unknown as string;

  describe("SourceBadge — malformed (non-string) source never crashes", () => {
    // The crash repro: each of these threw `source?.trim is not a function`
    // before the asText guard. A finite number / boolean stringifies and shows
    // raw (consistent with "unknown source renders raw"); an object / array /
    // NaN has no usable provenance label, so the badge renders nothing rather
    // than `[object Object]` — but in NO case does it throw.
    it("renders a finite number source raw (quiet zinc), not a crash", () => {
      render(<SourceBadge source={bad(42)} />);
      const badge = screen.getByTestId("source-badge");
      expect(badge).toHaveTextContent("42");
      expect(badge.className).toContain("zinc");
      // No NaN leaks into the rendered text.
      expect(badge.textContent ?? "").not.toMatch(/NaN/);
    });

    it("renders a boolean source raw, not a crash", () => {
      render(<SourceBadge source={bad(false)} />);
      const badge = screen.getByTestId("source-badge");
      expect(badge).toHaveTextContent("false");
      expect(badge.className).toContain("zinc");
    });

    it("renders NOTHING (no badge) for an object / array / NaN source, not a crash", () => {
      const { rerender } = render(<SourceBadge source={bad({ cli: true })} />);
      expect(screen.queryByTestId("source-badge")).toBeNull();

      rerender(<SourceBadge source={bad(["arxiv_pick"])} />);
      expect(screen.queryByTestId("source-badge")).toBeNull();
      // The garbage stringification must never reach the DOM.
      expect(document.body.textContent ?? "").not.toContain("[object Object]");

      rerender(<SourceBadge source={bad(Number.NaN)} />);
      expect(screen.queryByTestId("source-badge")).toBeNull();
    });

    it("none of the malformed inputs throw", () => {
      for (const v of [42, 0, -1, Number.NaN, Infinity, true, false, {}, [], { a: 1 }, [1, 2]]) {
        expect(() => render(<SourceBadge source={bad(v)} />)).not.toThrow();
      }
    });
  });

  describe("sourceTone — malformed (non-string) source returns a tone, never throws", () => {
    it("falls back to quiet zinc for any non-string, without throwing", () => {
      for (const v of [42, Number.NaN, true, false, {}, [], { x: 1 }]) {
        expect(() => sourceTone(bad(v))).not.toThrow();
        expect(sourceTone(bad(v))).toContain("zinc");
      }
    });
  });

  describe("CoordinatorCycleCard — a bad topic_source does not take the card down", () => {
    // The whole point of the guard: the card is the real consumer
    // (<SourceBadge source={cycle.topic_source} />). A single legacy/malformed
    // row's topic_source must NOT blank the card or log a React error — the rest
    // of the cycle (topic, agent, outcomes) must still render.
    const malformedCycle: CoordinatorCycle = {
      ...COORDINATOR_CYCLES_FIXTURE[1],
      run_id: "cyc-malformed-topic-source",
      // A producer bug: topic_source is a number, not the provenance string.
      topic_source: bad(7),
    };

    it("renders the card (and its other content) without React/console errors", () => {
      const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      render(<CoordinatorCycleCard cycle={malformedCycle} />);

      // The card itself survived the bad row — not a blank page.
      expect(screen.getByTestId("coordinator-cycle-card")).toBeInTheDocument();
      // And the rest of the cycle narrative is intact.
      expect(screen.getByText(malformedCycle.topic)).toBeInTheDocument();
      // The topic-source cell still exists; the badge inside is just a raw "7".
      const cell = screen.getByTestId("coordinator-topic-source");
      expect(within(cell).getByTestId("source-badge")).toHaveTextContent("7");

      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });

    it("survives an object topic_source by dropping the badge, card still renders clean", () => {
      const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      const objCycle: CoordinatorCycle = {
        ...COORDINATOR_CYCLES_FIXTURE[1],
        run_id: "cyc-object-topic-source",
        topic_source: bad({ source: "arxiv_pick" }),
      };
      render(<CoordinatorCycleCard cycle={objCycle} />);

      expect(screen.getByTestId("coordinator-cycle-card")).toBeInTheDocument();
      // No badge (object has no provenance label) but no garbage and no error.
      const cell = screen.getByTestId("coordinator-topic-source");
      expect(within(cell).queryByTestId("source-badge")).toBeNull();
      expect(document.body.textContent ?? "").not.toContain("[object Object]");
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });
  });
});

describe("SourceBadge hardening — round 3 (scale + hostile content)", () => {
  // Inherited Object.prototype member names — legal freeform strings, but each
  // collides with a key that lives on the prototype of TONE/LABEL (plain object
  // maps). These are the ones that caused the bug.
  const PROTO_KEYS = [
    "toString",
    "constructor",
    "__proto__",
    "valueOf",
    "hasOwnProperty",
    "isPrototypeOf",
    "propertyIsEnumerable",
  ];

  describe("SourceBadge — prototype-collision source values (content)", () => {
    it("renders proto-key sources as a raw quiet-zinc badge — no function in className, no blank text", () => {
      for (const key of PROTO_KEYS) {
        const { unmount } = render(<SourceBadge source={key} />);
        const badge = screen.getByTestId("source-badge");
        // The QUIET fallback actually fired: zinc, and NO leaked function source.
        expect(badge.className).toContain("zinc");
        expect(badge.className).not.toMatch(/function/);
        expect(badge.className).not.toContain("[native code]");
        // The provenance label is the raw string, not an empty/blank node and not
        // a coerced function body.
        expect(badge).toHaveTextContent(key);
        expect(badge.textContent ?? "").not.toMatch(/native code/);
        unmount();
      }
    });

    it("sourceTone returns a real zinc tone string (never a function) for a proto-key", () => {
      for (const key of PROTO_KEYS) {
        const tone = sourceTone(key);
        expect(typeof tone).toBe("string");
        expect(tone).toContain("zinc");
        expect(tone).not.toMatch(/function|native code/);
      }
    });

    it("does not log a React console.error on a proto-key source (the headline regression)", () => {
      const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
      for (const key of PROTO_KEYS) {
        const { unmount } = render(<SourceBadge source={key} />);
        unmount();
      }
      // Before the fix, "Functions are not valid as a React child." fired here.
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });
  });

  describe("SourceBadge — scale + hostile-content strings never crash or dirty the surface", () => {
    it("a single very long unbroken string (5k chars) renders raw without throwing or warning", () => {
      const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
      const big = "x".repeat(5000);
      expect(() => render(<SourceBadge source={big} />)).not.toThrow();
      const badge = screen.getByTestId("source-badge");
      // It is treated as an unknown source: shown raw (forward-compat), quiet zinc.
      expect(badge.className).toContain("zinc");
      expect((badge.textContent ?? "").length).toBe(5000);
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });

    it("unicode / emoji / RTL / newlines / HTML-looking content renders as inert text (no injection, no throw, no error)", () => {
      const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
      const samples = [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "نص عربي مع اتجاه RTL", // Arabic / RTL
        "emoji 🤖🔥🧪 mix",
        "line1\nline2\nline3",
        "tab\there",
        "{}}{<>&\"'`",
        "‮evil-rtl-override‬", // bidi override controls
      ];
      for (const s of samples) {
        const { unmount } = render(<SourceBadge source={s} />);
        const badge = screen.getByTestId("source-badge");
        // React escapes — the raw string lands as a text node, never parsed HTML.
        expect(badge).toHaveTextContent(s, { normalizeWhitespace: false });
        // No HTML element was injected by any sample.
        expect(document.querySelector("script")).toBeNull();
        expect(document.querySelector("img")).toBeNull();
        unmount();
      }
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });

    it("a trailing-newline KNOWN source still maps to its headline label (asText trims)", () => {
      // "nemoclaw_agent\n" is a content edge that must still resolve to the violet
      // headline, not fall through to a raw render.
      render(<SourceBadge source={"nemoclaw_agent\n"} />);
      const badge = screen.getByTestId("source-badge");
      expect(badge.className).toContain("violet");
      expect(badge).toHaveTextContent(/nemoclaw/i);
    });
  });

  describe("CoordinatorCycleCard — a proto-key topic_source does not take the card down", () => {
    // The real consumer: <SourceBadge source={cycle.topic_source} />. A single
    // "constructor"/"toString" topic_source must not log a React error or blank
    // the badge; the rest of the cycle narrative must render intact.
    it("renders the card clean with topic_source='constructor' (no React error, badge shows raw)", () => {
      const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      const cycle: CoordinatorCycle = {
        ...COORDINATOR_CYCLES_FIXTURE[1],
        run_id: "cyc-proto-topic-source",
        topic_source: "constructor",
      };
      render(<CoordinatorCycleCard cycle={cycle} />);

      expect(screen.getByTestId("coordinator-cycle-card")).toBeInTheDocument();
      expect(screen.getByText(cycle.topic)).toBeInTheDocument();
      const cell = screen.getByTestId("coordinator-topic-source");
      const badge = within(cell).getByTestId("source-badge");
      // Raw, quiet, and no leaked function source in the className or text.
      expect(badge).toHaveTextContent("constructor");
      expect(badge.className).toContain("zinc");
      expect(badge.className).not.toMatch(/function|native code/);
      expect(document.body.textContent ?? "").not.toContain("[native code]");

      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });
  });
});
