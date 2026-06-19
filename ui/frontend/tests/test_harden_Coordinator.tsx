// Consolidated edge-case + property-fuzz hardening for Coordinator (merged from per-round files).
//
// Merged from test_harden_Coordinator_r1.tsx (partial/legacy producer rows),
// test_harden_Coordinator_r2.tsx (malformed value TYPES),
// test_harden_Coordinator_r3.tsx (scale + content), and
// test_harden_Coordinator_r5.tsx (empty/absent bodies + boundary counts).
// Every it()/test() case and assertion is preserved verbatim; each source file's
// body lives in its own top-level describe() so names never collide. The only
// non-verbatim change is a helper-rename: r5's renderPollingQuietly variant (which
// adds an error-banner check to its settle condition) is renamed
// renderPollingQuietlyR5 to avoid colliding with the identical r2/r3 helper, and
// its call sites are updated to match.
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Coordinator from "../src/routes/Coordinator";
import type { CoordinatorCycle } from "../src/types/schemas";

// ---------------------------------------------------------------------------
// Shared module-scope substrate for the POLLING-path rounds (r2 / r3 / r5).
//
// The polling response the mocked api/http hands back. Mutable + module-scoped
// so the hoisted vi.mock factory reads the value each test stages. Typed
// `unknown` (the widest of the per-round types: r2/r3 used `{ cycles: unknown }`,
// r5 used `unknown`) because the staged bodies (null / {} / a bad-typed shape /
// {cycles:...}) violate the response interface on purpose — the on-disk /
// over-the-wire body is not typed. Reset in each round's afterEach.
let RESPONSE: unknown = { cycles: [] };
vi.mock("../src/api/http", () => ({
  getCoordinatorCycles: vi.fn(() => Promise.resolve(RESPONSE)),
}));

// A well-formed row, so the malformed/scale/content rows are exercised AROUND a
// good one — the page must keep rendering the valid cycle, never collapse to
// empty/error. (Byte-identical across r2/r3/r5; kept once.)
function mk(over: Record<string, unknown>): CoordinatorCycle {
  return {
    timestamp: "2026-06-09T10:00:00Z",
    run_id: `coordinator_${Math.random().toString(36).slice(2, 10)}`,
    agent: "coordinator",
    topic: "well-formed cycle",
    topic_source: "arxiv_pick",
    status: "executed",
    plan: [{ action: "noop", args: {} }],
    outcomes: [{ action: "noop", status: "passed" }],
    promoted_finding_ids: [],
    bubble_run_ids: [],
    ...over,
  } as unknown as CoordinatorCycle;
}

// Render the polling route, flush the async load + sort, and return the
// console.error/warn the render path emitted (a thrown render lands here too),
// with React's act() advisory filtered out (test-harness noise, not a prod log).
// The route loads via a Promise, so settle on a real steady-state condition (a
// card OR the empty state present) rather than a bare microtask flush.
// (Byte-identical across r2/r3; kept once.)
async function renderPollingQuietly() {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  render(<Coordinator pollMs={999_999} />);
  await waitFor(() => {
    const settled =
      document.querySelector('[data-testid="coordinator-cycle-card"]') !==
        null ||
      document.querySelector('[data-testid="coordinator-empty"]') !== null;
    expect(settled).toBe(true);
  });
  const calls = {
    error: errSpy.mock.calls
      .map((c) => String(c[0]))
      .filter((m) => !m.includes("not wrapped in act")),
    warn: warnSpy.mock.calls
      .map((c) => String(c[0]))
      .filter((m) => !m.includes("not wrapped in act")),
  };
  errSpy.mockRestore();
  warnSpy.mockRestore();
  return calls;
}

// ===========================================================================
// ROUND 1 — partial/legacy producer rows (the synchronous `initial` path).
// ===========================================================================
//
// ADVERSARIAL HARDENING (round 1) — routes/Coordinator.tsx, edge-case category:
// missing/null/undefined optional fields + entirely-absent nested objects on a
// coordinator-cycle row (a pre-2026-06-09 / partial / legacy producer row).
//
// run_state/coordinator_cycles.jsonl is producer-owned, append-only, and may be
// partial or malformed — a legacy row could omit `plan`/`outcomes` entirely, or
// carry them as null, or be missing `run_id`/`topic_source`. The contract is
// "one bad row must NEVER crash the whole page": the route renders a card per
// cycle, and CoordinatorCycleCard reads `cycle.outcomes.length` /
// `cycle.plan.map(...)` UNGUARDED, so one row missing those fields throws during
// render and (no error boundary) unmounts the entire Coordinator surface. The
// route must filter/skip a structurally-unrenderable row rather than blank out.
//
// We render the route via `initial` (network bypassed — the ResolvedIterationsList
// idiom the route already supports) and spy on console.error/console.warn: a
// thrown render and a duplicate/undefined React `key` both surface there.

// A well-formed row, so the bad rows are dropped AROUND a good one (the page
// must keep rendering the valid cycle, not collapse to empty).
const GOOD: CoordinatorCycle = {
  timestamp: "2026-06-09T10:00:00Z",
  run_id: "coordinator_good_001",
  agent: "coordinator",
  topic: "well-formed cycle",
  topic_source: "arxiv_pick",
  status: "executed",
  plan: [{ action: "noop", args: {} }],
  outcomes: [{ action: "noop", status: "passed" }],
  promoted_finding_ids: [],
  bubble_run_ids: [],
};

// Bad rows a real producer could plausibly emit. Each is `unknown`-cast because
// these violate the TS interface on purpose — the on-disk JSONL is not typed.

// (1) Nested arrays ENTIRELY ABSENT: no `plan`, no `outcomes` — a partial/legacy
//     row. CoordinatorCycleCard does cycle.outcomes.length -> throws on undefined.
const NO_PLAN_NO_OUTCOMES = {
  timestamp: "2026-06-09T09:00:00Z",
  run_id: "coordinator_bad_no_arrays",
  agent: "coordinator",
  topic: "legacy row: no plan/outcomes arrays",
  topic_source: "arxiv_pick",
  status: "planned",
} as unknown as CoordinatorCycle;

// (2) Nested arrays present but NULL (a producer that writes JSON null instead
//     of omitting). cycle.outcomes.length on null -> throws.
const NULL_ARRAYS = {
  timestamp: "2026-06-09T08:00:00Z",
  run_id: "coordinator_bad_null_arrays",
  agent: "coordinator",
  topic: "null plan/outcomes",
  topic_source: "arxiv_pick",
  status: "no_valid_plan",
  plan: null,
  outcomes: null,
  promoted_finding_ids: null,
  bubble_run_ids: null,
} as unknown as CoordinatorCycle;

// (3) EVERYTHING optional missing: no run_id (React key), no agent, no
//     topic_source, no topic, no nested objects/arrays. The minimal hostile row.
const ALL_OPTIONAL_MISSING = {
  timestamp: "2026-06-09T07:00:00Z",
} as unknown as CoordinatorCycle;

// (4) A SECOND run_id-less row, to force the duplicate-`undefined`-key React
//     warning if the route keys on a missing run_id.
const ALL_OPTIONAL_MISSING_2 = {
  timestamp: "2026-06-09T06:00:00Z",
  topic: "another keyless row",
} as unknown as CoordinatorCycle;

describe("Coordinator hardening — r1: partial/legacy producer rows", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not crash the page or log console errors on rows missing plan/outcomes", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    // The whole-page render must not throw even though several rows are malformed.
    expect(() =>
      render(
        <Coordinator
          initial={[
            NO_PLAN_NO_OUTCOMES,
            GOOD,
            NULL_ARRAYS,
            ALL_OPTIONAL_MISSING,
            ALL_OPTIONAL_MISSING_2,
          ]}
        />,
      ),
    ).not.toThrow();

    // The page surface is present (not blanked) and the well-formed cycle still
    // renders — a bad row is dropped, it does not take the page down with it.
    expect(screen.getByTestId("coordinator-page")).toBeInTheDocument();
    expect(screen.getByText("well-formed cycle")).toBeInTheDocument();

    // No React key warning / act warning / thrown-render surfaced to the console.
    expect(
      errSpy,
      `console.error: ${errSpy.mock.calls.map((c) => String(c[0])).join(" | ")}`,
    ).not.toHaveBeenCalled();
    expect(
      warnSpy,
      `console.warn: ${warnSpy.mock.calls.map((c) => String(c[0])).join(" | ")}`,
    ).not.toHaveBeenCalled();
  });

  it("renders a clean empty state (never a crash) when every row is malformed", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() =>
      render(
        <Coordinator
          initial={[NO_PLAN_NO_OUTCOMES, NULL_ARRAYS, ALL_OPTIONAL_MISSING]}
        />,
      ),
    ).not.toThrow();

    // All rows dropped -> the explicit empty state, not a blank gap and not a
    // half-rendered card skeleton.
    expect(screen.getByTestId("coordinator-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("coordinator-cycle-card")).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
  });
});

// ===========================================================================
// ROUND 2 — malformed value TYPES (POLLING + INITIAL paths).
// ===========================================================================
//
// ADVERSARIAL HARDENING (round 2) — routes/Coordinator.tsx, edge-case category:
// malformed value TYPES on a coordinator-cycle row (a string where a number is
// expected and vice-versa, an array/object where a scalar is expected, NaN /
// Infinity numbers, garbage/invalid ISO timestamps). run_state/coordinator_cycles.jsonl
// is producer-owned, append-only, and UNTYPED on disk — a legacy row or a
// serialization slip can write `timestamp` as a Unix epoch NUMBER, an object, or
// null even though the TS interface types it `string`.
//
// THE BUG THIS ROUND FIXED (route-owned, polling path): the newest-first sort
// compared timestamps with `(b.timestamp ?? "").localeCompare(...)`. `?? ""`
// only replaces null/undefined, so a NUMERIC timestamp survives, and
// `(<number>).localeCompare(...)` throws "(...).localeCompare is not a function"
// when the number lands in the comparator's RECEIVER slot. That throw rejects
// the load promise into `.catch`, which sets the error banner — blanking EVERY
// card, including the healthy string-timestamp rows. One bad-typed timestamp
// takes the whole Coordinator narrative down (the dark-loop failure this view
// exists to fix). The fix coerces each timestamp through a string before
// localeCompare (a numeric epoch still sorts sanely), and guards a non-array
// `cycles` body so spreading it can't throw either.
//
// We drive BOTH render paths: the POLLING path (api/http mocked — where the sort
// runs and the bug lived) and the synchronous `initial` path. console.error /
// console.warn are spied (filtering React's act() advisory, a test-harness
// artifact, not a production console error) and asserted empty; a thrown React
// render also surfaces as a console.error here, so a crash is caught even when
// render() does not rethrow. Matches the test_harden_Dashboard_r2 idiom: a
// module-mutable response the mock factory reads + a renderQuietly() flush +
// explicit cleanup().
describe("Coordinator hardening — r2: malformed value TYPES", () => {
  afterEach(() => {
    cleanup();
    RESPONSE = { cycles: [] };
    vi.clearAllMocks();
  });

  // The headline regression: a NUMERIC timestamp (newest-looking) among string
  // rows used to throw in the sort comparator and blank the whole page.
  it("POLLING: a numeric timestamp does not crash the sort or blank the page", async () => {
    RESPONSE = {
      cycles: [
        mk({ timestamp: 1_749_452_273, topic: "NUMERIC-TS-ROW" }),
        mk({ timestamp: "2026-06-09T09:00:00Z", topic: "STRING-TS-ROW" }),
      ],
    };
    const { error } = await renderPollingQuietly();

    // Both rows render — the comparator no longer throws into .catch.
    expect(screen.getByText("STRING-TS-ROW")).toBeInTheDocument();
    expect(screen.getByText("NUMERIC-TS-ROW")).toBeInTheDocument();
    expect(screen.getAllByTestId("coordinator-cycle-card")).toHaveLength(2);

    // No error banner (the .catch path would print the TypeError on the page).
    const pageText = screen.getByTestId("coordinator-page").textContent ?? "";
    expect(pageText).not.toMatch(/localeCompare|is not a function|TypeError/);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
  });

  // Two numeric timestamps: BOTH localeCompare operands are numbers — the
  // comparator threw on this arrangement pre-fix regardless of ordering.
  it("POLLING: two numeric timestamps still sort + render without throwing", async () => {
    RESPONSE = {
      cycles: [
        mk({ timestamp: 1_749_452_273, topic: "NUM-A" }),
        mk({ timestamp: 1_749_452_999, topic: "NUM-B" }),
      ],
    };
    const { error } = await renderPollingQuietly();
    expect(screen.getByText("NUM-A")).toBeInTheDocument();
    expect(screen.getByText("NUM-B")).toBeInTheDocument();
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
  });

  // The wider malformed-TYPE matrix through the polling path: garbage/empty ISO
  // strings, NaN/Infinity timestamps, object/array/number topics, an object
  // dispatched_iteration_id, and numeric fields where arrays are expected. None
  // may throw, print NaN, or blank the healthy row.
  it("POLLING: garbage ISO / NaN / Infinity / object+array fields render around a good row", async () => {
    RESPONSE = {
      cycles: [
        mk({ timestamp: "not-a-real-date", topic: "GARBAGE-ISO" }),
        mk({ timestamp: "2026-13-45T99:99:99Z", topic: "OVERFLOW-ISO" }),
        mk({ timestamp: "", topic: "EMPTY-ISO" }),
        mk({ timestamp: Number.NaN, topic: "NAN-TS" }),
        mk({ timestamp: Infinity, topic: "INF-TS" }),
        // object / array / number where a scalar string is expected (card asText)
        mk({ topic: { weird: "object" } as unknown as string }),
        mk({ topic: [1, 2, 3] as unknown as string }),
        mk({ topic: 42 as unknown as string }),
        mk({ dispatched_iteration_id: { x: 1 } as unknown as string }),
        // numbers/strings where arrays are expected (the footer .length reads)
        mk({
          promoted_finding_ids: 5 as unknown as string[],
          bubble_run_ids: "nope" as unknown as string[],
        }),
        mk({ topic: "GOOD-AMONG-BAD" }),
      ],
    };
    const { error, warn } = await renderPollingQuietly();

    expect(screen.getByText("GOOD-AMONG-BAD")).toBeInTheDocument();
    // The page must never surface a literal "NaN" anywhere in the narrative.
    const pageText = screen.getByTestId("coordinator-page").textContent ?? "";
    expect(pageText).not.toMatch(/NaN/);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  // The contract is {cycles:[...]}, but a malformed body could hand back a
  // non-array — spreading/sorting it would throw before any row renders.
  it("POLLING: a non-array cycles body degrades to the clean empty state", async () => {
    RESPONSE = { cycles: "oops-not-an-array" };
    const { error } = await renderPollingQuietly();

    expect(screen.getByTestId("coordinator-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("coordinator-cycle-card")).toBeNull();
    const pageText = screen.getByTestId("coordinator-page").textContent ?? "";
    expect(pageText).not.toMatch(/TypeError|is not a function/);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
  });

  // The synchronous `initial` path (no sort) must also survive a structurally-
  // renderable row carrying a malformed-type timestamp/topic next to a good row.
  it("INITIAL: bad-type timestamp + object topic render around a good row, no NaN", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    expect(() =>
      render(
        <Coordinator
          initial={[
            mk({ timestamp: 1_749_452_273, topic: { o: 1 } as unknown as string }),
            mk({ timestamp: Infinity, topic: [9] as unknown as string }),
            mk({ topic: "INITIAL-GOOD-ROW" }),
          ]}
        />,
      ),
    ).not.toThrow();

    expect(screen.getByTestId("coordinator-page")).toBeInTheDocument();
    expect(screen.getByText("INITIAL-GOOD-ROW")).toBeInTheDocument();
    const pageText = screen.getByTestId("coordinator-page").textContent ?? "";
    expect(pageText).not.toMatch(/NaN/);

    const realErr = errSpy.mock.calls
      .map((c) => String(c[0]))
      .filter((m) => !m.includes("not wrapped in act"));
    const realWarn = warnSpy.mock.calls
      .map((c) => String(c[0]))
      .filter((m) => !m.includes("not wrapped in act"));
    errSpy.mockRestore();
    warnSpy.mockRestore();
    expect(realErr, `console.error: ${realErr.join(" | ")}`).toHaveLength(0);
    expect(realWarn, `console.warn: ${realWarn.join(" | ")}`).toHaveLength(0);
  });
});

// ===========================================================================
// ROUND 3 — scale + content (POLLING + INITIAL paths).
// ===========================================================================
//
// ADVERSARIAL HARDENING (round 3) — routes/Coordinator.tsx, edge-case category:
// SCALE + CONTENT. A producer-owned, append-only run_state/coordinator_cycles.jsonl
// can hand the route (a) a very long unbroken string (5k chars), (b) 1000+ rows,
// and (c) unicode / emoji / RTL-override / newlines / HTML-looking text in fields.
// The route must render all of it without throwing, printing NaN, blanking the
// surface, or logging a React console.error/warn.
//
// THE BUG THIS ROUND FIXED (route-owned, the list key): each card was keyed
// `cycle.run_id ?? `cycle-${i}``. `run_id` is producer-owned and NOT guaranteed
// unique in an append-only JSONL — a retry/re-emit or a legacy collision can
// write the SAME run_id on two rows, and at scale (1000+ rows) that grows likely.
// `?? `cycle-${i}`` only substitutes a MISSING id, so two rows sharing the same
// non-null run_id still collide on an identical key and React logs
// "Encountered two children with the same key" (a console.error) — exactly the
// scale+content failure this round targets. The fix suffixes the index so the
// key is unique regardless of run_id (a missing/non-string id degrades to a bare
// index); the list is re-sorted and replaced wholesale each poll, so keying by
// index has no identity-stability cost.
//
// Drives BOTH render paths: the POLLING path (api/http mocked — where the
// re-sort + map runs) and the synchronous `initial` path. console.error /
// console.warn are spied (React's act() advisory filtered as test-harness noise)
// and asserted empty; a thrown React render also lands in console.error here, so
// a crash is caught even when render() does not rethrow. Matches the
// test_harden_Coordinator_r2 idiom: a module-mutable response the mock factory
// reads + a renderPollingQuietly() flush + explicit cleanup().
describe("Coordinator hardening — r3: scale + content", () => {
  afterEach(() => {
    cleanup();
    RESPONSE = { cycles: [] };
    vi.clearAllMocks();
  });

  // The headline regression: two rows carrying the SAME non-null run_id used to
  // collide on an identical React key and emit a console.error. Both must render
  // cleanly now (the index-suffixed key is unique).
  it("POLLING: duplicate run_id across rows does not log a duplicate-key error", async () => {
    RESPONSE = {
      cycles: [
        mk({ run_id: "coordinator_dup", topic: "DUP-ROW-A" }),
        mk({ run_id: "coordinator_dup", topic: "DUP-ROW-B" }),
      ],
    };
    const { error, warn } = await renderPollingQuietly();

    // Both rows render — neither is dropped by a key collision.
    expect(screen.getByText("DUP-ROW-A")).toBeInTheDocument();
    expect(screen.getByText("DUP-ROW-B")).toBeInTheDocument();
    expect(screen.getAllByTestId("coordinator-cycle-card")).toHaveLength(2);

    // No "same key" diagnostic on the console (the bug this round fixed).
    expect(
      error.some((m) => m.includes("same key")),
      `console.error: ${error.join(" | ")}`,
    ).toBe(false);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  // Many rows ALL sharing one run_id — the worst-case collision (e.g. a producer
  // that forgot to vary the id). Every row must still render, key-clean.
  it("POLLING: many rows sharing one run_id all render without a key warning", async () => {
    RESPONSE = {
      cycles: Array.from({ length: 25 }, (_, i) =>
        mk({ run_id: "coordinator_same", topic: `same-${i}` }),
      ),
    };
    const { error, warn } = await renderPollingQuietly();

    expect(screen.getAllByTestId("coordinator-cycle-card")).toHaveLength(25);
    expect(
      error.some((m) => m.includes("same key")),
      `console.error: ${error.join(" | ")}`,
    ).toBe(false);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  // The pure scale+content sub-category (already robust): 1000+ rows, a 5k-char
  // unbroken string, and a row with unicode / emoji / RTL-override / HTML-looking
  // text / newlines / tabs. None may throw, print NaN, blank the page, or log.
  it("POLLING: 1000+ rows + a 5k string + unicode/RTL/emoji/HTML/newlines render cleanly", async () => {
    const longString = "x".repeat(5000);
    const rows: CoordinatorCycle[] = Array.from({ length: 1000 }, (_, i) =>
      mk({ run_id: `coordinator_${i}`, topic: `bulk-${i}` }),
    );
    rows.push(
      mk({
        run_id: "coordinator_unicode",
        // RTL override (U+202E/U+202C) + Arabic + emoji + HTML-looking text +
        // newlines + a tab — no injection, just hostile-looking content. React
        // escapes the markup; nothing executes; the layout must not break.
        topic:
          "مرحبا بالعالم ‮evil-reversed‬ 🚀🔥 <script>alert('x')</script>\nsecond line\tafter-tab",
      }),
    );
    rows.push(mk({ run_id: "coordinator_long", topic: longString }));
    RESPONSE = { cycles: rows };

    const { error, warn } = await renderPollingQuietly();

    // All rows rendered (1000 bulk + the two content rows).
    expect(screen.getAllByTestId("coordinator-cycle-card")).toHaveLength(1002);
    // The header count reflects the renderable total, not NaN.
    expect(screen.getByText("1002")).toBeInTheDocument();
    // The 5k string is present verbatim somewhere in the page.
    expect(screen.getByText(longString)).toBeInTheDocument();
    // The page never surfaces a literal "NaN" in the narrative.
    const pageText = screen.getByTestId("coordinator-page").textContent ?? "";
    expect(pageText).not.toMatch(/NaN/);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  // The synchronous `initial` path (no re-sort) must also survive duplicate
  // run_ids + a 5k string + unicode content around a good row.
  it("INITIAL: duplicate run_ids + 5k string + unicode render without a key error", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    expect(() =>
      render(
        <Coordinator
          initial={[
            mk({ run_id: "coordinator_dup", topic: "INIT-DUP-A" }),
            mk({ run_id: "coordinator_dup", topic: "INIT-DUP-B" }),
            mk({ run_id: "coordinator_long", topic: "y".repeat(5000) }),
            mk({
              run_id: "coordinator_emoji",
              topic: "🧪 résumé — naïve 日本語 ‮rtl‬",
            }),
            mk({ run_id: "coordinator_good", topic: "INITIAL-GOOD-ROW" }),
          ]}
        />,
      ),
    ).not.toThrow();

    expect(screen.getByTestId("coordinator-page")).toBeInTheDocument();
    expect(screen.getByText("INITIAL-GOOD-ROW")).toBeInTheDocument();
    expect(screen.getByText("INIT-DUP-A")).toBeInTheDocument();
    expect(screen.getByText("INIT-DUP-B")).toBeInTheDocument();
    expect(screen.getAllByTestId("coordinator-cycle-card")).toHaveLength(5);
    const pageText = screen.getByTestId("coordinator-page").textContent ?? "";
    expect(pageText).not.toMatch(/NaN/);

    const realErr = errSpy.mock.calls
      .map((c) => String(c[0]))
      .filter((m) => !m.includes("not wrapped in act"));
    const realWarn = warnSpy.mock.calls
      .map((c) => String(c[0]))
      .filter((m) => !m.includes("not wrapped in act"));
    errSpy.mockRestore();
    warnSpy.mockRestore();
    expect(
      realErr.some((m) => m.includes("same key")),
      `console.error: ${realErr.join(" | ")}`,
    ).toBe(false);
    expect(realErr, `console.error: ${realErr.join(" | ")}`).toHaveLength(0);
    expect(realWarn, `console.warn: ${realWarn.join(" | ")}`).toHaveLength(0);
  });
});

// ===========================================================================
// ROUND 5 — empty/absent bodies + boundary counts (POLLING path).
// ===========================================================================
//
// ADVERSARIAL HARDENING (round 5) — routes/Coordinator.tsx, edge-case category:
// EMPTY-vs-ABSENT collections + boundary numbers. A producer-owned, append-only
// data stream (and the backend that serializes it) can hand the route the whole
// gradient of "nothing": an empty-but-present array, an object with the `cycles`
// key absent, and — the one that bit — a bare `null`/`undefined` response body.
// The contract (ui_autonomy_observability_plan.md / the handoff) is explicit:
// when the cycle log is absent the panel shows a CLEAN EMPTY STATE, never a
// blank gap and never a crash. This view exists precisely so the dark loop is
// legible; a raw TypeError in the error banner is itself a dark-gap.
//
// THE BUG THIS ROUND FIXED (route-owned, polling path): the load did
// `Array.isArray(r.cycles) ? r.cycles : []` — a guard the author added against a
// NON-ARRAY `cycles`, but it reads `.cycles` off `r` FIRST. When the body is a
// bare `null`/`undefined` (a malformed 200; getJSON returns the parsed body
// verbatim, and `null` is valid JSON), `r.cycles` throws "Cannot read properties
// of null (reading 'cycles')" BEFORE Array.isArray runs. That throw rejects the
// load promise into `.catch`, which paints the raw TypeError string in the red
// error banner — and `loaded` never flips true, so the clean empty state never
// shows either. The absent-data case (the headline reason this view exists)
// degraded to a crash banner. The fix is `r?.cycles`: a null/undefined body
// short-circuits to undefined → not an array → [] → setLoaded(true) → the
// explicit empty state. (Mirrors the existing non-array guard, one level up.)
//
// Drives the POLLING path (api/http mocked — where the body is read and the bug
// lived); the empty-but-present and key-absent bodies are exercised alongside as
// the rest of the empty/absent gradient. console.error/console.warn are spied
// (React's act() advisory filtered as test-harness noise) and asserted empty; a
// thrown React render lands in console.error here too. Matches the
// test_harden_Coordinator_r2/r3 idiom: a module-mutable response the mock factory
// reads + a renderPollingQuietly() flush + explicit cleanup().

// Render the polling route, flush the async load, and return the console.error/
// warn the render path emitted (a thrown render lands here too), with React's
// act() advisory filtered out. The route loads via a Promise, so settle on a real
// steady state: a card, the empty state, OR an error banner present (so a
// regressed crash-banner is observed, not waited on forever).
// (Renamed from r5's renderPollingQuietly — it differs from the shared r2/r3
// helper by also settling on a `.text-red-400` error banner.)
async function renderPollingQuietlyR5() {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  render(<Coordinator pollMs={999_999} />);
  await waitFor(() => {
    const page = document.querySelector('[data-testid="coordinator-page"]');
    const settled =
      document.querySelector('[data-testid="coordinator-cycle-card"]') !==
        null ||
      document.querySelector('[data-testid="coordinator-empty"]') !== null ||
      (page?.querySelector(".text-red-400") ?? null) !== null;
    expect(settled).toBe(true);
  });
  const calls = {
    error: errSpy.mock.calls
      .map((c) => String(c[0]))
      .filter((m) => !m.includes("not wrapped in act")),
    warn: warnSpy.mock.calls
      .map((c) => String(c[0]))
      .filter((m) => !m.includes("not wrapped in act")),
  };
  errSpy.mockRestore();
  warnSpy.mockRestore();
  return calls;
}

// True when an error banner carrying a raw exception is on the page — the
// forbidden "crash instead of empty state" outcome.
function hasCrashBanner(): boolean {
  const page = screen.getByTestId("coordinator-page");
  const banner = page.querySelector(".text-red-400")?.textContent ?? "";
  return /TypeError|is not a function|Cannot read properties|undefined|null/i.test(
    banner,
  );
}

describe("Coordinator hardening — r5: empty/absent bodies + boundary counts", () => {
  afterEach(() => {
    cleanup();
    RESPONSE = { cycles: [] };
    vi.clearAllMocks();
  });

  // The headline regression: a bare `null` body used to throw "Cannot read
  // properties of null (reading 'cycles')" and paint the raw TypeError in the
  // red banner — the absent-data crash this view exists to prevent. It must now
  // degrade to the clean empty state.
  it("POLLING: a null response body degrades to the clean empty state, not a crash banner", async () => {
    RESPONSE = null;
    const { error, warn } = await renderPollingQuietlyR5();

    expect(screen.getByTestId("coordinator-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("coordinator-cycle-card")).toBeNull();
    expect(hasCrashBanner(), "raw exception leaked to the error banner").toBe(
      false,
    );
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  // Same root cause via `undefined` (a body that parsed to nothing).
  it("POLLING: an undefined response body degrades to the clean empty state", async () => {
    RESPONSE = undefined;
    const { error } = await renderPollingQuietlyR5();

    expect(screen.getByTestId("coordinator-empty")).toBeInTheDocument();
    expect(hasCrashBanner()).toBe(false);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
  });

  // The `cycles` key entirely ABSENT (an object body the producer wrote without
  // it). `r.cycles` is undefined → not an array → [] → empty state. Already
  // robust; pinned so a future refactor can't regress it back into a crash.
  it("POLLING: a body with the cycles key absent shows the empty state", async () => {
    RESPONSE = {};
    const { error } = await renderPollingQuietlyR5();

    expect(screen.getByTestId("coordinator-empty")).toBeInTheDocument();
    expect(hasCrashBanner()).toBe(false);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
  });

  // EMPTY-but-PRESENT array — the live absent-file case (the merged backend
  // returns {cycles:[]} when run_state/coordinator_cycles.jsonl is missing). The
  // count reads 0 (not NaN, not blank), and the explicit empty state shows.
  it("POLLING: an empty-but-present cycles array shows the empty state with a 0 count", async () => {
    RESPONSE = { cycles: [] };
    const { error, warn } = await renderPollingQuietlyR5();

    expect(screen.getByTestId("coordinator-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("coordinator-cycle-card")).toBeNull();
    // The header count is an honest 0, never NaN/blank.
    const page = screen.getByTestId("coordinator-page");
    expect(page.textContent ?? "").not.toMatch(/NaN/);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  // SINGLE-element boundary: exactly one renderable cycle (not zero, not many).
  // The empty state must NOT show, exactly one card renders, the count reads 1.
  it("POLLING: a single-element list renders one card, no empty state, count 1", async () => {
    RESPONSE = { cycles: [mk({ run_id: "coordinator_solo", topic: "SOLO-CYCLE" })] };
    const { error, warn } = await renderPollingQuietlyR5();

    expect(screen.getByText("SOLO-CYCLE")).toBeInTheDocument();
    expect(screen.getAllByTestId("coordinator-cycle-card")).toHaveLength(1);
    expect(screen.queryByTestId("coordinator-empty")).toBeNull();
    const page = screen.getByTestId("coordinator-page");
    expect(page.textContent ?? "").not.toMatch(/NaN/);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  // A body where EVERY row is structurally unrenderable (all-empty/all-falsy
  // shapes a producer could append) collapses to the empty state, not a crash and
  // not a blank gap — the filter drops them all and `loaded` still flips true.
  it("POLLING: a body of only structurally-empty rows shows the empty state", async () => {
    RESPONSE = {
      cycles: [
        {} as unknown as CoordinatorCycle, // entirely empty row
        { plan: null, outcomes: null } as unknown as CoordinatorCycle, // null arrays
        null as unknown as CoordinatorCycle, // a null element
      ],
    };
    const { error } = await renderPollingQuietlyR5();

    expect(screen.getByTestId("coordinator-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("coordinator-cycle-card")).toBeNull();
    expect(hasCrashBanner()).toBe(false);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
  });
});

// ===========================================================================
// FE4 — time-range filter + sort-direction toggle (render-boundary, `initial`).
// ===========================================================================
//
// SLICE FE4 — the Coordinator header gains a time-range filter (all / today /
// this-week) and a newest/oldest-first sort toggle. The contract: DEFAULTS are
// range=all + direction=newest, so the unfiltered view is byte-for-byte the
// prior behavior (the r1/r2/r3/r5 hardening rounds above stay green untouched).
//
// Both axes compose at the RENDER boundary over the already-filtered renderable
// rows (the poll-effect sort is not touched), so we drive them through the
// synchronous `initial` path — no network, no microtask flush, just the
// controls. Date buckets read `useNow()`, so fixtures are stamped relative to
// the real wall clock at render time (a today-row = `new Date().toISOString()`,
// an old row = a fixed 2020 date well outside the 7-day window).
//
// A row's `topic` is rendered as text by CoordinatorCycleCard, so presence /
// absence of a topic string is the per-row visibility probe; the header count
// span (`renderable.length`) is read inside the header div to avoid colliding
// with the bulk-content topics.
const FE4_OLD: CoordinatorCycle = {
  timestamp: "2020-01-01T00:00:00Z",
  run_id: "fe4_old",
  agent: "coordinator",
  topic: "FE4-OLD-ROW",
  topic_source: "arxiv_pick",
  status: "executed",
  plan: [{ action: "noop", args: {} }],
  outcomes: [{ action: "noop", status: "passed" }],
  promoted_finding_ids: [],
  bubble_run_ids: [],
} as unknown as CoordinatorCycle;

function fe4Today(topic: string): CoordinatorCycle {
  return {
    timestamp: new Date().toISOString(),
    run_id: `fe4_today_${topic}`,
    agent: "coordinator",
    topic,
    topic_source: "arxiv_pick",
    status: "executed",
    plan: [{ action: "noop", args: {} }],
    outcomes: [{ action: "noop", status: "passed" }],
    promoted_finding_ids: [],
    bubble_run_ids: [],
  } as unknown as CoordinatorCycle;
}

// A structurally-renderable row whose timestamp will NOT parse — it must live in
// `all` but be excluded from `today`/`week`.
const FE4_NAN_TS: CoordinatorCycle = {
  timestamp: "not-a-real-date",
  run_id: "fe4_nan",
  agent: "coordinator",
  topic: "FE4-NAN-ROW",
  topic_source: "arxiv_pick",
  status: "executed",
  plan: [{ action: "noop", args: {} }],
  outcomes: [{ action: "noop", status: "passed" }],
  promoted_finding_ids: [],
  bubble_run_ids: [],
} as unknown as CoordinatorCycle;

describe("Coordinator FE4 — time-range filter + sort-direction toggle", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  // Default (range=all + direction=newest): every renderable row shows, ordered
  // newest-first by timestamp — the prior unfiltered behavior, unchanged.
  it("defaults to all rows, newest-first", () => {
    const a = "2026-06-09T08:00:00Z";
    const b = "2026-06-09T10:00:00Z";
    const c = "2026-06-09T12:00:00Z";
    render(
      <Coordinator
        initial={[
          { ...FE4_OLD, timestamp: a, run_id: "ord_a", topic: "ROW-A" },
          { ...FE4_OLD, timestamp: c, run_id: "ord_c", topic: "ROW-C" },
          { ...FE4_OLD, timestamp: b, run_id: "ord_b", topic: "ROW-B" },
        ]}
      />,
    );
    const cards = screen.getAllByTestId("coordinator-cycle-card");
    expect(cards).toHaveLength(3);
    // Newest first: C (12:00) → B (10:00) → A (08:00).
    const order = cards.map((card) => within(card).getByText(/ROW-[ABC]/).textContent);
    expect(order).toEqual(["ROW-C", "ROW-B", "ROW-A"]);
    // Caption reflects the defaults.
    expect(screen.getByText(/all · newest first/)).toBeInTheDocument();
  });

  // Flipping the direction toggle reverses the order (oldest-first) without
  // touching the row set.
  it("oldest-first reverses the order when the direction toggle is flipped", () => {
    render(
      <Coordinator
        initial={[
          { ...FE4_OLD, timestamp: "2026-06-09T08:00:00Z", run_id: "r_a", topic: "ROW-A" },
          { ...FE4_OLD, timestamp: "2026-06-09T12:00:00Z", run_id: "r_c", topic: "ROW-C" },
          { ...FE4_OLD, timestamp: "2026-06-09T10:00:00Z", run_id: "r_b", topic: "ROW-B" },
        ]}
      />,
    );
    fireEvent.click(screen.getByLabelText("sort direction"));
    const cards = screen.getAllByTestId("coordinator-cycle-card");
    const order = cards.map((card) => within(card).getByText(/ROW-[ABC]/).textContent);
    expect(order).toEqual(["ROW-A", "ROW-B", "ROW-C"]);
    expect(screen.getByText(/all · oldest first/)).toBeInTheDocument();
  });

  // The `today` filter keeps a today-stamped row and hides an old one.
  it("the today filter shows a today row and hides an old one", () => {
    render(<Coordinator initial={[fe4Today("FE4-TODAY-ROW"), FE4_OLD]} />);

    // Before filtering, both are present.
    expect(screen.getByText("FE4-TODAY-ROW")).toBeInTheDocument();
    expect(screen.getByText("FE4-OLD-ROW")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("time range"), {
      target: { value: "today" },
    });

    expect(screen.getByText("FE4-TODAY-ROW")).toBeInTheDocument();
    expect(screen.queryByText("FE4-OLD-ROW")).toBeNull();
    expect(screen.getAllByTestId("coordinator-cycle-card")).toHaveLength(1);
    expect(screen.getByText(/today · newest first/)).toBeInTheDocument();
  });

  // A NaN/unparseable-timestamp row is INCLUDED in `all` but EXCLUDED from
  // `today` and `week`.
  it("a NaN-timestamp row is in all, excluded from today and week", () => {
    render(<Coordinator initial={[FE4_NAN_TS, fe4Today("FE4-TODAY-ROW")]} />);

    // all (default): both visible.
    expect(screen.getByText("FE4-NAN-ROW")).toBeInTheDocument();
    expect(screen.getByText("FE4-TODAY-ROW")).toBeInTheDocument();

    // today: the NaN row drops, the today row stays.
    fireEvent.change(screen.getByLabelText("time range"), {
      target: { value: "today" },
    });
    expect(screen.queryByText("FE4-NAN-ROW")).toBeNull();
    expect(screen.getByText("FE4-TODAY-ROW")).toBeInTheDocument();

    // week: still drops the NaN row.
    fireEvent.change(screen.getByLabelText("time range"), {
      target: { value: "week" },
    });
    expect(screen.queryByText("FE4-NAN-ROW")).toBeNull();
    expect(screen.getByText("FE4-TODAY-ROW")).toBeInTheDocument();
  });
});
