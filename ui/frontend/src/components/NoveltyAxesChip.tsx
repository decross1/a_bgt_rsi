// NoveltyAxesChip — compact chip for the decomposed novelty judgment
// `novelty.novelty_axes` ({phenomenon, substrate, predicted_direction}; EMIT:
// workers/novelty_classify.py, 2026-06-09 evening additions — additive on the
// frozen 0fdb671 join contract, explicit-null on sentinel/legacy outputs).
// Renders the three axes as one scannable token, e.g.
// "axes: known/unstudied_llm/deviates".
//
// The bucket worth EMPHASIS is phenomenon="known" && predicted_direction in
// {"matches","silent"} — the rubric's transfer/replication bucket
// (docs/novelty_two_axis_rubric.md; ADJUDICATED 2026-06-10). The decision rule
// keys the class on `predicted_direction`, NOT substrate: known+deviates
// derives class `novel` (a deviation claim, not mere transfer), while
// known+matches|silent is transfer/replication "even on an unstudied_llm
// substrate" — substrate is explicitly not-class-determining. That bucket
// reads cyan, distinct from the quiet zinc of every other combination, so a
// human scanning can tell a replication-transfer thesis from a new-phenomenon
// (or known-but-deviates) one at a glance. Mirrors the Badge/SourceBadge chip
// idiom (rounded, text-[10px], uppercase, tracking-wide).
//
// `axes` is producer-owned JSONL parsed unchecked — the declared prop type is
// a compile-time fiction. A legacy/buggy row can hand a string, number, array,
// or null where the object was meant, and an axis VALUE can be an object or
// NaN. A non-object axes (or one with no usable axis at all) renders null —
// no chip for no signal, never a throw and never "[object Object]".

const QUIET = "bg-zinc-800 text-zinc-400";
const TRANSFER = "bg-cyan-950 text-cyan-300";

// Same scalar coercion as SourceBadge's asText: a string trims; a finite
// number / boolean stringifies (forward-compat — a numeric enum still shows
// raw); anything without a usable scalar form (object, array, NaN, null,
// undefined) yields "" → that axis is treated as absent. There is no
// value-keyed map lookup here (the own-key hazard SourceBadge/toneFor guard),
// only fixed-name reads of `phenomenon`/`substrate`/`predicted_direction` —
// names that do not collide with any Object.prototype member.
function asText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  if (typeof value === "boolean") return String(value);
  return "";
}

export default function NoveltyAxesChip({
  axes,
}: {
  axes?: {
    phenomenon?: string;
    substrate?: string;
    predicted_direction?: string;
  } | null;
}) {
  // Null/absent (legacy or sentinel rows) and any non-object garbage (string,
  // number, boolean, array — Array.isArray catches typeof "object") render
  // nothing rather than throwing on the property reads below.
  if (axes == null || typeof axes !== "object" || Array.isArray(axes)) {
    return null;
  }

  const phenomenon = asText(axes.phenomenon);
  const substrate = asText(axes.substrate);
  const direction = asText(axes.predicted_direction);
  // No usable axis at all ({} or all-garbage values) → no chip, not "axes: ?/?/?".
  if (!phenomenon && !substrate && !direction) return null;

  // The pre-registered rubric's transfer/replication bucket
  // (docs/novelty_two_axis_rubric.md; pinned by the 2026-06-10 adjudication):
  // known phenomenon + matches/silent predicted direction — transfer, not
  // discovery, REGARDLESS of substrate (the rubric's decision rule keys on
  // direction; known+deviates derives class `novel` and must stay quiet).
  // Exact-match on the announced enum values; any other (or forward-compat)
  // value stays quiet. The cyan emphasis and the quiet "transfer" text label
  // both name this one bucket.
  const transfer =
    phenomenon === "known" &&
    (direction === "matches" || direction === "silent");
  const tone = transfer ? TRANSFER : QUIET;

  // Compact "axes: a/b/c"; a missing/garbled axis shows as "?" so a partial
  // row still renders its known axes without faking the absent one.
  const label = `axes: ${phenomenon || "?"}/${substrate || "?"}/${direction || "?"}`;
  const title = transfer
    ? `Transfer/replication bucket: a known phenomenon whose predicted direction matches or is silent — rediscovery/transfer regardless of substrate (${label}).`
    : `Decomposed novelty judgment — phenomenon/substrate/predicted_direction (${label}).`;

  return (
    <>
      <span
        data-testid="novelty-axes-chip"
        title={title}
        className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${tone}`}
      >
        {label}
      </span>
      {transfer && (
        <span
          data-testid="novelty-transfer-label"
          title="Known phenomenon, predicted direction matches/silent — the rubric's transfer/replication bucket (rediscovery), not a discovery claim."
          className="text-[10px] lowercase tracking-wide text-zinc-500"
        >
          transfer
        </span>
      )}
    </>
  );
}
