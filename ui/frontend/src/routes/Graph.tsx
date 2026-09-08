// PAGE /graph — thin page for the recent-history react-flow graph (UI
// simplification S3: ActivityGraph survives the /activity deletion as its own
// engine-nav destination). The data fetch is ported from the old Activity
// page: poll getActivityGraph(detail) at 5 s with change-detection so
// react-flow only relayouts when the graph actually changed.
import { useEffect, useRef, useState } from "react";
import ActivityGraph from "../components/ActivityGraph";
import { getActivityGraph } from "../api/activity";
import type { ActivityGraphResponse } from "../types/activity";

type Detail = "overview" | "full";

const GRAPH_POLL_MS = 5000;

interface GraphProps {
  // Tests inject the graph so the page renders synchronously with no poll.
  initialGraph?: ActivityGraphResponse;
}

export default function Graph({ initialGraph }: GraphProps) {
  const [graph, setGraph] = useState<ActivityGraphResponse | null>(
    initialGraph ?? null,
  );
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail>("overview");
  // Last graph content signature — skip setGraph (and the react-flow
  // relayout it triggers) when nothing structural changed between polls.
  const graphSig = useRef<string>("");
  const live = initialGraph === undefined;

  useEffect(() => {
    if (!live) return;
    let cancelled = false;
    graphSig.current = ""; // detail changed — force the next graph to apply
    const poll = () => {
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
    poll();
    const id = setInterval(poll, GRAPH_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [live, detail]);

  return (
    <div className="mx-auto w-full max-w-[1800px] px-6 py-5">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="font-mono text-sm text-zinc-200">graph</h1>
        <div className="flex items-baseline gap-3">
          <span className="text-xs text-zinc-600">recent task history · 5 s</span>
          <DetailToggle value={detail} onChange={setDetail} />
        </div>
      </div>
      {error && (
        <div className="mt-2 text-xs text-red-400" data-testid="graph-error">
          {error}
        </div>
      )}
      <div className="mt-3">
        {graph ? (
          <ActivityGraph data={graph} />
        ) : (
          <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-500">
            Loading activity graph…
          </div>
        )}
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
