// Consolidated edge-case + property-fuzz hardening for BubblesPanel (merged from per-round files).
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BubblesPanel from "../src/components/BubblesPanel";
import type { Bubble } from "../src/types/schemas";

describe("BubblesPanel hardening — r1 (malformed/partial producer rows)", () => {
  // Rows a real JSONL producer could plausibly emit. Typed `any` deliberately —
  // the point is values the Bubble type forbids but the wire does not.
  const MALFORMED_ROWS: any[] = [
    {}, // entirely-absent optional fields (a pre-2026-06-09 / empty row)
    { note: "note only — no run_id, finding_ids, or timestamp" },
    { run_id: "r-nulled", finding_ids: null, note: null, timestamp: null },
    { run_id: "r-undef", finding_ids: undefined },
    // finding_ids carries null/undefined/blank/non-string AND a duplicate "ok":
    {
      run_id: "r-mixed",
      finding_ids: ["ok", null, undefined, 42, "", { x: 1 }, "ok"],
      note: "mixed + duplicate finding chips",
    },
    // finding_ids is a scalar string, not an array:
    { run_id: "r-scalar", finding_ids: "sf-not-an-array", note: "scalar finding_ids" },
    // timestamp is an epoch number and note is a number:
    { run_id: "r-epoch", timestamp: 1700000000, note: 12345, finding_ids: [] },
    null, // malformed JSONL line parsed to null
    undefined,
    "i am a string row",
    123,
  ];

  describe("BubblesPanel hardening r1 — malformed/partial producer rows", () => {
    it("never throws or logs React errors/warnings on a malformed batch", () => {
      const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      expect(() =>
        render(<BubblesPanel initial={MALFORMED_ROWS as unknown as Bubble[]} />),
      ).not.toThrow();

      // The panel renders rather than blanking the whole surface.
      expect(screen.getByTestId("bubbles-panel")).toBeInTheDocument();

      // No React key warning / render error from the bad rows or bad chips.
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();

      errSpy.mockRestore();
      warnSpy.mockRestore();
    });

    it("skips non-object rows instead of crashing the list", () => {
      // 7 of the 11 rows are bubble objects; the 4 non-objects (2 nulls, a string,
      // a number) are dropped, not rendered as blank rows.
      render(<BubblesPanel initial={MALFORMED_ROWS as unknown as Bubble[]} />);
      expect(screen.getAllByTestId(/^bubble-\d+$/)).toHaveLength(7);
    });

    it("renders valid finding-id chips and drops null/blank ones", () => {
      render(<BubblesPanel initial={MALFORMED_ROWS as unknown as Bubble[]} />);
      // The "r-mixed" row keeps its two real "ok" chips and drops the
      // null/undefined/numeric/blank/object entries — and no blank chip leaks.
      const mixed = screen.getByTestId("bubble-4");
      expect(within(mixed).getAllByText("ok")).toHaveLength(2);
    });

    it("renders a non-string timestamp as a dash rather than throwing", () => {
      render(<BubblesPanel initial={MALFORMED_ROWS as unknown as Bubble[]} />);
      const epochRow = screen.getByTestId("bubble-6");
      expect(within(epochRow).getByText("—")).toBeInTheDocument();
    });

    it("shows a clean empty state when every row is malformed/non-object", () => {
      render(<BubblesPanel initial={[null, undefined, 0, "x"] as unknown as Bubble[]} />);
      expect(screen.getByTestId("bubbles-empty")).toBeInTheDocument();
    });
  });
});

describe("BubblesPanel hardening — round 2 (malformed value TYPES)", () => {
  let errSpy: ReturnType<typeof vi.spyOn>;
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    errSpy.mockRestore();
    warnSpy.mockRestore();
  });

  function expectClean() {
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  }

  describe("BubblesPanel — malformed value TYPES (round 2)", () => {
    it("does not crash when `note` is an object/array instead of a string", () => {
      const rows = [
        { run_id: "cyc-1", finding_ids: [], note: { msg: "structured note" } },
        { run_id: "cyc-2", finding_ids: [], note: ["a", "b"] },
      ] as unknown as Bubble[];
      render(<BubblesPanel initial={rows} />);
      // Both rows render (not dropped — they are valid objects), and a bad-typed
      // note falls back to the placeholder rather than throwing the React-child
      // error that blanked the whole panel pre-guard.
      expect(screen.getByTestId("bubble-0")).toBeInTheDocument();
      expect(screen.getByTestId("bubble-1")).toBeInTheDocument();
      expect(screen.getAllByText("(no note)")).toHaveLength(2);
      expectClean();
    });

    it("does not crash when `run_id` is an object instead of a string", () => {
      const rows = [
        { run_id: { id: "cyc-1" }, finding_ids: [], note: "real note" },
      ] as unknown as Bubble[];
      render(<BubblesPanel initial={rows} />);
      // The row still renders and its (good) note shows; the object run_id is
      // treated as absent — no run_id chip, no React-child crash.
      expect(screen.getByTestId("bubble-0")).toBeInTheDocument();
      expect(screen.getByText("real note")).toBeInTheDocument();
      expectClean();
    });

    it("renders a clean empty state when the `bubbles` payload is not an array", () => {
      // A producer/backend could hand back a single object or null instead of a
      // list; `.filter` would throw and blank the panel. Coerced to [] → the
      // standard empty state.
      const notAList = { nope: true } as unknown as Bubble[];
      render(<BubblesPanel initial={notAList} />);
      expect(screen.getByTestId("bubbles-empty")).toBeInTheDocument();
      expectClean();
    });

    it("does not print NaN for a NaN/garbage timestamp and a numeric note/run_id", () => {
      const rows = [
        { run_id: 7, finding_ids: [], timestamp: NaN, note: 42 },
        { run_id: 0, finding_ids: [], timestamp: "not-a-date", note: "" },
      ] as unknown as Bubble[];
      const { container } = render(<BubblesPanel initial={rows} />);
      expect(screen.getByTestId("bubble-0")).toBeInTheDocument();
      expect(screen.getByTestId("bubble-1")).toBeInTheDocument();
      // A finite numeric run_id stringifies (still reads); a numeric note shows;
      // NaN timestamp renders the "—" placeholder; the literal text "NaN" never
      // leaks into the DOM, and a falsy 0 run_id doesn't leak a stray "0" node.
      expect(container.textContent).not.toContain("NaN");
      expect(screen.getByText("42")).toBeInTheDocument();
      expectClean();
    });

    it("skips non-object rows (null / scalar) without crashing the list", () => {
      const rows = [
        null,
        "a malformed JSONL line that parsed to a bare string",
        { run_id: "cyc-good", finding_ids: ["sf-1"], note: "the one good bubble" },
      ] as unknown as Bubble[];
      render(<BubblesPanel initial={rows} />);
      // Only the one renderable bubble survives; the count reflects it.
      expect(screen.getByText("the one good bubble")).toBeInTheDocument();
      expect(screen.getByText("sf-1")).toBeInTheDocument();
      expect(screen.getByTestId("bubbles-panel").textContent).toContain("1");
      expectClean();
    });
  });
});

describe("BubblesPanel hardening — fuzz (property-fuzz ~50 randomized rows)", () => {
  // Deterministic 32-bit hash of an integer seed → uint32. Pure; no external
  // entropy. (mulberry32's mixing step — enough spread for field selection.)
  function hash(seed: number): number {
    let t = (seed + 0x6d2b79f5) | 0;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return (t ^ (t >>> 14)) >>> 0;
  }

  // A small deterministic stream of picks for one row index. Each call advances a
  // sub-seed so a single row draws several independent-looking-but-fixed choices.
  function picker(index: number) {
    let n = 0;
    return {
      // integer in [0, mod)
      int(mod: number): number {
        return hash(index * 1000 + n++) % mod;
      },
      // true with ~`pct`% probability (deterministic)
      chance(pct: number): boolean {
        return hash(index * 1000 + n++) % 100 < pct;
      },
    };
  }

  // The menu of values any single field might take — strings, numbers (incl.
  // non-finite), booleans, null/undefined, and the React-child-hostile shapes
  // (objects / arrays / nested). Indexed deterministically by the picker.
  const SCALAR_MENU: unknown[] = [
    "cyc-2026-06-09-001",
    "sf-iter-2026-06-09-002",
    "", // empty string → treated as absent by displayText callers
    "a".repeat(2000), // pathologically long
    "line\nwith\nnewlines\tand\ttabs",
    "unicode ✓ … 漢字 🫧   control",
    0,
    -1,
    42,
    3.14159,
    Number.NaN, // must never print "NaN"
    Number.POSITIVE_INFINITY,
    Number.NEGATIVE_INFINITY,
    true,
    false,
    null,
    undefined,
    { nested: { msg: "object where a string is expected" } }, // React-child crash pre-guard
    ["array", "where", "a", "string", "is", "expected"],
    [], // empty array
    () => "fn", // a function snuck in
  ];

  // Values the `timestamp` field might carry. Strings (valid + junk), epoch
  // numbers, non-finite, and non-string shapes (all must degrade to "—").
  const TIMESTAMP_MENU: unknown[] = [
    "2026-06-09T11:35:00Z",
    "2026-06-09T11:35:00.123+00:00",
    "not-a-date",
    "", // empty → "—"
    "Z-only-no-T",
    1700000000, // epoch number
    Number.NaN,
    Number.POSITIVE_INFINITY,
    { when: "now" },
    ["2026"],
    null,
    undefined,
    true,
  ];

  // Build one finding_ids value. Sometimes a clean string[], sometimes a non-array
  // scalar (must be skipped, never `.map`'d), sometimes an array salted with
  // null/blank/non-string/duplicate/object entries (the chip coercion must drop
  // them and emit no duplicate-key warning).
  function buildFindingIds(p: ReturnType<typeof picker>): unknown {
    const kind = p.int(5);
    if (kind === 0) return undefined;
    if (kind === 1) return null;
    if (kind === 2) return "sf-not-an-array"; // scalar, not array
    if (kind === 3) {
      // a salted array: real ids + every hostile element + a duplicate
      return [
        "sf-real-1",
        "sf-real-1", // duplicate (dup-key risk)
        "", // blank (blank-chip risk)
        null,
        undefined,
        123,
        { x: 1 },
        ["nested"],
        true,
        "a".repeat(500), // long chip
      ];
    }
    // a clean, variable-length array of plausible ids
    const len = p.int(6);
    return Array.from({ length: len }, (_, j) => `sf-${index_for_chip(p, j)}`);
  }

  // Deterministic chip-id suffix (kept tiny; no entropy source).
  function index_for_chip(p: ReturnType<typeof picker>, j: number): number {
    return (p.int(9973) + j) % 9973;
  }

  // Assemble one fuzzed row for a given index. With some probability the whole row
  // is a non-object (null / undefined / scalar / array) — the producer can emit a
  // malformed JSONL line that parses to a bare value, and the panel must skip it.
  function fuzzRow(index: number): unknown {
    const p = picker(index);

    // ~18% of rows are not objects at all.
    if (p.chance(18)) {
      const nonObj = p.int(5);
      if (nonObj === 0) return null;
      if (nonObj === 1) return undefined;
      if (nonObj === 2) return "a malformed JSONL line that parsed to a string";
      if (nonObj === 3) return p.int(100000);
      return [1, 2, 3]; // a bare array
    }

    const row: Record<string, unknown> = {};
    // Each optional field is independently present-or-absent, and when present
    // draws a (possibly hostile) value from the menu.
    if (p.chance(80)) row.run_id = SCALAR_MENU[p.int(SCALAR_MENU.length)];
    if (p.chance(80)) row.note = SCALAR_MENU[p.int(SCALAR_MENU.length)];
    if (p.chance(80)) row.timestamp = TIMESTAMP_MENU[p.int(TIMESTAMP_MENU.length)];
    if (p.chance(85)) row.finding_ids = buildFindingIds(p);

    // Forward-compatible extra fields (the Bubble index signature) — a future
    // EMIT addition / unknown producer key must be ignored, never rendered-crash.
    if (p.chance(40)) {
      row[`extra_${p.int(50)}`] = SCALAR_MENU[p.int(SCALAR_MENU.length)];
    }
    if (p.chance(15)) row.severity = SCALAR_MENU[p.int(SCALAR_MENU.length)];
    if (p.chance(15)) row.bubble_id = SCALAR_MENU[p.int(SCALAR_MENU.length)];

    return row;
  }

  const N = 50;
  const FUZZ_ROWS: unknown[] = Array.from({ length: N }, (_, i) => fuzzRow(i));

  let errSpy: ReturnType<typeof vi.spyOn>;
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    errSpy.mockRestore();
    warnSpy.mockRestore();
  });

  describe("BubblesPanel property-fuzz — ~50 randomized producer rows", () => {
    // Render each fuzzed row on its OWN so a failure pinpoints the exact index
    // (and its deterministic seed) rather than burying it in a 50-row batch.
    for (let i = 0; i < N; i++) {
      it(`row #${i} renders without throwing or logging`, () => {
        const { unmount } = render(
          <BubblesPanel initial={[FUZZ_ROWS[i]] as unknown as Bubble[]} />,
        );
        // The panel container always renders (it never blanks to nothing).
        expect(screen.getByTestId("bubbles-panel")).toBeInTheDocument();
        // No React child-crash and no duplicate-key / invalid-child warning.
        expect(errSpy).not.toHaveBeenCalled();
        expect(warnSpy).not.toHaveBeenCalled();
        // No "NaN" / "Infinity" / "undefined" literal leaked into the DOM from a
        // non-finite or absent scalar.
        const text = document.body.textContent ?? "";
        expect(text).not.toContain("NaN");
        expect(text).not.toContain("Infinity");
        unmount();
      });
    }

    it("renders the whole 50-row batch at once without throwing or logging", () => {
      // The producer hands the panel the entire list in one payload; the batch
      // mixes object + non-object rows, dup chips across rows, etc.
      expect(() =>
        render(<BubblesPanel initial={FUZZ_ROWS as unknown as Bubble[]} />),
      ).not.toThrow();
      expect(screen.getByTestId("bubbles-panel")).toBeInTheDocument();
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
      // Every rendered bubble corresponds to a row the panel KEEPS. The panel's
      // own filter is `typeof b === "object" && b !== null` (BubblesPanel.tsx) —
      // which by JS semantics also admits a bare array (a malformed JSONL line
      // that parsed to `[...]`): it renders as an empty bubble, not a crash. Match
      // that filter exactly so the count reflects the component's contract, not a
      // stricter notion of "object". The seed is fixed, so this number is stable.
      const renderableRows = FUZZ_ROWS.filter(
        (r) => typeof r === "object" && r !== null,
      ).length;
      expect(screen.queryAllByTestId(/^bubble-\d+$/)).toHaveLength(renderableRows);
      expect(renderableRows).toBeGreaterThan(0);
    });
  });
});
