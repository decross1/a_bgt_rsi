// chips.tsx — the shared chip primitives for iteration surfaces (UI
// simplification S2). Moved VERBATIM out of IterationDetailModal.tsx (which
// dies this slice; its unique sections were absorbed by PipelineJourney):
// tone maps, Badge, RedteamChip, ExperimentChip, OverrideProvenance, and the
// scalar guards. Consumers: ResolvedIterationsList (row chips; dies S3),
// PipelineJourney (the dossier reader's spine), DossierIndex (resolved-
// iteration rows). Tones are unchanged — the forward-compat pins (quiet zinc
// fallback, the deliberate undecidable /40) still bite; test_chips.tsx carries
// the ported pins.
//
// Every field below is producer-owned JSONL parsed unchecked — the TS types
// are a compile-time fiction. All scalars render through badgeText/asScalar
// (never "[object Object]", never NaN); absent fields omit their line rather
// than faking a value.
import type { IterationRecord } from "../types/schemas";

export const NOVELTY_TONE: Record<string, string> = {
  novel: "bg-emerald-950 text-emerald-400",
  rediscovery: "bg-amber-950 text-amber-400",
  unclear: "bg-zinc-800 text-zinc-400",
  nonsense: "bg-red-950 text-red-400",
};

export const VERDICT_TONE: Record<string, string> = {
  survives: "bg-emerald-950 text-emerald-400",
  restated: "bg-amber-950 text-amber-400",
  falsified: "bg-red-950 text-red-400",
  malformed: "bg-red-950 text-red-400",
  // "undecidable" (close-out 2026-06-09, EMIT: workers/critic_loop_v0.py) fails
  // closed — "could not be judged on this retrieval", never promotes. A
  // DELIBERATE quiet-grey entry, not the unknown-enum fallback: same quiet lane
  // (no emerald/red/amber alarm), the /40 translucency marks it as intentional.
  // The forward-compat pins (test_forwardcompat_iterations_list) require the
  // tone to keep the bg-zinc-800 + text-zinc-400 quiet family.
  undecidable: "bg-zinc-800/40 text-zinc-400",
};

// Loop v1 Step 8 human-gate state.
export const GATE_TONE: Record<string, string> = {
  pending: "bg-sky-950 text-sky-300",
  valid: "bg-emerald-950 text-emerald-400",
  invalid: "bg-red-950 text-red-400",
  needs_revision: "bg-amber-950 text-amber-400",
};

// Tone lookup for the producer-owned enum fields (novelty.class / critique.verdict
// / gate_status). These are append-only JSONL values, so an UNKNOWN/forward-compat
// enum (a never-seen class, or a value colliding with an inherited Object.prototype
// member name — "toString", "constructor", "valueOf", "hasOwnProperty", "__proto__")
// must fall back to the quiet tone, NOT resolve a prototype function. A bare
// `MAP[value] ?? fallback` resolves "toString" to `Function.prototype.toString` (a
// function, not undefined), so `?? fallback` does NOT fire and that function
// interpolates into className as "function toString() { [native code] }". Own-key
// lookup only; any unknown value (prototype collision included) takes `fallback`.
// Mirrors SourceBadge / AgentBadge's prototype-collision guard.
export function toneFor(
  map: Record<string, string>,
  key: string | null | undefined,
  fallback: string,
): string {
  if (typeof key !== "string") return fallback;
  return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : fallback;
}

// Process-status badge. `status` mirrors /api/loop_v0/processes:
// running / exited_clean / exited_error_<rc> / killed_signal_<sig>.
// `status` is producer-owned (joined from /api/loop_v0/processes); a malformed
// row can hand a number/object, and `.startsWith` then throws
// ("status.startsWith is not a function") and takes the row down. A non-string
// is treated as "no status" — the `typeof` guards stand in for the previous
// falsy check.
export function processTone(status: string | undefined): string {
  if (typeof status !== "string" || !status) return "bg-zinc-800 text-zinc-400";
  if (status === "running") return "bg-sky-950 text-sky-300";
  if (status === "exited_clean") return "bg-emerald-950 text-emerald-400";
  if (status.startsWith("exited_error_")) return "bg-red-950 text-red-400";
  if (status.startsWith("killed_signal_")) return "bg-red-950 text-red-400";
  return "bg-zinc-800 text-zinc-400";
}

export function processLabel(status: string | undefined): string | null {
  if (typeof status !== "string" || !status) return null;
  if (status === "exited_clean") return "pid clean";
  if (status === "running") return "pid running";
  if (status.startsWith("exited_error_")) return `pid err ${status.slice("exited_error_".length)}`;
  if (status.startsWith("killed_signal_")) return `pid killed ${status.slice("killed_signal_".length)}`;
  return status;
}

// `text` is fed producer-owned enum fields (novelty.class / critique.verdict /
// gate_status). The `string | null | undefined` type is a compile-time fiction
// over unchecked JSONL: a malformed/legacy row can emit an object or array, and
// React throws "Objects are not valid as a React child" the moment one reaches
// {text} — crashing the whole row. Coerce to a safe scalar string: a string /
// finite number renders as-is; anything without a usable scalar form (object,
// array, NaN, null, undefined) yields no badge rather than a throw.
export function badgeText(text: string | null | undefined): string {
  if (typeof text === "string") return text;
  if (typeof text === "number") return Number.isFinite(text) ? String(text) : "";
  return "";
}

// Wider scalar guard for detail lines: also stringifies booleans
// (relevance.low_confidence, topicality flags). Same stance as
// SourceBadge.asText — anything without a usable scalar form yields "".
function asScalar(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  if (typeof value === "boolean") return String(value);
  return "";
}

// Skeptic-gate override provenance (close-out 2026-06-09):
// verdict_overridden_from / skeptic_verdict are plain strings that may appear
// on BOTH the novelty and critique blocks (absent on legacy rows). On the ROW
// they surface as a title tooltip on that block's badge; the journey's verdict
// header additionally renders all three as visible text (OverrideProvenance).
// Producer-owned: a garbled field (object/array, per the forward-compat pins)
// is dropped via badgeText so "[object Object]" can never land in the title
// attribute. Returns undefined (no tooltip) when neither field is usable.
export function overrideTooltip(
  block:
    | { verdict_overridden_from?: unknown; skeptic_verdict?: unknown }
    | null
    | undefined,
): string | undefined {
  const from = badgeText(
    block?.verdict_overridden_from as string | null | undefined,
  );
  const skeptic = badgeText(block?.skeptic_verdict as string | null | undefined);
  const parts: string[] = [];
  if (from) parts.push(`overridden from ${from}`);
  if (skeptic) parts.push(`skeptic said ${skeptic}`);
  return parts.length > 0 ? parts.join("; ") : undefined;
}

export function Badge({
  text,
  tone,
  title,
}: {
  text: string | null | undefined;
  tone: string;
  title?: string;
}) {
  const safe = badgeText(text);
  if (!safe) return null;
  return (
    <span
      title={title}
      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${tone}`}
    >
      {safe}
    </span>
  );
}

// Loop v1 Step 2.5 red-team chip. Highlighted (red) when the critic ruled
// fatal_flaw OR any revision retries were spent — those are the rows a
// human most needs to eyeball. A clean "proceed / 0 retries" pass renders
// quiet zinc. Returns null when no redteam block is present (pre-v1 rows).
export function RedteamChip({
  redteam,
}: {
  redteam: IterationRecord["redteam"];
}) {
  if (!redteam || (redteam.verdict == null && redteam.retries_used == null)) {
    return null;
  }
  const retries = redteam.retries_used ?? 0;
  const fatal = redteam.verdict === "fatal_flaw";
  const highlight = fatal || retries > 0;
  const tone = highlight
    ? "bg-red-950 text-red-400"
    : "bg-zinc-800 text-zinc-400";
  const label = `redteam ${redteam.verdict ?? "?"}${
    retries > 0 ? ` · ${retries} retr${retries === 1 ? "y" : "ies"}` : ""
  }`;
  return (
    <span
      data-testid="redteam-chip"
      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${tone}`}
    >
      {label}
    </span>
  );
}

// TRUE when the redteam record is the ALARMING kind (fatal_flaw or retries
// spent) — the state that earns the row's single alarm slot. A clean
// proceed/0 pass (and a boundary NaN/negative retries count, which `> 0`
// rejects) is quiet and lives in the detail surface only.
export function redteamAlarm(redteam: IterationRecord["redteam"]): boolean {
  if (!redteam || typeof redteam !== "object") return false;
  if (redteam.verdict === "fatal_flaw") return true;
  const retries = redteam.retries_used;
  return typeof retries === "number" && retries > 0;
}

// Derive the Verdict=YES|NO chip text from the producer's own summary line
// ("Verdict=YES. …" / "VCG verdict=YES. …" — the exp001/exp003/exp004 shape in
// docs/DATA_SHAPES.md). The verdict is rendered ONLY when the summary literally
// states it; an outcome without a verdict line gets the quiet "experiment"
// marker — never a fabricated verdict.
export function experimentVerdict(
  outcome: IterationRecord["experiment_outcome"],
): "YES" | "NO" | null {
  if (outcome == null || typeof outcome !== "object" || Array.isArray(outcome)) {
    return null;
  }
  const summary = (outcome as { summary?: unknown }).summary;
  if (typeof summary !== "string") return null;
  const m = summary.match(/verdict\s*=\s*(YES|NO)\b/i);
  return m ? (m[1].toUpperCase() as "YES" | "NO") : null;
}

// experiment_outcome chip (handoff Task 4 alarm slot / Task 6): emerald for a
// stated Verdict=YES, red for Verdict=NO, quiet zinc when the outcome carries
// no verdict line. Scalar-guard idiom on metric/value (value may legitimately
// be an OBJECT for multi-metric outcomes — only a usable scalar reaches the
// title; mirrors Experiments.tsx bridgeLabel).
export function ExperimentChip({
  outcome,
}: {
  outcome: IterationRecord["experiment_outcome"];
}) {
  if (outcome == null || typeof outcome !== "object" || Array.isArray(outcome)) {
    return null;
  }
  const verdict = experimentVerdict(outcome);
  const tone =
    verdict === "YES"
      ? "bg-emerald-950 text-emerald-400"
      : verdict === "NO"
        ? "bg-red-950 text-red-400"
        : "bg-zinc-800 text-zinc-400";
  const id = asScalar(outcome.experiment_id);
  const metric = asScalar(outcome.metric);
  const value = asScalar(outcome.value); // object value -> "" (multi-metric)
  const titleParts: string[] = [];
  if (id) titleParts.push(id);
  if (metric && value) titleParts.push(`${metric}=${value}`);
  else if (metric) titleParts.push(metric);
  const summary = asScalar(outcome.summary);
  if (summary) titleParts.push(summary);
  return (
    <span
      data-testid="experiment-chip"
      title={titleParts.length > 0 ? titleParts.join(" · ") : undefined}
      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${tone}`}
    >
      {verdict ? `exp verdict=${verdict}` : "experiment"}
    </span>
  );
}

// loop_memory.jsonl is producer-owned; a buggy/legacy row can emit
// meta_review.conditioning_bullets as a bare string (not a list) or with junk
// entries (null, numbers, objects). A non-array used to crash the whole list
// via `.map`, and a raw-object entry crashes React's child renderer. Return
// only the string bullets so one bad row degrades to "no bullets" instead of
// blanking the page.
export function conditioningBullets(row: IterationRecord): string[] {
  const bullets = row.meta_review?.conditioning_bullets;
  if (!Array.isArray(bullets)) return [];
  return bullets.filter((b): b is string => typeof b === "string");
}

// seed.topic is likewise producer-owned: coerce a non-string topic to a safe
// string so neither a topic filter (`.toLowerCase()`) nor the row render
// throws on a malformed row.
export function seedTopic(row: IterationRecord): string {
  const topic = row.seed?.topic;
  return typeof topic === "string" ? topic : "";
}

// ended_at is producer-owned: a legacy/buggy row can emit it as a number
// (epoch), object, or garbage rather than an ISO string. `.replace` then
// throws ("iso.replace is not a function") and crashes the whole row. Treat a
// non-string as no-timestamp ("—") rather than throwing; a string passes
// through unchanged.
export function shortTimestamp(iso: unknown): string {
  if (typeof iso !== "string" || !iso) return "—";
  return iso.replace("T", " ").replace("Z", "");
}

// The override provenance AS VISIBLE TEXT (formerly IterationDetailModal
// section 1 — the condensed row keeps tooltip-only; the journey's verdict
// header shows this). Renders nothing when no usable field exists.
export function OverrideProvenance({
  label,
  testid,
  block,
}: {
  label: string;
  testid: string;
  block:
    | {
        verdict_overridden_from?: unknown;
        override_reason?: unknown;
        skeptic_verdict?: unknown;
      }
    | null
    | undefined;
}) {
  if (block == null || typeof block !== "object") return null;
  const from = badgeText(
    block.verdict_overridden_from as string | null | undefined,
  );
  const reason = badgeText(block.override_reason as string | null | undefined);
  const skeptic = badgeText(block.skeptic_verdict as string | null | undefined);
  if (!from && !reason && !skeptic) return null;
  return (
    <div
      data-testid={testid}
      className="mt-1.5 rounded border border-amber-900/40 bg-amber-950/20 px-2 py-1 text-[11px] text-amber-200/90"
    >
      <div className="text-[10px] uppercase tracking-wide text-amber-500/90">
        {label} override
      </div>
      {from && (
        <div>
          overridden from <span className="font-mono">{from}</span>
        </div>
      )}
      {reason && <div>reason: {reason}</div>}
      {skeptic && (
        <div>
          skeptic said <span className="font-mono">{skeptic}</span>
        </div>
      )}
    </div>
  );
}
