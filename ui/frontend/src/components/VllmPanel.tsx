// vLLM internals panel: queue, KV-cache, prefix cache, MTP, decode tok/s.
// See ui_plan.md section 5.3.
import { useEffect, useState, type ReactNode } from "react";
import { getWorkloadHint } from "../api/http";
import { fmt, fmtRatioPct } from "../format";
import type { TelemetrySample, WorkloadHint } from "../types/schemas";
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

// Day-7 UX audit (ui_plan.md r10): the day-1 decode band [80,130] was
// measured with 256-tok completions. A PD workload with ~2 tok/call
// makes the tile read ~11 tok/s by construction. The workload-hint pill
// surfaces that context so the user doesn't read low decode as a bug.
function decodeRegimeColor(regime: WorkloadHint["regime"]): string {
  switch (regime) {
    case "short_completion":
      return "text-zinc-400";       // not a regression — workload-bound
    case "decode_bound":
      return "text-emerald-400";    // day-1 band applies
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

export default function VllmPanel({ samples }: { samples: TelemetrySample[] }) {
  const latest = samples[samples.length - 1] ?? null;
  const vllm = latest?.vllm ?? null;
  const series = (pick: (s: TelemetrySample) => number | null | undefined) =>
    samples.map(pick);

  const [hint, setHint] = useState<WorkloadHint | null>(null);
  useEffect(() => {
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
  }, []);

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          gemma-4-26b-a4b
        </h2>
        <span
          className={`ml-auto font-mono text-[11px] ${
            vllm ? "text-emerald-400" : "text-red-400"
          }`}
          data-testid="vllm-status"
        >
          {vllm ? "● up" : "● down"}
        </span>
      </div>
      {!vllm ? (
        <div className="mt-3 text-sm text-zinc-500">
          vLLM /metrics unavailable — the server may be down or still loading.
        </div>
      ) : (
        <div className="mt-2">
          {/* Core health — always visible: decode tok/s (the throughput
              signal, colored against the workload-aware band) and KV-cache
              headroom (red over 85%). Everything else is operator-grade
              detail behind the disclosure below. */}
          <Row
            label="Decode tok/s"
            value={fmt(vllm.tokens_per_sec_decode, 1)}
            spark={
              <Sparkline
                values={series((s) => s.vllm?.tokens_per_sec_decode)}
                color="#34d399"
                reference={
                  hint?.regime === "decode_bound" ? 40 : undefined
                }
              />
            }
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
          {hint?.available && (
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
                  ~{hint.median_output_tokens} tok/call ·{" "}
                  {hint.calls_per_s} call/s
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
          <details className="mt-2 group" data-testid="vllm-details">
            <summary className="cursor-pointer list-none text-[11px] uppercase tracking-wide text-zinc-500 hover:text-zinc-300">
              <span className="group-open:hidden">show internals ▸</span>
              <span className="hidden group-open:inline">hide internals ▾</span>
            </summary>
            <div className="mt-1">
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
            </div>
          </details>
        </div>
      )}
    </div>
  );
}
