// PAGE /coordinator — the missing cycle narrative. The autonomous coordinator
// loop ran "dark" (an unlabeled ad_hoc blip on the activity panel); this page
// is where a human auditor reads the whole arc of each cycle. One
// <CoordinatorCycleCard> per row of run_state/coordinator_cycles.jsonl,
// newest-first: the auto-chosen topic (+ its source) → the plan as per-action
// status chips (executed/skipped/errored+error) → the linked iteration →
// promoted findings → bubbles. See ui_plan.md §AUTONOMY OBSERVABILITY.
//
// Poll discipline mirrors ResolvedIterationsList: an `initial` prop bypasses
// polling (tests render synchronously from the fixture); otherwise it polls
// getCoordinatorCycles() at ~0.2 Hz, cleans up on unmount, and surfaces an
// error string rather than throwing. The data file is gitignored and may be
// absent → backend returns {cycles:[]} → a clean empty state, never a blank gap.
import { useEffect, useState } from "react";
import CoordinatorCycleCard from "../components/CoordinatorCycleCard";
import { getCoordinatorCycles } from "../api/http";
import type { CoordinatorCycle } from "../types/schemas";

interface Props {
  initial?: CoordinatorCycle[];
  pollMs?: number;
}

export default function Coordinator({ initial, pollMs = 5000 }: Props) {
  const [cycles, setCycles] = useState<CoordinatorCycle[]>(initial ?? []);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(initial !== undefined);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getCoordinatorCycles()
        .then((r) => {
          if (!active) return;
          // Backend returns newest-first per the contract; sort defensively by
          // timestamp descending so a producer appending out-of-order can't
          // scramble the narrative order.
          const sorted = [...r.cycles].sort((a, b) =>
            (b.timestamp ?? "").localeCompare(a.timestamp ?? ""),
          );
          setCycles(sorted);
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
    <div className="mx-auto max-w-7xl p-5" data-testid="coordinator-page">
      <div className="flex items-baseline gap-3">
        <h1 className="text-base font-semibold text-zinc-100">Coordinator</h1>
        <span className="text-[10px] text-zinc-600">
          /api/coordinator/cycles · newest first
        </span>
        <span className="ml-auto text-[11px] text-zinc-500">
          {cycles.length}
        </span>
      </div>
      <p className="mt-1 text-xs text-zinc-500">
        One cycle = one narrative: the auto-chosen topic, the plan and each
        action's outcome (a failed dispatch is an explicit red row), the linked
        iteration, promoted findings, and bubbles raised.
      </p>

      {error && <div className="mt-3 text-sm text-red-400">{error}</div>}

      {loaded && cycles.length === 0 && !error && (
        <div
          className="mt-4 rounded border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-500"
          data-testid="coordinator-empty"
        >
          No coordinator cycles yet. The loop has not run — or its cycle log is
          not present.
        </div>
      )}

      {cycles.length > 0 && (
        <div className="mt-4 space-y-4">
          {cycles.map((cycle) => (
            <CoordinatorCycleCard key={cycle.run_id} cycle={cycle} />
          ))}
        </div>
      )}
    </div>
  );
}
