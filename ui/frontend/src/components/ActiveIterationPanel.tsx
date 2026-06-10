// LOOP_V0 active-iteration panel. Polls /api/loop_v0/active at 1 Hz and
// renders Nara's current step, narration, elapsed time per step, and the
// list of tool calls so far. The endpoint returns 204 when no iteration
// is in flight; the panel renders "idle" in that case. See
// agent/prompts/ui_session.md §"Active panel".
//
// Step strip (2026-06-10 Task 5): when active_iteration.json carries the new
// optional `steps[]` board ({name, status pending|running|passed|failed|
// skipped, started_at?, ended_at?} — schema/active_iteration.schema.json) the
// strip renders it IN PRODUCER ORDER: meta_review + the 5-step chain
// (hypothesize, retrieve_literature, novelty_classify, critic_loop_v0,
// journal_writer — orchestrator/nara.py:_LOOP_V0_STEPS) with dynamic
// redteam/ml_intern chips inserted by the producer when those sub-loops fire.
// UNKNOWN names render raw — the producer may add steps; the strip never
// filters. When `steps` is absent (every pre-2026-06-10 iteration) the legacy
// static STEP_STRIP below renders unchanged.
import { useEffect, useState } from "react";
import { getActiveIteration } from "../api/http";
import { elapsed, toolDuration, useNow } from "../time";
import type { ActiveIteration, IterationStep } from "../types/schemas";

// LEGACY fallback strip — the pre-steps[] static board. Unchanged on purpose:
// it is what renders for every iteration written before 2026-06-10.
const STEP_STRIP: ReadonlyArray<{ id: string; label: string }> = [
  { id: "starting", label: "start" },
  { id: "nara_thinking", label: "thinking" },
  { id: "summarize_paper", label: "summarize" },
  { id: "play_pd_match", label: "PD match" },
  { id: "query_chroma", label: "retrieve" },
  { id: "journal_writer_stub", label: "journal" },
];

// Compact backend chip — shows "backend · model" when both present, else
// just whichever is set. Used both for the prominent orchestrator chip in
// the header and (divergence-only) per-tool chips.
function BackendChip({
  backend,
  model,
  testid,
  variant = "default",
}: {
  backend?: string | null;
  model?: string | null;
  testid?: string;
  // "default" = neutral zinc; "orchestrator" = emerald-accented for the
  // header chip; "subagent" = sky-accented to call out the Co-Scientist
  // critic-flip surface.
  variant?: "default" | "orchestrator" | "subagent";
}) {
  if (!backend && !model) return null;
  const label = backend && model ? `${backend} · ${model}` : (backend ?? model);
  const classes =
    variant === "orchestrator"
      ? "rounded border border-emerald-800/60 bg-emerald-950/40 px-1.5 py-0.5 font-mono text-[10px] text-emerald-300"
      : variant === "subagent"
        ? "rounded border border-sky-800/60 bg-sky-950/40 px-1.5 py-0.5 font-mono text-[10px] text-sky-300"
        : "rounded border border-zinc-700/60 bg-zinc-900/60 px-1.5 py-0.5 font-mono text-[10px] text-zinc-300";
  return (
    <span className={classes} data-testid={testid}>
      {label}
    </span>
  );
}

// Loop v1 gate-status badge tones (Step 8).
const GATE_TONE: Record<string, string> = {
  pending: "bg-sky-950 text-sky-300",
  valid: "bg-emerald-950 text-emerald-400",
  invalid: "bg-red-950 text-red-400",
  needs_revision: "bg-amber-950 text-amber-400",
};

// Loop v1 Step 2.5 red-team chip. Highlighted red when fatal_flaw or any
// retries were spent; quiet zinc on a clean proceed. Null when absent.
function RedteamChip({ redteam }: { redteam: ActiveIteration["redteam"] }) {
  if (!redteam || (redteam.verdict == null && redteam.retries_used == null)) {
    return null;
  }
  const retries = redteam.retries_used ?? 0;
  const highlight = redteam.verdict === "fatal_flaw" || retries > 0;
  const tone = highlight ? "bg-red-950 text-red-400" : "bg-zinc-800 text-zinc-400";
  const label = `redteam ${redteam.verdict ?? "?"}${
    retries > 0 ? ` · ${retries} retr${retries === 1 ? "y" : "ies"}` : ""
  }`;
  return (
    <span
      data-testid="active-redteam-chip"
      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${tone}`}
    >
      {label}
    </span>
  );
}

// `steps` is producer-owned JSON parsed unchecked: keep only entries that are
// objects with a usable string name. A junk entry degrades to "not on the
// board" rather than a crash; a non-array `steps` yields [] → legacy strip.
function usableSteps(steps: unknown): IterationStep[] {
  if (!Array.isArray(steps)) return [];
  return steps.filter(
    (s): s is IterationStep =>
      s != null &&
      typeof s === "object" &&
      !Array.isArray(s) &&
      typeof (s as { name?: unknown }).name === "string" &&
      (s as { name: string }).name.length > 0,
  );
}

// Duration of a finished step (ended_at - started_at). "" when either
// timestamp is absent/unparseable — the chip then shows no duration rather
// than NaN.
function stepDuration(step: IterationStep): string {
  if (typeof step.started_at !== "string" || typeof step.ended_at !== "string") {
    return "";
  }
  const start = Date.parse(step.started_at);
  const end = Date.parse(step.ended_at);
  if (Number.isNaN(start) || Number.isNaN(end)) return "";
  return `${Math.max(0, (end - start) / 1000).toFixed(1)}s`;
}

// Tones per steps[] status. pending = zinc; running = emerald BORDER with a
// ticking elapsed; passed = quiet emerald + duration; failed = red + duration;
// skipped = dim zinc. An unknown status renders raw in the quiet zinc lane —
// forward-compat, never filtered.
const STEP_STATUS_TONE: Record<string, string> = {
  pending: "border-zinc-800 bg-zinc-900/40 text-zinc-500",
  running: "border-emerald-600 bg-emerald-950/60 text-emerald-300",
  passed: "border-emerald-900/60 bg-emerald-950/30 text-emerald-500",
  failed: "border-red-800 bg-red-950 text-red-400",
  skipped: "border-zinc-800/60 bg-zinc-900/20 text-zinc-600",
};

function stepStatusTone(status: unknown): string {
  // Own-key lookup (the Object.prototype hazard toneFor/SourceBadge guard):
  // a status of "toString" must take the quiet fallback, not a function.
  if (
    typeof status === "string" &&
    Object.prototype.hasOwnProperty.call(STEP_STATUS_TONE, status)
  ) {
    return STEP_STATUS_TONE[status];
  }
  return "border-zinc-800 bg-zinc-900/40 text-zinc-500";
}

// The steps[] board chip strip, in PRODUCER ORDER (array order as emitted —
// never sorted, never filtered by name). Duplicate names are possible (the
// producer may insert redteam more than once), so keys composite the index.
function StepsBoard({ steps, now }: { steps: IterationStep[]; now: number }) {
  return (
    <>
      <ol
        data-testid="steps-board"
        className="mt-2 flex flex-wrap gap-1 text-[10px] uppercase tracking-wide"
      >
        {steps.map((step, i) => {
          const status = typeof step.status === "string" ? step.status : "";
          const running = status === "running";
          const timing = running
            ? elapsed(step.started_at, now)
            : status === "passed" || status === "failed"
              ? stepDuration(step)
              : "";
          return (
            <li
              key={`${step.name}-${i}`}
              data-testid={`board-step-${step.name}`}
              data-status={status || "unknown"}
              className={`rounded border px-1.5 py-0.5 ${stepStatusTone(step.status)}`}
            >
              {step.name}
              {timing && (
                <span className="ml-1 font-mono normal-case">{timing}</span>
              )}
            </li>
          );
        })}
      </ol>
      <div className="mt-1 text-[10px] text-zinc-600" data-testid="steps-caption">
        steps run sequentially within an iteration — concurrency happens across
        runs (see the Now board)
      </div>
    </>
  );
}

function StepStrip({
  current,
  steps,
  now,
}: {
  current: string;
  steps?: ActiveIteration["steps"];
  now: number;
}) {
  // The new steps[] board wins when the producer emitted it; otherwise the
  // legacy static strip renders exactly as before (pre-2026-06-10 fallback).
  const board = usableSteps(steps);
  if (board.length > 0) return <StepsBoard steps={board} now={now} />;
  return (
    <ol className="mt-2 flex flex-wrap gap-1 text-[10px] uppercase tracking-wide">
      {STEP_STRIP.map((step) => {
        const active = step.id === current;
        return (
          <li
            key={step.id}
            data-testid={`step-${step.id}`}
            className={
              active
                ? "rounded border border-emerald-700 bg-emerald-950 px-1.5 py-0.5 text-emerald-300"
                : "rounded border border-zinc-800 bg-zinc-900/40 px-1.5 py-0.5 text-zinc-500"
            }
          >
            {step.label}
          </li>
        );
      })}
    </ol>
  );
}

interface Props {
  // Tests pass a fixture directly; production uses the polling fetch.
  initial?: ActiveIteration | null;
  pollMs?: number;
  // When true, render a single high-level status line (idle / running:
  // <topic> · <step> · elapsed) instead of the full step strip + tool-call
  // detail. The dashboard uses compact mode to stay health-first; the deep
  // view lives on /experiments and the /chain inspector.
  compact?: boolean;
}

function stepLabel(stepId: string): string {
  return STEP_STRIP.find((s) => s.id === stepId)?.label ?? stepId;
}

export default function ActiveIterationPanel({
  initial = undefined,
  pollMs = 1000,
  compact = false,
}: Props) {
  const controlled = initial !== undefined;
  const [data, setData] = useState<ActiveIteration | null>(
    controlled ? initial : null,
  );
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(controlled);
  const now = useNow(pollMs);

  // Controlled mode: the parent (Activity.tsx) lifts the active-iteration
  // poll and feeds it down as `initial` so the page can gate its idle
  // empty-state on it. Keep our state in sync with each new prop value
  // (useState only reads the initializer once). Self-polling is disabled.
  useEffect(() => {
    if (!controlled) return;
    setData(initial ?? null);
    setLoaded(true);
  }, [controlled, initial]);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getActiveIteration()
        .then((d) => {
          if (!active) return;
          setData(d);
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

  if (compact) {
    return (
      <div
        className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded border border-zinc-800 bg-zinc-900/40 px-4 py-2.5 text-sm"
        data-testid="active-iteration-compact"
      >
        <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Active
        </span>
        {error ? (
          <span className="text-xs text-red-400">{error}</span>
        ) : data ? (
          <>
            <span className="font-mono text-[11px] text-emerald-400">● running</span>
            <span className="text-zinc-200">{data.topic}</span>
            <span className="text-zinc-500">·</span>
            <span className="text-zinc-400">{stepLabel(data.current_step)}</span>
            <span className="text-zinc-500">·</span>
            <span className="font-mono text-zinc-300">{elapsed(data.started_at, now)}</span>
          </>
        ) : loaded ? (
          <span className="text-zinc-500">idle — type a topic to start an iteration</span>
        ) : (
          <span className="text-zinc-600">loading…</span>
        )}
      </div>
    );
  }

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4" data-testid="active-iteration-panel">
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Active iteration
        </h2>
        <span className="text-[10px] text-zinc-600">
          /api/loop_v0/active · polling {(pollMs / 1000).toFixed(0)}s
        </span>
        {data && (
          <span className="ml-auto font-mono text-[11px] text-emerald-400">
            ● running
          </span>
        )}
        {loaded && !data && !error && (
          <span className="ml-auto text-[11px] text-zinc-500">idle</span>
        )}
      </div>

      {error && (
        <div className="mt-2 text-xs text-red-400">{error}</div>
      )}

      {!data && loaded && !error && (
        <div className="mt-2 text-sm text-zinc-500">
          No iteration in flight. Type a topic above to start one.
        </div>
      )}

      {data && (
        <>
          <div className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs">
            <span className="text-zinc-500">id</span>
            <span className="flex flex-wrap items-baseline gap-2">
              <span className="font-mono text-zinc-200">{data.iteration_id}</span>
              {/* Prominent orchestrator chip: which model drives Nara for
                  this whole iteration. The chip is the diagnostic for "what
                  brain is in the chair". Per-tool chips below ONLY render on
                  divergence — showing it everywhere would be noise since
                  most tools inherit. */}
              <BackendChip
                backend={data.orchestrator_backend}
                model={data.orchestrator_model}
                variant="orchestrator"
                testid="orchestrator-chip"
              />
            </span>
            <span className="text-zinc-500">topic</span>
            <span className="text-zinc-200">{data.topic}</span>
            <span className="text-zinc-500">elapsed</span>
            <span className="font-mono text-zinc-300">{elapsed(data.started_at, now)}</span>
          </div>

          <StepStrip current={data.current_step} steps={data.steps} now={now} />

          {/* Loop v1 chips: red-team verdict + human-gate status. Render
              only when the producer has populated them (v1 rows). */}
          {(data.redteam || data.gate_status) && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <RedteamChip redteam={data.redteam} />
              {data.gate_status && (
                <span
                  data-testid="active-gate-badge"
                  className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
                    GATE_TONE[data.gate_status] ?? "bg-zinc-800 text-zinc-400"
                  }`}
                >
                  {data.gate_status}
                </span>
              )}
            </div>
          )}

          {(data.meta_review?.conditioning_bullets?.length ?? 0) > 0 && (
            // Loop v1 Step 1.5: the prior-memory bullets conditioning this
            // iteration. Shown up front so the human sees what was carried in.
            <div
              data-testid="active-conditioning"
              className="mt-2 rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5"
            >
              <div className="text-[10px] uppercase tracking-wide text-zinc-500">
                conditioned by
              </div>
              <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-[11px] text-zinc-400">
                {data.meta_review!.conditioning_bullets!.map((bullet, i) => (
                  <li key={i}>{bullet}</li>
                ))}
              </ul>
            </div>
          )}

          {data.latest_narration && (
            <div className="mt-2 rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5 text-xs italic text-zinc-300">
              {data.latest_narration}
            </div>
          )}

          <div className="mt-2">
            <div className="text-[10px] uppercase tracking-wide text-zinc-500">
              tool calls
            </div>
            {(data.tool_calls_so_far?.length ?? 0) === 0 ? (
              <div className="mt-1 text-xs text-zinc-500">none yet</div>
            ) : (
              <ul className="mt-1 space-y-0.5 text-xs">
                {data.tool_calls_so_far!.map((call, i) => {
                  // Divergence-only: render a backend chip ONLY when the
                  // tool's backend differs from the orchestrator's. If most
                  // tools inherit (the common case), the list stays quiet
                  // and the chip MEANS "this step is on a different brain".
                  const divergent =
                    call.backend != null &&
                    data.orchestrator_backend != null &&
                    call.backend !== data.orchestrator_backend;
                  // critic_loop_v0's subagent_backend is the Co-Scientist
                  // surface: when Phase 3 flips the critic to a non-Gemma
                  // backend, this chip is THE diagnostic the human watches.
                  // Render it prominently when present (even if it matches
                  // the orchestrator today, so we can see the wiring).
                  const showSubagent =
                    call.tool === "critic_loop_v0" &&
                    call.subagent_backend != null;
                  return (
                    <li
                      key={`${call.tool}-${i}`}
                      className="flex flex-wrap items-baseline gap-2 font-mono"
                    >
                      <span className="text-zinc-300">{call.tool}</span>
                      <span className="text-zinc-500">{toolDuration(call, now)}</span>
                      <span
                        className={
                          call.status === "passed"
                            ? "text-emerald-400"
                            : call.status === "error"
                              ? "text-red-400"
                              : "text-amber-400"
                        }
                      >
                        {call.status ?? "in_progress"}
                      </span>
                      {divergent && (
                        <BackendChip
                          backend={call.backend}
                          model={call.model}
                          variant="default"
                          testid={`tool-backend-chip-${i}`}
                        />
                      )}
                      {showSubagent && (
                        <BackendChip
                          backend={call.subagent_backend}
                          model={call.subagent_model}
                          variant="subagent"
                          testid={`tool-subagent-chip-${i}`}
                        />
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}
