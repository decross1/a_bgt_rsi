// PAGE A — the synthetic inference internals, SUBORDINATE. Per-worker
// decode-step / tokens / ETA have no on-disk source yet; they live behind a
// ▸/▾ <details> disclosure (collapsed by default) so they read as a secondary
// reference, not co-equal with the real active-worker data. The amber
// data-testid="synthetic-marker" ("synthetic — needs worker_activity.jsonl")
// is preserved verbatim so these numbers are never read as measured
// (CLAUDE.md rule 4). Split out of the old AgentMonitorPanel.
import { fmt } from "../format";
import type { MonitorResponse } from "../types/activity";

interface SyntheticInferencePanelProps {
  data: MonitorResponse;
}

export default function SyntheticInferencePanel({
  data,
}: SyntheticInferencePanelProps) {
  // Nothing to subordinate when the monitor is unavailable — the synthetic
  // block is still carried on that payload, but the active-workers panel owns
  // the unavailable notice. Render the disclosure either way so the marker is
  // always reachable.
  const syn = data.synthetic_inference;

  return (
    <details
      className="group rounded border border-amber-700/50 bg-amber-950/20"
      data-testid="synthetic-inference"
    >
      <summary className="flex cursor-pointer list-none items-baseline justify-between px-4 py-2.5">
        <span className="text-xs font-medium uppercase tracking-wide text-amber-300/90">
          <span className="group-open:hidden">▸ inference internals</span>
          <span className="hidden group-open:inline">▾ inference internals</span>
        </span>
        <span
          data-testid="synthetic-marker"
          className="rounded border border-amber-600/60 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-300"
        >
          synthetic — needs worker_activity.jsonl (primary-session)
        </span>
      </summary>
      <div className="px-4 pb-4">
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
      </div>
    </details>
  );
}
