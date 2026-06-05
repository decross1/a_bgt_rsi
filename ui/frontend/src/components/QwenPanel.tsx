// Qwen3.6-27B NVFP4-MTP internals panel. Mirrors VllmPanel.tsx but reads
// `samples[i].vllm_qwen` (the second sampler reader, see
// ui/sampler/sampler.py). The Qwen endpoint is staged but not yet wired
// into any worker — the expected display today is the "no data" state
// (until a request actually fires against :8001, vllm-qwen's internal
// gauges sit at zero and `vllm_qwen` may still be populated; only when
// the endpoint itself is unreachable does it fall through to null).
//
// Workload-hint pill (decode regime) is intentionally omitted — that hint
// is derived from the Gemma orchestrator's calls.jsonl shape; there is no
// equivalent for the Qwen side yet.
import { type ReactNode } from "react";
import { fmt, fmtRatioPct } from "../format";
import type { TelemetrySample } from "../types/schemas";
import Sparkline from "./Sparkline";

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

export default function QwenPanel({ samples }: { samples: TelemetrySample[] }) {
  const latest = samples[samples.length - 1] ?? null;
  const qwen = latest?.vllm_qwen ?? null;
  const series = (pick: (s: TelemetrySample) => number | null | undefined) =>
    samples.map(pick);

  // "No data" = every sample we have is missing vllm_qwen. Expected today
  // (Qwen is staged but not yet wired into a worker) — explicit message
  // so the empty panel doesn't read as "broken UI".
  const anyQwen = samples.some((s) => s.vllm_qwen != null);

  return (
    <div className="rounded border border-sky-900/60 bg-zinc-900/40 p-4">
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-sky-400">
          Qwen3.6-27B · NVFP4-MTP
        </h2>
        {/* Badge is deliberately binary (emerald up / red down) for parity
            with VllmPanel, which keys off `vllm` alone. It flattens the
            three body states into two: in the transient-drop state
            (anyQwen && !qwen) the header reads hard-red "● down" while the
            body shows the softer amber "dropped on the latest sample"
            banner. This is intended — the latest sample genuinely has no
            data — and the body carries the intermittent-vs-outage nuance. */}
        <span
          className={`ml-auto font-mono text-[11px] ${
            qwen ? "text-emerald-400" : "text-red-400"
          }`}
          data-testid="qwen-status"
        >
          {qwen ? "● up" : "● down"}
        </span>
      </div>
      {!anyQwen ? (
        <div className="mt-3 text-sm text-zinc-500">
          Qwen endpoint unreachable — backend may be down or not enabled.
        </div>
      ) : !qwen ? (
        // Sampler had a reading earlier but the latest sample lost it
        // (transient failure). Render a softer banner so the panel keeps
        // its space and the user knows the loss is intermittent.
        <div className="mt-3 text-sm text-amber-400/80">
          Qwen /metrics dropped on the latest sample.
        </div>
      ) : (
        <div className="mt-2">
          {/* Core health — always visible: decode tok/s and KV-cache
              headroom (red over 85%). Mirrors VllmPanel; the workload-hint
              pill is intentionally absent (see file header). */}
          <Row
            label="Decode tok/s"
            value={fmt(qwen.tokens_per_sec_decode, 1)}
            spark={
              <Sparkline
                values={series((s) => s.vllm_qwen?.tokens_per_sec_decode)}
                color="#34d399"
              />
            }
          />
          <Row
            label="KV-cache usage"
            value={`${fmt(qwen.gpu_cache_usage_pct, 1)} %`}
            valueClass={
              qwen.gpu_cache_usage_pct > 85 ? "text-red-400" : "text-zinc-100"
            }
            spark={
              <Sparkline
                values={series((s) => s.vllm_qwen?.gpu_cache_usage_pct)}
                color="#38bdf8"
              />
            }
          />

          {/* Operator-grade internals: queue depth, prefix-cache, MTP
              acceptance. Kept but collapsed so the glance stays clean. */}
          <details className="mt-2 group" data-testid="qwen-details">
            <summary className="cursor-pointer list-none text-[11px] uppercase tracking-wide text-zinc-500 hover:text-zinc-300">
              <span className="group-open:hidden">show internals ▸</span>
              <span className="hidden group-open:inline">hide internals ▾</span>
            </summary>
            <div className="mt-1">
              <Row
                label="Running requests"
                value={fmt(qwen.running_requests)}
                spark={<Sparkline values={series((s) => s.vllm_qwen?.running_requests)} />}
              />
              <Row
                label="Waiting requests"
                value={fmt(qwen.waiting_requests)}
                spark={<Sparkline values={series((s) => s.vllm_qwen?.waiting_requests)} />}
              />
              <Row
                label="Prefix-cache hit rate"
                value={
                  qwen.gpu_prefix_cache_hit_rate == null
                    ? "n/a"
                    : `${fmtRatioPct(qwen.gpu_prefix_cache_hit_rate, 1)} %`
                }
              />
              <Row
                label="MTP acceptance"
                value={
                  qwen.mtp_acceptance_rate == null
                    ? "MTP off / metric absent"
                    : `${fmtRatioPct(qwen.mtp_acceptance_rate, 1)} %`
                }
                // Same heuristic as VllmPanel: ≥50% reads as healthy MTP. The
                // 20-prompt smoke (2026-05-27) on this build saw 76–83%
                // acceptance against qwen3_5_mtp, so a healthy panel should
                // sit well into the green.
                valueClass={
                  qwen.mtp_acceptance_rate == null
                    ? "text-zinc-600"
                    : qwen.mtp_acceptance_rate >= 0.5
                      ? "text-emerald-400"
                      : "text-amber-400"
                }
                spark={
                  qwen.mtp_acceptance_rate != null ? (
                    <Sparkline values={series((s) => s.vllm_qwen?.mtp_acceptance_rate)} />
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
