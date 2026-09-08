import { useEffect, useMemo, useRef } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import {
  Background,
  Controls,
  Position,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { ActivityEdge, ActivityGraphResponse, ActivityNode } from "../types/activity";

const STATUS_CLASS: Record<string, string> = {
  active: "border-sky-500 text-sky-700 dark:text-sky-300",
  ok: "border-emerald-600 text-emerald-700 dark:text-emerald-300",
  error: "border-red-600 text-red-700 dark:text-red-300",
  unknown: "border-zinc-500 text-zinc-700 dark:text-zinc-300",
};

export function statusClass(status: string | null | undefined): string {
  return STATUS_CLASS[status ?? "unknown"] ?? STATUS_CLASS.unknown;
}

function valueText(value: unknown, fallback = "Unknown"): string {
  return typeof value === "string" && value ? value : fallback;
}

function shortId(value: string | null | undefined): string {
  if (!value) return "Not supplied";
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

function isNode(value: unknown): value is ActivityNode {
  if (!value || typeof value !== "object") return false;
  const node = value as Partial<ActivityNode>;
  return (
    typeof node.id === "string" &&
    node.id.length > 0 &&
    typeof node.label === "string" &&
    ["dispatch", "call", "tool"].includes(String(node.kind))
  );
}

function isEdge(value: unknown): value is ActivityEdge {
  if (!value || typeof value !== "object") return false;
  const edge = value as Partial<ActivityEdge>;
  return typeof edge.id === "string" && typeof edge.source === "string" && typeof edge.target === "string";
}

export function GraphNodeCell({
  node,
  onSelect,
  selected = false,
  buttonRef,
}: {
  node: ActivityNode;
  onSelect?: (nodeId: string) => void;
  selected?: boolean;
  buttonRef?: (element: HTMLButtonElement | null) => void;
}) {
  const identity = node.task_id || node.request_id || node.id;
  return (
    <button
      ref={buttonRef}
      type="button"
      data-testid={`node-${node.id}`}
      data-kind={node.kind}
      data-request-id={node.request_id ?? ""}
      data-selected={selected ? "true" : "false"}
      aria-pressed={selected}
      aria-label={`${node.label} · ${node.kind} · ${identity} · status ${valueText(node.status)}`}
      onClick={() => onSelect?.(node.id)}
      className={`trace-graph-node rounded border ${statusClass(node.status)}`}
      title="Select this recorded node"
    >
      <span>{node.label}</span>
      <small>{node.kind} · {shortId(identity)}</small>
    </button>
  );
}

function computeLayout(nodes: ActivityNode[], edges: ActivityEdge[]): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const children = new Map<string, string[]>();
  const indegree = new Map<string, number>();
  nodes.forEach((node) => indegree.set(node.id, 0));
  edges.forEach((edge) => {
    const list = children.get(edge.source) ?? [];
    list.push(edge.target);
    children.set(edge.source, list);
    indegree.set(edge.target, (indegree.get(edge.target) ?? 0) + 1);
  });
  const depth = new Map<string, number>();
  const queue = nodes.filter((node) => (indegree.get(node.id) ?? 0) === 0).map((node) => node.id);
  queue.forEach((id) => depth.set(id, 0));
  if (queue.length === 0 && nodes[0]) {
    queue.push(nodes[0].id);
    depth.set(nodes[0].id, 0);
  }
  while (queue.length > 0) {
    const id = queue.shift()!;
    for (const child of children.get(id) ?? []) {
      if (depth.has(child)) continue;
      depth.set(child, (depth.get(id) ?? 0) + 1);
      queue.push(child);
    }
  }
  const rows = new Map<number, number>();
  nodes.forEach((node) => {
    const column = depth.get(node.id) ?? 0;
    const row = rows.get(column) ?? 0;
    rows.set(column, row + 1);
    positions.set(node.id, { x: column * 278, y: row * 78 });
  });
  return positions;
}

function toFlowEdges(edges: ActivityEdge[]): Edge[] {
  return edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    style: { stroke: "var(--fg-muted)" },
  }));
}

function nodeMatches(node: ActivityNode, query: string, status: string): boolean {
  const statusMatches = status === "all" || valueText(node.status, "unknown").toLowerCase() === status;
  if (!statusMatches) return false;
  if (!query) return true;
  return [node.label, node.kind, node.id, node.task_id, node.request_id, node.status]
    .filter((value): value is string => typeof value === "string")
    .join(" ")
    .toLocaleLowerCase()
    .includes(query);
}

function GraphList({
  nodes,
  selectedId,
  onSelect,
  setNodeRef,
}: {
  nodes: ActivityNode[];
  selectedId: string | null;
  onSelect: (nodeId: string) => void;
  setNodeRef: (nodeId: string, element: HTMLButtonElement | null) => void;
}) {
  return (
    <ul className="trace-map-list" data-testid="activity-graph-nodes">
      {nodes.map((node) => (
        <li key={node.id}>
          <GraphNodeCell
            node={node}
            selected={selectedId === node.id}
            onSelect={onSelect}
            buttonRef={(element) => setNodeRef(node.id, element)}
          />
        </li>
      ))}
    </ul>
  );
}

export default function ActivityGraph({ data }: { data: ActivityGraphResponse }) {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const nodeRefs = useRef(new Map<string, HTMLButtonElement>());
  const query = (params.get("q") ?? "").trim().toLocaleLowerCase();
  const statusFilter = params.get("status") ?? "all";
  const selectedId = params.get("node");

  const malformedResponse = !Array.isArray(data?.nodes) || !Array.isArray(data?.edges);
  const rawNodes: unknown[] = Array.isArray(data?.nodes) ? data.nodes : [];
  const rawEdges: unknown[] = Array.isArray(data?.edges) ? data.edges : [];
  const nodes = rawNodes.filter(isNode);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = rawEdges.filter(isEdge).filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target));
  const excludedCount = rawNodes.length - nodes.length + rawEdges.length - edges.length;
  const filteredNodes = nodes.filter((node) => nodeMatches(node, query, statusFilter));
  const filteredIds = new Set(filteredNodes.map((node) => node.id));
  const filteredEdges = edges.filter((edge) => filteredIds.has(edge.source) && filteredIds.has(edge.target));
  const selected = nodes.find((node) => node.id === selectedId) ?? null;

  const selectNode = (nodeId: string) => {
    const next = new URLSearchParams(params);
    next.set("node", nodeId);
    setParams(next);
  };

  const setNodeRef = (nodeId: string, element: HTMLButtonElement | null) => {
    if (element) nodeRefs.current.set(nodeId, element);
    else nodeRefs.current.delete(nodeId);
  };

  useEffect(() => {
    const state = location.state as { focusNodeId?: unknown } | null;
    if (typeof state?.focusNodeId !== "string") return;
    nodeRefs.current.get(state.focusNodeId)?.focus();
  }, [location.state, filteredNodes.length]);

  const positions = useMemo(() => computeLayout(filteredNodes, filteredEdges), [filteredEdges, filteredNodes]);
  const flowNodes = useMemo<Node[]>(
    () =>
      filteredNodes.map((node) => ({
        id: node.id,
        position: positions.get(node.id) ?? { x: 0, y: 0 },
        data: { label: <GraphNodeCell node={node} selected={selectedId === node.id} onSelect={selectNode} /> },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        style: { background: "transparent", border: "none", padding: 0, width: 220 },
      })),
    // URLSearchParams has stable content semantics here; params changes rebuild selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [filteredNodes, positions, selectedId],
  );
  const flowEdges = useMemo(() => toFlowEdges(filteredEdges), [filteredEdges]);

  if (data?.available === false) {
    return (
      <div className="trace-empty" data-testid="activity-graph-unavailable">
        <strong>Recorded map unavailable.</strong>{" "}
        {typeof data.reason === "string" && data.reason ? data.reason : "The source did not provide a map."}
      </div>
    );
  }

  if (malformedResponse) {
    return (
      <div className="trace-empty" data-testid="activity-graph-malformed">
        The map response is malformed. No relationship or empty-state claim can be made from it.
      </div>
    );
  }

  if (nodes.length === 0) {
    return <div className="trace-empty" data-testid="activity-graph-empty">No recorded task nodes in this loaded map.</div>;
  }

  const fullWithoutDescendants =
    data.detail === "full" && edges.length === 0 && nodes.every((node) => node.kind === "dispatch");
  const noRelationships = filteredEdges.length === 0;
  const generatedAt = typeof data.generated_at === "string" && data.generated_at ? data.generated_at : "not reported";
  const returnTo = `${location.pathname}${location.search}`;

  return (
    <div>
      <div className="trace-map-meta">
        <span>{filteredNodes.length} of {nodes.length} readable nodes · {filteredEdges.length} recorded links</span>
        <span>Generated {generatedAt}</span>
      </div>

      {excludedCount > 0 && (
        <div className="trace-notice" data-tone="warning" data-testid="activity-graph-excluded">
          {excludedCount} malformed or dangling map item{excludedCount === 1 ? " was" : "s were"} excluded.
        </div>
      )}

      {data.truncated && (
        <div className="trace-notice" data-tone="warning" data-testid="activity-graph-truncated">
          This snapshot was capped at {data.node_limit ?? nodes.length} nodes. The map is incomplete.
        </div>
      )}

      {fullWithoutDescendants && (
        <div className="trace-notice" data-testid="activity-graph-no-descendants">
          Full view added no recorded descendants in this result.
        </div>
      )}

      {filteredNodes.length === 0 ? (
        <div className="trace-empty" data-testid="activity-graph-filtered-empty">
          No readable node matches these filters.
        </div>
      ) : (
        <div className="trace-map-workspace">
          <div>
            {noRelationships ? (
              <section className="trace-zero-edge" data-testid="activity-graph-zero-edge" aria-labelledby="zero-edge-heading">
                <div className="trace-section-heading">
                  <div>
                    <h2 id="zero-edge-heading">No recorded relationships</h2>
                    <p>These records have no supplied edges, so they are shown as a readable list.</p>
                  </div>
                </div>
                <GraphList nodes={filteredNodes} selectedId={selectedId} onSelect={selectNode} setNodeRef={setNodeRef} />
              </section>
            ) : (
              <>
                <div className="trace-map-legend">
                  <span>Lines: recorded parent links</span>
                  <span>Placement organizes the view; it does not establish causality.</span>
                </div>
                <div className="trace-flow-canvas" data-testid="activity-graph">
                  <ReactFlow nodes={flowNodes} edges={flowEdges} fitView proOptions={{ hideAttribution: true }} colorMode="system">
                    <Background color="var(--border-2)" gap={22} />
                    <Controls showInteractive={false} />
                  </ReactFlow>
                </div>
                <section className="trace-list-equivalent" aria-label="Map list equivalent">
                  <h3>List equivalent · {filteredNodes.length} records</h3>
                  <GraphList nodes={filteredNodes} selectedId={selectedId} onSelect={selectNode} setNodeRef={setNodeRef} />
                </section>
              </>
            )}
          </div>

          <aside className="trace-map-context" aria-label="Selected map record">
            {selected ? (
              <>
                <p className="trace-kicker">Selected record</p>
                <h2>{selected.label}</h2>
                <dl>
                  <div><dt>Kind</dt><dd>{selected.kind}</dd></div>
                  <div><dt>Status</dt><dd>{valueText(selected.status)}</dd></div>
                  <div><dt>Task ID</dt><dd><code>{selected.task_id || "Not supplied"}</code></dd></div>
                  <div><dt>Request ID</dt><dd><code>{selected.request_id || "Not supplied"}</code></dd></div>
                </dl>
                {selected.request_id ? (
                  <>
                    <p className="trace-lookup-note">
                      A request ID records this node's identity. It does not guarantee an indexed call record.
                    </p>
                    <Link
                      className="trace-action-button"
                      to={`/chain/req/${encodeURIComponent(selected.request_id)}`}
                      state={{ returnTo, focusNodeId: selected.id }}
                    >
                      Look up indexed call
                    </Link>
                  </>
                ) : (
                  <p className="trace-lookup-note">No request ID was supplied for an Inspector lookup.</p>
                )}
              </>
            ) : (
              <div className="trace-empty">Select a record to read its supplied metadata.</div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
