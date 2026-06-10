// roles.ts — ADDITIVE tone maps for the 2026-06-10 provenance EMIT renders
// (live-call group rows, backend chips, panel "driving" sub-lines). These maps
// are NEW ink only: they must never retint existing badges — NOVELTY_TONE /
// VERDICT_TONE / GATE_TONE / SourceBadge.TONE / AgentBadge stay exactly as
// they are.
//
// Both lookups take PRODUCER-OWNED strings (caller_tag / backend straight out
// of logs/calls.jsonl), so they carry the same two hazards SourceBadge guards:
//   1. Object.prototype collisions — a tag named "toString"/"constructor"
//      resolves through the prototype chain on a bare `obj[key]`, leaking a
//      function into className. Own-key lookup only
//      (Object.prototype.hasOwnProperty.call), mirroring SourceBadge.toneFor.
//   2. Non-string values from a malformed/legacy row — guarded to the quiet
//      zinc fallback, never a throw.
import type { LiveCalls } from "./types/activity";

// Quiet zinc — the unknown/unattributed fallback for chips (SourceBadge idiom).
export const TONE_QUIET = "bg-zinc-800 text-zinc-400";

// --- backend chips ---------------------------------------------------------
// Backend registry names stamped on calls.jsonl records by the 2026-06-10
// EMIT (schema/calls.jsonl.schema.json, optional top-level `backend`). A null
// backend is rendered ABSENT by consumers — never guessed from the model name
// — so this map only ever sees a real producer string.
const BACKEND_TONE: Record<string, string> = {
  "vllm-gemma": "bg-emerald-950 text-emerald-300",
  "vllm-qwen": "bg-sky-950 text-sky-300",
  "ollama-coder": "bg-amber-950 text-amber-300",
  anthropic: "bg-fuchsia-950 text-fuchsia-300",
};

// Producer-owned scalar → trimmed string, or "" when unusable (object/array/
// NaN). Mirrors SourceBadge.asText so a malformed row degrades, never throws.
function asKey(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  if (typeof value === "boolean") return String(value);
  return "";
}

/** Chip classes for a backend registry name. Unknown / absent / malformed →
 * quiet zinc. Own-key lookup only (prototype-collision guard). */
export function backendTone(backend: unknown): string {
  const key = asKey(backend);
  if (!key) return TONE_QUIET;
  return Object.prototype.hasOwnProperty.call(BACKEND_TONE, key)
    ? BACKEND_TONE[key]
    : TONE_QUIET;
}

// --- caller-tag accents ----------------------------------------------------
// Text-accent classes for a caller_tag, so the live-call group rows read by
// role at a glance: adversarial work rose, relevance/novelty gating indigo,
// the orchestrator chain emerald, the coordinator sky, the lit-falsification
// battery cyan, anything unknown quiet zinc (rendered raw, never filtered).
export const CALLER_TAG_TONE_UNKNOWN = "text-zinc-300";

const TAG_TONE_EXACT: Record<string, string> = {
  topicality_check: "text-indigo-300",
  novelty_classify: "text-indigo-300",
  hypothesize: "text-emerald-300",
  meta_review: "text-emerald-300",
  battery: "text-cyan-300",
};

// Ordered prefix rules — first match wins; the more specific
// "subagent.finding_skeptic_" precedes the generic "skeptic_" (same rose
// today, kept separate so the two families can diverge later). `startsWith`
// on a validated string has no prototype-chain hazard. The battery's wrapper
// calls are tagged per-step (it drives the worker chain), so the cyan battery
// accents key off its own id shapes ("battery-<case>" / "lit_battery_*").
const TAG_TONE_PREFIX: ReadonlyArray<readonly [string, string]> = [
  ["subagent.finding_skeptic_", "text-rose-300"],
  ["skeptic_", "text-rose-300"],
  ["nara.", "text-emerald-300"],
  ["coordinator.", "text-sky-300"],
  ["battery", "text-cyan-300"],
  ["lit_battery", "text-cyan-300"],
];

/** Text-accent classes for a caller_tag. Exact own-key match first, then the
 * ordered prefix rules; unknown / absent / malformed → quiet zinc text. */
export function callerTagTone(tag: unknown): string {
  const key = asKey(tag);
  if (!key) return CALLER_TAG_TONE_UNKNOWN;
  if (Object.prototype.hasOwnProperty.call(TAG_TONE_EXACT, key)) {
    return TAG_TONE_EXACT[key];
  }
  for (const [prefix, tone] of TAG_TONE_PREFIX) {
    if (key.startsWith(prefix)) return tone;
  }
  return CALLER_TAG_TONE_UNKNOWN;
}

// --- "driving" derivation for the backend panels ---------------------------
// Live-call groups whose `model` EXACTLY equals a panel's served model name
// (gemma-4-26b-a4b / qwen3.6-27b-nvfp4-mtp), folded per tag, count-desc.
// EXACT match only — no substring/heuristic matching, and never a guess from
// a null model (a group without a model attributes to no panel).
export interface DrivingTag {
  tag: string;
  count: number;
}

export function drivingTags(
  liveCalls: LiveCalls | null | undefined,
  servedModel: string,
): DrivingTag[] {
  const groups = liveCalls?.groups;
  if (!Array.isArray(groups)) return [];
  const byTag = new Map<string, number>();
  for (const g of groups) {
    if (g == null || typeof g !== "object") continue;
    // EXACT equality with the served model name; a null/absent/mismatched
    // model contributes nothing (never substring-matched).
    if ((g as { model?: unknown }).model !== servedModel) continue;
    const tag = asKey((g as { tag?: unknown }).tag) || "(untagged)";
    const raw = (g as { count?: unknown }).count;
    const count = typeof raw === "number" && Number.isFinite(raw) && raw > 0 ? raw : 0;
    if (count === 0) continue;
    byTag.set(tag, (byTag.get(tag) ?? 0) + count);
  }
  return [...byTag.entries()]
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count);
}
