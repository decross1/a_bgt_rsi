// Per-process cards for the tracked PID set. See ui_plan.md section 5.3.
import { fmt } from "../format";
import type { TelemetrySample } from "../types/schemas";
import Sparkline from "./Sparkline";

export default function ProcessGrid({ samples }: { samples: TelemetrySample[] }) {
  const latest = samples[samples.length - 1] ?? null;
  const processes = latest?.processes ?? [];

  if (processes.length === 0) {
    return (
      <div className="rounded border border-zinc-800 bg-zinc-900/40 p-3 text-sm text-zinc-500">
        No tracked processes — the vLLM container, orchestrator, workers, and
        ChromaDB are not currently detected.
      </div>
    );
  }

  const sorted = [...processes].sort((a, b) => b.rss_mb - a.rss_mb);

  return (
    <div className="grid grid-cols-4 gap-3">
      {sorted.map((proc) => {
        const cpuSeries = samples.map(
          (s) => s.processes.find((p) => p.pid === proc.pid)?.cpu_pct,
        );
        return (
          <div
            key={proc.pid}
            className="rounded border border-zinc-800 bg-zinc-900/40 p-3"
          >
            <div className="truncate font-mono text-sm text-zinc-100">
              {proc.name}
            </div>
            <div className="text-xs text-zinc-500">pid {proc.pid}</div>
            <div className="mt-1 flex justify-between text-xs tabular-nums text-zinc-400">
              <span>CPU {fmt(proc.cpu_pct)}%</span>
              <span>{fmt(proc.rss_mb)} MiB</span>
              <span>{proc.threads} thr</span>
            </div>
            <div className="mt-1">
              <Sparkline values={cpuSeries} width={180} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
