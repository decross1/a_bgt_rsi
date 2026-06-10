// PAGE A — the active-run HERO card. Surfaces run_state/active_run.json (the
// single "what is running now" state, written by ANY run-mode driver:
// experiment / autoresearch / loop_v0 / coordinator / ad_hoc). When `data` is
// null no run is in flight (the endpoint returned 204) and this renders
// NOTHING — an absent active_run must never produce an active-run hero. When
// present it shows the kind + label + current_step + progress + LIVE elapsed
// (since step_started_at, falling back to started_at) + narration + model.
// Elapsed reuses time.ts so it ticks at 1 Hz like the worker rows.
//
// Every field is producer-owned and optional in practice: a coordinator-kind
// run writes no current_step/narration, and a legacy/malformed row can carry
// a non-string anywhere the contract types string. Each field is coerced to a
// safe scalar independently (the SourceBadge.asText idiom) and rendered only
// when usable — the card shows what exists, never throws on what doesn't.
import { elapsed, useNow } from "../time";
import type { ActiveRun } from "../types/activity";

// Coerce a producer-owned display scalar to renderable text. An object/array
// rendered as a React child throws and blanks the page, so those drop to "";
// a finite number/bool stringifies (forward-compat).
function asText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  if (typeof value === "boolean") return String(value);
  return "";
}

interface ActiveRunCardProps {
  data: ActiveRun | null;
}

export default function ActiveRunCard({ data }: ActiveRunCardProps) {
  const now = useNow();
  // Null = no run in flight (204). A non-object body (a malformed 200 handing
  // back a string/number/array) carries no renderable run either — render
  // nothing so the hero never shows an active-run card when none is registered.
  if (data == null || typeof data !== "object" || Array.isArray(data)) {
    return null;
  }

  // Per-field coercion: kind variants ("experiment" | "coordinator" |
  // "ad_hoc" | any future driver) render verbatim; a missing/garbled field
  // simply drops its cell rather than crashing the card.
  const kind = asText(data.kind);
  const label = asText(data.label);
  const currentStep = asText(data.current_step);
  const narration = asText(data.narration);
  const model = asText(data.model);

  // Elapsed since the current step began, falling back to the run start when no
  // step timestamp is present. elapsed() renders "—" for absent/unparseable.
  const since = asText(data.step_started_at) || asText(data.started_at) || null;

  // progress is producer-owned too: only a plain object with at least one
  // usable scalar count renders; done/total degrade to "?" independently.
  const progress =
    data.progress != null &&
    typeof data.progress === "object" &&
    !Array.isArray(data.progress)
      ? data.progress
      : null;
  const progressDone = asText(progress?.done);
  const progressTotal = asText(progress?.total);
  const progressUnit = asText(progress?.unit);
  const hasProgress = Boolean(progressDone || progressTotal);

  return (
    <section
      data-testid="active-run-card"
      className="rounded border border-emerald-800/50 bg-emerald-950/20 p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex items-baseline gap-2">
          {kind && (
            <span className="rounded border border-emerald-700/60 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-300">
              {kind}
            </span>
          )}
          {label && (
            <span className="text-sm font-medium text-zinc-100">{label}</span>
          )}
        </div>
        <span
          className="font-mono text-xs text-emerald-300"
          data-testid="active-run-elapsed"
        >
          {elapsed(since, now)}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs">
        {currentStep && (
          <span className="text-zinc-300" data-testid="active-run-step">
            <span className="text-zinc-500">step:</span>{" "}
            <span className="font-mono">{currentStep}</span>
          </span>
        )}
        {hasProgress && (
          <span className="font-mono text-zinc-300" data-testid="active-run-progress">
            {progressDone || "?"}/{progressTotal || "?"}
            {progressUnit ? ` ${progressUnit}` : ""}
          </span>
        )}
        {model && (
          <span className="font-mono text-zinc-500" data-testid="active-run-model">
            {model}
          </span>
        )}
      </div>

      {narration && (
        <p
          className="mt-2 text-xs text-emerald-200/80"
          data-testid="active-run-narration"
        >
          {narration}
        </p>
      )}
    </section>
  );
}
