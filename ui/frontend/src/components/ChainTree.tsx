// Collapsible call-chain tree. See ui_plan.md section 5.3 (inspector).
// Each node expands to a generic dump of its underlying log record, so a
// future day-2 schema addition needs no code change here.
import { useState } from "react";
import type { ChainNode, RetrievalDoc } from "../types/schemas";

function shortId(id: string | null | undefined): string {
  if (!id) return "—";
  return id.length > 10 ? `${id.slice(0, 8)}…` : id;
}

function statusClass(status: string | null | undefined): string {
  switch (status) {
    case "passed":
      return "text-emerald-400";
    case "failed":
    case "aborted":
      return "text-red-400";
    case "started":
      return "text-amber-400";
    default:
      return "text-zinc-400";
  }
}

function Scalar({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <span className="text-zinc-600">null</span>;
  }
  if (typeof value === "object") {
    return (
      <pre className="mt-1 overflow-x-auto rounded bg-zinc-950 p-2 text-xs text-zinc-300">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }
  return <span className="text-zinc-200">{String(value)}</span>;
}

// Day-3.5: retrieval_context lands as a list of {doc_id, content_hash,
// chunk_offset, chunk_length}. Render as a small table rather than a generic
// JSON dump so the inspector reads cleanly at a glance.
function RetrievalContext({ docs }: { docs: RetrievalDoc[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2 rounded border border-zinc-800 bg-zinc-950/60 p-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-left text-xs text-zinc-400 hover:text-zinc-200"
      >
        <span className="w-3">{open ? "▾" : "▸"}</span>
        <span className="font-mono uppercase tracking-wide">retrieval_context</span>
        <span className="text-zinc-600">({docs.length})</span>
      </button>
      {open && (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-zinc-500">
              <tr>
                <th className="px-2 py-1 text-left font-normal">doc_id</th>
                <th className="px-2 py-1 text-left font-normal">content_hash</th>
                <th className="px-2 py-1 text-right font-normal">offset</th>
                <th className="px-2 py-1 text-right font-normal">length</th>
              </tr>
            </thead>
            <tbody className="font-mono text-zinc-300">
              {docs.map((doc, i) => (
                <tr key={i} className="border-t border-zinc-800/60">
                  <td className="px-2 py-1">{doc.doc_id ?? "—"}</td>
                  <td className="px-2 py-1 text-zinc-500">
                    {typeof doc.content_hash === "string"
                      ? doc.content_hash.slice(0, 12) +
                        (doc.content_hash.length > 12 ? "…" : "")
                      : "—"}
                  </td>
                  <td className="px-2 py-1 text-right">{doc.chunk_offset ?? "—"}</td>
                  <td className="px-2 py-1 text-right">{doc.chunk_length ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function NodeDetails({ node }: { node: ChainNode }) {
  // Hide retrieval_context from the raw dump — we render it as its own
  // collapsible table above. Avoids duplicating the same data in two places.
  const entries = Object.entries(node.raw).filter(([k]) => k !== "retrieval_context");
  return (
    <div className="mt-1 mb-1 ml-6 rounded border border-zinc-800 bg-zinc-900/60 p-3 text-sm">
      {node.retrieval_context && node.retrieval_context.length > 0 && (
        <RetrievalContext docs={node.retrieval_context} />
      )}
      {entries.length === 0 && <div className="text-zinc-500">no record fields</div>}
      {entries.map(([key, value]) => (
        <div key={key} className="mb-1.5">
          <span className="font-mono text-xs text-zinc-500">{key}</span>
          <div className="ml-2">
            <Scalar value={value} />
          </div>
        </div>
      ))}
    </div>
  );
}

function TreeNode({ node }: { node: ChainNode }) {
  const [open, setOpen] = useState(true);
  const [details, setDetails] = useState(false);
  const hasChildren = node.children.length > 0;
  const label =
    node.kind === "dispatch"
      ? `dispatch · ${node.task_type ?? "task"}`
      : node.kind === "tool"
        ? `tool · ${node.caller_tag ?? "tool"}`
        : node.caller_tag ?? "call";

  return (
    <div data-testid="chain-node">
      <div className="flex items-center gap-2 py-0.5">
        {hasChildren ? (
          <button
            onClick={() => setOpen((v) => !v)}
            className="w-4 text-zinc-500 hover:text-zinc-200"
            aria-label={open ? "collapse" : "expand"}
          >
            {open ? "▾" : "▸"}
          </button>
        ) : (
          <span className="w-4 text-center text-zinc-700">·</span>
        )}
        <button
          onClick={() => setDetails((v) => !v)}
          className="flex flex-1 items-center gap-3 rounded px-2 py-1 text-left hover:bg-zinc-800/60"
        >
          <span className="font-medium text-zinc-100">{label}</span>
          {node.kind === "dispatch" && node.status && (
            <span className={`text-xs ${statusClass(node.status)}`}>{node.status}</span>
          )}
          {node.parse_error && (
            <span className="rounded bg-red-950 px-1.5 py-0.5 text-xs text-red-300">
              parse error
            </span>
          )}
          {node.tool_calls_malformed && (
            <span className="rounded bg-red-950 px-1.5 py-0.5 text-xs text-red-300">
              malformed tool_calls
            </span>
          )}
          {node.retrieval_context && node.retrieval_context.length > 0 && (
            <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-400">
              ctx {node.retrieval_context.length}
            </span>
          )}
          {node.kind === "tool" && node.embedded && (
            <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-400">
              embedded
            </span>
          )}
          <span className="ml-auto font-mono text-xs text-zinc-500">
            {node.latency_ms != null ? `${node.latency_ms} ms` : ""}
          </span>
          <span className="font-mono text-xs text-zinc-600">{shortId(node.request_id)}</span>
        </button>
      </div>
      {details && <NodeDetails node={node} />}
      {hasChildren && open && (
        <div className="ml-3 border-l border-zinc-800 pl-3">
          {node.children.map((child, i) => (
            <TreeNode key={child.request_id ?? `n${i}`} node={child} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function ChainTree({ root }: { root: ChainNode }) {
  return (
    <div className="text-sm">
      <TreeNode node={root} />
    </div>
  );
}
