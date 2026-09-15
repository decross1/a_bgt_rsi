// Validate LowEvidenceBadge over checked-in, content-free JSONL retrieval
// shapes. Linked worktrees lack the private production loop-memory ledger;
// these fixtures keep the same fail-closed behavior portable.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import LowEvidenceBadge, {
  isLowEvidence,
} from "../src/components/LowEvidenceBadge";
import type { IterationRecord } from "../src/types/schemas";

function loadFixtureIterations(): IterationRecord[] {
  const path = resolve(dirname(fileURLToPath(import.meta.url)), "fixtures/low_evidence_rows.jsonl");
  const raw = readFileSync(path, "utf8");
  return raw
    .split("\n")
    .filter((l) => l.trim().length > 0)
    .map((l) => JSON.parse(l) as IterationRecord);
}

const ROWS = loadFixtureIterations();

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("low-evidence surface — checked-in JSONL contract shapes", () => {
  it("loads the five distinct retrieval shapes", () => {
    expect(ROWS.map((row) => row.iteration_id)).toEqual([
      "fixture-absent-retrieval", "fixture-populated-neighbors",
      "fixture-confident-relevance", "fixture-thin-relevance", "fixture-empty-neighbors",
    ]);
  });

  it("isLowEvidence fires exactly for the two explicit thin signals", () => {
    // These expectations are fixed by the fixture contract, independently of
    // the guard's implementation.
    expect(ROWS.map(isLowEvidence)).toEqual([false, false, false, true, true]);
    expect(ROWS.filter(isLowEvidence).map((row) => row.iteration_id)).toEqual([
      "fixture-thin-relevance", "fixture-empty-neighbors",
    ]);
  });

  it("never throws on absent retrieval, populated neighbors, or relevance rows", () => {
    for (const r of ROWS) {
      expect(() => isLowEvidence(r)).not.toThrow();
    }
    const confident = ROWS.find((row) => row.iteration_id === "fixture-confident-relevance")!;
    const { container } = render(<LowEvidenceBadge record={confident} />);
    expect(screen.queryByTestId("low-evidence-badge")).toBeNull();
    expect(container).toBeEmptyDOMElement();
  });

  it("an off-domain / low_confidence:true novel verdict raises the badge", () => {
    // Pin the false-novel shape separately from the JSONL rows: an off-domain
    // retrieval flag must still surface when novelty and critique look positive.
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
    // The per-row guard lights amber without claiming a scientific verdict.
    expect(isLowEvidence(offDomainRow)).toBe(true);
    render(<LowEvidenceBadge record={offDomainRow} />);
    const badge = screen.getByTestId("low-evidence-badge");
    expect(badge).toHaveTextContent(/low-evidence/i);
    expect(badge.className).toContain("amber"); // suspect, not broken
  });

  it("the empty-neighbors trigger also fires (structural backstop for 0-retrieval)", () => {
    // The second trigger: a present-but-empty neighbor list (nothing retrieved).
    // An absent neighbors field stays no-signal; an explicitly-empty list flags.
    const emptyNeighbors: IterationRecord = {
      iteration_id: "iter-empty-nb-synth",
      started_at: "2026-06-09T00:00:00Z",
      ended_at: "2026-06-09T00:01:00Z",
      journal_entry_path: "journal/iterations/synth2.md",
      retrieval: { k: 8, neighbors: [] },
      novelty: { class: "novel" },
    };
    expect(isLowEvidence(emptyNeighbors)).toBe(true);
    // Contrast an absent neighbors field, which must not flag.
    expect(
      isLowEvidence({ ...emptyNeighbors, retrieval: { k: 8 } }),
    ).toBe(false);
  });
});
