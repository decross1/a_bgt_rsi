// Day-4 robustness panel: invocation rate, per-trial outcomes, median
// latency from logs/day4_robust.jsonl. ui_plan.md section 5.3 style: numbers
// and text, no decorative gauges. Polls /api/robustness every 5 s.
import { useEffect, useState } from "react";
import { getRobustness } from "../api/http";
import type { RobustnessResponse, RobustnessTrial } from "../types/schemas";

function outcomeClass(outcome: string | undefined): string {
  switch (outcome) {
    case "ok":
      return "text-emerald-400";
    case "timeout":
      return "text-amber-400";
    case "missed":
    case "malformed":
    case "error":
      return "text-red-400";
    default:
      return "text-zinc-500";
  }
}

function TrialRow({ trial }: { trial: RobustnessTrial }) {
  return (
    <tr className="border-t border-zinc-800/60">
      <td className="px-2 py-1 font-mono text-zinc-400">
        {trial.caller_tag ?? trial.trial_id ?? "—"}
      </td>
      <td className="px-2 py-1">
        <span className={trial.invoked ? "text-zinc-200" : "text-zinc-600"}>
          {trial.invoked ? "yes" : "no"}
        </span>
      </td>
      <td className={`px-2 py-1 ${outcomeClass(trial.outcome)}`}>
        {trial.outcome ?? "—"}
      </td>
      <td className="px-2 py-1 text-right font-mono text-zinc-300">
        {typeof trial.latency_ms === "number" ? `${trial.latency_ms} ms` : "—"}
      </td>
    </tr>
  );
}

export default function RobustnessPanel() {
  const [data, setData] = useState<RobustnessResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = () =>
      getRobustness()
        .then((d) => {
          if (!active) return;
          setData(d);
          setError(null);
        })
        .catch((e) => {
          if (active) setError(String(e));
        });
    load();
    const id = setInterval(load, 5000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
      <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
        Robustness sweep
      </h2>
      {error && <div className="mt-2 text-sm text-red-400">{error}</div>}
      {data && !data.available && (
        <div className="mt-2 text-sm text-zinc-500">
          logs/day4_robust.jsonl is not present yet — the apparatus has not run the day-4 sweep.
        </div>
      )}
      {data && data.available && (
        <>
          <div className="mt-2 grid grid-cols-3 gap-3 text-sm">
            <div>
              <div className="text-xs uppercase tracking-wide text-zinc-500">
                Invocation rate
              </div>
              <div className="font-mono text-zinc-100">
                {data.invocation_rate != null
                  ? `${(data.invocation_rate * 100).toFixed(1)}%`
                  : "—"}
                <span className="ml-2 text-xs text-zinc-500">
                  {data.invocations}/{data.trial_count}
                </span>
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-zinc-500">
                Median latency
              </div>
              <div className="font-mono text-zinc-100">
                {data.median_latency_ms != null
                  ? `${data.median_latency_ms} ms`
                  : "—"}
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-zinc-500">
                Outcomes
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
                {Object.entries(data.outcomes).map(([outcome, count]) => (
                  <span key={outcome} className={outcomeClass(outcome)}>
                    {outcome}: <span className="font-mono">{count}</span>
                  </span>
                ))}
              </div>
            </div>
          </div>
          {data.trials.length > 0 && (
            <div className="mt-3 max-h-56 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="text-zinc-500">
                  <tr>
                    <th className="px-2 py-1 text-left font-normal">run</th>
                    <th className="px-2 py-1 text-left font-normal">invoked</th>
                    <th className="px-2 py-1 text-left font-normal">outcome</th>
                    <th className="px-2 py-1 text-right font-normal">latency</th>
                  </tr>
                </thead>
                <tbody>
                  {data.trials.map((t, i) => (
                    <TrialRow key={t.trial_id ?? i} trial={t} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
