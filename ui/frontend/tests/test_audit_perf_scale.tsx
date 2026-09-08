// CROSS-CUTTING AUDIT — perf-scale. The largest-cardinality surviving
// surface is run_state/coordinator_cycles.jsonl behind the /cycles route
// (one row per coordinator cycle, append-only, never truncated). This audit
// renders it at 2000 synthetic rows and asserts it (a) renders the real data
// (never blanks/crashes), (b) does not hang or recurse, and (c) emits no
// React console.error/console.warn. (The ResolvedIterationsList half died
// with that component in UI simplification S3 — the dossier index owns
// iteration browsing now and paginates its own way.)
//
//   - The /cycles route is NOT DOM-bounded: it maps EVERY renderable cycle
//     to a <CoordinatorCycleCard> with no pagination (`renderable.map(...)`),
//     so 2000 cycles → 2000 cards. It still renders without throwing/hanging/
//     logging (verified here), but the DOM grows O(N). That unbounded render
//     stays a reported followup; this test PINS the current linear behavior
//     so the audit is documented, not silently changed.
//
// jsdom note: there is no headless browser here, so "renders cleanly" = the
// component/route mounts, the expected nodes exist, and console.error/warn (a
// thrown React render lands in console.error too) are spied and asserted empty.
// Timing uses a deliberately LOOSE ceiling: it is a hang/quadratic-blowup trip
// wire, not a micro-benchmark — jsdom rendering thousands of React nodes is
// inherently slow, and a tight bound would be flaky across machines/CI load.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Cycles from "../src/routes/Cycles";
import type { CoordinatorCycle } from "../src/types/schemas";

const SCALE = 2000;

// A loose wall-clock ceiling for a single 2000-row synchronous render. This is
// NOT a benchmark target — it exists only to fail on a true hang / O(N^2)
// blowup (which would run for tens of seconds), not on ordinary jsdom slowness.
const RENDER_CEILING_MS = 20_000;

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

  // /cycles route at 2000 cycles. AUDIT FINDING: this route is NOT
  // DOM-bounded — it renders one card per cycle (no pagination). It still
  // renders without throwing/hanging/logging at scale (proven here); the
  // unbounded DOM growth is a reported followup, not fixed here (a pagination
  // change would also break the harden suite's 1002→1002 cards assertion +
  // need a route-owner edit). This test PINS the current linear behavior so
  // the audit is documented, not silently changed.
  it("Cycles route renders 2000 cycles without hang/crash (DOM grows O(N) — see followups)", () => {
    const { collect, restore } = spyConsole();
    const cycles = makeCycles(SCALE);

    const t0 = performance.now();
    expect(() =>
      render(<Cycles initial={cycles} initialPhasesRun={null} />),
    ).not.toThrow();
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
