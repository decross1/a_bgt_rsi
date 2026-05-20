// Call-chain inspector. ui_plan.md section 5.3. Drives two routes:
//   /chain/:taskId           — dispatch-rooted (day-6 orchestrator)
//   /chain/req/:requestId    — wrapper-rooted (day-4 tool-call chains)
// Both shapes share the ChainResponse contract; the only difference is the
// kind of root node and which fetcher we hit.
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import ChainTree from "../components/ChainTree";
import { getChain, getChainByRequest } from "../api/http";
import type { ChainNode, ChainResponse } from "../types/schemas";

function flatten(node: ChainNode | null): ChainNode[] {
  if (!node) return [];
  return [node, ...node.children.flatMap(flatten)];
}

export default function Inspector() {
  // Either :taskId (dispatch-rooted) or :requestId (wrapper-rooted, day-4).
  const params = useParams<{ taskId?: string; requestId?: string }>();
  const taskId = params.taskId;
  const requestId = params.requestId;
  const rootedAt = taskId ?? requestId ?? "";
  const isByRequest = requestId != null && taskId == null;
  const [data, setData] = useState<ChainResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    if (!rootedAt) return;
    let cancelled = false;
    setData(null);
    setError(null);
    const fetcher = isByRequest ? getChainByRequest : getChain;
    fetcher(rootedAt)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [rootedAt, isByRequest]);

  // Embedded tool nodes are not their own log lines (they live inside a
  // wrapper record), so the raw-JSONL dump skips them to stay 1:1 with the log.
  const rawLines = useMemo(
    () =>
      data
        ? flatten(data.root)
            .filter((n) => !n.embedded)
            .map((n) => JSON.stringify(n.raw))
        : [],
    [data],
  );

  if (error) {
    return (
      <div className="mx-auto max-w-4xl p-6">
        <div className="rounded border border-red-900 bg-red-950/50 p-4 text-red-300">
          Could not load chain for <span className="font-mono">{rootedAt}</span>: {error}
        </div>
      </div>
    );
  }
  if (!data) {
    return <div className="p-6 text-zinc-400">Loading {rootedAt}…</div>;
  }

  const rootedLabel = data.task_id ?? data.root_request_id ?? rootedAt;
  const malformedToolCount = data.malformed_tool_calls ?? 0;

  return (
    <div className="mx-auto max-w-4xl p-6">
      <h1 className="font-mono text-lg text-zinc-100">{rootedLabel}</h1>
      <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm text-zinc-400">
        <span>{data.node_count} nodes</span>
        <span>{data.total_latency_ms} ms total (sum of call latencies)</span>
        {data.root?.task_type && <span>type: {data.root.task_type}</span>}
        {data.root?.status && <span>status: {data.root.status}</span>}
        {isByRequest && (
          <span className="rounded bg-zinc-800 px-2 py-0.5 text-xs text-zinc-300">
            day-4 chain (wrapper-rooted)
          </span>
        )}
      </div>
      {malformedToolCount > 0 && (
        <div
          data-testid="malformed-tool-banner"
          className="mt-3 rounded border border-red-900 bg-red-950/60 p-3 text-sm text-red-200"
        >
          <span className="font-medium">Malformed tool_calls detected.</span>{" "}
          {malformedToolCount} node{malformedToolCount === 1 ? "" : "s"} in this
          chain carry a tool_calls payload that is not a JSON array. The inspector
          surfaces the raw record as stored — it does not silently format-fix.
        </div>
      )}
      {data.malformed && (
        <div className="mt-3 rounded border border-amber-900 bg-amber-950/50 p-2 text-sm text-amber-300">
          This chain is malformed — a parent_request_id cycle was detected and the
          walk stopped early.
        </div>
      )}
      <div className="mt-4 rounded border border-zinc-800 bg-zinc-900/40 p-3">
        {data.root ? (
          <ChainTree root={data.root} />
        ) : (
          <div className="text-zinc-500">empty chain</div>
        )}
      </div>
      <button
        onClick={() => setShowRaw((v) => !v)}
        className="mt-4 rounded border border-zinc-700 px-3 py-1 text-sm text-zinc-300 hover:bg-zinc-800"
      >
        {showRaw ? "hide" : "show"} raw JSONL ({rawLines.length} lines)
      </button>
      {showRaw && (
        <pre className="mt-2 max-h-96 overflow-auto rounded bg-zinc-950 p-3 text-xs text-zinc-400">
          {rawLines.join("\n")}
        </pre>
      )}
    </div>
  );
}
