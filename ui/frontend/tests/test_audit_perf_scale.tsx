// CROSS-CUTTING AUDIT — perf-scale. The two largest-cardinality surfaces are
// the producer-owned, append-only JSONL lists: memory/loop_memory.jsonl behind
// <ResolvedIterationsList> and run_state/coordinator_cycles.jsonl behind the
// /coordinator route. Both grow WITHOUT BOUND over the apparatus's lifetime
// (one row per iteration / per coordinator cycle, never truncated). This audit
// renders each at 2000 synthetic rows and asserts it (a) renders the real data
// (never blanks/crashes), (b) does not hang or recurse, (c) emits no React
// console.error/console.warn, and (d) keeps the DOM within the bound the
// component actually enforces.
//
// The two surfaces have DIFFERENT bounding contracts, and this audit pins each:
//
//   - <ResolvedIterationsList> IS DOM-bounded: it paginates (PAGE_SIZE rows/
//     page, `filtered.slice(...)`), so 2000 rows render exactly PAGE_SIZE
//     journal-row buttons — the DOM node count is O(PAGE_SIZE), independent of
//     input size. The pager reports "page 1 of 200". This is the desired shape.
//
//   - The /coordinator route is NOT DOM-bounded: it maps EVERY renderable cycle
//     to a <CoordinatorCycleCard> with no pagination (`renderable.map(...)`), so
//     2000 cycles → 2000 cards. It still renders without throwing/hanging/
//     logging (verified here), but the DOM grows O(N). That unbounded render is
//     reported as a followup for the serial integrator (a route-level pagination
//     change would also need a fixture/existing-test update — see
//     test_harden_Coordinator_r3.tsx, which asserts 1002 rows → 1002 cards — so
//     it is out of scope for a single parallel-safe component edit). This test
//     therefore PINS the current behavior (linear card count) rather than
//     contradicting that existing assertion: the audit's job is to surface the
//     scaling characteristic and prove "does not hang", not to silently flip it.
//
// jsdom note: there is no headless browser here, so "renders cleanly" = the
// component/route mounts, the expected nodes exist, and console.error/warn (a
// thrown React render lands in console.error too) are spied and asserted empty.
// Timing uses a deliberately LOOSE ceiling: it is a hang/quadratic-blowup trip
// wire, not a micro-benchmark — jsdom rendering thousands of React nodes is
// inherently slow, and a tight bound would be flaky across machines/CI load.
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResolvedIterationsList from "../src/components/ResolvedIterationsList";
import Coordinator from "../src/routes/Coordinator";
import type {
  CoordinatorCycle,
  IterationRecord,
} from "../src/types/schemas";

const PAGE_SIZE = 10; // mirrors ResolvedIterationsList's PAGE_SIZE
const SCALE = 2000;

// A loose wall-clock ceiling for a single 2000-row synchronous render. This is
// NOT a benchmark target — it exists only to fail on a true hang / O(N^2)
// blowup (which would run for tens of seconds), not on ordinary jsdom slowness.
const RENDER_CEILING_MS = 20_000;

// Build N synthetic iteration rows, newest-first by ended_at, cycling the
// novelty/verdict enums so the render path exercises the badge tone lookups.
// Mirrors makeRows() in test_resolved_iterations_list.tsx.
function makeIterations(n: number): IterationRecord[] {
  const novelties = ["novel", "rediscovery", "unclear", "nonsense"] as const;
  const verdicts = ["survives", "restated", "falsified", "malformed"] as const;
  return Array.from({ length: n }, (_, i) => {
    const day = String(28 - (i % 28)).padStart(2, "0");
    return {
      iteration_id: `iter-${String(i).padStart(4, "0")}`,
      started_at: `2026-05-${day}T10:00:00Z`,
      ended_at: `2026-05-${day}T10:05:00Z`,
      seed: { topic: `scale topic ${i}`, source: "coordinator" },
      novelty: { class: novelties[i % 4] },
      critique: { verdict: verdicts[i % 4] },
      journal_entry_path: `journal/iterations/${i}.md`,
    } satisfies IterationRecord;
  });
}

// Build N synthetic coordinator cycles, newest-first, each a well-formed row
// with a small plan/outcomes so every card walks its real render path (the
// plan list, the errored-chip branch, the footer counts). Mirrors the mk()
// shape in test_harden_Coordinator_r3.tsx but with a unique run_id per row.
function makeCycles(n: number): CoordinatorCycle[] {
  return Array.from({ length: n }, (_, i) => {
    const min = String(i % 60).padStart(2, "0");
    return {
      timestamp: `2026-06-09T10:${min}:00Z`,
      run_id: `cyc-${String(i).padStart(4, "0")}`,
      agent: "coordinator",
      topic: `scale cycle ${i}`,
      topic_source: "arxiv_pick",
      status: "executed",
      plan: [
        { action: "assess_memory", args: {} },
        { action: "run_loop_iteration", args: { k: 8 } },
      ],
      outcomes: [
        { action: "assess_memory", status: "passed" },
        { action: "run_loop_iteration", status: "passed" },
      ],
      promoted_finding_ids: [],
      bubble_run_ids: [],
    } satisfies CoordinatorCycle;
  });
}

// Count rendered journal-row buttons (excludes filter/pager controls) —
// mirrors visibleRowCount() in test_resolved_iterations_list.tsx.
function journalRowCount(): number {
  return screen.queryAllByRole("button", { name: /^load journal / }).length;
}

// React's act() advisory is test-harness noise, not a production log; a real
// thrown render or duplicate-key collision still lands in console.error and is
// kept. Returns the filtered error/warn messages a render emitted.
function spyConsole() {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  const collect = () => ({
    error: errSpy.mock.calls
      .map((c) => String(c[0]))
      .filter((m) => !m.includes("not wrapped in act")),
    warn: warnSpy.mock.calls
      .map((c) => String(c[0]))
      .filter((m) => !m.includes("not wrapped in act")),
  });
  const restore = () => {
    errSpy.mockRestore();
    warnSpy.mockRestore();
  };
  return { collect, restore };
}

describe("perf-scale audit — large producer-owned lists render bounded & quiet", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  // ResolvedIterationsList: the endpoint returns ALL rows newest-first and
  // grows without bound, but the component paginates. At 2000 rows the DOM must
  // stay capped at PAGE_SIZE journal-row buttons — the whole point of the
  // client-side pagination is that DOM size is O(PAGE_SIZE), not O(rows).
  it("ResolvedIterationsList caps the DOM at PAGE_SIZE with 2000 rows", () => {
    const { collect, restore } = spyConsole();
    const rows = makeIterations(SCALE);

    const t0 = performance.now();
    expect(() =>
      render(<ResolvedIterationsList initial={rows} />),
    ).not.toThrow();
    const elapsed = performance.now() - t0;

    // The DOM is bounded: exactly PAGE_SIZE rows render, not 2000. This is the
    // anti-"blow the DOM" assertion — a regression that dropped pagination
    // would render 2000 buttons and fail here.
    expect(journalRowCount()).toBe(PAGE_SIZE);

    // The full count is still surfaced (the panel reports "2000"), and the
    // pager reflects the full page span so the user can reach every row.
    expect(screen.getByTestId("resolved-count")).toHaveTextContent(
      String(SCALE),
    );
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      `page 1 of ${SCALE / PAGE_SIZE}`,
    );

    // Did not hang / recurse.
    expect(elapsed).toBeLessThan(RENDER_CEILING_MS);

    const { error, warn } = collect();
    restore();
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  // The polled path also re-sorts 2000 rows on every poll (the newest-first
  // localeCompare sort runs over the whole array). Exercise that path at scale
  // to prove the sort+slice does not hang or log, and still caps the DOM.
  it("ResolvedIterationsList polled path sorts+caps 2000 rows quietly", async () => {
    const rows = makeIterations(SCALE);
    vi.resetModules();
    vi.doMock("../src/api/http", () => ({
      getIterations: vi.fn(() => Promise.resolve({ iterations: rows })),
    }));
    const { default: Polled } = await import(
      "../src/components/ResolvedIterationsList"
    );

    const { collect, restore } = spyConsole();
    const t0 = performance.now();
    render(<Polled pollMs={999_999} />);
    await waitFor(() => {
      expect(journalRowCount()).toBe(PAGE_SIZE);
    });
    const elapsed = performance.now() - t0;
    expect(elapsed).toBeLessThan(RENDER_CEILING_MS);

    const { error, warn } = collect();
    restore();
    vi.doUnmock("../src/api/http");
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  // /coordinator route at 2000 cycles. AUDIT FINDING: this route is NOT
  // DOM-bounded — it renders one card per cycle (no pagination). It still
  // renders without throwing/hanging/logging at scale (proven here); the
  // unbounded DOM growth is a reported followup, not fixed here (a pagination
  // change would also break test_harden_Coordinator_r3.tsx's 1002→1002 cards
  // assertion + need a route-owner edit). This test PINS the current linear
  // behavior so the audit is documented, not silently changed.
  it("Coordinator route renders 2000 cycles without hang/crash (DOM grows O(N) — see followups)", () => {
    const { collect, restore } = spyConsole();
    const cycles = makeCycles(SCALE);

    const t0 = performance.now();
    expect(() => render(<Coordinator initial={cycles} />)).not.toThrow();
    const elapsed = performance.now() - t0;

    // The page mounted and is the real surface (not an error banner / blank).
    expect(screen.getByTestId("coordinator-page")).toBeInTheDocument();
    // The header count reflects the renderable total — not NaN, not truncated.
    const pageText =
      screen.getByTestId("coordinator-page").textContent ?? "";
    expect(pageText).not.toMatch(/NaN/);

    // Current (unbounded) contract: one card per cycle. If a future change adds
    // pagination this assertion flips — that is the intended trigger to revisit
    // the followup, not a silent regression.
    const cards = screen.getAllByTestId("coordinator-cycle-card");
    expect(cards).toHaveLength(SCALE);

    // The render completed — it did not hang or blow the stack on 2000 cards.
    expect(elapsed).toBeLessThan(RENDER_CEILING_MS);

    const { error, warn } = collect();
    restore();
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });
});
