// vLLM internals panel: queue, KV-cache, prefix cache, MTP, decode tok/s.
// See ui_plan.md section 5.3.
import type { ReactNode } from "react";
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

export default function VllmPanel({ samples }: { samples: TelemetrySample[] }) {
  const latest = samples[samples.length - 1] ?? null;
  const vllm = latest?.vllm ?? null;
  const series = (pick: (s: TelemetrySample) => number | null | undefined) =>
    samples.map(pick);

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
      <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
        vLLM internals
      </h2>
      {!vllm ? (
        <div className="mt-3 text-sm text-zinc-500">
          vLLM /metrics unavailable — the server may be down or still loading.
        </div>
      ) : (
        <div className="mt-2">
          <Row
            label="Running requests"
            value={fmt(vllm.running_requests)}
            spark={<Sparkline values={series((s) => s.vllm?.running_requests)} />}
          />
          <Row
            label="Waiting requests"
            value={fmt(vllm.waiting_requests)}
            spark={<Sparkline values={series((s) => s.vllm?.waiting_requests)} />}
          />
          <Row
            label="KV-cache usage"
            value={`${fmt(vllm.gpu_cache_usage_pct, 1)} %`}
            valueClass={
              vllm.gpu_cache_usage_pct > 85 ? "text-red-400" : "text-zinc-100"
            }
            spark={
              <Sparkline
                values={series((s) => s.vllm?.gpu_cache_usage_pct)}
                color="#38bdf8"
              />
            }
          />
          <Row
            label="Prefix-cache hit rate"
            value={
              vllm.gpu_prefix_cache_hit_rate == null
                ? "n/a"
                : `${fmtRatioPct(vllm.gpu_prefix_cache_hit_rate, 1)} %`
            }
          />
          <Row
            label="MTP acceptance"
            value={
              vllm.mtp_acceptance_rate == null
                ? "MTP off / metric absent"
                : `${fmtRatioPct(vllm.mtp_acceptance_rate, 1)} %`
            }
            // Chosen heuristic: ≥50% draft-token acceptance reads as healthy
            // MTP, below it as poor (decode tok/s then suffers). ui_plan.md
            // §5.3 says to color "against the baseline card's expected range",
            // but the card has no acceptance-rate row — so this threshold is
            // ours, not the plan's. Open question in ui/notes/ui-build.md.
            valueClass={
              vllm.mtp_acceptance_rate == null
                ? "text-zinc-600"
                : vllm.mtp_acceptance_rate >= 0.5
                  ? "text-emerald-400"
                  : "text-amber-400"
            }
            spark={
              vllm.mtp_acceptance_rate != null ? (
                <Sparkline values={series((s) => s.vllm?.mtp_acceptance_rate)} />
              ) : undefined
            }
          />
          <Row
            label="Decode tok/s"
            value={fmt(vllm.tokens_per_sec_decode, 1)}
            spark={
              <Sparkline
                values={series((s) => s.vllm?.tokens_per_sec_decode)}
                color="#34d399"
                reference={40}
              />
            }
          />
        </div>
      )}
    </div>
  );
}
