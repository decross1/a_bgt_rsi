// Consolidated edge-case + property-fuzz hardening for HealthSignalsPanel (merged from per-round files).
//
// This file merges the per-round hardening suites (r1 missing/null/object
// fields · r2 malformed value TYPES · r3 scale + content · r5 empty/absent
// collections + anchors) and the property-fuzz suite into one file. Each
// source's body is wrapped in its own top-level describe so describe/it names
// never collide; every it() case and assertion is preserved verbatim. The
// shared spyConsole() helper (identical across all sources) is kept once; each
// source's afterEach and its module-level fixtures are scoped inside its own
// describe block so per-round constants (e.g. GOOD_ROW, defined differently in
// r1/r2/r5) do not collide.
import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import HealthSignalsPanel from "../src/components/HealthSignalsPanel";
import type { HealthSignal } from "../src/types/schemas";

// Mock the http client so the polling (async) path can be driven with a
// malformed/empty backend payload — the branch the `initial` prop never reaches.
// (vi.mock is hoisted to module top-level by vitest; needed by the r5 suite.)
vi.mock("../src/api/http", () => ({
  getHealthSignals: vi.fn(),
}));
import { getHealthSignals } from "../src/api/http";

// Shared across every source file (identical body in each) — kept once.
function spyConsole() {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  return { errSpy, warnSpy };
}

// ===========================================================================
// HARDENING (round 1, edge-case category: missing/null/undefined optional
// fields + entirely-absent nested objects) — HealthSignalsPanel.
//
// run_state/health_signals.jsonl is PRODUCER-OWNED (orchestrator/
// coordinator_cycle_log.py) and append-only. A partial / legacy / malformed row
// — or a line that parses as a non-object — can plausibly reach the panel: the
// type calls `signal`/`detail`/`iteration_id`/`timestamp` strings, but a real
// JSONL line could carry a number, an object, null, or omit them. Before the
// harden these crashed the WHOLE Dashboard (the panel renders inside it):
//   • signal/detail/iteration_id as an object → React "Objects are not valid as
//     a React child" throw → blanks the page.
//   • timestamp as a number → shortTimestamp's iso.replace() → TypeError.
//   • a null row in the array → `sig.signal` on null → TypeError in .map.
// The fix coerces non-primitive field values to a safe label and skips a
// non-object row (filter/skip a bad row rather than crash the list — the spec's
// "make absence legible" #2). No headless browser: jsdom + a console spy is the
// "renders without console errors" stand-in (the test_validate_panels_empty
// idiom); a render-time throw / React act() warning lands on console.error.
// ===========================================================================
describe("HealthSignalsPanel hardening — r1: partial/malformed producer rows", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  // Rows a real, partial/legacy/malformed producer line could yield. `as` casts
  // past the type precisely because the producer is not bound by it.
  const MALFORMED_ROWS = [
    null, // a JSONL line that parsed to null — must be skipped, not crash .map
    { run_id: "r1", detail: "no signal field" }, // signal omitted
    { signal: null, detail: "null signal" }, // signal null
    { signal: {}, detail: "object signal" }, // signal as object → would throw
    { signal: "ml_intern_zero_papers", detail: { nested: 1 } }, // detail as object
    { signal: "ml_intern_zero_papers", iteration_id: { x: 1 } }, // iteration_id object
    { signal: "qwen_degraded_empty_content", timestamp: 12345 }, // numeric timestamp
    { signal: "ml_intern_zero_papers" }, // every optional field absent (no nested)
  ] as unknown as HealthSignal[];

  // One well-formed row so we can prove the good data still renders alongside the
  // bad — the panel degrades the bad rows, it doesn't blank the whole list.
  const GOOD_ROW: HealthSignal = {
    signal: "ml_intern_zero_papers",
    severity: "degraded",
    timestamp: "2026-06-09T11:34:00Z",
    run_id: "cyc-good",
    iteration_id: "iter-good",
    detail: "external-search blind this iteration.",
  };

  it("renders malformed rows without throwing or logging a console error/warn", () => {
    const { errSpy, warnSpy } = spyConsole();
    expect(() =>
      render(<HealthSignalsPanel initial={MALFORMED_ROWS} />),
    ).not.toThrow();

    // The panel itself stands (the Dashboard is not blanked).
    expect(screen.getByTestId("health-signals-panel")).toBeInTheDocument();
    // No "Objects are not valid as a React child" / act() warning / TypeError.
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("keeps a good row rendered when interleaved with malformed ones", () => {
    const { errSpy, warnSpy } = spyConsole();
    // null row up front used to crash the whole .map before the good row.
    render(
      <HealthSignalsPanel initial={[null as unknown as HealthSignal, GOOD_ROW]} />,
    );

    const panel = within(screen.getByTestId("health-signals-panel"));
    // The good row survives; the null row is skipped, not rendered.
    expect(panel.getByText("ml-intern · 0 papers")).toBeInTheDocument();
    expect(panel.getByText(GOOD_ROW.detail as string)).toBeInTheDocument();
    // Skipped row → list is reindexed; exactly the one good row is present.
    expect(panel.getByTestId("health-signal-0")).toBeInTheDocument();
    expect(panel.queryByTestId("health-signal-1")).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("falls back to the clean empty state when every row is malformed", () => {
    const { errSpy, warnSpy } = spyConsole();
    // All non-object rows are filtered out → loaded-but-empty must read as the
    // clean "workers nominal" empty state, not an empty <ul> with a stray count.
    render(
      <HealthSignalsPanel
        initial={[null, 42, "oops"] as unknown as HealthSignal[]}
      />,
    );

    const panel = within(screen.getByTestId("health-signals-panel"));
    expect(screen.getByTestId("health-signals-empty")).toBeInTheDocument();
    expect(panel.queryByTestId("health-signal-0")).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});

// ===========================================================================
// HARDENING (round 2, edge-case category: malformed value TYPES — a string
// where a number is expected and vice-versa, an array where an object is
// expected, null inside arrays, NaN/Infinity numbers, garbage ISO timestamps)
// — HealthSignalsPanel.
//
// run_state/health_signals.jsonl is PRODUCER-OWNED (orchestrator/
// coordinator_cycle_log.py), append-only, and may carry a degenerate numeric
// field: this signal's row already computes counts (papers_stored / empty_calls
// / total_calls), so a NON-FINITE number (NaN / Infinity / -Infinity) is a
// plausible legacy/degenerate value — e.g. an empty-content RATE
// `empty_calls/total_calls` with total_calls=0, or a malformed line. Round 1
// already covered missing/null/object fields; this round covers the *number*
// type-mismatches r1 did not.
//
// Before this round, asLabel did `String(v)` for any primitive, so a NaN field
// rendered the LITERAL TEXT "NaN" and an Infinity field rendered "Infinity"
// straight into a chip — a sentinel masquerading as a real signal value (the
// mission's explicit "must not print NaN"). The fix drops a non-finite number to
// "" inside asLabel (the same "drop, don't crash, and never leak a sentinel"
// rule already used for objects). No throw was involved — this is a value-leak,
// caught by asserting the rendered text carries no NaN/Infinity and that the
// good row alongside still renders. No headless browser: jsdom + a console spy
// is the "renders without console errors" stand-in (the r1 / test_health_strip
// idiom); a render-time throw or React act() warning would land on console.error.
// ===========================================================================
describe("HealthSignalsPanel hardening — r2: malformed value TYPES", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  // Rows whose value TYPES are wrong in ways a real producer line could yield.
  // `as` casts past the type precisely because the producer is not bound by it.
  const MALFORMED_TYPE_ROWS = [
    // NaN / Infinity in the string-rendered fields — used to print "NaN"/"Infinity".
    { signal: "ml_intern_zero_papers", detail: NaN },
    { signal: "ml_intern_zero_papers", iteration_id: Infinity, detail: "d1" },
    { signal: "qwen_degraded_empty_content", detail: -Infinity, timestamp: NaN },
    // Two rows sharing a NaN run_id → exercises the React `key` (no dup-key warn).
    { signal: "ml_intern_zero_papers", run_id: NaN, detail: "a" },
    { signal: "qwen_degraded_empty_content", run_id: NaN, detail: "b" },
    // Array where the type expects a string (signal) / a bare array as the row.
    { signal: ["ml_intern_zero_papers"], detail: "array-signal" },
    ["ml_intern_zero_papers", 1, 2], // the whole row parsed to an array
    // String where a number is expected + a number where a string is expected.
    { signal: "ml_intern_zero_papers", papers_stored: "zero", severity: 7, detail: "d2" },
    // Garbage ISO timestamp string — must render verbatim, not throw, not NaN.
    { signal: "ml_intern_zero_papers", timestamp: "not-a-date-99-99", detail: "d3" },
  ] as unknown as HealthSignal[];

  // One well-formed row so we prove the good data still renders alongside the bad.
  const GOOD_ROW: HealthSignal = {
    signal: "qwen_degraded_empty_content",
    severity: "degraded",
    timestamp: "2026-06-09T11:34:00Z",
    run_id: "cyc-good",
    iteration_id: "iter-good",
    detail: "the independent skeptic is degraded, not down.",
  };

  it("renders malformed-type rows without throwing, printing NaN/Infinity, or logging", () => {
    const { errSpy, warnSpy } = spyConsole();
    expect(() =>
      render(<HealthSignalsPanel initial={[...MALFORMED_TYPE_ROWS, GOOD_ROW]} />),
    ).not.toThrow();

    const panel = screen.getByTestId("health-signals-panel");
    // The panel stands (the Dashboard is not blanked).
    expect(panel).toBeInTheDocument();
    // No NaN / Infinity sentinel leaked into any chip (the headline of this round).
    expect(panel.textContent ?? "").not.toMatch(/NaN|Infinity/);
    // No "Objects are not valid as a React child" / dup-key / act() warning.
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("keeps the good row visible alongside the malformed-type rows", () => {
    const { errSpy, warnSpy } = spyConsole();
    render(<HealthSignalsPanel initial={[...MALFORMED_TYPE_ROWS, GOOD_ROW]} />);

    const panel = within(screen.getByTestId("health-signals-panel"));
    // The good row survives the bad ones (degrade the bad, don't blank the list).
    expect(panel.getByText(GOOD_ROW.detail as string)).toBeInTheDocument();
    // Its humanized signal label still resolves (good row renders normally).
    expect(panel.getAllByText("qwen · empty content").length).toBeGreaterThan(0);
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("drops a NaN/Infinity field to an empty value, not the literal text", () => {
    const { errSpy, warnSpy } = spyConsole();
    // A row whose ONLY interesting fields are non-finite numbers: detail is NaN,
    // iteration_id is Infinity. Both must vanish from the chip (no "NaN", no
    // "Infinity"), while the row itself still renders (signal label present).
    render(
      <HealthSignalsPanel
        initial={
          [
            { signal: "ml_intern_zero_papers", detail: NaN, iteration_id: Infinity },
          ] as unknown as HealthSignal[]
        }
      />,
    );

    const panel = within(screen.getByTestId("health-signals-panel"));
    const row = panel.getByTestId("health-signal-0");
    expect(row).toBeInTheDocument();
    // The signal label still resolves — the row is not dropped, only its bad fields.
    expect(within(row).getByText("ml-intern · 0 papers")).toBeInTheDocument();
    // Neither sentinel text appears anywhere in the row.
    expect(row.textContent ?? "").not.toMatch(/NaN|Infinity/);
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});

// ===========================================================================
// HARDENING (round 3, edge-case category: SCALE + CONTENT — a single very long
// unbroken string (5k chars), 1000+ rows in the list, and unicode / emoji / RTL /
// newlines / HTML-looking text in fields) — HealthSignalsPanel.
//
// run_state/health_signals.jsonl is PRODUCER-OWNED (orchestrator/
// coordinator_cycle_log.py), append-only, and the `HealthSignal` type carries an
// index signature (`[key: string]: unknown`) — so a row can legitimately carry
// fields the panel only reads for the React key (`run_id`) shaped as anything.
// Rounds 1 & 2 covered missing/null/object fields and malformed number TYPES;
// this round covers VOLUME and CONTENT the earlier rounds did not.
//
// The real bug this round caught: the `<li>` React key interpolated `run_id`
// RAW (`sig.run_id ?? i`) instead of through asLabel. A producer-emitted OBJECT
// run_id stringifies to the literal "[object Object]" for every such row, so
// several rows collapsed to ONE key → React logged "Encountered two children
// with the same key" on console.error (a real console error on this category,
// and duplicated/omitted rows — React's words). The fix routes run_id through
// asLabel and appends the row index (the BubblesPanel/SurfacedFindingsPanel key
// idiom), so the key is unique even when rows share a signal + run_id.
//
// The other vectors in this category were already robust and are pinned here as
// regression guards: 1000+ rows render without throwing; a 5k-char unbroken
// string in every field renders without throw/NaN; React escapes HTML-looking
// text (no <script>/<img> element is injected) and unicode/emoji/RTL/newlines
// pass through verbatim. No headless browser: jsdom + a console spy is the
// "renders without console errors" stand-in (the r1/r2 / test_health_strip
// idiom); a render-time throw, a dup-key error, or a React act() warning would
// land on console.error/warn.
// ===========================================================================
describe("HealthSignalsPanel hardening — r3: scale + content", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  // A single 5k-char unbroken string — the mission's scale-of-content vector.
  const HUGE = "x".repeat(5000);

  it("does not collide React keys when many rows share an object run_id", () => {
    const { errSpy, warnSpy } = spyConsole();
    // run_id is producer-owned and can arrive as an object; the key used to
    // stringify each to "[object Object]" → identical keys → React dup-key error.
    const rows = Array.from({ length: 6 }, (_, i) => ({
      signal: "ml_intern_zero_papers",
      run_id: {}, // object run_id — collapses to "[object Object]" in a raw key
      detail: `row ${i}`,
    })) as unknown as HealthSignal[];

    expect(() => render(<HealthSignalsPanel initial={rows} />)).not.toThrow();
    // All six rows are present (none omitted by a dup key) and the panel stands.
    const panel = within(screen.getByTestId("health-signals-panel"));
    expect(panel.getByTestId("health-signal-0")).toBeInTheDocument();
    expect(panel.getByTestId("health-signal-5")).toBeInTheDocument();
    // No "Encountered two children with the same key" on console.error/warn.
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("renders 1000+ rows without throwing or logging", () => {
    const { errSpy, warnSpy } = spyConsole();
    const rows = Array.from({ length: 1500 }, (_, i) => ({
      signal: i % 2 === 0 ? "ml_intern_zero_papers" : "qwen_degraded_empty_content",
      run_id: `cyc-${i}`,
      iteration_id: `iter-${i}`,
      timestamp: "2026-06-09T11:34:00Z",
      detail: `degraded signal ${i}`,
    })) as unknown as HealthSignal[];

    expect(() => render(<HealthSignalsPanel initial={rows} />)).not.toThrow();
    const panel = screen.getByTestId("health-signals-panel");
    // The count reflects the full set and the last row rendered (no silent cap).
    expect(within(panel).getByText("1500")).toBeInTheDocument();
    expect(within(panel).getByTestId("health-signal-1499")).toBeInTheDocument();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("renders a 5k-char unbroken string in every field without throwing or NaN", () => {
    const { errSpy, warnSpy } = spyConsole();
    const rows = [
      {
        signal: HUGE,
        detail: HUGE,
        iteration_id: HUGE,
        run_id: HUGE,
        timestamp: HUGE,
      },
    ] as unknown as HealthSignal[];

    expect(() => render(<HealthSignalsPanel initial={rows} />)).not.toThrow();
    const panel = screen.getByTestId("health-signals-panel");
    // The huge string renders verbatim — in BOTH the iteration_id chip and the
    // detail line (getAllByText: the panel renders it more than once, it does
    // not blank or throw on a 5k-char unbroken run).
    expect(within(panel).getAllByText(HUGE).length).toBeGreaterThan(0);
    // No sentinel text leaked from the long-string handling.
    expect(panel.textContent ?? "").not.toMatch(/NaN|Infinity/);
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("escapes HTML-looking text and passes unicode/emoji/RTL/newlines verbatim", () => {
    const { errSpy, warnSpy } = spyConsole();
    const htmlLike = "<script>alert(1)</script><img src=x onerror=boom>";
    const unicode = "ml-intern 🔬🧪 ‮مرحبا‬ line\nbreak\ttab";
    const rows = [
      { signal: "ml_intern_zero_papers", detail: htmlLike, iteration_id: "<b>x</b>" },
      { signal: "qwen_degraded_empty_content", detail: unicode, iteration_id: "iter-🧪" },
    ] as unknown as HealthSignal[];

    expect(() => render(<HealthSignalsPanel initial={rows} />)).not.toThrow();
    const panel = screen.getByTestId("health-signals-panel");
    // React escapes: the HTML-looking string is inert TEXT, not parsed nodes.
    expect(panel.querySelector("script")).toBeNull();
    expect(panel.querySelector("img")).toBeNull();
    expect(within(panel).getByText(htmlLike)).toBeInTheDocument();
    // Unicode/emoji/RTL/newline content renders verbatim. getByText normalizes
    // whitespace (collapses the \n/\t), so assert against the raw textContent —
    // the emoji, RTL marks and literal newline/tab all survive the render.
    expect(panel.textContent ?? "").toContain(unicode);
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});

// ===========================================================================
// HARDENING (round 5, edge-case category: empty-vs-absent collections + boundary
// numbers — empty arrays vs absent arrays, empty strings, all-falsy rows,
// single-element lists; empty states correct, no blank/phantom rows) —
// HealthSignalsPanel.
//
// run_state/health_signals.jsonl is PRODUCER-OWNED (orchestrator/
// coordinator_cycle_log.py), append-only, and a row's `signal` — the chip the
// panel renders UNCONDITIONALLY as the row's anchor — can plausibly arrive
// empty: an empty string, whitespace-only, or absent (asLabel coerces all three
// to ""). Rounds 1–3 covered null/object fields, malformed number TYPES, and
// scale/content; none asserted what a SURVIVING row with an EMPTY signal
// renders.
//
// The real bug this round caught: with `signal:""` the chip rendered a
// CONTENT-LESS amber pill (`<span ...amber-400></span>` with textContent "") —
// a phantom degraded signal with no identity, the opposite of the spec's
// "make absence legible" (#2). r1 let it pass because its empty-signal rows were
// all-malformed (→ tested only the empty-STATE), never a row that survives
// alongside good data. The fix gives signalLabel a legible "(unknown signal)"
// fallback for an empty/blank key (the sibling BubblesPanel `note || "(no note)"`
// idiom), so the anchor chip never renders blank.
//
// The other in-category vectors were already robust and are pinned here as
// regression guards: the ASYNC backend payload returning an ABSENT collection
// (`health_signals:null` / a non-array) → clean empty state, not a crash; an
// all-falsy row still renders its anchor; a single-element list renders. No
// headless browser: jsdom + a console spy is the "renders without console
// errors" stand-in (the r1–r3 / test_health_strip idiom); a render-time throw,
// a dup-key error, or a React act() warning lands on console.error/warn.
// (The vi.mock("../src/api/http") and getHealthSignals import are hoisted to
// module top-level above so the async polling path can be driven here.)
// ===========================================================================
describe("HealthSignalsPanel hardening — r5: empty/absent collections + anchors", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  // A good row so we can prove the fix degrades only the empty anchor, not the list.
  const GOOD_ROW: HealthSignal = {
    signal: "ml_intern_zero_papers",
    severity: "degraded",
    timestamp: "2026-06-09T11:34:00Z",
    run_id: "cyc-good",
    iteration_id: "iter-good",
    detail: "external-search blind this iteration.",
  };

  it("renders a legible chip (not a blank pill) for an empty-string signal", () => {
    const { errSpy, warnSpy } = spyConsole();
    // The headline: `signal:""` with a real detail — the row survives, so the
    // anchor chip must name something rather than render content-less.
    const rows = [
      { signal: "", detail: "qwen returned empty content on 2/3 calls", run_id: "r1" },
    ] as unknown as HealthSignal[];
    render(<HealthSignalsPanel initial={rows} />);

    const row = screen.getByTestId("health-signal-0");
    const chip = row.querySelector("span.text-amber-400");
    // The anchor chip carries a legible, non-blank token (the bug was "").
    expect((chip?.textContent ?? "").trim()).not.toBe("");
    expect(chip).toHaveTextContent("(unknown signal)");
    // The row's real detail still renders — only the empty anchor is filled in.
    expect(within(row).getByText("qwen returned empty content on 2/3 calls")).toBeInTheDocument();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("fills the anchor for a whitespace-only AND an absent signal too", () => {
    const { errSpy, warnSpy } = spyConsole();
    // Whitespace-only ("   " → blank pill pre-fix) and an entirely ABSENT signal
    // field (asLabel → "") both resolve to the same legible fallback.
    const rows = [
      { signal: "   ", detail: "whitespace signal", run_id: "rws" },
      { detail: "absent signal field", run_id: "rabs" }, // no `signal` key at all
    ] as unknown as HealthSignal[];
    render(<HealthSignalsPanel initial={rows} />);

    const panel = within(screen.getByTestId("health-signals-panel"));
    // Both rows render with a filled anchor (getAllByText: the fallback appears twice).
    expect(panel.getAllByText("(unknown signal)").length).toBe(2);
    // Neither anchor pill is left blank.
    for (const i of [0, 1]) {
      const chip = panel.getByTestId(`health-signal-${i}`).querySelector("span.text-amber-400");
      expect((chip?.textContent ?? "").trim()).not.toBe("");
    }
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("an all-falsy row renders its anchor and does not blank the list beside a good row", () => {
    const { errSpy, warnSpy } = spyConsole();
    // Every renderable field falsy/empty — the empty-vs-absent boundary case. The
    // row must still render (with the legible anchor) and not suppress the good row.
    const allFalsy = {
      signal: "",
      detail: "",
      iteration_id: "",
      run_id: "",
      timestamp: "",
    } as unknown as HealthSignal;
    render(<HealthSignalsPanel initial={[allFalsy, GOOD_ROW]} />);

    const panel = within(screen.getByTestId("health-signals-panel"));
    // The all-falsy row is present (anchor filled), index 0.
    const falsyRow = panel.getByTestId("health-signal-0");
    expect(within(falsyRow).getByText("(unknown signal)")).toBeInTheDocument();
    // An empty timestamp falls back to the em-dash (not blank, not a throw).
    expect(falsyRow.textContent ?? "").toContain("—");
    // The good row beside it still renders normally.
    expect(panel.getByText("ml-intern · 0 papers")).toBeInTheDocument();
    expect(panel.getByText(GOOD_ROW.detail as string)).toBeInTheDocument();
    // Count reflects both renderable rows.
    expect(panel.getByText("2")).toBeInTheDocument();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a known signal still humanizes (the fallback does not shadow real labels)", () => {
    const { errSpy, warnSpy } = spyConsole();
    // Guard: the empty-key fallback must not hijack a legitimate signal id.
    const rows = [
      { signal: "qwen_degraded_empty_content", detail: "d", run_id: "r" },
    ] as unknown as HealthSignal[];
    render(<HealthSignalsPanel initial={rows} />);

    const panel = within(screen.getByTestId("health-signals-panel"));
    expect(panel.getByText("qwen · empty content")).toBeInTheDocument();
    expect(panel.queryByText("(unknown signal)")).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("async backend returning an ABSENT collection (health_signals:null) → clean empty state", async () => {
    const { errSpy, warnSpy } = spyConsole();
    // The empty-vs-absent boundary on the POLLING path: a producer/backend that
    // returns {health_signals:null} (or omits the key) must coerce to [] and
    // show the clean "workers nominal" empty state — never crash on `null.filter`.
    (getHealthSignals as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue({
      health_signals: null,
    });
    render(<HealthSignalsPanel pollMs={1_000_000} />);

    // Wait for the async resolve to flip `loaded` and render the empty state.
    await waitFor(() =>
      expect(screen.getByTestId("health-signals-empty")).toBeInTheDocument(),
    );
    const panel = within(screen.getByTestId("health-signals-panel"));
    expect(panel.queryByTestId("health-signal-0")).toBeNull();
    expect(panel.getByText("0")).toBeInTheDocument();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("async backend returning a non-array collection (a bare object) → clean empty state", async () => {
    const { errSpy, warnSpy } = spyConsole();
    // `health_signals` arriving as a single object (not an array) is producer-
    // owned malformity on the polling path; the Array.isArray guard must coerce
    // it to [] rather than letting `.filter` throw and blank the Dashboard.
    (getHealthSignals as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue({
      health_signals: { signal: "ml_intern_zero_papers" },
    });
    render(<HealthSignalsPanel pollMs={1_000_000} />);

    await waitFor(() =>
      expect(screen.getByTestId("health-signals-empty")).toBeInTheDocument(),
    );
    expect(
      within(screen.getByTestId("health-signals-panel")).queryByTestId("health-signal-0"),
    ).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a single-element list renders that one row and a count of 1", () => {
    const { errSpy, warnSpy } = spyConsole();
    // Boundary: single-element collection (not empty, not many) — exactly one row.
    render(<HealthSignalsPanel initial={[GOOD_ROW]} />);
    const panel = within(screen.getByTestId("health-signals-panel"));
    expect(panel.getByTestId("health-signal-0")).toBeInTheDocument();
    expect(panel.queryByTestId("health-signal-1")).toBeNull();
    expect(panel.getByText("1")).toBeInTheDocument();
    expect(panel.queryByTestId("health-signals-empty")).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});

// ===========================================================================
// PROPERTY-FUZZ — HealthSignalsPanel.
//
// run_state/health_signals.jsonl is PRODUCER-OWNED (orchestrator/
// coordinator_cycle_log.py), append-only, and a JSONL line can carry ANY shape:
// the `HealthSignal` type calls signal/detail/iteration_id/timestamp/run_id
// strings, but a real line could put a number, NaN/Infinity, boolean, null,
// object, or array in any of them, or omit it entirely. The hand-written
// hardening rounds (r1 missing/null/object fields · r2 malformed number TYPES ·
// r3 scale/content/HTML/unicode · r5 empty/absent collections + anchors) each
// pinned ONE dimension in isolation. This file is the COMBINATION coverage:
// ~50 deterministic pseudo-random rows that vary presence/absence AND type AND
// length of every field at once, to catch a shape the isolated rounds missed.
//
// Determinism: every value is derived purely from the row index via a seeded
// LCG (mulberry32) — NO Math.random / Date.now / crypto, so a failing index is
// always the same row and the integrator can reproduce it. The invariant is the
// component's contract: it must NEVER throw and must log NO console.error/warn
// on ANY producer-shaped row (a render throw / "Objects are not valid as a React
// child" / dup-key / act() warning all land on console.error/warn). If a
// generated row DOES trip it, that is a real component bug — this test owns only
// the test file; the integrator/harden fixes the component (reported in
// bugs_found + followups). No headless browser: jsdom + a console spy is the
// "renders without console errors" stand-in (the test_health_strip /
// test_harden_HealthSignalsPanel_r* idiom).
// ===========================================================================
describe("HealthSignalsPanel hardening — fuzz: property fuzz (deterministic, ~50 rows)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  // mulberry32 — a tiny deterministic PRNG seeded from a 32-bit integer. Pure
  // function of its state: identical seed → identical stream, so row `i` is the
  // same on every run (no RNG source is consulted). Returns a float in [0, 1).
  function mulberry32(seed: number): () => number {
    let a = seed >>> 0;
    return function () {
      a |= 0;
      a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // The pool of value SHAPES a producer-owned JSONL field can plausibly hold —
  // the union the panel must survive in any field. Covers the primitives the type
  // claims (string), the malformed numbers (NaN/Infinity), the React-child hazards
  // (object/array), null/undefined, and content hazards (HTML/unicode/long).
  const KNOWN_SIGNALS = [
    "ml_intern_zero_papers",
    "qwen_degraded_empty_content",
    "some_future_emit_signal", // forward-compat: an unknown id must still render
  ];
  function valueForChoice(choice: number, rng: () => number): unknown {
    switch (choice) {
      case 0:
        return undefined; // field omitted
      case 1:
        return null;
      case 2:
        return ""; // empty string
      case 3:
        return "   "; // whitespace-only
      case 4:
        return KNOWN_SIGNALS[Math.floor(rng() * KNOWN_SIGNALS.length)];
      case 5:
        return `cyc-${Math.floor(rng() * 100000)}`;
      case 6:
        return Math.floor(rng() * 1e9); // a normal finite number
      case 7:
        return -(rng() * 1000); // a negative float
      case 8:
        return 0;
      case 9:
        return NaN;
      case 10:
        return rng() < 0.5 ? Infinity : -Infinity;
      case 11:
        return rng() < 0.5; // boolean
      case 12:
        return {}; // object — React-child hazard
      case 13:
        return { nested: { run_id: "x" }, n: Math.floor(rng() * 10) };
      case 14:
        return ["ml_intern_zero_papers", 1, null]; // array
      case 15:
        return "<script>alert(1)</script><img src=x onerror=boom>"; // HTML-looking
      case 16:
        return "ml-intern 🔬🧪 ‮مرحبا‬ line\nbreak\ttab"; // unicode/emoji/RTL/newline
      case 17:
        return "x".repeat(2000 + Math.floor(rng() * 1500)); // long unbroken string
      case 18:
        return "2026-06-09T11:34:00Z"; // a real ISO timestamp
      default:
        return "not-a-date-99-99"; // garbage ISO string
    }
  }

  // Build one fully-random row deterministically from `i`. Each render-relevant
  // field (signal/severity/timestamp/run_id/iteration_id/detail) and a couple of
  // index-signature extras independently picks a shape from the pool. Some rows
  // are deliberately degenerate: the WHOLE row may be a non-object (null / scalar /
  // array) — a JSONL line that parsed to a non-object, which the panel must skip
  // rather than crash on. Returns `unknown` because a producer is not bound by the
  // HealthSignal type (the same `as`-cast the hardening rounds use).
  function fuzzRow(i: number): unknown {
    const rng = mulberry32(i * 2654435761 + 1);
    const roll = rng();
    // ~1 in 9 rows is a non-object line (null / bare scalar / array) — the
    // "parsed to a non-object" case the component filters out.
    if (roll < 0.04) return null;
    if (roll < 0.08) return Math.floor(rng() * 1000);
    if (roll < 0.11) return ["ml_intern_zero_papers", 1, 2];

    const POOL = 20;
    const row: Record<string, unknown> = {};
    // For each field, ~15% of the time omit it entirely; otherwise pick a shape.
    const fields = [
      "signal",
      "severity",
      "timestamp",
      "run_id",
      "iteration_id",
      "detail",
      "papers_stored", // index-signature extra (numeric in the fixture)
      "empty_calls", // index-signature extra
      "extra_unknown_field", // a field the panel never reads
    ];
    for (const f of fields) {
      if (rng() < 0.15) continue; // omit
      row[f] = valueForChoice(Math.floor(rng() * POOL), rng);
    }
    return row;
  }

  const N = 50;
  const ROWS: unknown[] = Array.from({ length: N }, (_, i) => fuzzRow(i));

  it("renders the full batch of fuzzed rows without throwing or logging", () => {
    const { errSpy, warnSpy } = spyConsole();

    expect(() =>
      render(<HealthSignalsPanel initial={ROWS as unknown as HealthSignal[]} />),
    ).not.toThrow();

    // The panel itself always stands (the Dashboard embedding it is not blanked).
    expect(screen.getByTestId("health-signals-panel")).toBeInTheDocument();
    // The invariant: no render throw, no "Objects are not valid as a React
    // child", no duplicate-key error, no React act() warning — on ANY of the 50.
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("renders no NaN/Infinity sentinel text anywhere in the batch", () => {
    spyConsole();
    render(<HealthSignalsPanel initial={ROWS as unknown as HealthSignal[]} />);
    const panel = screen.getByTestId("health-signals-panel");
    // A non-finite number in any string-rendered field must drop to "", never
    // leak the literal "NaN"/"Infinity" into a chip (asLabel's contract).
    expect(panel.textContent ?? "").not.toMatch(/NaN|Infinity/);
    // No HTML-looking field is ever parsed into a live node (React escapes text).
    expect(panel.querySelector("script")).toBeNull();
    expect(panel.querySelector("img")).toBeNull();
  });

  it("renders EACH fuzzed row in isolation without throwing or logging", () => {
    // Render rows one at a time so a failure is attributable to a single index —
    // the batch test proves the aggregate, this localizes a regression for the
    // integrator. A throw or console.error/warn on row `i` fails here with `i`.
    for (let i = 0; i < N; i++) {
      const { errSpy, warnSpy } = spyConsole();
      const row = ROWS[i];
      let threw: unknown = null;
      try {
        render(
          <HealthSignalsPanel initial={[row] as unknown as HealthSignal[]} />,
        );
      } catch (e) {
        threw = e;
      }
      // Attach the offending row to the assertion message so a real bug report
      // carries the exact shape that tripped the component.
      const ctx = `row ${i} = ${(() => {
        try {
          return JSON.stringify(row);
        } catch {
          return String(row);
        }
      })()}`;
      expect(threw, `threw on ${ctx}`).toBeNull();
      expect(errSpy, `console.error on ${ctx}`).not.toHaveBeenCalled();
      expect(warnSpy, `console.warn on ${ctx}`).not.toHaveBeenCalled();
      vi.restoreAllMocks();
    }
  });
});
