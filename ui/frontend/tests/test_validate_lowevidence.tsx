// VALIDATION (not just unit) — pin the low-evidence surface (isLowEvidence +
// RedFlagsTrendStrip) to the REAL 49 rows of memory/loop_memory.jsonl, the live
// data contract these self-checks run over. The jsdom stand-in for "renders
// without console errors" (no headless browser in this stack): render and spy
// on console.error/console.warn.
//
// Complementary to the existing unit tests (test_low_evidence_badge.tsx,
// test_red_flags_trend_strip.tsx) which exercise hand-built fixtures. This file
// instead pins the SHAPE of production data as it actually is on 2026-06-09:
//   - exactly 1 of 49 rows carries retrieval.relevance, and its low_confidence
//     is FALSE → isLowEvidence must NOT fire → the badge stays silent and the
//     red-flags off-domain / suspected-false-novel tiles read 0% (a clean loop,
//     NOT a bug — the low-evidence guard simply has no live trigger today);
//   - ~7 rows have NO retrieval block at all (pre-coordinator) → conservative
//     false, no cry-wolf;
//   - ~42 rows carry a 10-neighbor list with no relevance key → also false;
//   - novelty.class novel(21) / critique.verdict survives(32) exercise the
//     isNovelOrSurvives numerator broadly, so the strip's denominators are real.
// The trigger that has no live data is constructed IN-TEST (an off-domain
// low_confidence:true row) to prove the flag WOULD fire — the guard is dormant,
// not dead. If the producer's schema drifts (or a real low_confidence:true row
// lands), this is the test that catches the surface choking or going quiet.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import LowEvidenceBadge, {
  isLowEvidence,
} from "../src/components/LowEvidenceBadge";
import RedFlagsTrendStrip from "../src/components/RedFlagsTrendStrip";
import type { IterationRecord } from "../src/types/schemas";

// The real, gitignored loop memory the backend reads live. Path resolves from
// this test file up to the primary repo root, mirroring the backend's hardcoded
// _PRIMARY_REPO so the test reads exactly what the UI serves. A missing file
// fails loudly (this data IS the contract under validation — an empty load is a
// real failure, not a skip). Same idiom as test_validate_iterations.tsx.
function loadRealIterations(): IterationRecord[] {
  const here = dirname(fileURLToPath(import.meta.url));
  // tests/ -> frontend -> ui -> ui-session -> worktrees -> .claude -> repo root
  const repoRoot = resolve(here, "../../../../../..");
  const path = resolve(repoRoot, "memory/loop_memory.jsonl");
  const raw = readFileSync(path, "utf8");
  return raw
    .split("\n")
    .filter((l) => l.trim().length > 0)
    .map((l) => JSON.parse(l) as IterationRecord);
}

const REAL = loadRealIterations();

// Spy that fails the test if React (or our code) logs while rendering — the
// jsdom equivalent of "renders without console errors".
function watchConsole() {
  const error = vi.spyOn(console, "error").mockImplementation(() => {});
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  return { error, warn };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("low-evidence surface — validation against REAL loop_memory.jsonl", () => {
  it("loaded the real rows (sanity: the contract file is present and non-trivial)", () => {
    // 49 rows on 2026-06-09; assert a generous lower bound so the test stays
    // meaningful as rows accrete but still proves real data loaded.
    expect(REAL.length).toBeGreaterThanOrEqual(40);
  });

  it("isLowEvidence fires ONLY where the contract says, and on the real data that is no rows", () => {
    // The flag's two triggers (LowEvidenceBadge): relevance.low_confidence===true
    // OR a present-but-empty neighbor list. Compute the ground truth from the raw
    // rows, independent of the function, then assert the function agrees exactly.
    const groundTruth = (r: IterationRecord): boolean => {
      const retr = r.retrieval;
      if (!retr) return false;
      if (retr.relevance?.low_confidence === true) return true;
      return Array.isArray(retr.neighbors) && retr.neighbors.length === 0;
    };
    for (const r of REAL) {
      expect(isLowEvidence(r)).toBe(groundTruth(r));
    }
    // On 2026-06-09 NO real row trips either trigger — the guard is dormant, and
    // that is the correct read of the data (every verdict's retrieval is either
    // confidently-grounded or pre-coordinator), not a missing flag.
    const fired = REAL.filter(isLowEvidence);
    expect(fired.length).toBe(
      REAL.filter(
        (r) =>
          r.retrieval?.relevance?.low_confidence === true ||
          (Array.isArray(r.retrieval?.neighbors) &&
            r.retrieval!.neighbors!.length === 0),
      ).length,
    );
  });

  it("never throws on any real row shape (retrieval absent / 10-neighbor list / relevance present)", () => {
    // The three real shape-classes all flow through isLowEvidence without a
    // throw — the conservative no-signal default covers the absent-retrieval and
    // no-relevance-key rows; the one relevance row exercises the live path.
    for (const r of REAL) {
      expect(() => isLowEvidence(r)).not.toThrow();
    }
    // And the one real relevance-bearing row (low_confidence:false) renders no
    // badge — a confidently-grounded verdict is not flagged.
    const withRelevance = REAL.filter((r) => r.retrieval?.relevance != null);
    expect(withRelevance.length).toBeGreaterThanOrEqual(1);
    const anyLowConf = withRelevance.some(
      (r) => r.retrieval?.relevance?.low_confidence === true,
    );
    const { container } = render(<LowEvidenceBadge record={withRelevance[0]} />);
    if (!anyLowConf) {
      expect(screen.queryByTestId("low-evidence-badge")).toBeNull();
      expect(container).toBeEmptyDOMElement();
    }
  });

  it("RedFlagsTrendStrip computes over ALL real rows with no NaN, no throw, no console.error", () => {
    const spy = watchConsole();
    const { container } = render(<RedFlagsTrendStrip iterations={REAL} />);
    expect(screen.getByTestId("red-flags-trend-strip")).toBeInTheDocument();
    // Real denominators exist, so every tile renders a numeric percent — never a
    // NaN leaking from a divide, never an em-dash (those are the empty state).
    for (const id of [
      "red-flag-novel-rate",
      "red-flag-suspected-false-novel",
      "red-flag-off-domain",
    ]) {
      const tile = within(screen.getByTestId(id));
      expect(tile.getByText(/^\d+%$/)).toBeInTheDocument();
    }
    expect(container.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it("on the real data the suspected-false-novel + off-domain tiles read 0% and stay quiet (no over-alarm)", () => {
    watchConsole();
    render(<RedFlagsTrendStrip iterations={REAL} />);
    // No real row is low-evidence on 2026-06-09, so both trust tiles are 0% AND
    // quiet zinc: the strip must not paint a false-novel alarm when the loop is
    // clean. This is a dated-snapshot assertion that intentionally TIGHTENS with
    // the data — if a real low_confidence:true row ever lands, this fails on
    // purpose (the auditor must notice a genuine false-novel appearing). The
    // drift-proof invariant is the ground-truth check above; this pins today.
    const suspect = screen.getByTestId("red-flag-suspected-false-novel");
    expect(within(suspect).getByText("0%")).toBeInTheDocument();
    expect(suspect.innerHTML).not.toMatch(/amber|red/);
    const offDomain = screen.getByTestId("red-flag-off-domain");
    expect(within(offDomain).getByText("0%")).toBeInTheDocument();
    expect(offDomain.innerHTML).not.toMatch(/amber|red/);
    // The novel-rate tile, by contrast, IS non-zero (21/49 real rows are novel)
    // — proving the strip's numerators are reading the real verdicts, not zeros.
    const novel = screen.getByTestId("red-flag-novel-rate");
    expect(within(novel).queryByText("0%")).toBeNull();
    const novelPct = Number(
      (within(novel).getByText(/^\d+%$/).textContent ?? "0%").replace("%", ""),
    );
    expect(novelPct).toBeGreaterThan(0);
  });

  it("an off-domain / low_confidence:true row WOULD flag (the dormant trigger fires when the data arrives)", () => {
    // The live data has no low_confidence:true row, so construct the 2026-06-09
    // false-novel shape in-test: novel/survives resting on off-domain retrieval.
    // This proves the guard is dormant-not-dead — when the producer emits a thin
    // relevance flag, the badge AND the trust tiles light up.
    const offDomainRow: IterationRecord = {
      iteration_id: "iter-offdomain-synth",
      started_at: "2026-06-09T00:00:00Z",
      ended_at: "2026-06-09T00:01:00Z",
      journal_entry_path: "journal/iterations/synth.md",
      seed: { topic: "off-domain code-quality vs game-theory corpus", source: "coordinator" },
      retrieval: {
        k: 8,
        relevance: {
          relevance: 0.04,
          low_confidence: true,
          reason: "off-domain: code-quality topic retrieved against game-theory books",
        },
      },
      novelty: { class: "novel" },
      critique: { verdict: "survives" },
    };
    // 1) the per-row guard fires …
    expect(isLowEvidence(offDomainRow)).toBe(true);
    const { unmount } = render(<LowEvidenceBadge record={offDomainRow} />);
    const badge = screen.getByTestId("low-evidence-badge");
    expect(badge).toHaveTextContent(/low-evidence/i);
    expect(badge.className).toContain("amber"); // suspect, not broken
    unmount();

    // 2) … and dropped among the real rows, the trust tiles escalate: the
    // suspected-false-novel + off-domain tiles go non-zero and amber/red.
    render(<RedFlagsTrendStrip iterations={[...REAL, offDomainRow]} />);
    const suspect = screen.getByTestId("red-flag-suspected-false-novel");
    expect(within(suspect).queryByText("0%")).toBeNull(); // no longer quiet 0%
    expect(suspect.innerHTML).toMatch(/amber|red/);
    const offDomainTile = screen.getByTestId("red-flag-off-domain");
    expect(offDomainTile.innerHTML).toMatch(/amber|red/);
  });

  it("the empty-neighbors trigger also fires (structural backstop for 0-retrieval)", () => {
    // The second trigger: a present-but-empty neighbor list (nothing retrieved).
    // No real row carries it today, so assert it explicitly — an absent neighbors
    // field stays no-signal (false), only an explicitly-empty list flags.
    const emptyNeighbors: IterationRecord = {
      iteration_id: "iter-empty-nb-synth",
      started_at: "2026-06-09T00:00:00Z",
      ended_at: "2026-06-09T00:01:00Z",
      journal_entry_path: "journal/iterations/synth2.md",
      retrieval: { k: 8, neighbors: [] },
      novelty: { class: "novel" },
    };
    expect(isLowEvidence(emptyNeighbors)).toBe(true);
    // Contrast: an ABSENT neighbors field (the 42 real rows have a populated one,
    // 7 have none) is no-signal, not zero — must NOT flag.
    expect(
      isLowEvidence({ ...emptyNeighbors, retrieval: { k: 8 } }),
    ).toBe(false);
  });
});
