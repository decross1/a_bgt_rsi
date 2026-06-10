// ActiveIterationPanel's step strip vs the new optional `steps[]` board
// (2026-06-10 Task 5; schema/active_iteration.schema.json). Pins:
//
//   1. PRODUCER ORDER: the board renders steps[] exactly as emitted —
//      meta_review + the 5-step chain with a dynamic `redteam` insertion and
//      an UNKNOWN name rendered raw (never sorted, never filtered).
//   2. TONES per status: pending zinc; running emerald-BORDER with a ticking
//      elapsed (src/time.ts useNow/elapsed); passed quiet emerald + duration;
//      failed red + duration; skipped dim zinc; unknown status → quiet zinc.
//   3. LEGACY FALLBACK: steps absent (or unusable garbage) → the static
//      pre-2026-06-10 strip renders unchanged, without the new caption.
//   4. The sequential-within / concurrent-across caption sits under the board.
//
// Fixtures are EXPLICITLY SYNTHETIC, shaped exactly like the schema (all five
// statuses, a dynamic redteam insertion, an unknown name) — the board lights
// up live on the first post-EMIT iteration.
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ActiveIterationPanel from "../src/components/ActiveIterationPanel";
import type { ActiveIteration, IterationStep } from "../src/types/schemas";

afterEach(() => {
  vi.restoreAllMocks();
});

// Producer-order board: every status from the schema enum, the dynamic
// redteam insertion after hypothesize, and one never-seen step name.
const STEPS: IterationStep[] = [
  {
    name: "meta_review",
    status: "passed",
    started_at: "2026-06-10T10:00:00Z",
    ended_at: "2026-06-10T10:00:12.300Z",
  },
  {
    name: "hypothesize",
    status: "passed",
    started_at: "2026-06-10T10:00:12.300Z",
    ended_at: "2026-06-10T10:00:30.300Z",
  },
  {
    // Dynamic sub-loop insertion (the producer adds it when redteam fires).
    name: "redteam",
    status: "failed",
    started_at: "2026-06-10T10:00:30.300Z",
    ended_at: "2026-06-10T10:01:00.300Z",
  },
  {
    name: "retrieve_literature",
    status: "running",
    started_at: "2026-06-10T10:01:00.300Z",
  },
  { name: "novelty_classify", status: "pending" },
  { name: "critic_loop_v0", status: "skipped" },
  // Unknown producer-added step: renders RAW, never filtered.
  { name: "entropy_probe_v2", status: "pending" },
  { name: "journal_writer", status: "pending" },
];

function fixture(over: Partial<ActiveIteration> = {}): ActiveIteration {
  return {
    iteration_id: "iter-2026-06-10-001",
    topic: "Steps-board synthetic iteration",
    started_at: "2026-06-10T10:00:00Z",
    current_step: "retrieve_literature",
    tool_calls_so_far: [],
    steps: STEPS,
    ...over,
  };
}

describe("step strip — steps[] board", () => {
  it("renders every step in PRODUCER ORDER, unknown names raw, nothing filtered", () => {
    render(<ActiveIterationPanel initial={fixture()} />);
    const board = screen.getByTestId("steps-board");
    const chips = Array.from(
      board.querySelectorAll('[data-testid^="board-step-"]'),
    );
    // Exact name sequence == array order as emitted.
    const names = chips.map(
      (c) => c.getAttribute("data-testid")!.replace("board-step-", ""),
    );
    expect(names).toEqual([
      "meta_review",
      "hypothesize",
      "redteam",
      "retrieve_literature",
      "novelty_classify",
      "critic_loop_v0",
      "entropy_probe_v2",
      "journal_writer",
    ]);
    // The unknown step renders its raw name.
    expect(screen.getByTestId("board-step-entropy_probe_v2")).toHaveTextContent(
      "entropy_probe_v2",
    );
  });

  it("tones: pending zinc, running emerald-border, passed quiet emerald + duration, failed red + duration, skipped dim zinc", () => {
    render(<ActiveIterationPanel initial={fixture()} />);

    const pending = screen.getByTestId("board-step-novelty_classify");
    expect(pending.className).toMatch(/zinc/);
    expect(pending.className).not.toMatch(/emerald|red/);

    const running = screen.getByTestId("board-step-retrieve_literature");
    expect(running.className).toContain("border-emerald-600");
    expect(running.getAttribute("data-status")).toBe("running");

    const passed = screen.getByTestId("board-step-meta_review");
    expect(passed.className).toMatch(/emerald/);
    expect(passed).toHaveTextContent("12.3s"); // ended_at - started_at

    const failed = screen.getByTestId("board-step-redteam");
    expect(failed.className).toMatch(/red/);
    expect(failed).toHaveTextContent("30.0s");

    const skipped = screen.getByTestId("board-step-critic_loop_v0");
    expect(skipped.className).toMatch(/zinc/);
    expect(skipped.getAttribute("data-status")).toBe("skipped");
  });

  it("the running step's elapsed TICKS off useNow", async () => {
    vi.useFakeTimers();
    try {
      // Freeze "now" 95s after the running step started so elapsed is exact,
      // then advance the clock and watch the label move.
      vi.setSystemTime(new Date("2026-06-10T10:02:35.300Z"));
      render(<ActiveIterationPanel initial={fixture()} pollMs={1000} />);
      const running = () =>
        screen.getByTestId("board-step-retrieve_literature");
      expect(running()).toHaveTextContent("1m 35s");
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });
      expect(running()).toHaveTextContent("1m 40s");
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders the sequential-within / concurrent-across caption under the board", () => {
    render(<ActiveIterationPanel initial={fixture()} />);
    expect(screen.getByTestId("steps-caption")).toHaveTextContent(
      "steps run sequentially within an iteration — concurrency happens across runs (see the Now board)",
    );
  });

  it("an unknown STATUS renders raw in the quiet lane (forward-compat, never dropped)", () => {
    render(
      <ActiveIterationPanel
        initial={fixture({
          steps: [{ name: "hypothesize", status: "paused_v2" }],
        })}
      />,
    );
    const chip = screen.getByTestId("board-step-hypothesize");
    expect(chip).toBeInTheDocument();
    expect(chip.getAttribute("data-status")).toBe("paused_v2");
    expect(chip.className).toMatch(/zinc/);
  });

  it("junk steps entries degrade per-entry; junk steps VALUE falls back to the legacy strip", () => {
    // Junk entries: only the one usable {name} survives; no crash.
    render(
      <ActiveIterationPanel
        initial={fixture({
          steps: [
            null,
            42,
            { status: "running" }, // no name → dropped
            { name: "ok_step", status: "running" },
          ] as unknown as IterationStep[],
        })}
      />,
    );
    const chips = screen
      .getByTestId("steps-board")
      .querySelectorAll('[data-testid^="board-step-"]');
    expect(chips).toHaveLength(1);
    expect(screen.getByTestId("board-step-ok_step")).toBeInTheDocument();
    cleanup();

    // A non-array steps value (producer bug) → legacy fallback, no throw.
    render(
      <ActiveIterationPanel
        initial={fixture({
          steps: "garbage" as unknown as IterationStep[],
          current_step: "query_chroma",
        })}
      />,
    );
    expect(screen.queryByTestId("steps-board")).toBeNull();
    expect(screen.getByTestId("step-query_chroma")).toBeInTheDocument();
  });
});

describe("step strip — legacy fallback (steps absent)", () => {
  it("renders the unchanged static strip with the active step highlighted, and NO caption", () => {
    render(
      <ActiveIterationPanel
        initial={fixture({ steps: undefined, current_step: "query_chroma" })}
      />,
    );
    expect(screen.queryByTestId("steps-board")).toBeNull();
    expect(screen.queryByTestId("steps-caption")).toBeNull();
    const active = screen.getByTestId("step-query_chroma");
    expect(active.className).toMatch(/emerald/);
    const inactive = screen.getByTestId("step-summarize_paper");
    expect(inactive.className).not.toMatch(/emerald/);
  });

  it("an EMPTY steps[] array also falls back to the legacy strip (no empty board)", () => {
    render(
      <ActiveIterationPanel
        initial={fixture({ steps: [], current_step: "starting" })}
      />,
    );
    expect(screen.queryByTestId("steps-board")).toBeNull();
    expect(screen.getByTestId("step-starting")).toBeInTheDocument();
  });
});
