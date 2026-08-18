// PAGE /model-io — the Model I/O viewer (owner request 2026-08-18).
//
// The health panels show THAT gemma/qwen are alive (KV usage, MTP, decode
// tok/s) but nothing of what actually passes THROUGH them. This page is the
// missing half: the dispatch trace up top (what Nara's orchestrator
// dispatched + which agents were spawned under contract), and below it a
// live, filterable table of wrapper calls out of the MAIN call log —
// model, caller, latency, tokens in/out, an EMPTY flag when a completion
// came back blank, and a click-to-expand full prompt/completion reader.
//
// Honesty rules carried from the rest of the dashboard:
//  - everything is backend-passthrough; a missing field renders as "—",
//    never a guess (backend is never derived from the model name);
//  - a failed poll says the table is STALE/UNKNOWN, keeping the last rows,
//    and a version-skew 404 degrades to the quiet EndpointMissingNote;
//  - the footnote states the ONE log this reads: experiments/bench redirect
//    their calls to runs/*.calls.jsonl (LOOP_V0_CALLS_LOG) and are NOT here.
import { useEffect, useState } from "react";
import Card from "../design/Card";
import EndpointMissingNote, {
  isVersionSkew404,
} from "../components/EndpointMissingNote";
import {
  getDispatchTrace,
  getModelIO,
  getModelIODetail,
  type DispatchTraceResponse,
  type ModelIOCall,
  type ModelIOCallDetail,
  type ModelIOFilters,
  type ModelIOResponse,
} from "../api/modelIO";
import { backendTone, callerTagTone, TONE_QUIET } from "../roles";
import { fmt } from "../format";

// Model badge tone — the SAME color families as the health panels (gemma =
// emerald, qwen = sky, per roles.ts BACKEND_TONE / ModelServerCard accents).
// This colors the model's OWN name by substring of itself; it never invents
// a backend for the row (backend stays its own passthrough chip).
export function modelTone(model: string | null): string {
  if (!model) return TONE_QUIET;
  const m = model.toLowerCase();
  if (m.includes("gemma")) return "bg-emerald-950 text-emerald-300";
  if (m.includes("qwen")) return "bg-sky-950 text-sky-300";
  return TONE_QUIET;
}

// Status tone for trace/spawn chips: done green, broken rose, in-flight sky.
function statusTone(status: string | null): string {
  switch (status) {
    case "passed":
    case "completed":
      return "text-emerald-400";
    case "failed":
    case "error":
    case "rejected":
    case "escalated":
      return "text-rose-400";
    case "dispatched":
    case "running":
    case "spawned":
      return "text-sky-300";
    default:
      return "text-zinc-500";
  }
}

const ROLE_TONE: Record<string, string> = {
  system: "text-zinc-400",
  user: "text-sky-300",
  assistant: "text-emerald-300",
  tool: "text-amber-300",
};

function roleTone(role: string): string {
  return Object.prototype.hasOwnProperty.call(ROLE_TONE, role)
    ? ROLE_TONE[role]
    : "text-zinc-500";
}

// hh:mm:ss (UTC) out of an ISO timestamp — table-density time; the full
// instant rides the title attribute. "—" when absent/short.
function clockTime(ts: string | null): string {
  return ts && ts.length >= 19 ? ts.slice(11, 19) : "—";
}

const INPUT_CLS =
  "rounded border border-zinc-800 bg-zinc-900/60 px-2 py-1 font-mono " +
  "text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 " +
  "focus:outline-none";

// ─── dispatch trace strip ───────────────────────────────────────────────

function TraceStrip({ trace }: { trace: DispatchTraceResponse | null }) {
  if (trace == null) return null;
  return (
    <div
      style={{
        display: "grid",
        gap: "var(--space-4)",
        gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
      }}
    >
      <Card title="Dispatch trace" testId="modelio-trace-tasks">
        {!trace.orchestrator_available ? (
          <div className="text-xs text-zinc-500">
            orchestrator.jsonl absent — no dispatch rows to show.
          </div>
        ) : trace.tasks.length === 0 ? (
          <div className="text-xs text-zinc-500">
            no recent dispatches in the log tail.
          </div>
        ) : (
          <div>
            {trace.tasks.map((t) => (
              <div
                key={t.task_id}
                data-testid="trace-task-row"
                className="flex items-baseline gap-2 border-b border-zinc-800/60 py-1 text-xs last:border-0"
              >
                <span
                  className="truncate font-mono text-zinc-300"
                  style={{ maxWidth: "14rem" }}
                  title={t.task_id}
                >
                  {t.task_id}
                </span>
                <span className="text-zinc-500">{t.task_type ?? "—"}</span>
                <span className={`ml-auto font-mono ${statusTone(t.status)}`}>
                  {t.status ?? "—"}
                </span>
                <span className="font-mono text-zinc-500" title={t.ts ?? ""}>
                  {clockTime(t.ts)}
                </span>
                {t.duration_ms != null && (
                  <span className="font-mono text-zinc-600">
                    {fmt(t.duration_ms, 1)}ms
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
      <Card title="Spawned agents" testId="modelio-trace-spawns">
        {!trace.spawn_available ? (
          <div className="text-xs text-zinc-500">
            spawn ledger absent — no agent contracts to show.
          </div>
        ) : trace.spawns.length === 0 ? (
          <div className="text-xs text-zinc-500">spawn ledger is empty.</div>
        ) : (
          <div>
            {trace.spawns.map((s, i) => (
              <div
                key={`${s.spawn_id ?? "?"}-${s.status ?? "?"}-${i}`}
                data-testid="trace-spawn-row"
                className="border-b border-zinc-800/60 py-1 text-xs last:border-0"
              >
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-zinc-300">
                    {s.spawn_id ?? "—"}
                  </span>
                  <span className={`font-mono ${statusTone(s.status)}`}>
                    {s.status ?? "—"}
                  </span>
                  <span
                    className="ml-auto font-mono text-zinc-500"
                    title={s.ts ?? ""}
                  >
                    {clockTime(s.ts)}
                  </span>
                </div>
                {s.task_statement && (
                  <div className="truncate text-zinc-500" title={s.task_statement}>
                    {s.task_statement}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

// ─── the expanded full prompt/completion reader ─────────────────────────

function CallExpansion({
  detail,
}: {
  detail: ModelIOCallDetail | "loading" | "error";
}) {
  if (detail === "loading") {
    return <div className="py-2 text-xs text-zinc-500">loading full record…</div>;
  }
  if (detail === "error") {
    return (
      <div className="py-2 text-xs text-amber-400/80">
        full record unavailable — it may have aged out of the bounded scan
        window, or the backend is unreachable.
      </div>
    );
  }
  const messages = Array.isArray(detail.prompt_messages)
    ? detail.prompt_messages
    : [];
  return (
    <div className="flex flex-col gap-2 py-2" data-testid="call-expansion">
      {messages.map((m, i) => (
        <div key={i}>
          <div
            className={`text-[10px] font-medium uppercase tracking-wide ${roleTone(m.role)}`}
          >
            {m.role}
          </div>
          <pre
            className="mt-0.5 max-h-64 overflow-y-auto whitespace-pre-wrap rounded border border-zinc-800 bg-zinc-950/60 p-2 font-mono text-xs text-zinc-300"
            data-testid={`message-${m.role}-${i}`}
          >
            {m.content}
          </pre>
        </div>
      ))}
      <div>
        <div className="text-[10px] font-medium uppercase tracking-wide text-fuchsia-300">
          completion
        </div>
        {typeof detail.completion === "string" &&
        detail.completion.trim() !== "" ? (
          <pre
            className="mt-0.5 max-h-64 overflow-y-auto whitespace-pre-wrap rounded border border-zinc-800 bg-zinc-950/60 p-2 font-mono text-xs text-zinc-100"
            data-testid="completion-body"
          >
            {detail.completion}
          </pre>
        ) : (
          <div className="mt-0.5 text-xs text-rose-400">
            EMPTY — the model returned no completion text.
          </div>
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 text-[11px] text-zinc-500">
        {detail.temperature != null && <span>temp {detail.temperature}</span>}
        {detail.seed != null && <span>seed {String(detail.seed)}</span>}
        {detail.parent_request_id && (
          <span className="font-mono">
            parent {detail.parent_request_id}
          </span>
        )}
      </div>
    </div>
  );
}

// ─── the page ───────────────────────────────────────────────────────────

export default function ModelIO({ pollMs = 5000 }: { pollMs?: number }) {
  const [data, setData] = useState<ModelIOResponse | null>(null);
  const [trace, setTrace] = useState<DispatchTraceResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [stale, setStale] = useState(false);
  const [paused, setPaused] = useState(false);
  const [filters, setFilters] = useState<ModelIOFilters>({});
  const [expanded, setExpanded] = useState<string | null>(null);
  const [details, setDetails] = useState<
    Record<string, ModelIOCallDetail | "loading" | "error">
  >({});

  // One effect owns both polls; pausing tears the interval down (the last
  // rows stay on screen, labelled paused). A filter change re-runs the
  // effect → immediate refetch with the new params.
  useEffect(() => {
    if (paused) return;
    let on = true;
    const load = () => {
      getModelIO(filters)
        .then((r) => {
          if (!on) return;
          setData(r);
          setError(null);
          setStale(false);
        })
        .catch((e) => {
          if (!on) return;
          // Keep the last rows; say they are stale rather than blanking.
          setError(e);
          setStale(true);
        });
      getDispatchTrace()
        .then((r) => {
          if (on) setTrace(r);
        })
        .catch(() => {
          /* the strip keeps its last state; the table's error line covers
             the unreachable-backend case */
        });
    };
    load();
    const id = setInterval(load, pollMs);
    return () => {
      on = false;
      clearInterval(id);
    };
  }, [paused, filters, pollMs]);

  const toggleRow = (requestId: string | null) => {
    if (!requestId) return;
    if (expanded === requestId) {
      setExpanded(null);
      return;
    }
    setExpanded(requestId);
    if (details[requestId] === undefined) {
      setDetails((d) => ({ ...d, [requestId]: "loading" }));
      getModelIODetail(requestId)
        .then((r) =>
          setDetails((d) => ({ ...d, [requestId]: r.call ?? "error" })),
        )
        .catch(() =>
          setDetails((d) => ({ ...d, [requestId]: "error" })),
        );
    }
  };

  const calls = data?.calls ?? [];
  const skew =
    isVersionSkew404(error, "/api/model_io") && calls.length === 0;

  return (
    <div className="page-full" data-testid="modelio-page">
      <div className="mb-3 flex flex-wrap items-baseline gap-3">
        <h2 className="text-sm font-medium text-zinc-200">Model I/O</h2>
        <span className="text-xs text-zinc-500">
          what is actually passing through gemma & qwen — live off{" "}
          <span className="font-mono">logs/calls.jsonl</span>
        </span>
      </div>

      {/* Top strip: the nara chain (orchestrator triples) + spawned agents. */}
      <TraceStrip trace={trace} />

      {/* Filters + live-state controls. */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <input
          className={INPUT_CLS}
          placeholder="model (substring)"
          aria-label="filter by model"
          value={filters.model ?? ""}
          onChange={(e) =>
            setFilters((f) => ({ ...f, model: e.target.value || undefined }))
          }
        />
        <input
          className={INPUT_CLS}
          placeholder="caller_tag (substring)"
          aria-label="filter by caller tag"
          value={filters.callerTag ?? ""}
          onChange={(e) =>
            setFilters((f) => ({
              ...f,
              callerTag: e.target.value || undefined,
            }))
          }
        />
        <input
          className={INPUT_CLS}
          placeholder="run_id (exact)"
          aria-label="filter by run id"
          value={filters.runId ?? ""}
          onChange={(e) =>
            setFilters((f) => ({ ...f, runId: e.target.value || undefined }))
          }
        />
        <button
          type="button"
          className="ml-auto rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:border-zinc-500"
          aria-pressed={paused}
          onClick={() => setPaused((p) => !p)}
        >
          {paused ? "resume" : "pause"}
        </button>
        <span className="text-[11px] text-zinc-600">
          {paused ? "paused" : `polling every ${Math.round(pollMs / 1000)}s`}
        </span>
      </div>

      {/* Honest degradations, in order of severity. */}
      {skew ? (
        <div className="mt-3">
          <EndpointMissingNote endpoint="/api/model_io" />
        </div>
      ) : (
        <>
          {stale && (
            <div className="mt-2 text-xs text-amber-400/80">
              /api/model_io unreachable — showing the last loaded rows; the
              live state is UNKNOWN, not idle.
            </div>
          )}
          {data?.window_truncated && (
            <div className="mt-2 text-xs text-zinc-500">
              scan window truncated at {data.max_scan_bytes} bytes — older
              matching calls may exist beyond it.
            </div>
          )}

          <Card className="mt-3" testId="modelio-table">
            {calls.length === 0 && data != null ? (
              <div className="text-xs text-zinc-500">
                no calls match in the log tail.
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                {calls.map((c, i) => (
                  <CallRow
                    key={c.request_id ?? `${c.ts ?? "row"}-${i}`}
                    call={c}
                    expanded={expanded != null && expanded === c.request_id}
                    detail={
                      c.request_id ? details[c.request_id] : undefined
                    }
                    onToggle={() => toggleRow(c.request_id)}
                  />
                ))}
              </div>
            )}
          </Card>
        </>
      )}

      {/* The one-log footnote — this slice reads the MAIN log only. */}
      <div className="mt-3 text-[11px] text-zinc-600" data-testid="modelio-footnote">
        reads the main log <span className="font-mono">logs/calls.jsonl</span>{" "}
        only — experiment/bench runs redirect their calls to their own{" "}
        <span className="font-mono">runs/*.calls.jsonl</span> (via
        LOOP_V0_CALLS_LOG) and are not shown here; a log picker is future
        work.
      </div>
    </div>
  );
}

function CallRow({
  call,
  expanded,
  detail,
  onToggle,
}: {
  call: ModelIOCall;
  expanded: boolean;
  detail: ModelIOCallDetail | "loading" | "error" | undefined;
  onToggle: () => void;
}) {
  return (
    <div className="border-b border-zinc-800/60 last:border-0">
      <div
        role="button"
        tabIndex={0}
        data-testid="modelio-row"
        className="flex cursor-pointer flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1.5 text-xs hover:bg-zinc-900/50"
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggle();
          }
        }}
      >
        <span className="font-mono text-zinc-500" title={call.ts ?? ""}>
          {clockTime(call.ts)}
        </span>
        <span
          className={`rounded px-1.5 py-0.5 font-mono text-[11px] ${modelTone(call.model)}`}
        >
          {call.model ?? "—"}
        </span>
        {call.backend && (
          <span
            className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${backendTone(call.backend)}`}
          >
            {call.backend}
          </span>
        )}
        <span className={`font-mono ${callerTagTone(call.caller_tag)}`}>
          {call.caller_tag ?? "—"}
        </span>
        {call.run_id && (
          <span className="font-mono text-zinc-600">{call.run_id}</span>
        )}
        <span className="ml-auto font-mono tabular-nums text-zinc-400">
          {call.latency_ms != null ? `${fmt(call.latency_ms, 0)}ms` : "—"}
        </span>
        <span className="font-mono tabular-nums text-zinc-500">
          {call.input_tokens ?? "—"}→{call.output_tokens ?? "—"} tok
        </span>
        {call.empty && (
          <span
            className="rounded bg-rose-950 px-1.5 py-0.5 font-mono text-[10px] text-rose-300"
            data-testid="empty-flag"
          >
            EMPTY
          </span>
        )}
        <span className="w-full truncate text-zinc-600">
          {call.completion_preview || call.prompt_preview || ""}
        </span>
      </div>
      {expanded && <CallExpansion detail={detail ?? "loading"} />}
    </div>
  );
}
