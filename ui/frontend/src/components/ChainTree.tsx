// Collapsible call-chain tree. See ui_plan.md section 5.3 (inspector).
// Each node expands to a generic dump of its underlying log record, so a
// future day-2 schema addition needs no code change here.
import { useState } from "react";
import type { ChainNode } from "../types/schemas";

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

function NodeDetails({ node }: { node: ChainNode }) {
  const entries = Object.entries(node.raw);
  return (
    <div className="mt-1 mb-1 ml-6 rounded border border-zinc-800 bg-zinc-900/60 p-3 text-sm">
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
