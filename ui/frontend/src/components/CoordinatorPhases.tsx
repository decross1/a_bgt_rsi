import type { CoordinatorActiveRun } from "../types/schemas";
import { elapsed, useNow } from "../time";

const PHASES = ["assess", "plan", "validate", "dispatch"] as const;
const STALE_AFTER_MS = 30 * 60_000;

function freshestTimestamp(run: CoordinatorActiveRun): string | null {
  if (typeof run.step_started_at === "string" && run.step_started_at) return run.step_started_at;
  if (typeof run.started_at === "string" && run.started_at) return run.started_at;
  return null;
}

type PhaseState = "done" | "active" | "future";

function phaseState(phase: string, currentStep: unknown): PhaseState {
  const current = typeof currentStep === "string"
    ? PHASES.indexOf(currentStep as (typeof PHASES)[number])
    : -1;
  const index = PHASES.indexOf(phase as (typeof PHASES)[number]);
  if (current < 0) return "future";
  if (index < current) return "done";
  if (index === current) return "active";
  return "future";
}

export default function CoordinatorPhases({
  activeRun,
  sourceError = null,
  sourcePending = false,
}: {
  activeRun: CoordinatorActiveRun | null;
  sourceError?: string | null;
  sourcePending?: boolean;
}) {
  const now = useNow();

  if (sourcePending) return <section className="trace-observation" data-state="loading" data-testid="coordinator-phases"><div><h2 className="trace-kicker">Current coordinator observation</h2><strong>Active-cycle observation loading</strong><p>Running or idle state is not established yet.</p></div></section>;

  if (sourceError) {
    return (
      <section className="trace-observation" data-state="unavailable" data-testid="coordinator-phases">
        <div>
          <h2 className="trace-kicker">Current coordinator observation</h2>
          <strong>Active-cycle feed unavailable</strong>
          <p>No idle or running claim can be made from this read.</p>
        </div>
        <details>
          <summary>Source diagnostic</summary>
          <code>{sourceError}</code>
        </details>
      </section>
    );
  }

  if (!activeRun || activeRun.kind !== "coordinator") {
    return (
      <section className="trace-observation" data-state="idle" data-testid="coordinator-phases">
        <div>
          <h2 className="trace-kicker">Current coordinator observation</h2>
          <strong data-testid="coordinator-idle">Coordinator idle · No active coordinator cycle recorded</strong>
          <p>The active-runs source returned no coordinator entry. Recorded history remains below.</p>
        </div>
        <details>
          <summary>Source</summary>
          <code>/api/activity/active_runs</code>
        </details>
      </section>
    );
  }

  const freshest = freshestTimestamp(activeRun);
  const parsedAge = freshest ? now - Date.parse(freshest) : null;
  const ageMs = parsedAge != null && Number.isFinite(parsedAge) ? parsedAge : null;
  const possiblyStale = ageMs != null && ageMs > STALE_AFTER_MS;
  const currentStep = activeRun.current_step;

  return (
    <section className="trace-observation" data-state={possiblyStale ? "stale" : "active"} data-testid="coordinator-phases">
      <div className="trace-observation-heading">
        <div>
          <h2 className="trace-kicker">Current coordinator observation</h2>
          <strong>{possiblyStale ? "Recorded active cycle may be stale" : "Coordinator cycle recorded as active"}</strong>
        </div>
        {typeof activeRun.run_id === "string" && activeRun.run_id && (
          <code title={activeRun.run_id}>{activeRun.run_id}</code>
        )}
      </div>

      {possiblyStale && (
        <div className="trace-notice" data-tone="warning" data-testid="coordinator-stale-hint">
          Last recorded update {elapsed(freshest, now)} ago. The producer may not have cleared this entry.
        </div>
      )}

      <ol className="trace-phase-list" data-testid="coordinator-stepper">
        {PHASES.map((phase) => {
          const state = phaseState(phase, currentStep);
          return (
            <li
              key={phase}
              data-testid={`phase-${phase}`}
              data-state={state}
              aria-current={state === "active" ? "step" : undefined}
            >
              <span>{phase}</span>
              <small>{state === "active" ? "current" : state === "done" ? "recorded" : "not reached"}</small>
            </li>
          );
        })}
      </ol>

      {typeof activeRun.narration === "string" && activeRun.narration && (
        <p className="trace-observation-narration" data-testid="coordinator-narration">
          {activeRun.narration}
        </p>
      )}
      <details className="trace-source-disclosure">
        <summary>Source and exact update</summary>
        <code>/api/activity/active_runs{freshest ? ` · ${freshest}` : " · update time not reported"}</code>
      </details>
    </section>
  );
}
