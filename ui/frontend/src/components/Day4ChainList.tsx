// Day-4 tool-call chains list: enumerates wrapper-rooted chains from
// day4_e2e.jsonl and links each into the inspector. Each row carries node
// count, total latency, and a red "malformed" badge when the chain has any
// parse-error nodes. ui_plan.md section 5.3.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getDay4Chains } from "../api/http";
import type { Day4ChainSummary } from "../types/schemas";

function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 10)}…` : id;
}

export default function Day4ChainList() {
  const [chains, setChains] = useState<Day4ChainSummary[] | null>(null);
  const [available, setAvailable] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = () =>
      getDay4Chains()
        .then((d) => {
          if (!active) return;
          setAvailable(d.available);
          setChains(d.chains);
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
        Day-4 tool-call chains{" "}
        <span className="ml-1 normal-case text-[10px] text-zinc-600">
          (logs/day4_e2e.jsonl — day-4-specific; quiet during other workloads)
        </span>
      </h2>
      {error && <div className="mt-2 text-sm text-red-400">{error}</div>}
      {!available && (
        <div className="mt-2 text-sm text-zinc-500">
          logs/day4_e2e.jsonl not present — this panel only lights up during
          the day-4 tool-call check. A running PD experiment or summarize
          worker will not appear here.
        </div>
      )}
      {available && chains && chains.length === 0 && (
        <div className="mt-2 text-sm text-zinc-500">
          day4_e2e.jsonl is present but carries no wrapper-rooted chains.
        </div>
      )}
      {available && chains && chains.length > 0 && (
        <div className="mt-2 max-h-64 overflow-y-auto">
          {chains.map((c) => (
            <Link
              key={c.request_id}
              to={`/chain/req/${encodeURIComponent(c.request_id)}`}
              className="flex items-center gap-3 rounded px-2 py-1.5 hover:bg-zinc-800/60"
            >
              <span className="font-mono text-xs text-zinc-400">
                {shortId(c.request_id)}
              </span>
              <span className="text-xs text-zinc-500">{c.caller_tag ?? "—"}</span>
              <span className="text-xs text-zinc-600">
                {c.node_count} nodes · {c.total_latency_ms} ms
              </span>
              {c.malformed_tool_calls > 0 && (
                <span className="rounded bg-red-950 px-1.5 py-0.5 text-xs text-red-300">
                  malformed
                </span>
              )}
              <span className="ml-auto text-xs text-zinc-700">
                {c.timestamp ?? ""}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
