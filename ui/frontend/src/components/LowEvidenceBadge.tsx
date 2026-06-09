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

// TRUE when the verdict rests on thin evidence. Conservative: with NO retrieval
// signal at all we return false (an absent `retrieval` block is a pre-coordinator
// row, not a low-evidence one — don't cry wolf). Two independent triggers:
//   1. retrieval.relevance.low_confidence === true — the AUTHORITATIVE signal.
//      workers/retrieval_relevance.py owns the calibrated thin/off-domain
//      thresholds and sets this boolean; we trust it rather than re-derive a
//      score cutoff (the blended `relevance` score's distribution is the
//      worker's to interpret).
//   2. retrieval.neighbors is present AND empty (0 neighbors → nothing was
//      retrieved). An ABSENT neighbors field is no-signal, not zero — structural
//      backstop for the empty-retrieval case.
export function isLowEvidence(record: IterationRecord): boolean {
  // `record` is one producer-owned JSONL row, forwarded by the backend as-is: a
  // bare `null` line (or any non-object) round-trips to a null/primitive array
  // element (backend/loop_v0.py _read_jsonl does not drop None). The declared
  // `IterationRecord` type can't enforce object-ness at runtime, and a bare
  // `record.retrieval` then throws "Cannot read properties of null" — which
  // would crash whatever maps the badge over rows. RedFlagsTrendStrip already
  // pre-filters non-objects before calling this; guard at the source too so the
  // exported contract is robust no matter which caller forgets. A non-object
  // row carries no retrieval signal → conservative false (same "treat a wrong
  // type as absent" stance as AgentBadge / SourceBadge).
  if (record == null || typeof record !== "object") return false;
  const retrieval = record.retrieval;
  if (!retrieval) return false;

  if (retrieval.relevance?.low_confidence === true) return true;

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
  if (relevance?.low_confidence === true) {
    // `reason` is producer-owned and may legacy/malformed-emit as a non-string
    // (object/array/number). A template literal would stringify an object to
    // "[object Object]" and dump that garbage into the human-facing tooltip —
    // the very text meant to explain *why* the verdict is suspect. Only fold in
    // a non-empty STRING reason; otherwise fall back to the bare phrase (same
    // "use it only if it's the expected type" guard as ResolvedIterationsList's
    // seedTopic / conditioningBullets).
    const why =
      typeof relevance.reason === "string" && relevance.reason.trim()
        ? relevance.reason
        : null;
    parts.push(
      why
        ? `retrieval flagged low-confidence — ${why}`
        : "retrieval flagged low-confidence",
    );
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
