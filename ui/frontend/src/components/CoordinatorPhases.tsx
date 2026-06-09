// CoordinatorPhases — the assess → plan → validate → dispatch stepper for the
// live coordinator cycle. Part of the autonomy-observability views: the loop
// must stop running "dark", so when a cycle is in flight this says WHAT stage
// it's in and WHY (the chosen topic + rationale from active_run.narration).
// See ui_plan.md §AUTONOMY OBSERVABILITY ("make absence legible", "one cycle =
// one narrative").
//
// Pure + prop-driven: the parent (Coordinator/Activity page) polls
// getCoordinatorActive() and hands us the result, so this component renders
// synchronously from a fixture in tests — no fetch to mock.
//
// State per phase relative to current_step's position in the ordered phases:
//   prior   -> done   (quiet emerald — it's been walked through)
//   current -> active (emerald, ring — where the loop is now)
//   future  -> quiet  (zinc — not reached yet)
// An unrecognized current_step (outside the four) leaves every phase "future"
// (nothing highlighted), the same forgiving degrade the LOOP_V0 step strip uses.
//
// When there's no live coordinator cycle (activeRun null OR kind !== "coordinator"
// — e.g. an ad-hoc or nara run is what's active) we render a quiet idle state
// rather than an empty gap: idle ≠ failed ≠ running.
import type { CoordinatorActiveRun } from "../types/schemas";

// The coordinator's four phases, in order. The stepper's join key.
const PHASES = ["assess", "plan", "validate", "dispatch"] as const;

type PhaseState = "done" | "active" | "future";

function phaseState(phase: string, currentStep: string | null | undefined): PhaseState {
  const current = currentStep ? PHASES.indexOf(currentStep as (typeof PHASES)[number]) : -1;
  const idx = PHASES.indexOf(phase as (typeof PHASES)[number]);
  // current === -1 → an unrecognized (or absent) step: nothing is highlighted,
  // every phase reads as not-yet-reached.
  if (current < 0) return "future";
  if (idx < current) return "done";
  if (idx === current) return "active";
  return "future";
}

const STEP_TONE: Record<PhaseState, string> = {
  active: "border-emerald-600 bg-emerald-950/40 text-emerald-300",
  done: "border-emerald-900/60 bg-emerald-950/20 text-emerald-500",
  future: "border-zinc-800 bg-zinc-950/40 text-zinc-600",
};

export default function CoordinatorPhases({
  activeRun,
}: {
  activeRun: CoordinatorActiveRun | null;
}) {
  // No live coordinator cycle: an ad-hoc/nara run, or nothing running at all.
  // Render a quiet idle state — absence is legible, not a blank gap.
  if (!activeRun || activeRun.kind !== "coordinator") {
    return (
      <div
        className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
        data-testid="coordinator-phases"
      >
        <div className="flex items-baseline gap-2">
          <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
            Coordinator phases
          </h2>
          <span className="text-[10px] text-zinc-600">
            /api/coordinator/active
          </span>
        </div>
        <div className="mt-2 text-sm text-zinc-500" data-testid="coordinator-idle">
          coordinator idle — no cycle running.
        </div>
      </div>
    );
  }

  const currentStep = activeRun.current_step;

  return (
    <div
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="coordinator-phases"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Coordinator phases
        </h2>
        <span className="text-[10px] text-zinc-600">/api/coordinator/active</span>
        {/* run_id is producer-owned JSONL — a malformed/legacy row could carry a
            non-string (object/array) here. Guard on `typeof === "string"` so a
            bad value is dropped (the chip just omits, like a null run_id) rather
            than rendered as a React child, which would throw "Objects are not
            valid as a React child" and crash the whole page on one bad row. */}
        {typeof activeRun.run_id === "string" && activeRun.run_id && (
          <span className="ml-auto font-mono text-[10px] text-zinc-500">
            {activeRun.run_id}
          </span>
        )}
      </div>

      {/* Horizontal stepper. Each phase is a chip; connectors between them. */}
      <ol
        className="mt-3 flex items-stretch gap-1"
        data-testid="coordinator-stepper"
      >
        {PHASES.map((phase, i) => {
          const state = phaseState(phase, currentStep);
          return (
            <li key={phase} className="flex flex-1 items-center gap-1">
              <div
                data-testid={`phase-${phase}`}
                data-state={state}
                aria-current={state === "active" ? "step" : undefined}
                className={`flex-1 rounded border px-2 py-1.5 text-center text-[10px] uppercase tracking-wide ${STEP_TONE[state]}`}
              >
                {phase}
              </div>
              {i < PHASES.length - 1 && (
                <span
                  aria-hidden="true"
                  className={
                    state === "done"
                      ? "text-emerald-600"
                      : "text-zinc-700"
                  }
                >
                  →
                </span>
              )}
            </li>
          );
        })}
      </ol>

      {/* Narration — the chosen topic + why, so the panel says what stage and
          why, not just "running". Same producer-malformed guard as run_id: only
          render a string narration (a non-string from a bad/legacy row would
          crash the page as an invalid React child); a non-string is omitted,
          like a null narration. */}
      {typeof activeRun.narration === "string" && activeRun.narration && (
        <div
          className="mt-3 rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5 text-xs text-zinc-300"
          data-testid="coordinator-narration"
        >
          {activeRun.narration}
        </div>
      )}
    </div>
  );
}
