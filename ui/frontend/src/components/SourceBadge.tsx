// SourceBadge — provenance chip for a `seed.source` / `topic_source` string,
// the autonomy-observability "where did this come from" signal. Used on the
// coordinator-cycle card (topic_source) and the resolved-iterations rows
// (seed.source) so EVERY row badges its origin consistently, not just the
// coordinator-driven ones. See ui_plan.md §AUTONOMY OBSERVABILITY ("provenance
// everywhere"). Mirrors the AgentBadge idiom (rounded, text-[10px], uppercase,
// tracking-wide) so the two provenance signals read as a family.
//
// The HEADLINE β signal is "nemoclaw_agent" — Nara forming AND running a thesis
// itself inside nara-sandbox, an in-sandbox autonomous origin. It reads VIOLET,
// distinct from a host-coordinator cycle (sky), so the moment the loop drives
// itself is visible at a glance.
//
// Tone by source:
//   nemoclaw_agent      -> violet  (THE headline: in-sandbox NemoClaw agent)
//   coordinator         -> sky     (the host coordinator loop)
//   arxiv_pick          -> indigo  (an arxiv-picked topic)
//   loop_memory_probe   -> zinc    (a memory-probe re-seed)
//   human_cli/human_ui/human -> quiet zinc (a person seeded it)
//   unknown / absent    -> quiet zinc, rendering the raw string (never crash)
// Renders null when `source` is null/empty (no badge for an unattributed row).

const TONE: Record<string, string> = {
  nemoclaw_agent: "bg-violet-950 text-violet-300",
  coordinator: "bg-sky-950 text-sky-300",
  arxiv_pick: "bg-indigo-950 text-indigo-300",
  loop_memory_probe: "bg-zinc-800 text-zinc-400",
  human_cli: "bg-zinc-800 text-zinc-400",
  human_ui: "bg-zinc-800 text-zinc-400",
  human: "bg-zinc-800 text-zinc-400",
};

const QUIET = "bg-zinc-800 text-zinc-400";

// A short humanized label per source. Unknown sources render their raw string
// (lowercased by CSS), so a new EMIT provenance value still shows rather than
// vanishing.
const LABEL: Record<string, string> = {
  nemoclaw_agent: "nemoclaw",
  loop_memory_probe: "memory-probe",
  human_cli: "human",
  human_ui: "human",
};

// `source` is producer-owned JSONL (seed.source / topic_source), parsed
// unchecked — the `string | null` type is a compile-time fiction. A malformed
// or legacy row can hand us a number, boolean, object, or array; calling
// `.trim()` on those throws and crashes the whole cycle/iterations list (one
// bad row would take the page down). Normalize to a trimmed string defensively:
// a string trims as before; a finite number / boolean stringifies (a numeric
// enum still shows raw, consistent with "unknown source renders raw"); anything
// without a usable scalar form (object, array, NaN) yields "" → treated as an
// unattributed row (no badge), never `[object Object]` and never a throw.
function asText(source: unknown): string {
  if (typeof source === "string") return source.trim();
  if (typeof source === "number") return Number.isFinite(source) ? String(source) : "";
  if (typeof source === "boolean") return String(source);
  return "";
}

// Exported so consumers (or tests) can reuse the tone mapping without
// re-rendering the badge — keeps the source→tone decision in one place. The
// signature stays `string | null | undefined` (callers pass that type); the
// body guards a non-string runtime value via `asText`.
export function sourceTone(source: string | null | undefined): string {
  const value = asText(source);
  if (!value) return QUIET;
  // `value` is producer-owned text, so it can collide with an inherited
  // Object.prototype member name ("constructor", "toString", "__proto__",
  // "valueOf", "hasOwnProperty", ...). A bare `TONE[value]` then resolves to a
  // function via the prototype chain instead of undefined, so `?? QUIET` does
  // NOT fall through and that function interpolates into className as
  // "function toString() { [native code] }". Look up own keys only; any
  // prototype collision falls back to QUIET. (Mirrors AgentBadge's guard.)
  return Object.prototype.hasOwnProperty.call(TONE, value) ? TONE[value] : QUIET;
}

function sourceLabel(source: string): string {
  // Same prototype-collision hazard as the tone map: `LABEL["toString"]` is
  // `Function.prototype.toString`, a function — `LABEL[source] ?? source` would
  // return that function, which React then refuses to render as a child
  // ("Functions are not valid as a React child", a console.error) and the
  // provenance label silently vanishes. Own-key lookup only; otherwise show the
  // raw source string, consistent with "unknown source renders raw".
  return Object.prototype.hasOwnProperty.call(LABEL, source) ? LABEL[source] : source;
}

export default function SourceBadge({
  source,
  className,
}: {
  source?: string | null;
  className?: string;
}) {
  // `asText` guards a non-string runtime value (number/object/array from a
  // malformed JSONL row) that `source?.trim()` alone would throw on.
  const value = asText(source);
  if (!value) return null;

  const tone = sourceTone(value);
  const label = sourceLabel(value);

  return (
    <span
      data-testid="source-badge"
      title={value}
      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${tone}${
        className ? ` ${className}` : ""
      }`}
    >
      {label}
    </span>
  );
}
