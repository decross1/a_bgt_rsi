// Consolidated edge-case + property-fuzz hardening for RedFlagsTrendStrip (merged from per-round files).
//
// ---------------------------------------------------------------------------
// From test_harden_RedFlagsTrendStrip_r1.tsx:
// HARDENING (round 1, edge-case category: missing/null/undefined optional fields
// + entirely-absent nested objects). RedFlagsTrendStrip's `iterations` prop is
// producer-owned JSONL the backend forwards verbatim — a literal `null` line in
// memory/loop_memory.jsonl round-trips to a `null` array element (backend/
// loop_v0.py:_read_jsonl appends json.loads(line) with NO None filter), and the
// declared IterationRecord[] type cannot enforce non-null at runtime. Every count
// in the strip dereferences r.novelty / r.retrieval, so one such row threw
// `TypeError: Cannot read properties of null (reading 'novelty')` and white-screened
// the whole Dashboard route. This pins the defensive skip-bad-row guard (design
// principle #2: filter/skip a malformed row rather than crash the list).
//
// From test_harden_RedFlagsTrendStrip_r5.tsx:
// HARDENING (round 5, edge-case category: empty-vs-absent collections +
// boundary numbers). The earlier r1 file pins per-ROW robustness (a null/
// non-object element inside the array is skipped). This file pins the
// orthogonal gap that category surfaced: the whole COLLECTION arriving as a
// NON-ARRAY.
//
// From test_fuzz_RedFlagsTrendStrip.tsx:
// PROPERTY-FUZZ (RedFlagsTrendStrip). The enumerated harden files (r1, r5) pin
// named edge cases — a null/non-object row, non-object nested fields, a
// non-array collection. This file is their property-based complement: it
// generates ~50 pseudo-random but plausibly-shaped rows that vary the
// presence / absence / type / length of EVERY optional field the strip and its
// two imported helpers touch, and asserts the component NEVER throws and logs NO
// console error/warn.
//
// jsdom stand-in for "renders without console errors" (no headless browser in
// this stack): render and spy on console.error/console.warn; assert not called.
// ---------------------------------------------------------------------------
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RedFlagsTrendStrip from "../src/components/RedFlagsTrendStrip";
import type { IterationRecord } from "../src/types/schemas";

function watchConsole() {
  const error = vi.spyOn(console, "error").mockImplementation(() => {});
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  return { error, warn };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// === From test_harden_RedFlagsTrendStrip_r1.tsx ===========================

// A well-formed novel/survives row, so a real denominator exists alongside the
// junk and we can prove the good rows are still scored after the bad ones drop.
const GOOD: IterationRecord = {
  iteration_id: "iter-good",
  started_at: "2026-06-09T00:00:00Z",
  ended_at: "2026-06-09T00:01:00Z",
  journal_entry_path: "journal/iterations/good.md",
  novelty: { class: "novel" },
  critique: { verdict: "survives" },
};

describe("RedFlagsTrendStrip hardening — adversarial null/undefined/absent-nested rows (round 1)", () => {
  it("does not crash, NaN, or console.error when a null row is in the array", () => {
    const spy = watchConsole();
    // A literal `null` JSONL line forwarded by the backend. Cast through unknown:
    // the runtime data violates the declared type, which is exactly the hazard.
    const rows = [GOOD, null as unknown as IterationRecord];
    expect(() =>
      render(<RedFlagsTrendStrip iterations={rows} />),
    ).not.toThrow();
    expect(screen.getByTestId("red-flags-trend-strip")).toBeInTheDocument();
    // The bad row is skipped, so the one good novel/survives row IS scored:
    // denominator 1, novel-rate 100% — never a NaN leaking from a divide.
    const novel = within(screen.getByTestId("red-flag-novel-rate"));
    expect(novel.getByText("100%")).toBeInTheDocument();
    expect(novel.getByText("1 of 1")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it("survives undefined rows and rows with entirely-absent nested objects", () => {
    const spy = watchConsole();
    // A pre-2026-06-09 legacy row with no novelty/critique/retrieval/meta_review/
    // redteam at all, plus an undefined element. The component must read every
    // field through a guard and skip the undefined one.
    const legacy = {
      iteration_id: "iter-legacy",
      started_at: "2026-06-09T00:00:00Z",
      ended_at: "2026-06-09T00:01:00Z",
      journal_entry_path: "journal/iterations/legacy.md",
    } as IterationRecord;
    const rows = [
      legacy,
      undefined as unknown as IterationRecord,
      GOOD,
    ];
    render(<RedFlagsTrendStrip iterations={rows} />);
    expect(screen.getByTestId("red-flags-trend-strip")).toBeInTheDocument();
    // Two scoreable rows survive (legacy + good); the undefined is dropped.
    // One is novel → 50% novel-rate, and "self-checks over 2 iterations".
    expect(
      within(screen.getByTestId("red-flag-novel-rate")).getByText("50%"),
    ).toBeInTheDocument();
    expect(screen.getByText(/self-checks over 2 iterations/i)).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it("survives non-object field values a malformed producer could emit", () => {
    const spy = watchConsole();
    // Fields the type declares as objects, arriving as scalars/strings (a partial
    // or legacy write). Optional-chaining + Array.isArray must absorb these — none
    // of them is a low-evidence/novel signal, so they read as quiet zeros, not a
    // throw and not a false alarm.
    const malformed = [
      { iteration_id: "m1", started_at: "", ended_at: "", journal_entry_path: "",
        novelty: "novel", retrieval: "oops" },
      { iteration_id: "m2", started_at: "", ended_at: "", journal_entry_path: "",
        retrieval: { neighbors: "many", relevance: "high" } },
      { iteration_id: "m3", started_at: "", ended_at: "", journal_entry_path: "",
        retrieval: 42 },
    ] as unknown as IterationRecord[];
    render(<RedFlagsTrendStrip iterations={malformed} />);
    expect(screen.getByTestId("red-flags-trend-strip")).toBeInTheDocument();
    // No malformed row trips novel/suspect/off-domain → all three tiles read 0%
    // over a real denominator of 3, and the trust tiles stay quiet (no over-alarm).
    for (const id of [
      "red-flag-novel-rate",
      "red-flag-suspected-false-novel",
      "red-flag-off-domain",
    ]) {
      expect(within(screen.getByTestId(id)).getByText("0%")).toBeInTheDocument();
    }
    const suspect = screen.getByTestId("red-flag-suspected-false-novel");
    expect(suspect.innerHTML).not.toMatch(/amber|red/);
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it("an all-junk array degrades to the clean empty state (em-dash, no alarm)", () => {
    const spy = watchConsole();
    // Every row is null/undefined → after the skip there is no denominator, which
    // is the same as the zero-iteration case: em-dash tiles, quiet zinc. Absence
    // renders cleanly, never a blank gap or crash.
    const rows = [null, undefined, null] as unknown as IterationRecord[];
    render(<RedFlagsTrendStrip iterations={rows} />);
    expect(screen.getByTestId("red-flags-trend-strip")).toBeInTheDocument();
    const suspect = screen.getByTestId("red-flag-suspected-false-novel");
    expect(within(suspect).getByText("—")).toBeInTheDocument();
    expect(suspect.innerHTML).not.toMatch(/amber|red/);
    expect(screen.getByText(/self-checks over 0 iterations/i)).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });
});

// === From test_harden_RedFlagsTrendStrip_r5.tsx ===========================

// Every shape a non-array `iterations` body could take: the JSON null line, an
// absent value, an object/scalar a malformed payload could substitute, and an
// array-like with a `length` key (the classic `.filter`-is-not-a-function trap).
const NON_ARRAYS: [string, unknown][] = [
  ["null", null],
  ["undefined", undefined],
  ["bare object", {}],
  ["number", 42],
  ["string", "oops"],
  ["array-like with length", { length: 3 }],
];

describe("RedFlagsTrendStrip hardening — non-array collection (round 5)", () => {
  it.each(NON_ARRAYS)(
    "does not crash and shows the clean empty state when iterations is %s",
    (_label, bad) => {
      const spy = watchConsole();
      // The runtime data violates the declared type — exactly the hazard. Cast
      // through unknown so the test compiles while feeding the bad runtime shape.
      expect(() =>
        render(
          <RedFlagsTrendStrip
            iterations={bad as unknown as IterationRecord[]}
          />,
        ),
      ).not.toThrow();
      // Strip renders (no white-screen), all three tiles fall back to the
      // zero-denominator em-dash, and the header reports 0 iterations.
      expect(screen.getByTestId("red-flags-trend-strip")).toBeInTheDocument();
      for (const id of [
        "red-flag-novel-rate",
        "red-flag-suspected-false-novel",
        "red-flag-off-domain",
      ]) {
        expect(within(screen.getByTestId(id)).getByText("—")).toBeInTheDocument();
      }
      expect(
        screen.getByText(/self-checks over 0 iterations/i),
      ).toBeInTheDocument();
      // No NaN leaked from a divide, and the trust tile stays quiet zinc — a
      // non-array payload is "no data", never a false false-novel alarm.
      expect(document.body.innerHTML).not.toContain("NaN");
      const suspect = screen.getByTestId("red-flag-suspected-false-novel");
      expect(suspect.innerHTML).not.toMatch(/amber|red/);
      expect(spy.error).not.toHaveBeenCalled();
      expect(spy.warn).not.toHaveBeenCalled();
    },
  );

  it("still scores real rows after the array guard (a normal array is untouched)", () => {
    // The guard must NOT change behavior for a well-formed array: prove a single
    // novel/survives row still computes (denominator 1, novel 100%) so the
    // coercion only catches the non-array case and never the happy path.
    const spy = watchConsole();
    const good: IterationRecord = {
      iteration_id: "iter-good",
      started_at: "2026-06-09T00:00:00Z",
      ended_at: "2026-06-09T00:01:00Z",
      journal_entry_path: "journal/iterations/good.md",
      novelty: { class: "novel" },
      critique: { verdict: "survives" },
    };
    render(<RedFlagsTrendStrip iterations={[good]} />);
    expect(
      within(screen.getByTestId("red-flag-novel-rate")).getByText("100%"),
    ).toBeInTheDocument();
    expect(screen.getByText(/self-checks over 1 iteration\b/i)).toBeInTheDocument();
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });
});

// === From test_fuzz_RedFlagsTrendStrip.tsx ================================

// Deterministic per-index PRNG: a 32-bit LCG (Numerical Recipes constants)
// seeded purely from the loop index. Each call advances the state and returns a
// float in [0,1). No ambient entropy — index N always yields the same row.
function makeRng(seed: number) {
  let state = (seed * 2654435761 + 1013904223) >>> 0; // mix the index first
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

// A grab-bag of values a field could plausibly hold once a malformed/legacy/
// partial producer write reaches the UI: the absent case, the JSON null, the
// wrong scalar types, boundary numbers that have bitten divides/rounding
// before (NaN, ±Infinity, huge, negative), strings of varied length, an array,
// and a nested plain object. `pick` chooses one deterministically.
function junkValue(rng: () => number): unknown {
  const pool: unknown[] = [
    undefined,
    null,
    true,
    false,
    0,
    1,
    -1,
    42,
    Number.NaN,
    Number.POSITIVE_INFINITY,
    Number.NEGATIVE_INFINITY,
    Number.MAX_SAFE_INTEGER,
    "",
    "novel",
    "survives",
    "x".repeat(2000), // a pathologically long string
    [],
    [1, 2, 3],
    ["novel"],
    {},
    { nested: { deep: true } },
  ];
  return pool[Math.floor(rng() * pool.length)];
}

// Maybe-include a key: ~half the time the field is absent entirely (the legacy
// row), otherwise it carries a junk value. Returns a fragment to spread.
function maybe(rng: () => number, key: string): Record<string, unknown> {
  return rng() < 0.5 ? {} : { [key]: junkValue(rng) };
}

// One pseudo-random row. The required IterationRecord fields are always present
// and well-typed (they are not the hazard surface here); every OPTIONAL field
// the strip reads is independently varied. `novelty`, `critique`, `retrieval`
// are sometimes a junk scalar/array and sometimes a partial object whose own
// sub-fields are independently junked — so e.g. `retrieval.relevance.low_confidence`
// is exercised both when `relevance` is an object and when `retrieval` is a number.
function fuzzRow(index: number): unknown {
  const rng = makeRng(index);

  // novelty: absent | junk scalar | partial object with a junk `class`.
  const noveltyPick = rng();
  const novelty =
    noveltyPick < 0.33
      ? undefined
      : noveltyPick < 0.55
        ? junkValue(rng)
        : { ...maybe(rng, "class"), ...maybe(rng, "rationale") };

  // critique: absent | junk scalar | partial object with a junk `verdict`.
  const critiquePick = rng();
  const critique =
    critiquePick < 0.33
      ? undefined
      : critiquePick < 0.55
        ? junkValue(rng)
        : { ...maybe(rng, "verdict"), ...maybe(rng, "rationale") };

  // retrieval: absent | junk scalar (incl. truthy number/string that passes the
  // `if (!retrieval)` gate in isLowEvidence) | partial object whose `relevance`
  // and `neighbors` are each independently junked. `relevance` itself is
  // sometimes a junk scalar and sometimes a sub-object with junk
  // low_confidence/relevance/reason — the field names ARE the EMIT contract.
  const retrievalPick = rng();
  let retrieval: unknown;
  if (retrievalPick < 0.3) {
    retrieval = undefined;
  } else if (retrievalPick < 0.5) {
    retrieval = junkValue(rng); // string/number/array/null/etc.
  } else {
    const relevancePick = rng();
    const relevance =
      relevancePick < 0.4
        ? junkValue(rng)
        : {
            ...maybe(rng, "low_confidence"),
            ...maybe(rng, "relevance"),
            ...maybe(rng, "reason"),
          };
    retrieval = {
      ...maybe(rng, "k"),
      ...(rng() < 0.5 ? {} : { neighbors: junkValue(rng) }),
      ...(rng() < 0.5 ? {} : { relevance }),
    };
  }

  return {
    iteration_id: `fuzz-${index}`,
    started_at: "2026-06-09T00:00:00Z",
    ended_at: "2026-06-09T00:01:00Z",
    journal_entry_path: `journal/iterations/fuzz-${index}.md`,
    ...(novelty === undefined ? {} : { novelty }),
    ...(critique === undefined ? {} : { critique }),
    ...(retrieval === undefined ? {} : { retrieval }),
  };
}

const ROW_COUNT = 50;

describe("RedFlagsTrendStrip hardening — property fuzz over plausible producer rows (fuzz)", () => {
  // Each row in isolation: render the strip with exactly one fuzzed row and
  // assert it neither throws nor logs. Per-index so a failure names the seed.
  for (let i = 0; i < ROW_COUNT; i++) {
    it(`renders a single fuzzed row #${i} without throw or console noise`, () => {
      const spy = watchConsole();
      const rows = [fuzzRow(i)] as unknown as IterationRecord[];
      expect(() =>
        render(<RedFlagsTrendStrip iterations={rows} />),
      ).not.toThrow();
      // The strip still mounts (no white-screen) and never leaks a NaN from a
      // divide/round even when a junk number (NaN/Infinity) sits in a field.
      expect(screen.getByTestId("red-flags-trend-strip")).toBeInTheDocument();
      expect(document.body.innerHTML).not.toContain("NaN");
      expect(spy.error).not.toHaveBeenCalled();
      expect(spy.warn).not.toHaveBeenCalled();
    });
  }

  it("renders ALL 50 fuzzed rows together without throw or console noise", () => {
    // The whole batch in one array: exercises the filter→count→pct pipeline over
    // a mixed denominator (well-typed required fields keep every row scoreable,
    // so the denominator is 50) with every optional field independently junked.
    const spy = watchConsole();
    const rows = Array.from(
      { length: ROW_COUNT },
      (_unused, i) => fuzzRow(i),
    ) as unknown as IterationRecord[];
    expect(() =>
      render(<RedFlagsTrendStrip iterations={rows} />),
    ).not.toThrow();
    expect(screen.getByTestId("red-flags-trend-strip")).toBeInTheDocument();
    // Every row carries the required fields → all 50 survive the non-object
    // filter → the header reports the full denominator and no tile shows a NaN.
    expect(
      screen.getByText(/self-checks over 50 iterations/i),
    ).toBeInTheDocument();
    for (const id of [
      "red-flag-novel-rate",
      "red-flag-suspected-false-novel",
      "red-flag-off-domain",
    ]) {
      // A real percentage (digits + %) or the em-dash, never "NaN%".
      const tile = within(screen.getByTestId(id));
      expect(tile.queryByText(/NaN/)).toBeNull();
    }
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it("is deterministic — the same index yields the identical row", () => {
    // Pin the no-ambient-entropy contract: if a future edit reaches for
    // Math.random/Date this assertion (and the per-index reproducibility it
    // guarantees) breaks loudly.
    expect(JSON.stringify(fuzzRow(7))).toBe(JSON.stringify(fuzzRow(7)));
    expect(JSON.stringify(fuzzRow(7))).not.toBe(JSON.stringify(fuzzRow(8)));
  });
});
