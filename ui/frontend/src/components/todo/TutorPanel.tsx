// TutorPanel — an explain/tutor affordance for a finding, STRICTLY FENCED from
// the verdict path (2026-06-14 session note PART 2 "Tutor FENCED from the
// verdict"): no single agreeable model both teaches and validates the same
// finding. The fence is structural, not just documented:
//
//   - This component takes NO verdict props (no verdict, no setter, no
//     onResolved, no calibration). It CANNOT influence or auto-fill a verdict,
//     because it is never handed the means to.
//   - It renders a visible "tutor — does not affect your verdict" note so the
//     human sees the separation.
//
// It is a STUB today: the tutor content is placeholder until the explain seam
// lands. It NEVER fabricates a verdict or a confidence. Props are intentionally
// minimal — a finding id + a short title to explain — and nothing verdict-shaped
// is accepted.
interface Props {
  findingId: string;
  /** A short human-readable title/claim to anchor the explanation. */
  title?: string;
}

// `findingId` / `title` are forwarded raw from producer-owned state
// (selected.id / selected.title in Todo.tsx, sourced from loop_memory.jsonl).
// The `string` prop type is a compile-time fiction: a legacy / partial / buggy
// row can hand this a null, number, object, or array. Normalize to a usable
// scalar the same way SourceBadge.asText / LowEvidenceBadge.asText do — a string
// trims, a finite number / boolean stringifies, anything else (object / array /
// NaN / Infinity / null / undefined) yields "" so the field is DROPPED, never
// "[object Object]" / "NaN" in the DOM and never a raw object reaching React as
// a child (which throws "Objects are not valid as a React child" and blanks the
// whole /todo cockpit on one bad row). The verdict fence is unchanged: this
// guard only touches display text; no verdict-shaped prop is accepted.
function asText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  if (typeof value === "boolean") return String(value);
  return "";
}

export default function TutorPanel({ findingId, title }: Props) {
  const titleText = asText(title);
  const idText = asText(findingId);
  return (
    <div
      data-testid="tutor-panel"
      className="rounded border border-indigo-900/60 bg-indigo-950/20 px-2 py-1.5"
    >
      <div className="text-[10px] uppercase tracking-wide text-indigo-400">
        tutor / explain
      </div>
      {/* The visible fence: the human sees that this surface is separated from
          the verdict path. */}
      <div
        data-testid="tutor-fence-note"
        className="mt-0.5 text-[10px] text-zinc-500"
      >
        tutor — does not affect your verdict. No model both teaches and
        validates the same finding (D-044 independence).
      </div>
      <div
        data-testid="tutor-stub-banner"
        className="mt-0.5 text-[10px] text-zinc-500"
      >
        stub — lights up when the explain/tutor primary seam lands.
      </div>
      <div className="mt-1 text-[11px] text-zinc-400">
        {titleText.length > 0 ? (
          <>
            Asked to explain: <span className="text-zinc-300">{titleText}</span>
          </>
        ) : (
          <>Ask the tutor to explain this finding.</>
        )}
        {idText.length > 0 ? (
          <span className="text-zinc-600"> ({idText})</span>
        ) : null}
      </div>
    </div>
  );
}
