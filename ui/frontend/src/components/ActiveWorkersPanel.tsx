// PAGE A — the HERO active-worker view. Rich rows for orchestrator dispatches
// still in flight: task_id, task_type, status (statusTone), `detail` ("what
// it's doing"), LIVE elapsed since the row's timestamp, and cpu/rss from the
// latest telemetry sample. Split out of the old AgentMonitorPanel so the live
// workers are the focal element on /activity, not a cramped sidebar.
//
// The {available:false} degrade path is preserved here: when the monitor
// source is absent the panel renders the unavailable notice rather than 500.
import { fmt } from "../format";
import { elapsed, useNow } from "../time";
import type { MonitorResponse, MonitorWorker } from "../types/activity";

const STATUS_TONE: Record<string, string> = {
  running: "text-sky-300",
  dispatched: "text-sky-300",
  started: "text-sky-300",
  passed: "text-emerald-400",
  failed: "text-red-400",
  error: "text-red-400",
};

export function statusTone(status: string | null): string {
  return STATUS_TONE[status ?? ""] ?? "text-zinc-300";
}

function WorkerRow({ w, now }: { w: MonitorWorker; now: number }) {
  return (
    <tr data-testid={`worker-${w.task_id}`} className="border-t border-zinc-800/70 align-top">
      <td className="py-1.5 pr-3 font-mono text-xs text-zinc-300">{w.task_id ?? "—"}</td>
      <td className="py-1.5 pr-3 text-xs text-zinc-400">{w.task_type ?? "—"}</td>
      <td className={`py-1.5 pr-3 text-xs ${statusTone(w.status)}`}>
        ● {w.status ?? "—"}
      </td>
      {/* "what it's doing" — the human-readable orchestrator detail. */}
      <td
        className="py-1.5 pr-3 text-xs text-zinc-400"
        data-testid={`worker-detail-${w.task_id}`}
      >
        {w.detail ?? "—"}
      </td>
      {/* LIVE elapsed since the row's stage timestamp. */}
      <td
        className="py-1.5 pr-3 text-right font-mono text-xs text-zinc-300"
        data-testid={`worker-elapsed-${w.task_id}`}
      >
        {elapsed(w.timestamp, now)}
      </td>
      <td className="py-1.5 pr-3 text-right font-mono text-xs text-zinc-400">
        {w.cpu_pct == null ? "—" : `${fmt(w.cpu_pct, 1)}%`}
      </td>
      <td className="py-1.5 text-right font-mono text-xs text-zinc-400">
        {w.rss_mb == null ? "—" : `${fmt(w.rss_mb, 0)} MB`}
      </td>
    </tr>
  );
}

interface ActiveWorkersPanelProps {
  data: MonitorResponse;
}

// Live-call groups whose caller_tag starts with "subagent." — sub-agents run
// OUTSIDE the orchestrator's worker dispatch, so an empty workers table while
// they call is "no ORCHESTRATOR workers", not "nothing running". Producer-
// shaped: a malformed groups array / element / tag contributes nothing.
function subagentGroupCount(data: MonitorResponse): number {
  const groups = data.live_calls?.groups;
  if (!Array.isArray(groups)) return 0;
  let n = 0;
  for (const g of groups) {
    if (g == null || typeof g !== "object") continue;
    const tag = (g as { tag?: unknown }).tag;
    if (typeof tag === "string" && tag.startsWith("subagent.")) n += 1;
  }
  return n;
}

export default function ActiveWorkersPanel({ data }: ActiveWorkersPanelProps) {
  const now = useNow();

  if (!data.available) {
    return (
      <div
        className="rounded border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-500"
        data-testid="active-workers-unavailable"
      >
        Agent monitor unavailable
        {data.reason ? <span className="text-zinc-600"> — {data.reason}</span> : null}
      </div>
    );
  }

  const telemetryMissing = data.telemetry_available === false;

  return (
    <section
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="active-workers-panel"
    >
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-400">
          Active workers
        </h2>
        <span className="text-xs text-zinc-600">{data.active.length} in flight</span>
      </div>
      {telemetryMissing && (
        <div className="mb-2 text-xs text-amber-500/80" data-testid="telemetry-missing">
          process metrics unavailable — telemetry sample has no processes[]
        </div>
      )}
      {data.active.length === 0 ? (
        // When sub-agent call groups are live (caller_tag "subagent.*"), an
        // empty ORCHESTRATOR table must not read as a quiet machine — the
        // sub-agents bypass worker dispatch and show in the live calls above.
        <div className="text-sm text-zinc-500" data-testid="active-workers-empty">
          {(() => {
            const n = subagentGroupCount(data);
            return n > 0
              ? `No orchestrator workers in flight — ${n} sub-agent call group${
                  n === 1 ? "" : "s"
                } active (see live calls)`
              : "No workers in flight.";
          })()}
        </div>
      ) : (
        <table className="w-full">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wide text-zinc-600">
              <th className="pb-1 pr-3 font-normal">task</th>
              <th className="pb-1 pr-3 font-normal">type</th>
              <th className="pb-1 pr-3 font-normal">status</th>
              <th className="pb-1 pr-3 font-normal">doing</th>
              <th className="pb-1 pr-3 text-right font-normal">elapsed</th>
              <th className="pb-1 pr-3 text-right font-normal">cpu</th>
              <th className="pb-1 text-right font-normal">rss</th>
            </tr>
          </thead>
          <tbody>
            {data.active.map((w, i) => (
              // Stable key: fall back to the row index, never Math.random()
              // — the panel ticks at 1 Hz (useNow), and a fresh random key
              // each tick would remount any null-task_id row (DOM thrash /
              // lost focus / flicker).
              <WorkerRow key={w.task_id ?? `idx-${i}`} w={w} now={now} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
