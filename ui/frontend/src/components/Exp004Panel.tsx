// exp004 combinatorial-auction summary panel. Reads GET
// /api/experiments/exp004 (ui/backend/experiments.py) and renders one row
// per mechanism: truthful fraction, mean efficiency, mean revenue, and a
// YES/NO verdict chip. Mirrors VllmPanel/QwenPanel's card + Row style.
// Graceful empty-state when the results file is absent (experiment not
// yet run) — the panel self-describes rather than rendering as broken.
import { useEffect, useState } from "react";
import { getExp004Summary } from "../api/http";
import { fmt, fmtRatioPct } from "../format";
import type { Exp004Mechanism, Exp004Summary } from "../types/schemas";

// YES = the mechanism elicited truthful bidding at the pre-registered bar;
// anything else reads as a miss. Tone mirrors the novelty/verdict badges.
function verdictTone(verdict: string | null): string {
  if (verdict === "YES") return "bg-emerald-950 text-emerald-400";
  if (verdict === "NO") return "bg-red-950 text-red-400";
  return "bg-zinc-800 text-zinc-400";
}

function MechanismRow({ row }: { row: Exp004Mechanism }) {
  return (
    <div className="border-b border-zinc-800/60 py-2 last:border-0">
      <div className="flex items-center justify-between gap-3">
        <span className="font-mono text-sm text-zinc-200">
          {row.mechanism ?? "—"}
        </span>
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${verdictTone(
            row.verdict,
          )}`}
        >
          {row.verdict ?? "—"}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-zinc-400">
        <span>
          truthful{" "}
          <span className="tabular-nums text-zinc-200">
            {fmtRatioPct(row.truthful_fraction, 1)} %
          </span>
        </span>
        <span>
          efficiency{" "}
          <span className="tabular-nums text-zinc-200">
            {fmtRatioPct(row.mean_efficiency, 1)} %
          </span>
        </span>
        <span>
          revenue{" "}
          <span className="tabular-nums text-zinc-200">
            {fmt(row.mean_revenue, 1)}
          </span>
        </span>
      </div>
    </div>
  );
}

interface Props {
  // Tests pass a fixture directly; production fetches once on mount.
  initial?: Exp004Summary;
}

export default function Exp004Panel({ initial }: Props) {
  const [data, setData] = useState<Exp004Summary | null>(initial ?? null);

  useEffect(() => {
    if (initial !== undefined) return;
    let cancelled = false;
    getExp004Summary()
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        /* backend unreachable — leave as null, render empty-state */
      });
    return () => {
      cancelled = true;
    };
  }, [initial]);

  const mechanisms = data?.available ? data.per_mechanism : [];

  return (
    <div
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="exp004-panel"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          exp004 · combinatorial auction
        </h2>
        {data?.available && data.n_trials != null && (
          <span className="text-[10px] text-zinc-600">
            n={data.n_trials} trials
          </span>
        )}
      </div>
      {!data?.available || mechanisms.length === 0 ? (
        <div className="mt-3 text-sm text-zinc-500">
          No exp004 results yet — the experiment has not been run.
        </div>
      ) : (
        <div className="mt-2">
          {mechanisms.map((row, i) => (
            <MechanismRow key={row.mechanism ?? i} row={row} />
          ))}
        </div>
      )}
    </div>
  );
}
