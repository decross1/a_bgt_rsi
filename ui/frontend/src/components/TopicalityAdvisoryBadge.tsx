// The topicality ADVISORY hint — D-052's outcome C (DATA_SHAPES Changelog
// 2026-06-14). An independent adversarial topicality judge once GATED the loop
// (`NARA_TOPICALITY_SKEPTIC`); D-052 RETIRED it as a gate because it
// systematically OVER-FLAGS novel on-domain claims — three falsified-anchor
// failures in a row. It survives only as a NON-GATING, human-facing dissent:
// when `NARA_TOPICALITY_ADVISORY=1` (dark by default) AND the primary judge did
// not already condemn, the orchestrator rides its dissent on the additive
// `retrieval.relevance.topicality_advisory` field — ABSENT on every normal row.
//
// This badge is therefore DELIBERATELY QUIET (zinc, never amber): it is NOT a
// low-evidence flag and NOT a gate. It reads as "a second, known-trigger-happy
// opinion disagrees" — a hint to eyeball, never an assertion the verdict is
// wrong. It pairs beside (never inside) the LowEvidence alarm slot, and renders
// nothing unless the dissent is an explicit `"off"`.
import type { IterationRecord } from "../types/schemas";

// Normalize the producer-owned advisory value to a usable scalar, same stance
// as LowEvidenceBadge.asText / SourceBadge.asText: a string trims; anything
// else (object/array/number/NaN from a malformed partial write) → "" so a
// garbled row never surfaces "[object Object]". We compare case-insensitively
// because the enum is lowercase but a producer typo shouldn't crash the render.
function advisoryValue(record: IterationRecord): string {
  // A bare-null / non-object row round-trips from the append-only log as a
  // primitive (backend _read_jsonl forwards it as-is). Guard at the source so
  // the exported helper is robust no matter which caller forgets — mirrors
  // isLowEvidence's stance.
  if (record == null || typeof record !== "object") return "";
  const raw = record.retrieval?.relevance?.topicality_advisory;
  if (typeof raw !== "string") return "";
  return raw.trim().toLowerCase();
}

// TRUE only for the dissent worth surfacing: an explicit `"off"`. The field can
// also carry `"on"`/`"unsure"`/null, but those are not a dissent the human needs
// nudged about (DATA_SHAPES UI guidance: "surface an `off`"), so we stay quiet —
// don't cry wolf, same conservatism as isLowEvidence. The raw value still shows
// verbatim in the detail modal for anyone who wants it.
export function hasTopicalityDissent(record: IterationRecord): boolean {
  return advisoryValue(record) === "off";
}

export default function TopicalityAdvisoryBadge({
  record,
}: {
  record: IterationRecord;
}) {
  if (!hasTopicalityDissent(record)) return null;
  return (
    <span
      data-testid="topicality-advisory-badge"
      title={
        "Advisory only — NOT a gate. An independent topicality judge (retired as " +
        "a gate per D-052 for over-flagging novel on-domain claims) dissents that " +
        "this retrieval is off-topic. The primary judge did not condemn; treat " +
        "this as a weak prompt to eyeball, not a low-evidence flag."
      }
      className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400"
    >
      topicality dissent
    </span>
  );
}
