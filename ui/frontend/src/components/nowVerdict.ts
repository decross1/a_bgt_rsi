// nowVerdict.ts — the pure "what is the machine doing RIGHT NOW" verdict,
// ported VERBATIM from SystemActivityHero.tsx (UI simplification S1) so the
// merged NowBoard headline strip and the (S3-dying) hero share one
// implementation. No React here — computeActivity and its builders are plain
// functions, unit-tested directly (tests/test_now_verdict.tsx).
//
// The three-state verdict:
//   registered        (emerald) — an active iteration or coordinator run is
//                       registered; name it ("RUNNING — <topic/step>").
//   busy-unregistered (amber)   — the DRIFT state: no registered run, but
//                       calls flowed recently OR vllm has running requests OR
//                       the GPU is loaded. Activity without provenance is
//                       itself a legible finding (reconciliation plan A1).
//   idle              (zinc)    — none of the above.
//
// The verdict must NEVER say idle while the machine works; conversely a
// live-call aggregate whose last_call_at is stale (a snapshot computed from
// old data) must NOT light it — the timestamp is trusted over the count
// (render honestly; the stale-run_id producer bug means counts alone can lie).
import { elapsed } from "../time";
import type { LiveCalls } from "../types/activity";
import type {
  ActiveIteration,
  CoordinatorActiveRun,
  TelemetrySample,
} from "../types/schemas";

export type ActivityState = "registered" | "busy-unregistered" | "idle";

// A wrapper call within this window counts as "calls flowing right now".
const RECENT_CALL_MS = 60_000;
// GPU util above this with no registered run is busy-unregistered. Above
// idle noise, below any real decode load.
const GPU_BUSY_PCT = 20;

// Producer-owned JSON is unvalidated: a field rendered as a React child may
// arrive as a number, boolean, or — fatally — an object/array. Coerce a
// scalar to a string and DROP an object/array (return null) so one malformed
// field can never blank the page. (SurfacedFindingsPanel idiom.)
function asText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  if (typeof v === "boolean") return String(v);
  return null;
}

// First NON-EMPTY rendered text from candidates (coalesce on truthiness so a
// producer's `topic:""` falls through to the next legible field).
export function firstText(...candidates: unknown[]): string | null {
  for (const c of candidates) {
    const s = asText(c);
    if (s && s.trim() !== "") return s;
  }
  return null;
}

// Finite number or null. NaN gpu util / running_requests must never render
// ("GPU NaN%") nor trip a threshold comparison.
function asNum(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export interface ActivityInput {
  liveCalls?: LiveCalls | null;
  telemetry?: TelemetrySample | null;
  activeIteration?: ActiveIteration | null;
  coordinatorActive?: CoordinatorActiveRun | null;
}

export interface ActivityVerdict {
  state: ActivityState;
  headline: string;
  // Evidence chips, strongest-first: caller_tag × model, call rate, GPU,
  // running requests, decode rate, last-call age. Shown in ALL states.
  evidence: string[];
}

// Did wrapper calls land recently? Trust last_call_at over the count: the
// aggregate may be a stale snapshot whose window-count is no longer true.
// Only when no timestamp exists at all does the backend's `active` flag
// (computed server-side against the same window) carry the verdict.
export function callsRecent(
  lc: LiveCalls | null | undefined,
  nowMs: number,
): boolean {
  if (!lc) return false;
  const t = lc.last_call_at ? Date.parse(lc.last_call_at) : NaN;
  if (Number.isFinite(t)) return nowMs - t < RECENT_CALL_MS;
  const count = asNum(lc.count) ?? 0;
  return lc.active === true && count > 0;
}

// Top caller tag from the aggregate. caller_tags is producer-shaped: guard
// the array, the element object, and the tag scalar.
function topCallerTag(lc: LiveCalls | null | undefined): string | null {
  if (!lc || !Array.isArray(lc.caller_tags)) return null;
  for (const t of lc.caller_tags) {
    const tag =
      t && typeof t === "object"
        ? firstText((t as { tag?: unknown }).tag)
        : firstText(t);
    if (tag) return tag;
  }
  return null;
}

// Named-rollup phrases from the additive groups[] (2026-06-10 EMIT), e.g.
// "skeptic_attack ×12 on qwen3.6-27b-nvfp4-mtp". The backend sorts
// count-desc; we take the top two legible groups. Producer-shaped throughout:
// a malformed element contributes nothing, and absent groups (older backend)
// yields [] so the caller falls back to the anonymous aggregate phrasing.
export function topGroupPhrases(
  lc: LiveCalls | null | undefined,
  max = 2,
): string[] {
  if (!lc || !Array.isArray(lc.groups)) return [];
  const phrases: string[] = [];
  for (const g of lc.groups) {
    if (phrases.length >= max) break;
    if (g == null || typeof g !== "object") continue;
    const tag = firstText((g as { tag?: unknown }).tag);
    const model = firstText((g as { model?: unknown }).model);
    const count = asNum((g as { count?: unknown }).count);
    if (!tag && !model) continue;
    const name = tag ?? "(untagged)";
    const counted = count != null && count > 0 ? `${name} ×${count}` : name;
    phrases.push(model ? `${counted} on ${model}` : counted);
  }
  return phrases;
}

export function buildEvidence(input: ActivityInput, nowMs: number): string[] {
  const lc = input.liveCalls;
  const evidence: string[] = [];

  const tag = topCallerTag(lc);
  const model = firstText(lc?.model);
  if (tag && model) evidence.push(`${tag} × ${model}`);
  else if (tag) evidence.push(tag);
  else if (model) evidence.push(model);

  const count = asNum(lc?.count);
  const windowS = asNum(lc?.window_s);
  if (count != null && count > 0) {
    const rate = asNum(lc?.calls_per_s);
    evidence.push(
      `${count} call${count === 1 ? "" : "s"}/${windowS ?? "?"}s` +
        (rate != null ? ` (~${rate}/s)` : ""),
    );
  }

  const gpu = asNum(input.telemetry?.gpu?.util_pct);
  if (gpu != null) evidence.push(`GPU ${Math.round(gpu)}%`);

  const reqs = asNum(input.telemetry?.vllm?.running_requests);
  if (reqs != null && reqs > 0)
    evidence.push(`${reqs} running req${reqs === 1 ? "" : "s"}`);

  const tok = asNum(input.telemetry?.vllm?.tokens_per_sec_decode);
  if (tok != null && tok > 0) evidence.push(`${tok.toFixed(1)} tok/s decode`);

  if (lc?.last_call_at && !Number.isNaN(Date.parse(lc.last_call_at))) {
    evidence.push(`last call ${elapsed(lc.last_call_at, nowMs)} ago`);
  }

  return evidence;
}

export function computeActivity(
  input: ActivityInput,
  nowMs: number,
): ActivityVerdict {
  const evidence = buildEvidence(input, nowMs);
  const lc = input.liveCalls;

  // REGISTERED wins over everything: a registered run with calls flowing is
  // a healthy run, not drift.
  const iter = input.activeIteration;
  const coord = input.coordinatorActive;
  if (iter || coord) {
    const label = iter
      ? [firstText(iter.topic, iter.iteration_id), firstText(iter.current_step)]
          .filter(Boolean)
          .join(" · ")
      : [
          firstText(coord?.label, coord?.narration, coord?.run_id),
          firstText(coord?.current_step),
        ]
          .filter(Boolean)
          .join(" · ");
    return {
      state: "registered",
      headline: `RUNNING — ${label || (iter ? "loop iteration" : "coordinator cycle")}`,
      evidence,
    };
  }

  const recent = callsRecent(lc, nowMs);
  const gpu = asNum(input.telemetry?.gpu?.util_pct);
  const reqs = asNum(input.telemetry?.vllm?.running_requests);
  const busy =
    recent || (reqs != null && reqs > 0) || (gpu != null && gpu > GPU_BUSY_PCT);

  if (busy) {
    // NAMED rollup (2026-06-10): when the live-call aggregate carries
    // groups[], the drift headline names the top groups instead of the
    // anonymous "BUSY (unregistered)". Gated on `recent` (a stale snapshot's
    // groups must not be named as live work). The state machine is untouched
    // — only the headline string changes.
    const groupPhrases = recent ? topGroupPhrases(lc) : [];
    if (groupPhrases.length > 0) {
      const age =
        lc?.last_call_at && !Number.isNaN(Date.parse(lc.last_call_at))
          ? ` · last ${elapsed(lc.last_call_at, nowMs)}`
          : "";
      return {
        state: "busy-unregistered",
        headline: `${groupPhrases.join(" + ")}${age} — no registered run`,
        evidence,
      };
    }
    // Older backend (no groups[]): the original aggregate phrasing.
    const tag = topCallerTag(lc);
    const model = firstText(lc?.model);
    const parts: string[] = [];
    if (recent && (tag || model)) {
      if (tag && model) parts.push(`${tag} driving ${model}`);
      else parts.push((tag ?? model) as string);
      const count = asNum(lc?.count);
      const windowS = asNum(lc?.window_s);
      if (count != null && count > 0)
        parts.push(`${count} calls/${windowS ?? "?"}s`);
    }
    if (gpu != null) parts.push(`GPU ${Math.round(gpu)}%`);
    if (!recent && reqs != null && reqs > 0)
      parts.push(`${reqs} running req${reqs === 1 ? "" : "s"}`);
    return {
      state: "busy-unregistered",
      headline:
        `BUSY (unregistered)${parts.length ? ` — ${parts.join(" · ")}` : ""}` +
        " — activity without provenance (see reconciliation plan A1)",
      evidence,
    };
  }

  return {
    state: "idle",
    headline: "IDLE — no registered run, no recent activity",
    evidence,
  };
}

// Tailwind tone per state — the zinc/emerald/amber idiom (HealthVerdict).
// Shared by the hero and the NowBoard headline strip.
export const STATE_LABEL: Record<ActivityState, string> = {
  registered: "RUNNING",
  "busy-unregistered": "BUSY",
  idle: "IDLE",
};

export const STATE_TONE: Record<
  ActivityState,
  { dot: string; text: string; border: string }
> = {
  registered: {
    dot: "bg-emerald-400",
    text: "text-emerald-300",
    border: "border-emerald-800/60",
  },
  "busy-unregistered": {
    dot: "bg-amber-400",
    text: "text-amber-300",
    border: "border-amber-800/60",
  },
  idle: {
    dot: "bg-zinc-600",
    text: "text-zinc-400",
    border: "border-zinc-800",
  },
};
