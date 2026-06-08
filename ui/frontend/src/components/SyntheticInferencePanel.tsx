// PAGE A — the inference internals disclosure. Per-worker tokens / tok/s / ETA.
//
// The data.synthetic_inference.synthetic flag is LOAD-BEARING and branches the
// whole presentation (CLAUDE.md rule 4):
//   - synthetic === true  -> the FIXTURE. Amber frame + the verbatim
//     data-testid="synthetic-marker" ("synthetic — needs worker_activity.jsonl
//     (primary-session)") so these numbers are never read as measured. Carries
//     a `decode step` column from the fixture.
//   - synthetic === false -> REAL data from worker_activity.jsonl. Zinc frame,
//     "Inference internals (live)", NO amber marker. Real tok/s + tokens.
// The marker must NEVER appear over real data, and the real framing must NEVER
// appear over the fixture. Split out of the old AgentMonitorPanel.
import { fmt } from "../format";
import type { MonitorResponse } from "../types/activity";

interface SyntheticInferencePanelProps {
  data: MonitorResponse;
}

export default function SyntheticInferencePanel({
  data,
}: SyntheticInferencePanelProps) {
  const syn = data.synthetic_inference;
  // REAL branch: worker_activity.jsonl has recent rows. No amber marker.
  if (!syn.synthetic) {
    return <LiveInferencePanel data={data} />;
  }
  return <SyntheticPanel data={data} />;
}

// REAL — worker_activity.jsonl. No synthetic marker, no decode-step column.
function LiveInferencePanel({ data }: SyntheticInferencePanelProps) {
  const inf = data.synthetic_inference;
  return (
    <details
      className="group rounded border border-zinc-800 bg-zinc-900/40"
      data-testid="synthetic-inference"
      data-synthetic="false"
    >
      <summary className="flex cursor-pointer list-none items-baseline justify-between px-4 py-2.5">
        <span className="text-xs font-medium uppercase tracking-wide text-zinc-300">
          <span className="group-open:hidden">▸ inference internals (live)</span>
          <span className="hidden group-open:inline">
            ▾ inference internals (live)
          </span>
        </span>
        <span
          data-testid="live-inference-marker"
          className="rounded border border-emerald-700/60 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-300"
        >
          live — worker_activity.jsonl
        </span>
      </summary>
      <div className="px-4 pb-4">
        {inf.workers.length === 0 ? (
          <div className="text-sm text-zinc-500">No live workers.</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wide text-zinc-600">
                <th className="pb-1 pr-3 font-normal">task</th>
                <th className="pb-1 pr-3 text-right font-normal">tokens</th>
                <th className="pb-1 pr-3 text-right font-normal">tok/s</th>
                <th className="pb-1 text-right font-normal">eta</th>
              </tr>
            </thead>
            <tbody>
              {inf.workers.map((w) => (
                <tr
                  key={w.task_id}
                  data-testid={`live-worker-${w.task_id}`}
                  className="border-t border-zinc-800/70"
                >
                  <td className="py-1 pr-3 font-mono text-xs text-zinc-300">
                    {w.task_id}
                  </td>
                  <td className="py-1 pr-3 text-right font-mono text-xs text-zinc-400">
                    {w.tokens_generated}/{w.tokens_target}
                  </td>
                  <td className="py-1 pr-3 text-right font-mono text-xs text-zinc-400">
                    {fmt(w.tok_per_s, 1)}
                  </td>
                  <td className="py-1 text-right font-mono text-xs text-zinc-400">
                    {/* Producer writes eta_s=null when tok_per_s is 0; render a
                        bare dash, not "n/as". */}
                    {w.eta_s == null ? "—" : `${fmt(w.eta_s, 1)}s`}
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

// SYNTHETIC — the fixture. The amber data-testid="synthetic-marker" is
// preserved verbatim so the not-measured flag survives the default-collapsed
// state.
function SyntheticPanel({ data }: SyntheticInferencePanelProps) {
  const syn = data.synthetic_inference;
  return (
    <details
      className="group rounded border border-amber-700/50 bg-amber-950/20"
      data-testid="synthetic-inference"
      data-synthetic="true"
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
