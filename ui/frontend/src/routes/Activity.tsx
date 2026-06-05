// PAGE A (/activity) — Activity Graph + Agent Monitor.
// Left: the orchestrator -> worker -> wrapper -> tool causal graph (one node
// per task in "overview", whole chain in "full"). Right: the agent-activity
// panel (active workers + synthetic inference).
//
// IMPORTANT framing: the graph shows the most RECENT orchestrator dispatches,
// which are usually historical (completed) runs — not necessarily live. The
// status strip makes "active now" vs "recent history" explicit so an idle
// apparatus does not look like it is running. Monitor polls at 1 Hz; the
// (heavier, slower-changing) graph at 5 s, with change-detection so react-flow
// only relayouts when the graph actually changed.
import { useEffect, useRef, useState } from "react";
import ActivityGraph from "../components/ActivityGraph";
import AgentMonitorPanel from "../components/AgentMonitorPanel";
import { getActivityGraph, getActivityMonitor } from "../api/activity";
import type {
  ActivityGraphResponse,
  MonitorResponse,
} from "../types/activity";

interface ActivityProps {
  initialGraph?: ActivityGraphResponse;
  initialMonitor?: MonitorResponse;
}

type Detail = "overview" | "full";

const GRAPH_POLL_MS = 5000;
const MONITOR_POLL_MS = 1000;

export default function Activity({
  initialGraph,
  initialMonitor,
}: ActivityProps) {
  const [graph, setGraph] = useState<ActivityGraphResponse | null>(
    initialGraph ?? null,
  );
  const [monitor, setMonitor] = useState<MonitorResponse | null>(
    initialMonitor ?? null,
  );
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail>("overview");
  // Last graph content signature — skip setGraph (and the react-flow
  // relayout it triggers) when nothing structural changed between polls.
  const graphSig = useRef<string>("");

  // When fixtures are injected, do not poll — the page is static for tests.
  const live = initialGraph === undefined && initialMonitor === undefined;

  useEffect(() => {
    if (!live) return;
    let cancelled = false;
    graphSig.current = ""; // detail changed — force the next graph to apply

    const pollGraph = () => {
      getActivityGraph(detail)
        .then((g) => {
          if (cancelled) return;
          const sig = JSON.stringify({ d: g.detail, n: g.nodes, e: g.edges });
          if (sig !== graphSig.current) {
            graphSig.current = sig;
            setGraph(g);
          }
        })
        .catch((e) => !cancelled && setError(String(e)));
    };
    const pollMonitor = () => {
      getActivityMonitor()
        .then((m) => !cancelled && setMonitor(m))
        .catch((e) => !cancelled && setError(String(e)));
    };

    pollGraph();
    pollMonitor();
    const gid = setInterval(pollGraph, GRAPH_POLL_MS);
    const mid = setInterval(pollMonitor, MONITOR_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(gid);
      clearInterval(mid);
    };
  }, [live, detail]);

  const activeCount = monitor?.active.length ?? 0;

  return (
    <div className="mx-auto w-full max-w-[1800px] px-6 py-5">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="font-mono text-sm text-zinc-200">activity</h1>
        <div className="flex items-center gap-3">
          <DetailToggle value={detail} onChange={setDetail} />
          <span className="text-xs text-zinc-600">
            monitor 1 Hz · graph 5 s
          </span>
        </div>
      </div>

      {/* Live-vs-history status strip. */}
      {monitor && (
        <div
          data-testid="activity-status"
          className={`mt-3 rounded border px-3 py-2 text-xs ${
            activeCount > 0
              ? "border-emerald-800/50 bg-emerald-950/20 text-emerald-300"
              : "border-zinc-800 bg-zinc-900/40 text-zinc-400"
          }`}
        >
          {activeCount > 0 ? (
            <>
              <span className="font-medium text-emerald-300">
                {activeCount} task{activeCount === 1 ? "" : "s"} active now.
              </span>{" "}
              Graph and monitor are live.
            </>
          ) : (
            <>
              <span className="font-medium text-zinc-300">Idle</span> — nothing
              running right now. The graph below shows the most recent task
              chains (history), not live activity.
            </>
          )}
        </div>
      )}

      {error && (
        <div className="mt-2 text-xs text-red-400" data-testid="activity-error">
          {error}
        </div>
      )}

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-4">
        <div className="xl:col-span-3">
          {graph ? (
            <ActivityGraph data={graph} />
          ) : (
            <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-500">
              Loading activity graph…
            </div>
          )}
        </div>
        <div>
          {monitor ? (
            <AgentMonitorPanel data={monitor} />
          ) : (
            <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-500">
              Loading agent monitor…
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DetailToggle({
  value,
  onChange,
}: {
  value: Detail;
  onChange: (d: Detail) => void;
}) {
  const opts: { key: Detail; label: string; title: string }[] = [
    { key: "overview", label: "overview", title: "one node per task" },
    { key: "full", label: "full chain", title: "expand each task's calls" },
  ];
  return (
    <div
      className="flex overflow-hidden rounded border border-zinc-800"
      data-testid="detail-toggle"
    >
      {opts.map((o) => (
        <button
          key={o.key}
          type="button"
          title={o.title}
          onClick={() => onChange(o.key)}
          className={`px-2 py-0.5 font-mono text-xs ${
            value === o.key
              ? "bg-zinc-800 text-zinc-100"
              : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
