// SurfacedFindingsPanel — the UI surface for memory/surfaced_findings.jsonl
// (the coordinator's promote_findings output, previously invisible). Polls
// /api/coordinator/findings newest-first and renders each promoted finding's
// text with its provenance (AgentBadge — coordinator vs nara vs human), the
// iteration it came out of, and when. See ui_plan.md §AUTONOMY OBSERVABILITY:
// promoted findings had no view, so the loop's "here's what's worth keeping"
// output ran dark.
//
// Poll discipline mirrors ResolvedIterationsList: an `initial` prop bypasses
// polling (tests render synchronously from fixtures); otherwise it polls the
// api/http.ts helper, cleans up on unmount, and surfaces an error string
// rather than throwing. Absent (gitignored) data file → backend returns
// {findings:[]} → a clean empty state, never a blank gap.
import { useEffect, useState } from "react";
import { getSurfacedFindings } from "../api/http";
import type { SurfacedFinding } from "../types/schemas";
import AgentBadge from "./AgentBadge";

function shortTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  return iso.replace("T", " ").replace("Z", "");
}

interface Props {
  initial?: SurfacedFinding[];
  pollMs?: number;
}

export default function SurfacedFindingsPanel({
  initial,
  pollMs = 5000,
}: Props) {
  const [findings, setFindings] = useState<SurfacedFinding[]>(initial ?? []);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(initial !== undefined);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getSurfacedFindings()
        .then((r) => {
          if (!active) return;
          // Backend returns newest-first per the contract; sort defensively by
          // timestamp descending so a producer appending out-of-order can't
          // scramble the panel.
          const sorted = [...r.findings].sort((a, b) =>
            (b.timestamp ?? "").localeCompare(a.timestamp ?? ""),
          );
          setFindings(sorted);
          setLoaded(true);
          setError(null);
        })
        .catch((e) => {
          if (active) setError(String(e));
        });
    load();
    const id = setInterval(load, pollMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [initial, pollMs]);

  return (
    <div
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="surfaced-findings-panel"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Surfaced findings
        </h2>
        <span className="text-[10px] text-zinc-600">
          /api/coordinator/findings · newest first
        </span>
        <span className="ml-auto text-[11px] text-zinc-500">
          {findings.length}
        </span>
      </div>

      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}

      {loaded && findings.length === 0 && !error && (
        <div className="mt-2 text-sm text-zinc-500">
          No surfaced findings yet.
        </div>
      )}

      {findings.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {findings.map((finding) => (
            <li
              key={finding.finding_id}
              className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5"
            >
              <div className="flex flex-wrap items-baseline gap-2 text-[11px]">
                <AgentBadge agent={finding.agent} />
                {finding.iteration_id && (
                  <span className="font-mono text-zinc-400">
                    {finding.iteration_id}
                  </span>
                )}
                <span className="ml-auto font-mono text-[10px] text-zinc-500">
                  {shortTimestamp(finding.timestamp)}
                </span>
              </div>
              <div className="mt-1 text-xs text-zinc-300">{finding.text}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
