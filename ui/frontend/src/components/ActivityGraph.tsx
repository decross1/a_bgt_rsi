// PAGE A — the orchestrator -> worker -> wrapper -> tool causal graph.
// Renders the flattened node/edge list from /api/activity/graph with
// @xyflow/react. Clicking a node that carries a real request_id deep-links
// into the existing inspector at /chain/req/:requestId. Synthesized tool
// nodes (request_id === null) are NOT linkable.
//
// The per-node cell is factored out as `GraphNodeCell` so its color tone
// and deep-link behavior are unit-testable directly — @xyflow/react does
// not render custom node labels under jsdom (no ResizeObserver / layout),
// so the graph wrapper itself is smoke-tested while the cell carries the
// asserted color + link contract.
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  Background,
  Controls,
  Position,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type {
  ActivityEdge,
  ActivityGraphResponse,
  ActivityNode,
} from "../types/activity";

// Tone -> tailwind text + border classes (dark-mode tokens).
const STATUS_CLASS: Record<string, string> = {
  active: "border-sky-500 text-sky-300",
  ok: "border-emerald-600 text-emerald-300",
  error: "border-red-600 text-red-300",
  unknown: "border-zinc-600 text-zinc-300",
};

export function statusClass(status: string | null | undefined): string {
  return STATUS_CLASS[status ?? "unknown"] ?? STATUS_CLASS.unknown;
}

const KIND_PREFIX: Record<string, string> = {
  dispatch: "▢",
  call: "→",
  tool: "·",
};

/** One node cell: color by status, deep-link by request_id. A node with
 * a null request_id (synthesized tool node) is not clickable. */
export function GraphNodeCell({
  node,
  onOpen,
}: {
  node: ActivityNode;
  onOpen?: (requestId: string) => void;
}) {
  const linkable = Boolean(node.request_id);
  return (
    <button
      type="button"
      data-testid={`node-${node.id}`}
      data-kind={node.kind}
      data-linkable={linkable ? "true" : "false"}
      data-request-id={node.request_id ?? ""}
      disabled={!linkable}
      onClick={() => {
        if (node.request_id && onOpen) onOpen(node.request_id);
      }}
      className={`rounded border bg-zinc-900/80 px-2 py-1 text-left font-mono text-[11px] ${statusClass(
        node.status,
      )} ${linkable ? "cursor-pointer" : "cursor-default opacity-90"}`}
      title={
        linkable
          ? `open chain /chain/req/${node.request_id}`
          : "synthesized node — no request_id to inspect"
      }
    >
      <span className="text-zinc-500">{KIND_PREFIX[node.kind] ?? ""}</span>{" "}
      {node.label}
      <span className="ml-1 text-zinc-600">{node.kind}</span>
    </button>
  );
}

// Position every node so the graph fills the canvas instead of stacking in
// one column. Two regimes:
//   - no edges (the "overview": independent task nodes) -> a balanced grid.
//   - with edges (the "full" tree) -> layered left-to-right by BFS depth, so
//     a deep call chain spreads across the width rather than down a ribbon.
function computeLayout(
  nodes: ActivityNode[],
  edges: ActivityEdge[],
): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>();

  if (edges.length === 0) {
    const cols = Math.max(1, Math.ceil(Math.sqrt(nodes.length)));
    const COL_W = 240;
    const ROW_H = 88;
    nodes.forEach((n, i) => {
      pos.set(n.id, { x: (i % cols) * COL_W, y: Math.floor(i / cols) * ROW_H });
    });
    return pos;
  }

  // BFS depth from roots (nodes with no incoming edge).
  const children = new Map<string, string[]>();
  const indeg = new Map<string, number>();
  nodes.forEach((n) => indeg.set(n.id, 0));
  edges.forEach((e) => {
    (children.get(e.source) ?? children.set(e.source, []).get(e.source)!).push(
      e.target,
    );
    indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1);
  });
  const depth = new Map<string, number>();
  const queue: string[] = [];
  nodes.forEach((n) => {
    if ((indeg.get(n.id) ?? 0) === 0) {
      depth.set(n.id, 0);
      queue.push(n.id);
    }
  });
  if (queue.length === 0 && nodes.length) {
    depth.set(nodes[0].id, 0); // all-cycle fallback — seed one root
    queue.push(nodes[0].id);
  }
  while (queue.length) {
    const id = queue.shift()!;
    const d = depth.get(id) ?? 0;
    for (const c of children.get(id) ?? []) {
      if (!depth.has(c)) {
        depth.set(c, d + 1);
        queue.push(c);
      }
    }
  }
  const COL_W = 300;
  const ROW_H = 70;
  const rowByDepth = new Map<number, number>();
  nodes.forEach((n) => {
    const d = depth.get(n.id) ?? 0;
    const row = rowByDepth.get(d) ?? 0;
    rowByDepth.set(d, row + 1);
    pos.set(n.id, { x: d * COL_W, y: row * ROW_H });
  });
  return pos;
}

function toFlowNodes(
  nodes: ActivityNode[],
  edges: ActivityEdge[],
  onOpen: (requestId: string) => void,
): Node[] {
  const pos = computeLayout(nodes, edges);
  return nodes.map((n) => ({
    id: n.id,
    position: pos.get(n.id) ?? { x: 0, y: 0 },
    data: { label: <GraphNodeCell node={n} onOpen={onOpen} /> },
    type: "default",
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    style: { background: "transparent", border: "none", padding: 0, width: 220 },
  }));
}

function toFlowEdges(edges: ActivityGraphResponse["edges"]): Edge[] {
  return edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    style: { stroke: "#52525b" },
  }));
}

interface ActivityGraphProps {
  data: ActivityGraphResponse;
}

export default function ActivityGraph({ data }: ActivityGraphProps) {
  const navigate = useNavigate();
  const onOpen = (requestId: string) =>
    navigate(`/chain/req/${encodeURIComponent(requestId)}`);

  const flowNodes = useMemo(
    () => toFlowNodes(data.nodes, data.edges, onOpen),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data.nodes, data.edges],
  );
  const flowEdges = useMemo(() => toFlowEdges(data.edges), [data.edges]);

  if (!data.available) {
    return (
      <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-500">
        Activity graph unavailable
        {data.reason ? <span className="text-zinc-600"> — {data.reason}</span> : null}
        <span className="text-zinc-600"> (logs/orchestrator.jsonl not found)</span>
      </div>
    );
  }

  if (data.nodes.length === 0) {
    return (
      <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-500">
        No recent task chains to graph.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {data.truncated && (
        <div
          data-testid="activity-graph-truncated"
          className="rounded border border-amber-800/50 bg-amber-900/10 px-3 py-1.5 text-xs text-amber-300"
        >
          Graph capped at {data.node_limit ?? data.nodes.length} nodes — a
          single experiment chain can be thousands of calls. Open a node in
          the inspector (/chain/req/…) to walk a full chain.
        </div>
      )}
      <div
        data-testid="activity-graph"
        className="h-[calc(100vh-15rem)] min-h-[520px] rounded border border-zinc-800 bg-zinc-900/40"
      >
      {/* Fallback list — also the test-visible node surface, since
          @xyflow/react does not mount node labels under jsdom. Hidden
          from sighted users by the graph drawing on top in a real
          browser is not relied on; instead the list sits above with
          sr-only so screen readers + tests can reach every node cell. */}
      <ul className="sr-only" data-testid="activity-graph-nodes">
        {data.nodes.map((n) => (
          <li key={n.id}>
            <GraphNodeCell node={n} onOpen={onOpen} />
          </li>
        ))}
      </ul>
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        fitView
        proOptions={{ hideAttribution: true }}
        colorMode="dark"
      >
        <Background color="#27272a" gap={20} />
        <Controls showInteractive={false} />
      </ReactFlow>
      </div>
    </div>
  );
}
