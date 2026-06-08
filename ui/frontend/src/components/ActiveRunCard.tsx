// PAGE A — the active-run HERO card. Surfaces run_state/active_run.json (the
// single "what is running now" state, written by ANY run-mode driver:
// experiment / autoresearch / loop_v0 / ad_hoc). When `data` is null no run is
// in flight (the endpoint returned 204) and this renders NOTHING — an absent
// active_run must never produce an active-run hero. When present it shows the
// kind + label + current_step + progress + LIVE elapsed (since step_started_at,
// falling back to started_at) + narration + model. Elapsed reuses time.ts so it
// ticks at 1 Hz like the worker rows.
import { elapsed, useNow } from "../time";
import type { ActiveRun } from "../types/activity";

interface ActiveRunCardProps {
  data: ActiveRun | null;
}

export default function ActiveRunCard({ data }: ActiveRunCardProps) {
  const now = useNow();
  // Null = no run in flight (204). Render nothing so the hero never shows an
  // active-run card when none is registered.
  if (data == null) return null;

  // Elapsed since the current step began, falling back to the run start when no
  // step timestamp is present.
  const since = data.step_started_at ?? data.started_at;
  const progress = data.progress;
  const hasProgress =
    progress != null &&
    (progress.done != null || progress.total != null);

  return (
    <section
      data-testid="active-run-card"
      className="rounded border border-emerald-800/50 bg-emerald-950/20 p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex items-baseline gap-2">
          <span className="rounded border border-emerald-700/60 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-300">
            {data.kind}
          </span>
          <span className="text-sm font-medium text-zinc-100">
            {data.label}
          </span>
        </div>
        <span
          className="font-mono text-xs text-emerald-300"
          data-testid="active-run-elapsed"
        >
          {elapsed(since, now)}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs">
        {data.current_step && (
          <span className="text-zinc-300" data-testid="active-run-step">
            <span className="text-zinc-500">step:</span>{" "}
            <span className="font-mono">{data.current_step}</span>
          </span>
        )}
        {hasProgress && (
          <span className="font-mono text-zinc-300" data-testid="active-run-progress">
            {progress!.done ?? "?"}/{progress!.total ?? "?"}
            {progress!.unit ? ` ${progress!.unit}` : ""}
          </span>
        )}
        {data.model && (
          <span className="font-mono text-zinc-500" data-testid="active-run-model">
            {data.model}
          </span>
        )}
      </div>

      {data.narration && (
        <p
          className="mt-2 text-xs text-emerald-200/80"
          data-testid="active-run-narration"
        >
          {data.narration}
        </p>
      )}
    </section>
  );
}
