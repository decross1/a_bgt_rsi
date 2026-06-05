// PAGE A — live wrapper-call banner. The run-mode-agnostic "something is
// happening right now" signal: when /api/activity/monitor reports recent calls
// in the call log (live_calls.active), the apparatus is working even if no
// orchestrator task and no loop iteration is registered — e.g. a raw
// experiment driver (exp005/run.py) calling nara.run_iteration directly. This
// is exactly the case that used to leave /activity blank during a live run.
import { elapsed, useNow } from "../time";
import type { LiveCalls } from "../types/activity";

export default function LiveCallsBanner({ data }: { data: LiveCalls }) {
  const now = useNow();
  if (!data.active) return null;
  const tags = data.caller_tags.map((t) => t.tag).join(", ");
  return (
    <div
      data-testid="live-calls-banner"
      className="rounded border border-emerald-800/50 bg-emerald-950/20 p-3 text-xs text-emerald-300"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-medium">
          ● live — {data.count} call{data.count === 1 ? "" : "s"} in last{" "}
          {data.window_s}s
          {data.calls_per_s != null ? ` (~${data.calls_per_s}/s)` : ""}
        </span>
        {tags && <span className="font-mono text-emerald-400/80">{tags}</span>}
        {data.model && (
          <span className="font-mono text-emerald-400/60">{data.model}</span>
        )}
        {data.last_call_at && (
          <span className="text-emerald-500/70">
            last call {elapsed(data.last_call_at, now)} ago
          </span>
        )}
      </div>
      <div className="mt-0.5 text-emerald-500/60">
        wrapper-call activity — this run isn't dispatching through the
        orchestrator or the loop, so there are no per-task rows below.
      </div>
    </div>
  );
}
