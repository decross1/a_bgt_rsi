// CoordinatorPhases — the assess → plan → validate → dispatch stepper for the
// live coordinator cycle. Part of the autonomy-observability views: the loop
// must stop running "dark", so when a cycle is in flight this says WHAT stage
// it's in and WHY (the chosen topic + rationale from active_run.narration).
// See ui_plan.md §AUTONOMY OBSERVABILITY ("make absence legible", "one cycle =
// one narrative").
//
// Pure + prop-driven: the parent (the /cycles page post-S3) polls the D-047
// multi-run registry (getActiveRuns) and hands us the kind==="coordinator"
// doc, so this component renders synchronously from a fixture in tests — no
// fetch to mock. (The old /api/coordinator/active mirror was retired in S3.)
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
import { elapsed, useNow } from "../time";

// The coordinator's four phases, in order. The stepper's join key.
const PHASES = ["assess", "plan", "validate", "dispatch"] as const;

// An active_run whose freshest timestamp is older than this is "possibly
// stale": a known producer bug (a lock-leak past a finally-block clear) can
// leave active_run.json behind after the iteration completed, and the UI must
// not present that old file as a confidently-live cycle. 30 minutes is well
// past any observed real step duration.
const STALE_AFTER_MS = 30 * 60_000;

/** The run's freshest timestamp (step_started_at, else started_at), or null
 * when absent / non-string. Producer-owned JSON: a malformed row can carry a
 * non-string here (and Date.parse coerces arrays/objects), so only a
 * non-empty string qualifies. */
function freshestTimestamp(run: CoordinatorActiveRun): string | null {
  if (typeof run.step_started_at === "string" && run.step_started_at) {
    return run.step_started_at;
  }
  if (typeof run.started_at === "string" && run.started_at) {
    return run.started_at;
  }
  return null;
}

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
  // Live clock for the staleness check (the codebase idiom for current-time
  // rendering — Dashboard uses the same hook). Called unconditionally, before
  // the idle early-return, per the rules of hooks.
  const now = useNow();

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
            /api/activity/active_runs
          </span>
        </div>
        <div className="mt-2 text-sm text-zinc-500" data-testid="coordinator-idle">
          coordinator idle — no cycle running.
        </div>
      </div>
    );
  }

  const currentStep = activeRun.current_step;

  // Phantom-presence guard: a completed iteration can leave active_run.json
  // behind (producer lock-leak), and this panel would then show a "running"
  // stepper forever. When the freshest timestamp is older than ~30 minutes,
  // annotate — but STILL render the stepper (don't hide state; annotate it).
  // Date.parse → NaN must mean "freshness unknown" (NO hint), never a
  // false-stale — same Number.isFinite ageMs guard the Dashboard hero uses.
  const freshestIso = freshestTimestamp(activeRun);
  const parsedAge = freshestIso != null ? now - Date.parse(freshestIso) : null;
  const ageMs =
    parsedAge != null && Number.isFinite(parsedAge) ? parsedAge : null;
  const possiblyStale = ageMs != null && ageMs > STALE_AFTER_MS;

  return (
    <div
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="coordinator-phases"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Coordinator phases
        </h2>
        <span className="text-[10px] text-zinc-600">/api/activity/active_runs</span>
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

      {/* Stale-active-run hint — the dual of "make absence legible": phantom
          presence. The stepper below still renders (annotate state, don't hide
          it); this just withdraws the panel's claim that the cycle is
          confidently live. freshestIso is non-null whenever possiblyStale is
          (ageMs derives from it). */}
      {possiblyStale && (
        <div
          className="mt-3 rounded border border-amber-900/60 bg-amber-950/30 px-2 py-1.5 text-xs text-amber-400"
          data-testid="coordinator-stale-hint"
        >
          possibly stale — last update {elapsed(freshestIso, now)} ago; the
          producer may have failed to clear active_run.json
        </div>
      )}

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
