// ModelServerCard — the ONE parameterized model-server panel (UI
// simplification S1), replacing VllmPanel + QwenPanel. Both cards were the
// same skeleton — status badge, "driving" sub-line, core Decode/KV rows,
// internals disclosure, MTP tile — differing only in the sample block they
// read (`pick`), the served-model name their DrivingLine attributes to, the
// header accent, the Gemma-only workload-hint pill, and Qwen's tri-state
// transient-drop banner. Those differences are now props.
//
// Body states:
//   - transientDropBanner=false (Gemma): binary — latest sample carries the
//     block, or the "unavailable" message.
//   - transientDropBanner=true (Qwen): tri-state — NO sample ever carried the
//     block ("endpoint unreachable", expected while a server is unwired),
//     the LATEST sample lost it (soft amber "dropped on the latest sample" —
//     the header badge stays deliberately binary hard-red; the body carries
//     the intermittent-vs-outage nuance), or data.
//
// The "driving" derivation (roles.drivingTags) is EXACT-match on the served
// model name — no substring/heuristic matching, absent when none.
import { useEffect, useState, type ReactNode } from "react";
import { getWorkloadHint } from "../api/http";
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

export default function ModelServerCard({
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
  const block = latest ? (pick(latest) ?? null) : null;
  const anyBlock = samples.some((s) => pick(s) != null);
  const series = (metric: (b: VllmSample) => number | null | undefined) =>
    samples.map((s) => {
      const b = pick(s);
      return b == null ? null : metric(b);
    });

  const [hint, setHint] = useState<WorkloadHint | null>(null);
  useEffect(() => {
    if (!workloadHint) return;
    let active = true;
    const load = () =>
      getWorkloadHint()
        .then((h) => {
          if (active) setHint(h);
        })
        .catch(() => {});
    load();
    const id = setInterval(load, 10000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [workloadHint]);

  const tone = Object.prototype.hasOwnProperty.call(ACCENT, accent)
    ? ACCENT[accent]
    : ACCENT.zinc;

  // Body state: without the tri-state banner, "no block on the LATEST sample"
  // is the down message; with it, "never any block" and "lost on the latest
  // sample" are distinguished honestly.
  const body =
    block != null
      ? "data"
      : transientDropBanner
        ? anyBlock
          ? "dropped"
          : "unreachable"
        : "unavailable";

  return (
    <div className={`rounded border ${tone.border} bg-zinc-900/40 p-4`}>
      <div className="flex items-baseline gap-2">
        <h2
          className={`text-xs font-medium uppercase tracking-wide ${tone.header}`}
        >
          {title}
        </h2>
        {/* Badge is deliberately binary (emerald up / red down), keyed off
            the LATEST sample alone. In the transient-drop state the header
            reads hard-red "● down" while the body shows the softer amber
            banner — intended: the latest sample genuinely has no data, and
            the body carries the intermittent-vs-outage nuance. */}
        <span
          className={`ml-auto font-mono text-[11px] ${
            block ? "text-emerald-400" : "text-red-400"
          }`}
          data-testid={`${servedModel}-status`}
        >
          {block ? "● up" : "● down"}
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
        // Sampler had a reading earlier but the latest sample lost it
        // (transient failure). Softer banner so the panel keeps its space
        // and the user knows the loss is intermittent.
        <div className="mt-3 text-sm text-amber-400/80">
          /metrics dropped on the latest sample.
        </div>
      )}
      {body === "data" && block != null && (
        <div className="mt-2">
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
