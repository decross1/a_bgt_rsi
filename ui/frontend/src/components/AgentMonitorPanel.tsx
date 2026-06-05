// PAGE A — agent-activity side panel. Two sections:
//  (1) "Active now": orchestrator dispatches still in flight, with cpu/rss
//      cross-referenced from the latest telemetry sample.
//  (2) "Inference internals": per-worker decode-step / tokens / ETA. These
//      are SYNTHETIC (no on-disk source yet) — rendered behind a visible
//      "synthetic — needs worker_activity.jsonl (primary-session)" marker
//      so they are never read as measured numbers (CLAUDE.md rule 4).
import { fmt } from "../format";
import type { MonitorResponse, MonitorWorker } from "../types/activity";

const STATUS_TONE: Record<string, string> = {
  running: "text-sky-300",
  dispatched: "text-sky-300",
  started: "text-sky-300",
  passed: "text-emerald-400",
  failed: "text-red-400",
  error: "text-red-400",
};

function statusTone(status: string | null): string {
  return STATUS_TONE[status ?? ""] ?? "text-zinc-300";
}

function WorkerRow({ w }: { w: MonitorWorker }) {
  return (
    <tr data-testid={`worker-${w.task_id}`} className="border-t border-zinc-800/70">
      <td className="py-1 pr-3 font-mono text-xs text-zinc-300">{w.task_id ?? "—"}</td>
      <td className="py-1 pr-3 text-xs text-zinc-400">{w.task_type ?? "—"}</td>
      <td className={`py-1 pr-3 text-xs ${statusTone(w.status)}`}>
        ● {w.status ?? "—"}
      </td>
      <td className="py-1 pr-3 text-right font-mono text-xs text-zinc-400">
        {w.worker_pid ?? "—"}
      </td>
      <td className="py-1 pr-3 text-right font-mono text-xs text-zinc-400">
        {w.cpu_pct == null ? "—" : `${fmt(w.cpu_pct, 1)}%`}
      </td>
      <td className="py-1 text-right font-mono text-xs text-zinc-400">
        {w.rss_mb == null ? "—" : `${fmt(w.rss_mb, 0)} MB`}
      </td>
    </tr>
  );
}

interface AgentMonitorPanelProps {
  data: MonitorResponse;
}

export default function AgentMonitorPanel({ data }: AgentMonitorPanelProps) {
  if (!data.available) {
    return (
      <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-500">
        Agent monitor unavailable
        {data.reason ? <span className="text-zinc-600"> — {data.reason}</span> : null}
      </div>
    );
  }

  const syn = data.synthetic_inference;
  const telemetryMissing = data.telemetry_available === false;

  return (
    <div className="space-y-4">
      <section className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
        <div className="mb-2 flex items-baseline justify-between">
          <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-400">
            Active now
          </h2>
          <span className="text-xs text-zinc-600">
            {data.active.length} in flight
          </span>
        </div>
        {telemetryMissing && (
          <div className="mb-2 text-xs text-amber-500/80" data-testid="telemetry-missing">
            process metrics unavailable — telemetry sample has no processes[]
          </div>
        )}
        {data.active.length === 0 ? (
          <div className="text-sm text-zinc-500">No workers in flight.</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wide text-zinc-600">
                <th className="pb-1 pr-3 font-normal">task</th>
                <th className="pb-1 pr-3 font-normal">type</th>
                <th className="pb-1 pr-3 font-normal">status</th>
                <th className="pb-1 pr-3 text-right font-normal">pid</th>
                <th className="pb-1 pr-3 text-right font-normal">cpu</th>
                <th className="pb-1 text-right font-normal">rss</th>
              </tr>
            </thead>
            <tbody>
              {data.active.map((w) => (
                <WorkerRow key={w.task_id ?? Math.random()} w={w} />
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section
        className="rounded border border-amber-700/50 bg-amber-950/20 p-4"
        data-testid="synthetic-inference"
      >
        <div className="mb-2 flex items-baseline justify-between">
          <h2 className="text-xs font-medium uppercase tracking-wide text-amber-300/90">
            Inference internals
          </h2>
          <span
            data-testid="synthetic-marker"
            className="rounded border border-amber-600/60 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-300"
          >
            synthetic — needs worker_activity.jsonl (primary-session)
          </span>
        </div>
        <p className="mb-2 text-xs text-amber-200/70">{syn.note}</p>
        {syn.workers.length === 0 ? (
          <div className="text-sm text-zinc-500">No synthetic workers.</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wide text-amber-200/50">
                <th className="pb-1 pr-3 font-normal">task</th>
                <th className="pb-1 pr-3 text-right font-normal">decode step</th>
                <th className="pb-1 pr-3 text-right font-normal">tokens</th>
                <th className="pb-1 pr-3 text-right font-normal">tok/s</th>
                <th className="pb-1 text-right font-normal">eta</th>
              </tr>
            </thead>
            <tbody>
              {syn.workers.map((w) => (
                <tr
                  key={w.task_id}
                  data-testid={`synthetic-worker-${w.task_id}`}
                  className="border-t border-amber-900/40"
                >
                  <td className="py-1 pr-3 font-mono text-xs text-amber-200/80">
                    {w.task_id}
                  </td>
                  <td className="py-1 pr-3 text-right font-mono text-xs text-amber-200/70">
                    {w.decode_step}
                  </td>
                  <td className="py-1 pr-3 text-right font-mono text-xs text-amber-200/70">
                    {w.tokens_generated}/{w.tokens_target}
                  </td>
                  <td className="py-1 pr-3 text-right font-mono text-xs text-amber-200/70">
                    {fmt(w.tok_per_s, 1)}
                  </td>
                  <td className="py-1 text-right font-mono text-xs text-amber-200/70">
                    {fmt(w.eta_s, 1)}s
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
