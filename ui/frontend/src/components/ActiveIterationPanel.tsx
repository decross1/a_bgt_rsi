// LOOP_V0 active-iteration panel. Polls /api/loop_v0/active at 1 Hz and
// renders Nara's current step, narration, elapsed time per step, and the
// list of tool calls so far. The endpoint returns 204 when no iteration
// is in flight; the panel renders "idle" in that case. See
// agent/prompts/ui_session.md §"Active panel".
import { useEffect, useState } from "react";
import { getActiveIteration } from "../api/http";
import type { ActiveIteration, LoopV0ToolCall } from "../types/schemas";

const STEP_STRIP: ReadonlyArray<{ id: string; label: string }> = [
  { id: "starting", label: "start" },
  { id: "nara_thinking", label: "thinking" },
  { id: "summarize_paper", label: "summarize" },
  { id: "play_pd_match", label: "PD match" },
  { id: "query_chroma", label: "retrieve" },
  { id: "journal_writer_stub", label: "journal" },
];

function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

function elapsed(fromIso: string | null | undefined, nowMs: number): string {
  if (!fromIso) return "—";
  const t = Date.parse(fromIso);
  if (Number.isNaN(t)) return "—";
  const s = Math.max(0, (nowMs - t) / 1000);
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${(s - m * 60).toFixed(0)}s`;
}

function toolDuration(call: LoopV0ToolCall, nowMs: number): string {
  const start = Date.parse(call.started_at);
  if (Number.isNaN(start)) return "—";
  const end = call.ended_at ? Date.parse(call.ended_at) : nowMs;
  const s = Math.max(0, (end - start) / 1000);
  return `${s.toFixed(1)}s`;
}

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

function StepStrip({ current }: { current: string }) {
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
}

export default function ActiveIterationPanel({ initial = undefined, pollMs = 1000 }: Props) {
  const [data, setData] = useState<ActiveIteration | null>(
    initial === undefined ? null : initial,
  );
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(initial !== undefined);
  const now = useNow(pollMs);

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

          <StepStrip current={data.current_step} />

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
