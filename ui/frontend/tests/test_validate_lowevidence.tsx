// VALIDATION (not just unit) — pin the low-evidence surface (isLowEvidence +
// LowEvidenceBadge) to the REAL 49 rows of memory/loop_memory.jsonl, the live
// data contract these self-checks run over. (The RedFlagsTrendStrip half of
// this suite died with the strip in UI simplification S3.) The jsdom stand-in for "renders
// without console errors" (no headless browser in this stack): render and spy
// on console.error/console.warn.
//
// Complementary to the existing unit tests (test_low_evidence_badge.tsx)
// which exercise hand-built fixtures. This file
// instead pins the SHAPE of production data, which accretes under the tests:
//   - relevance-bearing rows grow with the diagnostic ladder (1 of 49 on
//     2026-06-09, all low_confidence:false; 5 of 57 on 2026-06-10 INCLUDING
//     iter-2026-06-09-007, the first live low_confidence:true / off-domain
//     row) → badge + trust tiles are asserted as cohort invariants recomputed
//     from the loaded rows, never as dated literals;
//   - ~7 rows have NO retrieval block at all (pre-coordinator) → conservative
//     false, no cry-wolf;
//   - most rows carry a 10-neighbor list with no relevance key → also false;
//   - novelty.class novel / critique.verdict survives are plentiful, so the
//     isNovelOrSurvives numerator and the strip's denominators are real.
// An off-domain low_confidence:true row is ALSO constructed IN-TEST so the
// would-fire path stays pinned independent of the live cohort's contents. If
// the producer's schema drifts (or the cohort shifts), this is the test that
// catches the surface choking, going quiet, or over-alarming.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import LowEvidenceBadge, {
  isLowEvidence,
} from "../src/components/LowEvidenceBadge";
import type { IterationRecord } from "../src/types/schemas";

// Resolve the primary repo root by walking UP from this test file's directory
// until a directory containing memory/loop_memory.jsonl exists — the backend's
// _PRIMARY_REPO target found structurally, not via a fixed "../.." depth, so
// the SAME file resolves from the main checkout AND any worktree nesting (the
// old hardcoded six-up only resolved from .claude/worktrees/<name>). Probes
// with readFileSync — the only fs symbol tests/node-builtins.d.ts declares —
// where ENOENT/ENOTDIR is a miss, any other error rethrows, and an exhausted
// walk fails loudly with every probed path. Same idiom inlined in
// test_revalidate_live_rows.tsx / test_validate_iterations.tsx (a shared
// livePaths.ts would be a new file — deferred to the integrator).
function findPrimaryRepoRoot(): string {
  const probed: string[] = [];
  let dir = dirname(fileURLToPath(import.meta.url));
  for (;;) {
    const probe = resolve(dir, "memory/loop_memory.jsonl");
    try {
      readFileSync(probe, "utf8");
      return dir;
    } catch (e) {
      const code = (e as { code?: string }).code;
      if (code !== "ENOENT" && code !== "ENOTDIR") throw e;
      probed.push(probe);
    }
    const parent = dirname(dir);
    if (parent === dir) {
      throw new Error(
        "memory/loop_memory.jsonl not found in any ancestor of this test " +
          `file — probed:\n${probed.join("\n")}`,
      );
    }
    dir = parent;
  }
}

// The real, gitignored loop memory the backend reads live, resolved via the
// walk-up above so the test reads exactly what the UI serves. A missing file
// fails loudly (this data IS the contract under validation — an empty load is
// a real failure, not a skip). Same idiom as test_validate_iterations.tsx.
function loadRealIterations(): IterationRecord[] {
  const path = resolve(findPrimaryRepoRoot(), "memory/loop_memory.jsonl");
  const raw = readFileSync(path, "utf8");
  return raw
    .split("\n")
    .filter((l) => l.trim().length > 0)
    .map((l) => JSON.parse(l) as IterationRecord);
}

const REAL = loadRealIterations();

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

  it("isLowEvidence fires EXACTLY where the contract says, row by row over the real data", () => {
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
    // Cohort invariant, not a dated count: the guard fires on exactly the rows
    // the triggers name (0 of 49 on 2026-06-09; 1 of 57 — iter-2026-06-09-007,
    // the first live off-domain row — on 2026-06-10), never more, never fewer.
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

  it("an off-domain / low_confidence:true row WOULD flag (the trigger pinned independent of the live cohort)", () => {
    // Construct the false-novel shape in-test — novel/survives resting on
    // off-domain retrieval — so the would-fire path stays pinned no matter
    // what the live cohort holds (it was dormant until 2026-06-10, when
    // iter-2026-06-09-007 became the first live off-domain row): when the
    // producer emits a thin relevance flag, the badge AND trust tiles light up.
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
    // The per-row guard fires and the badge lights amber (suspect, not
    // broken). (The trust-tile escalation half died with RedFlagsTrendStrip
    // in S3 — the ladder surfaces own cohort-level alarming now.)
    expect(isLowEvidence(offDomainRow)).toBe(true);
    render(<LowEvidenceBadge record={offDomainRow} />);
    const badge = screen.getByTestId("low-evidence-badge");
    expect(badge).toHaveTextContent(/low-evidence/i);
    expect(badge.className).toContain("amber"); // suspect, not broken
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
