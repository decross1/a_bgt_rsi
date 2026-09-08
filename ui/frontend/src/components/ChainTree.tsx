import { useId, useState } from "react";
import type { ChainNode, RetrievalDoc } from "../types/schemas";

function text(value: unknown, fallback: string): string {
  if (typeof value === "string" && value) return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return fallback;
}

function shortId(value: unknown): string {
  if (typeof value !== "string" || !value) return "ID not supplied";
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

function childrenOf(node: ChainNode): ChainNode[] {
  return Array.isArray(node.children)
    ? node.children.filter((child): child is ChainNode => child !== null && typeof child === "object")
    : [];
}

function recordOf(node: ChainNode): Record<string, unknown> {
  return node.raw !== null && typeof node.raw === "object" && !Array.isArray(node.raw)
    ? node.raw
    : {};
}

function nodeLabel(node: ChainNode): string {
  if (node.kind === "dispatch") return `dispatch · ${text(node.task_type, "task")}`;
  if (node.kind === "tool") return `tool · ${text(node.caller_tag, "tool")}`;
  return text(node.caller_tag, "call");
}

function latencyLabel(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value)} ms`
    : "Latency not reported";
}

function statusClass(status: unknown): string {
  if (status === "passed") return "text-emerald-700 dark:text-emerald-300";
  if (status === "failed" || status === "aborted") return "text-red-700 dark:text-red-300";
  if (status === "started") return "text-amber-700 dark:text-amber-300";
  return "text-[var(--fg-muted)]";
}

function Scalar({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="trace-null">null</span>;
  if (typeof value === "object") {
    let serialized = "Unreadable object";
    try {
      serialized = JSON.stringify(value, null, 2);
    } catch {
      serialized = "Value could not be serialized";
    }
    return <pre className="trace-node-json">{serialized}</pre>;
  }
  return <span className="trace-scalar">{String(value)}</span>;
}

function RetrievalContext({ docs }: { docs: RetrievalDoc[] }) {
  const admitted = docs.filter((doc): doc is RetrievalDoc => doc !== null && typeof doc === "object");
  return (
    <details className="trace-retrieval">
      <summary>Retrieval context · {admitted.length} recorded chunk{admitted.length === 1 ? "" : "s"}</summary>
      <div className="trace-table-wrap">
        <table>
          <thead>
            <tr><th>Document</th><th>Content hash</th><th>Offset</th><th>Length</th></tr>
          </thead>
          <tbody>
            {admitted.map((doc, index) => (
              <tr key={`${text(doc.doc_id, "doc")}-${index}`}>
                <td>{text(doc.doc_id, "Not reported")}</td>
                <td title={typeof doc.content_hash === "string" ? doc.content_hash : undefined}>{shortId(doc.content_hash)}</td>
                <td>{text(doc.chunk_offset, "Not reported")}</td>
                <td>{text(doc.chunk_length, "Not reported")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function NodeDetails({ node, id }: { node: ChainNode; id: string }) {
  const raw = recordOf(node);
  const entries = Object.entries(raw).filter(([key]) => key !== "retrieval_context");
  const docs = Array.isArray(node.retrieval_context) ? node.retrieval_context : [];
  return (
    <div className="trace-node-details" id={id}>
      {docs.length > 0 && <RetrievalContext docs={docs} />}
      {entries.length === 0 && <p>No additional record fields.</p>}
      {entries.map(([key, value]) => (
        <div className="trace-record-field" key={key}>
          <dt>{key}</dt>
          <dd><Scalar value={value} /></dd>
        </div>
      ))}
    </div>
  );
}

function TreeNode({ node, depth, path }: { node: ChainNode; depth: number; path: string }) {
  const [childrenOpen, setChildrenOpen] = useState(true);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const detailsId = useId();
  const children = childrenOf(node);
  const label = nodeLabel(node);
  const indent = Math.min(depth, 6) * 12 + 8;
  const exactId = typeof node.request_id === "string" ? node.request_id : undefined;

  return (
    <li className="trace-chain-node" data-testid="chain-node" role="treeitem" aria-expanded={children.length > 0 ? childrenOpen : undefined}>
      <div className="trace-chain-row" style={{ paddingInlineStart: indent }}>
        {children.length > 0 ? (
          <button
            type="button"
            className="trace-chain-toggle"
            aria-label={`${childrenOpen ? "Collapse" : "Expand"} children for ${label}`}
            onClick={() => setChildrenOpen((value) => !value)}
          >
            {childrenOpen ? "Hide" : "Show"}
          </button>
        ) : (
          <span className="trace-chain-leaf">Leaf</span>
        )}
        <button
          type="button"
          className="trace-chain-record"
          aria-expanded={detailsOpen}
          aria-controls={detailsId}
          onClick={() => setDetailsOpen((value) => !value)}
        >
          <span className="trace-chain-label">{label}</span>
          {typeof node.status === "string" && node.status && (
            <span className={statusClass(node.status)}>{node.status}</span>
          )}
          {node.parse_error && <span className="trace-warning-chip">parse error</span>}
          {node.tool_calls_malformed && <span className="trace-warning-chip">malformed tool_calls</span>}
          {Array.isArray(node.retrieval_context) && node.retrieval_context.length > 0 && (
            <span className="trace-neutral-chip">context {node.retrieval_context.length}</span>
          )}
          {node.kind === "tool" && node.embedded && <span className="trace-neutral-chip">embedded</span>}
          <span className="trace-chain-latency">{latencyLabel(node.latency_ms)}</span>
          <span className="trace-chain-id" title={exactId}>{shortId(node.request_id)}</span>
        </button>
      </div>
      {detailsOpen && <NodeDetails node={node} id={detailsId} />}
      {children.length > 0 && childrenOpen && (
        <ul className="trace-chain-children" role="group">
          {children.map((child, index) => (
            <TreeNode key={`${path}.${index}.${shortId(child.request_id)}`} node={child} depth={depth + 1} path={`${path}.${index}`} />
          ))}
        </ul>
      )}
    </li>
  );
}

export default function ChainTree({ root }: { root: ChainNode }) {
  return (
    <ul className="trace-chain-tree" role="tree" aria-label="Recorded request chain">
      <TreeNode node={root} depth={0} path="root" />
    </ul>
  );
}
