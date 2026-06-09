// Dashboard hero — "what is the machine doing RIGHT NOW". The headline fix
// for the 2026-06-09 screenshot complaint: GPU at 96% + gemma decoding while
// the dashboard read "ACTIVE: idle / HEALTHY all systems nominal". This hero
// composes what already flows — the live wrapper-call aggregate (caller_tag ×
// model × rate from /api/activity/monitor), the latest telemetry sample (GPU
// util, vllm running requests / decode tok/s), and the registered-run mirrors
// (active iteration / coordinator active_run) — into a three-state verdict:
//
//   registered        (emerald) — an active iteration or coordinator run is
//                       registered; name it ("RUNNING — <topic/step>").
//   busy-unregistered (amber)   — the DRIFT state: no registered run, but
//                       calls flowed recently OR vllm has running requests OR
//                       the GPU is loaded. Activity without provenance is
//                       itself a legible finding (reconciliation plan A1);
//                       until A1/A2 land this shows often — that's correct.
//   idle              (zinc)    — none of the above.
//
// The hero must NEVER say idle while the machine works; conversely a live-call
// aggregate whose last_call_at is stale (a snapshot computed from old data)
// must NOT light it — the timestamp is trusted over the count (render
// honestly; the stale-run_id producer bug means counts alone can lie).
//
// computeActivity is pure so it can be unit-tested directly; the component is
// a thin presentational shell over it (the HealthVerdict idiom). Pure /
// prop-driven: no fetching here — the Dashboard wires the feeds in.
import { elapsed, useNow } from "../time";
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
// field can never blank the Dashboard. (SurfacedFindingsPanel idiom.)
function asText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  if (typeof v === "boolean") return String(v);
  return null;
}

// First NON-EMPTY rendered text from candidates (coalesce on truthiness so a
// producer's `topic:""` falls through to the next legible field).
function firstText(...candidates: unknown[]): string | null {
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
function callsRecent(lc: LiveCalls | null | undefined, nowMs: number): boolean {
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

function buildEvidence(input: ActivityInput, nowMs: number): string[] {
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

const STATE_LABEL: Record<ActivityState, string> = {
  registered: "RUNNING",
  "busy-unregistered": "BUSY",
  idle: "IDLE",
};

// Tailwind tone per state — the zinc/emerald/amber idiom (HealthVerdict).
const STATE_TONE: Record<
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

export interface SystemActivityHeroProps extends ActivityInput {
  // Injectable clock for tests; defaults to the shared 1 Hz live clock.
  nowMs?: number;
}

export default function SystemActivityHero(props: SystemActivityHeroProps) {
  const tick = useNow();
  const now = props.nowMs ?? tick;
  const verdict = computeActivity(props, now);
  const tone = STATE_TONE[verdict.state];

  return (
    <div
      data-testid="system-activity-hero"
      data-state={verdict.state}
      className={`rounded border ${tone.border} bg-zinc-900/40 px-4 py-3`}
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="flex items-center gap-2">
          <span className={`h-2.5 w-2.5 rounded-full ${tone.dot}`} aria-hidden />
          <span className={`text-lg font-semibold tracking-wide ${tone.text}`}>
            {STATE_LABEL[verdict.state]}
          </span>
        </span>
        <span className="text-sm text-zinc-400">{verdict.headline}</span>
      </div>
      {verdict.evidence.length > 0 && (
        <div
          className="mt-1 font-mono text-xs text-zinc-500"
          data-testid="system-activity-evidence"
        >
          {verdict.evidence.join(" · ")}
        </div>
      )}
    </div>
  );
}
