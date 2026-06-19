// InFlightRollup — a compact, read-only "what is RUNNING + what's next" list
// for the Dashboard, mounted below the LLM-panel grid (FE5). It answers the
// at-a-glance question the health hero and activity hero leave open: across the
// whole apparatus — the LOOP_V0 loop, the coordinator cycle, the tracked
// subprocesses — what is in flight right now, and what is the next thing the
// human owns. It is purely prop-driven (the SystemActivityHero idiom): the
// Dashboard wires the feeds in; no fetching here, so it unit-tests directly.
//
// Every rendered field is producer-owned and UNVALIDATED (active_iteration.json,
// active_run.json, the /processes rollup). A field rendered as a React child can
// arrive as a number, boolean, or — fatally — an object/array; rendering an
// object as a child throws "Objects are not valid as a React child" and blanks
// the whole Dashboard. asText coerces a scalar and DROPS an object/array so one
// malformed field can never crash the page (the SurfacedFindingsPanel idiom).
import type {
  ActiveIteration,
  CoordinatorActiveRun,
  ProcessRow,
} from "../types/schemas";

// Coerce a producer field to renderable text; drop anything non-scalar.
function asText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  if (typeof v === "boolean") return String(v);
  // object / array / anything else: not safely renderable as text — skip it.
  return null;
}

// First NON-EMPTY rendered text from candidates (coalesce on truthiness so a
// producer's `topic:""` falls through to the next legible field).
function firstText(...candidates: unknown[]): string | null {
  for (const c of candidates) {
    const s = asText(c);
    if (s && s.trim() !== "") return s;
  }
  return null;
}

// A non-negative integer count, clamped. findingsAwaiting is derived from a
// producer-owned counts map; guard a negative / fractional / non-finite value
// so the next-step line never reads "-1 findings awaiting" or "2.7".
function asCount(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v)
    ? Math.max(0, Math.floor(v))
    : 0;
}

// A subprocess is "running" when its status is exactly that. status is an open
// producer string (running | exited_clean | exited_error_<rc> | killed_signal_<sig>);
// only "running" rows belong in an in-flight list. A missing/garbled status is
// NOT assumed running (fail quiet, don't over-report).
function isRunning(p: ProcessRow): boolean {
  return asText(p?.status) === "running";
}

export interface InFlightRollupProps {
  activeIteration?: ActiveIteration | null;
  coordinatorActive?: CoordinatorActiveRun | null;
  processes?: ProcessRow[] | null;
  findingsAwaiting?: number;
}

export default function InFlightRollup({
  activeIteration,
  coordinatorActive,
  processes,
  findingsAwaiting,
}: InFlightRollupProps) {
  // The active LOOP_V0 iteration: topic + current step.
  const iterTopic = activeIteration
    ? firstText(activeIteration.topic, activeIteration.iteration_id)
    : null;
  const iterStep = activeIteration
    ? firstText(activeIteration.current_step)
    : null;

  // The coordinator cycle: it has NO .topic — the topic lives in label /
  // narration. Read those (not a nonexistent .topic).
  const coordLabel = coordinatorActive
    ? firstText(
        coordinatorActive.label,
        coordinatorActive.narration,
        coordinatorActive.run_id,
      )
    : null;
  const coordStep = coordinatorActive
    ? firstText(coordinatorActive.current_step)
    : null;
  // current_step=="dispatch" is the closest signal that the coordinator is
  // handing an iteration off to be experiment-bridged (Phase 2). It does not
  // wire a real experiment feed.
  const dispatching = coordStep === "dispatch";

  // Tracked subprocesses still running. Guard the array (producer/ legacy body
  // could hand back null or a non-array) before filtering.
  const running = (Array.isArray(processes) ? processes : []).filter(isRunning);

  const awaiting = asCount(findingsAwaiting);

  const anyInFlight =
    iterTopic != null ||
    iterStep != null ||
    coordLabel != null ||
    running.length > 0;

  return (
    <div
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="in-flight-rollup"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          In flight
        </h2>
        <span className="text-[10px] text-zinc-600">
          what's running · what's next
        </span>
      </div>

      {!anyInFlight && (
        <div
          className="mt-2 text-sm text-zinc-500"
          data-testid="in-flight-empty"
        >
          Nothing in flight.
        </div>
      )}

      {anyInFlight && (
        <ul className="mt-2 space-y-1.5">
          {(iterTopic || iterStep) && (
            <li
              className="flex flex-wrap items-baseline gap-2 text-xs"
              data-testid="in-flight-iteration"
            >
              <span className="h-2 w-2 rounded-full bg-emerald-400" aria-hidden />
              <span className="text-zinc-300">
                Loop iteration{iterTopic ? ": " : ""}
                {iterTopic && <span className="text-zinc-200">{iterTopic}</span>}
              </span>
              {iterStep && (
                <span className="font-mono text-[11px] text-zinc-500">
                  {iterStep}
                </span>
              )}
            </li>
          )}

          {coordLabel && (
            <li
              className="flex flex-wrap items-baseline gap-2 text-xs"
              data-testid="in-flight-coordinator"
            >
              <span className="h-2 w-2 rounded-full bg-emerald-400" aria-hidden />
              <span className="text-zinc-300">Coordinator:</span>
              <span className="text-zinc-200">{coordLabel}</span>
              {coordStep && (
                <span className="font-mono text-[11px] text-zinc-500">
                  {coordStep}
                </span>
              )}
            </li>
          )}

          {running.map((p, i) => {
            const pid = asText(p?.pid);
            const topic = firstText(p?.topic);
            return (
              <li
                key={`proc-${pid ?? i}`}
                data-testid={`in-flight-process-${pid ?? i}`}
                className="flex flex-wrap items-baseline gap-2 text-xs"
              >
                <span
                  className="h-2 w-2 rounded-full bg-emerald-400"
                  aria-hidden
                />
                <span className="text-zinc-300">Process</span>
                {pid && (
                  <span className="font-mono text-[11px] text-zinc-500">
                    pid {pid}
                  </span>
                )}
                {topic && <span className="text-zinc-400">{topic}</span>}
              </li>
            );
          })}
        </ul>
      )}

      {/* Next steps — the human-owned follow-ups, below the live feeds. */}
      <div className="mt-3 space-y-1 border-t border-zinc-800/60 pt-2 text-xs">
        {/* Experiment bridging is Phase 2 — render a GREYED placeholder rather
            than wire a nonexistent feed. coordinator current_step=="dispatch"
            is the closest live signal that bridging is imminent. */}
        <div
          className="text-zinc-600"
          data-testid="in-flight-experiment-bridging"
        >
          Experiment bridging{" "}
          {dispatching ? "(dispatching…)" : "(Phase 2 — not wired)"}
        </div>

        {awaiting > 0 && (
          <div className="text-amber-300" data-testid="in-flight-findings-awaiting">
            {awaiting} finding{awaiting === 1 ? "" : "s"} awaiting your applied
            sign-off
          </div>
        )}
      </div>
    </div>
  );
}
