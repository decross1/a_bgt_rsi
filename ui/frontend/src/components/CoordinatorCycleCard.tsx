// CoordinatorCycleCard — one cycle = one narrative. Renders a single row of
// run_state/coordinator_cycles.jsonl so a human auditor can read the whole
// decision in one scroll: the auto-chosen topic (+ its source) → the plan as
// per-action status chips → the linked dispatched iteration → how many findings
// were promoted and bubbles raised. See ui_plan.md §AUTONOMY OBSERVABILITY
// ("one cycle = one narrative") and ui_autonomy_observability_plan.md.
//
// The headline design principle here is "make absence legible": a dispatched
// action that ERRORED is a visible red chip carrying its error string inline,
// never a silent gap. Executed = emerald, skipped = zinc, errored = red.
// Provenance is on the header via <AgentBadge> + a topic_source badge.
import AgentBadge from "./AgentBadge";
import type {
  CoordinatorCycle,
  CoordinatorOutcome,
} from "../types/schemas";

// Status → chip tone. Open default (quiet zinc) so an unrecognized EMIT-side
// status renders generically rather than crashing.
const STATUS_TONE: Record<string, string> = {
  passed: "bg-emerald-950 text-emerald-400",
  skipped: "bg-zinc-800 text-zinc-400",
  errored: "bg-red-950 text-red-400",
};

function statusTone(status: string): string {
  return STATUS_TONE[status] ?? "bg-zinc-800 text-zinc-400";
}

// topic_source provenance badge (coordinator / human / arxiv_pick / …). Sky for
// the loop driver; quiet zinc otherwise — distinct from the AgentBadge so the
// "who chose the topic" signal reads apart from "who ran the cycle".
function sourceTone(source: string): string {
  return source === "coordinator"
    ? "bg-sky-950 text-sky-300"
    : "bg-zinc-800 text-zinc-400";
}

function shortTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  return iso.replace("T", " ").replace("Z", "");
}

// One action's chip. For an errored action the error string is shown inline
// (red) — a failed dispatch must be a visible row, never hidden.
function ActionChip({ outcome }: { outcome: CoordinatorOutcome }) {
  const errored = outcome.status === "errored";
  return (
    <li
      data-testid={`coordinator-action-${outcome.action}`}
      className="flex flex-wrap items-baseline gap-2"
    >
      <span className="font-mono text-xs text-zinc-300">{outcome.action}</span>
      <span
        className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${statusTone(
          outcome.status,
        )}`}
      >
        {outcome.status}
      </span>
      {errored && outcome.error && (
        <span
          data-testid={`coordinator-action-error-${outcome.action}`}
          className="w-full rounded border border-red-900/60 bg-red-950/30 px-2 py-1 font-mono text-[11px] text-red-300"
        >
          {outcome.error}
        </span>
      )}
    </li>
  );
}

export default function CoordinatorCycleCard({
  cycle,
}: {
  cycle: CoordinatorCycle;
}) {
  const promotedCount = cycle.promoted_finding_ids?.length ?? 0;
  const bubbleCount = cycle.bubble_run_ids?.length ?? 0;

  return (
    <div
      data-testid="coordinator-cycle-card"
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
    >
      {/* Header — topic, its source, the actor, and when. */}
      <div className="flex flex-wrap items-baseline gap-2">
        <AgentBadge agent={cycle.agent} />
        <span
          data-testid="coordinator-topic-source"
          className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${sourceTone(
            cycle.topic_source,
          )}`}
        >
          {cycle.topic_source}
        </span>
        <span className="ml-auto font-mono text-[10px] text-zinc-500">
          {shortTimestamp(cycle.timestamp)}
        </span>
      </div>
      <div className="mt-1 text-sm text-zinc-200">{cycle.topic}</div>

      {/* Plan — per-action status chips. Errored chips carry the error inline. */}
      <div className="mt-3">
        <div className="text-[10px] uppercase tracking-wide text-zinc-500">
          plan
        </div>
        <ul className="mt-1 space-y-1.5">
          {cycle.outcomes.map((outcome, i) => (
            <ActionChip key={`${outcome.action}-${i}`} outcome={outcome} />
          ))}
        </ul>
      </div>

      {/* Footer — the join keys: dispatched iteration, promoted findings,
          bubbles. */}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-zinc-500">
        {cycle.dispatched_iteration_id && (
          <span data-testid="coordinator-dispatched-iteration">
            dispatched{" "}
            <span className="font-mono text-zinc-300">
              {cycle.dispatched_iteration_id}
            </span>
          </span>
        )}
        <span data-testid="coordinator-promoted-count">
          {promotedCount} finding{promotedCount === 1 ? "" : "s"} promoted
        </span>
        <span data-testid="coordinator-bubble-count">
          {bubbleCount} bubble{bubbleCount === 1 ? "" : "s"}
        </span>
      </div>
    </div>
  );
}
