// ModelServerCard — the ONE parameterized model-server panel (UI
// simplification S1), replacing VllmPanel + QwenPanel. Both cards were the
// same skeleton — status badge, "driving" sub-line, core Decode/KV rows,
// internals disclosure, MTP tile — differing only in the sample block they
// read (`pick`), the served-model name their DrivingLine attributes to, the
// header accent, the Gemma-only workload-hint pill, and Qwen's tri-state
// transient-drop banner. Those differences are now props.
//
// Body states (LAST-GOOD RETENTION, adversarial-review residual fix 5,
// 2026-08-18 — the badge + body used to key off the LATEST sample alone, so
// ONE missed /metrics scrape swapped a healthy card to "/metrics
// unavailable" under a hard-red badge):
//   - the latest sample carries the block → data, "● up".
//   - the latest sample lost the block but a sample within the last
//     STALE_MISS_LIMIT scrapes carried it → the body KEEPS the last-good
//     data with an explicit staleness note ("stale telemetry — last sample
//     Xs ago"), and the badge reads amber "● stale": stale telemetry is not
//     a down server, and the badge now says which is which.
//   - STALE_MISS_LIMIT consecutive misses → the body degrades:
//     transientDropBanner=false (Gemma) shows "/metrics unavailable";
//     transientDropBanner=true (Qwen) shows the amber "/metrics dropped"
//     banner. Badge "● down".
//   - NO sample ever carried the block → "unavailable" (binary mode) or
//     "endpoint unreachable" (tri-state; expected while a server is
//     unwired). Badge "● down".
// There is no per-card hard down signal on today's wire (read_errors are
// sampler-reader-keyed and filtered upstream of this card), so consecutive
// misses are the sole degrade trigger.
//
// The "driving" derivation (roles.drivingTags) is EXACT-match on the served
// model name — no substring/heuristic matching, absent when none.
import { memo, type ReactNode } from "react";
import { useNow } from "../time";
import { getWorkloadHint } from "../api/http";
import { usePolled } from "../api/pollhub";
import { fmt, fmtRatioPct } from "../format";
import { callerTagTone, drivingTags } from "../roles";
import type { LiveCalls } from "../types/activity";
import type { TelemetrySample, VllmSample, WorkloadHint } from "../types/schemas";
import Sparkline from "./Sparkline";

// LAST-RESORT fallbacks only. These are what the servers served on
// 2026-06-10; they are NOT the truth about what is running now. The live name
// comes from GET /api/served_models — on 2026-08-16 these constants had the
// dashboard announcing "Qwen3.6" for an hour while :8001 served 3.8, which is
// why a card title must never be sourced from here.
export const VLLM_SERVED_MODEL = "gemma-4-26b-a4b";
export const QWEN_SERVED_MODEL = "qwen3.6-27b-nvfp4-mtp";

// How many CONSECUTIVE trailing samples may miss this card's block before
// the body stops showing retained last-good data and degrades to its
// no-data message (residual fix 5; the reviewer's pick of 3). Below the
// limit the miss renders as "stale telemetry", never as an outage.
const STALE_MISS_LIMIT = 3;

// "last sample Xs ago" — self-ticking (30 s) so the note cannot freeze
// under the card's memo between telemetry flushes; the tick re-renders this
// leaf alone, never the rows/sparklines around it.
function SampleAge({ iso }: { iso: string | null }) {
  const now = useNow(30_000);
  if (typeof iso !== "string") return <>an unknown time</>;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return <>an unknown time</>;
  const s = Math.max(0, Math.round((now - t) / 1000));
  const text =
    s < 120
      ? `${s}s`
      : s < 7200
        ? `${Math.floor(s / 60)}m`
        : s < 172800
          ? `${Math.floor(s / 3600)}h`
          : `${Math.floor(s / 86400)}d`;
  return <>{text}</>;
}

// "driving: <tag> ×N" — who is generating this panel's load right now,
// derived from the live-call groups (2026-06-10 EMIT). Absent (renders null)
// when no group's model exactly equals the served model.
export function DrivingLine({
  liveCalls,
  servedModel,
  testId,
}: {
  liveCalls: LiveCalls | null | undefined;
  servedModel: string;
  testId: string;
}) {
  const tags = drivingTags(liveCalls, servedModel);
  if (tags.length === 0) return null;
  return (
    <div className="mt-1 text-[11px] leading-snug" data-testid={testId}>
      <span className="text-zinc-500">driving: </span>
      {tags.slice(0, 3).map((t, i) => (
        <span key={t.tag} className="font-mono">
          {i > 0 && <span className="text-zinc-600"> · </span>}
          <span className={callerTagTone(t.tag)}>{t.tag}</span>
          <span className="text-zinc-400"> ×{t.count}</span>
        </span>
      ))}
    </div>
  );
}

function Row({
  label,
  value,
  valueClass = "text-zinc-100",
  spark,
}: {
  label: string;
  value: string;
  valueClass?: string;
  spark?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-zinc-800/60 py-2 last:border-0">
      <span className="text-sm text-zinc-400">{label}</span>
      <div className="flex items-center gap-3">
        {spark}
        <span className={`w-24 text-right text-sm tabular-nums ${valueClass}`}>
          {value}
        </span>
      </div>
    </div>
  );
}

// Day-7 UX audit (ui_plan.md r10): the day-1 decode band [80,130] was
// measured with 256-tok completions. A PD workload with ~2 tok/call makes the
// tile read ~11 tok/s by construction. The workload-hint pill surfaces that
// context so the user doesn't read low decode as a bug.
function decodeRegimeColor(regime: WorkloadHint["regime"]): string {
  switch (regime) {
    case "short_completion":
      return "text-zinc-400"; // not a regression — workload-bound
    case "decode_bound":
      return "text-emerald-400"; // day-1 band applies
    case "mixed":
      return "text-amber-400";
    default:
      return "text-zinc-600";
  }
}

function regimeShortLabel(regime: WorkloadHint["regime"]): string {
  switch (regime) {
    case "short_completion":
      return "short-completion";
    case "decode_bound":
      return "decode-bound";
    case "mixed":
      return "mixed";
    default:
      return "idle";
  }
}

// Header/border accent per server. Gemma keeps the quiet zinc header; Qwen
// keeps its sky identity (the roles.ts backend-tone family).
const ACCENT: Record<string, { header: string; border: string }> = {
  zinc: { header: "text-zinc-500", border: "border-zinc-800" },
  sky: { header: "text-sky-400", border: "border-sky-900/60" },
};

export interface ModelServerCardProps {
  // Header text (e.g. "gemma-4-26b-a4b" / "Qwen3.6-27B · NVFP4-MTP").
  title: string;
  // The exact served-model name for the DrivingLine attribution and this
  // card's testids (`<servedModel>-status` / `-driving` / `-details`).
  servedModel: string;
  // Which per-sample block this card reads (s.vllm vs s.vllm_qwen).
  pick: (s: TelemetrySample) => VllmSample | null | undefined;
  samples: TelemetrySample[];
  // Optional (additive): the live-call aggregate, for the "driving" sub-line.
  liveCalls?: LiveCalls | null;
  // Header/border accent family; unknown keys degrade to zinc.
  accent?: "zinc" | "sky" | string;
  // Gemma-only: poll /api/workload_hint and render the decode-regime pill +
  // the decode sparkline's expected-band reference line.
  workloadHint?: boolean;
  // Qwen-mode tri-state body (see file header). Default false = binary.
  transientDropBanner?: boolean;
}

function ModelServerCard({
  title,
  servedModel,
  pick,
  samples,
  liveCalls,
  accent = "zinc",
  workloadHint = false,
  transientDropBanner = false,
}: ModelServerCardProps) {
  const latest = samples[samples.length - 1] ?? null;
  const latestBlock = latest ? (pick(latest) ?? null) : null;
  // LAST-GOOD RETENTION (residual fix 5): the newest sample that carried
  // this card's block, scanned from the tail. `missedScrapes` counts the
  // consecutive trailing samples WITHOUT it — the staleness the body and
  // badge now key off, instead of the latest sample alone.
  let lastGoodIdx = -1;
  for (let i = samples.length - 1; i >= 0; i--) {
    if (pick(samples[i]) != null) {
      lastGoodIdx = i;
      break;
    }
  }
  const lastGood = lastGoodIdx >= 0 ? (pick(samples[lastGoodIdx]) ?? null) : null;
  const lastGoodAt =
    lastGoodIdx >= 0 ? (samples[lastGoodIdx]?.timestamp ?? null) : null;
  const missedScrapes =
    lastGoodIdx >= 0 ? samples.length - 1 - lastGoodIdx : samples.length;
  const anyBlock = lastGood != null;
  const retaining =
    latestBlock == null && lastGood != null && missedScrapes < STALE_MISS_LIMIT;
  // What the body renders: the live block, or the retained last-good one
  // while the miss run is still below the limit.
  const block = latestBlock ?? (retaining ? lastGood : null);
  const series = (metric: (b: VllmSample) => number | null | undefined) =>
    samples.map((s) => {
      const b = pick(s);
      return b == null ? null : metric(b);
    });

  // pollhub (perf 2026-08-18): the hint endpoint measured 3.2s under load —
  // 30s cadence (was a bare 10s setInterval), in-flight-guarded, SWR (a
  // failed refetch keeps the previous hint rather than flapping the pill).
  const hint: WorkloadHint | null =
    usePolled<WorkloadHint>("workload_hint", getWorkloadHint, {
      intervalMs: 30000,
      initialDelayMs: 400,
      enabled: workloadHint,
    }).data ?? null;

  const tone = Object.prototype.hasOwnProperty.call(ACCENT, accent)
    ? ACCENT[accent]
    : ACCENT.zinc;

  // Body state: `block` already folds in the retention rule, so a null here
  // means EITHER no sample ever carried the block or the miss run reached
  // STALE_MISS_LIMIT. Tri-state mode still distinguishes "never any block"
  // (unreachable — expected while a server is unwired) from "had it, lost
  // it" (dropped).
  const body =
    block != null
      ? "data"
      : transientDropBanner
        ? anyBlock
          ? "dropped"
          : "unreachable"
        : "unavailable";
  // Badge (residual fix 5): three states, so stale telemetry no longer
  // reads as a down server — "● up" (latest sample has data), amber
  // "● stale" (retaining last-good data through a short miss run), red
  // "● down" (miss run at the limit, or no data ever).
  const badge = latestBlock != null ? "up" : retaining ? "stale" : "down";

  return (
    <div className={`rounded border ${tone.border} bg-zinc-900/40 p-4`}>
      <div className="flex items-baseline gap-2">
        <h2
          className={`text-xs font-medium uppercase tracking-wide ${tone.header}`}
        >
          {title}
        </h2>
        {/* Badge distinguishes 'down' from 'stale telemetry' (residual
            fix 5): a short scrape-miss run reads amber "● stale" while the
            body keeps the last-good data; hard-red "● down" is reserved for
            a miss run at the limit or a server that never reported. */}
        <span
          className={`ml-auto font-mono text-[11px] ${
            badge === "up"
              ? "text-emerald-400"
              : badge === "stale"
                ? "text-amber-400"
                : "text-red-400"
          }`}
          data-testid={`${servedModel}-status`}
        >
          {badge === "up" ? "● up" : badge === "stale" ? "● stale" : "● down"}
        </span>
      </div>
      {/* Who is generating this backend's load right now — exact-match
          live-call groups only; absent when none. Rendered in EVERY body
          state: the derivation comes from the call log, not the sampler, so
          a panel whose /metrics reader is down can still be the busy backend. */}
      <DrivingLine
        liveCalls={liveCalls}
        servedModel={servedModel}
        testId={`${servedModel}-driving`}
      />
      {body === "unavailable" && (
        <div className="mt-3 text-sm text-zinc-500">
          /metrics unavailable — the server may be down or still loading.
        </div>
      )}
      {body === "unreachable" && (
        <div className="mt-3 text-sm text-zinc-500">
          endpoint unreachable — server may be down or not enabled.
        </div>
      )}
      {body === "dropped" && (
        // Sampler had readings earlier but the miss run reached the limit
        // (residual fix 5: a SINGLE missed scrape no longer lands here — it
        // renders as retained data + the stale note). Softer banner so the
        // panel keeps its space and the user knows data existed before.
        <div className="mt-3 text-sm text-amber-400/80">
          /metrics dropped — {missedScrapes} consecutive scrape
          {missedScrapes === 1 ? "" : "s"} without a reading.
        </div>
      )}
      {body === "data" && block != null && (
        <div className="mt-2">
          {retaining && (
            // The explicit staleness note that makes retention honest: the
            // rows below are the LAST GOOD sample, aged out loud.
            <div
              className="mb-1 text-[11px] leading-snug text-amber-400/80"
              data-testid={`${servedModel}-stale-note`}
            >
              stale telemetry — last sample <SampleAge iso={lastGoodAt} /> ago
              ({missedScrapes} missed scrape{missedScrapes === 1 ? "" : "s"})
            </div>
          )}
          {/* Core health — always visible: decode tok/s and KV-cache
              headroom (red over 85%). Everything else is operator-grade
              detail behind the disclosure below. */}
          <Row
            label="Decode tok/s"
            value={fmt(block.tokens_per_sec_decode, 1)}
            spark={
              <Sparkline
                values={series((b) => b.tokens_per_sec_decode)}
                color="#34d399"
                reference={
                  workloadHint && hint?.regime === "decode_bound"
                    ? 40
                    : undefined
                }
              />
            }
          />
          <Row
            label="KV-cache usage"
            value={`${fmt(block.gpu_cache_usage_pct, 1)} %`}
            valueClass={
              block.gpu_cache_usage_pct > 85 ? "text-red-400" : "text-zinc-100"
            }
            spark={
              <Sparkline
                values={series((b) => b.gpu_cache_usage_pct)}
                color="#38bdf8"
              />
            }
          />
          {workloadHint && hint?.available && (
            <div className="mt-1 flex flex-wrap items-baseline gap-x-2 text-[11px] leading-snug">
              <span
                className={`rounded bg-zinc-800/60 px-1.5 py-0.5 font-mono ${decodeRegimeColor(
                  hint.regime,
                )}`}
              >
                workload: {regimeShortLabel(hint.regime)}
              </span>
              {hint.median_output_tokens != null && hint.calls_per_s != null && (
                <span className="text-zinc-500">
                  ~{hint.median_output_tokens} tok/call · {hint.calls_per_s}{" "}
                  call/s
                </span>
              )}
              {hint.expected_decode_tok_s_lower != null &&
                hint.expected_decode_tok_s_upper != null && (
                  <span className="text-zinc-500">
                    expected ~{hint.expected_decode_tok_s_lower}–
                    {hint.expected_decode_tok_s_upper} tok/s
                  </span>
                )}
              <span className="text-zinc-600">{hint.note}</span>
            </div>
          )}

          {/* Operator-grade internals: queue depth, prefix-cache, MTP
              acceptance. Kept but collapsed so the glance stays clean. */}
          <details className="mt-2 group" data-testid={`${servedModel}-details`}>
            <summary className="cursor-pointer list-none text-[11px] uppercase tracking-wide text-zinc-500 hover:text-zinc-300">
              <span className="group-open:hidden">show internals ▸</span>
              <span className="hidden group-open:inline">hide internals ▾</span>
            </summary>
            <div className="mt-1">
              <Row
                label="Running requests"
                value={fmt(block.running_requests)}
                spark={<Sparkline values={series((b) => b.running_requests)} />}
              />
              <Row
                label="Waiting requests"
                value={fmt(block.waiting_requests)}
                spark={<Sparkline values={series((b) => b.waiting_requests)} />}
              />
              <Row
                label="Prefix-cache hit rate"
                value={
                  block.gpu_prefix_cache_hit_rate == null
                    ? "n/a"
                    : `${fmtRatioPct(block.gpu_prefix_cache_hit_rate, 1)} %`
                }
              />
              <Row
                label="MTP acceptance"
                value={
                  block.mtp_acceptance_rate == null
                    ? "MTP off / metric absent"
                    : `${fmtRatioPct(block.mtp_acceptance_rate, 1)} %`
                }
                // Chosen heuristic (carried from VllmPanel): ≥50% draft-token
                // acceptance reads as healthy MTP, below it as poor (decode
                // tok/s then suffers). This threshold is ours, not a plan's —
                // open question in ui/notes/ui-build.md.
                valueClass={
                  block.mtp_acceptance_rate == null
                    ? "text-zinc-600"
                    : block.mtp_acceptance_rate >= 0.5
                      ? "text-emerald-400"
                      : "text-amber-400"
                }
                spark={
                  block.mtp_acceptance_rate != null ? (
                    <Sparkline values={series((b) => b.mtp_acceptance_rate)} />
                  ) : undefined
                }
              />
            </div>
          </details>
        </div>
      )}
    </div>
  );
}

// Memoized: `samples` identity changes only on a telemetry flush (~0.5 Hz)
// and `pick` is a module-level constant in Pulse — page clock ticks and
// unrelated polls no longer re-render the card (and its sparklines).
export default memo(ModelServerCard);
