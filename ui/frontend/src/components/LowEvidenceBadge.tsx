// The low-evidence flag — the headline guard against the 2026-06-09 false
// `novel/survives` bug, where a verdict rested on thin / off-domain retrieval
// (an off-domain code-quality topic retrieved against game-theory books). Per
// ui_autonomy_observability_plan.md design principle #4 ("show the epistemic
// basis"): a verdict is only as trustworthy as the evidence under it, so flag
// the ones standing on thin air. Amber, not red — a low-evidence verdict is
// suspect, not broken; it asks a human to eyeball, it doesn't assert a failure.
//
// Pairs with the coordinator/recent-iterations rows. Renders nothing when the
// evidence is fine, so a clean row stays clean.
import type { IterationRecord } from "../types/schemas";

// SCORE_FLOOR: a retrieval-relevance score under this is "thin" regardless of
// the flag. ~0.3 per the spec; the EMIT side bands "low"/"thin" around here, so
// this catches a low score even on a row whose flag didn't get set.
const SCORE_FLOOR = 0.3;

// TRUE when the verdict rests on thin evidence. Conservative: with NO retrieval
// signal at all we return false (an absent `retrieval` block is a pre-coordinator
// row, not a low-evidence one — don't cry wolf). Three independent triggers:
//   1. relevance.flag is "low" or "thin" (the EMIT-side verdict);
//   2. relevance.score is present AND below SCORE_FLOOR (a thin score even
//      without a flag); note `score === 0` is a real signal, so test presence
//      explicitly rather than truthiness;
//   3. retrieval.neighbors is present AND empty (0 neighbors → nothing was
//      retrieved). An ABSENT neighbors field is no-signal, not zero.
export function isLowEvidence(record: IterationRecord): boolean {
  const retrieval = record.retrieval;
  if (!retrieval) return false;

  const relevance = retrieval.relevance;
  if (relevance) {
    if (relevance.flag === "low" || relevance.flag === "thin") return true;
    if (typeof relevance.score === "number" && relevance.score < SCORE_FLOOR) {
      return true;
    }
  }

  // Only an explicitly-present, empty neighbor list counts as a signal.
  if (Array.isArray(retrieval.neighbors) && retrieval.neighbors.length === 0) {
    return true;
  }

  return false;
}

// Build the tooltip from whatever signal actually fired, so a human hovering
// learns *why* the verdict is suspect (thin score vs off-domain flag vs 0
// neighbors), not just that it is.
function reason(record: IterationRecord): string {
  const relevance = record.retrieval?.relevance;
  const parts: string[] = [];
  if (relevance?.flag === "low" || relevance?.flag === "thin") {
    parts.push(`retrieval relevance flagged "${relevance.flag}"`);
  }
  if (typeof relevance?.score === "number" && relevance.score < SCORE_FLOOR) {
    parts.push(`relevance score ${relevance.score.toFixed(2)} below ${SCORE_FLOOR}`);
  }
  if (
    Array.isArray(record.retrieval?.neighbors) &&
    record.retrieval!.neighbors!.length === 0
  ) {
    parts.push("0 retrieved neighbors");
  }
  const why = parts.length ? parts.join("; ") : "thin / off-domain retrieval";
  return `Low-evidence verdict: ${why}. The verdict rests on thin or off-domain retrieval — eyeball before trusting.`;
}

export default function LowEvidenceBadge({
  record,
}: {
  record: IterationRecord;
}) {
  if (!isLowEvidence(record)) return null;
  return (
    <span
      data-testid="low-evidence-badge"
      title={reason(record)}
      className="rounded bg-amber-950 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-amber-400"
    >
      low-evidence
    </span>
  );
}
