// Local model activity for Pulse. Live content comes only from the opt-in
// local-model-trace/v1 writer; completed fallback rows come from the existing
// bounded calls.jsonl reader. Endpoint load, GPU activity, or a configured
// model never fabricates a trace.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  getModelIO,
  getModelIODetail,
  getModelTraces,
  type LocalModelTrace,
  type LocalModelTraceResponse,
  type ModelIOCall,
  type ModelIOCallDetail,
  type ModelIOResponse,
} from "../api/modelIO";
import { usePolled } from "../api/pollhub";
import { useNow } from "../time";
import MessageBody from "./payload/MessageBody";
import { splitThought } from "./payload/parse";

const TRACE_STATUSES = new Set([
  "streaming",
  "completed",
  "tool_call",
  "exhausted",
  "no_final",
  "repetition_aborted",
  "transport_error",
  "parser_error",
  "interrupted",
]);
const TRACE_FRESH_SECONDS = 5;

function object(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

function optionalString(value: unknown): boolean {
  return value == null || typeof value === "string";
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** A malformed 200 is unavailable evidence, never an empty/idle trace list. */
export function admitModelTraces(raw: unknown): LocalModelTraceResponse {
  const fail = (): never => {
    throw new Error("Local model trace source is malformed");
  };
  if (
    !object(raw) ||
    raw.schema_version !== 1 ||
    raw.source !== "logs/model_traces" ||
    typeof raw.available !== "boolean" ||
    !Array.isArray(raw.traces) ||
    !finite(raw.skipped_files) ||
    typeof raw.scan_truncated !== "boolean" ||
    typeof raw.generated_at !== "string"
  ) {
    return fail();
  }
  for (const trace of raw.traces) {
    const truncated = object(trace) && object(trace.truncated)
      ? trace.truncated
      : null;
    const freshness = object(trace) && object(trace.freshness)
      ? trace.freshness
      : null;
    if (
      !object(trace) ||
      trace.schema !== "local-model-trace/v1" ||
      ![
        "request_id",
        "model",
        "backend",
        "source",
        "started_at",
        "updated_at",
        "prompt_preview",
        "reasoning_content",
        "content",
      ].every((key) => typeof trace[key] === "string") ||
      !finite(trace.elapsed_s) ||
      typeof trace.prompt_truncated !== "boolean" ||
      typeof trace.status !== "string" ||
      !TRACE_STATUSES.has(trace.status) ||
      !Array.isArray(trace.tool_calls) ||
      !(trace.usage_truncated === undefined || typeof trace.usage_truncated === "boolean") ||
      !optionalString(trace.finish_reason) ||
      !optionalString(trace.error) ||
      truncated == null ||
      !["reasoning_content", "content", "tool_calls"].every(
        (key) => typeof truncated[key] === "boolean",
      ) ||
      freshness == null ||
      !["live", "stale"].includes(String(freshness.state)) ||
      !finite(freshness.age_s)
    ) {
      return fail();
    }
    for (const tool of trace.tool_calls) {
      if (
        !object(tool) ||
        typeof tool.id !== "string" ||
        tool.type !== "function" ||
        !object(tool.function) ||
        typeof tool.function.name !== "string" ||
        typeof tool.function.arguments !== "string"
      ) {
        return fail();
      }
    }
  }
  return raw as unknown as LocalModelTraceResponse;
}

function admitRecentCalls(raw: ModelIOResponse): ModelIOResponse {
  if (!object(raw) || !Array.isArray(raw.calls)) {
    throw new Error("Recorded model-call source is malformed");
  }
  for (const call of raw.calls) {
    if (
      !object(call) ||
      ![
        "ts",
        "request_id",
        "model",
        "backend",
        "caller_tag",
        "completion_preview",
      ].every((key) => optionalString(call[key])) ||
      typeof call.completion_preview !== "string" ||
      typeof call.empty !== "boolean"
    ) {
      throw new Error("Recorded model-call source is malformed");
    }
  }
  return raw;
}

function relativeAge(iso: string | null | undefined, now: number): string {
  const parsed = iso ? Date.parse(iso) : Number.NaN;
  if (!Number.isFinite(parsed)) return "time unknown";
  const seconds = Math.max(0, Math.floor((now - parsed) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `${hours}h ago` : `${Math.floor(hours / 24)}d ago`;
}

function readablePreview(raw: string | null | undefined): string {
  if (!raw?.trim()) return "No answer text recorded";
  const parsed = splitThought(raw);
  const text = parsed?.answer || parsed?.thought || raw;
  return text.trim().replace(/\s+/g, " ");
}

function trailingSnippet(raw: string): string {
  const readable = readablePreview(raw);
  if (readable.length <= 240) return readable;
  return `…${readable.slice(-239)}`;
}

export function traceSnippet(trace: LocalModelTrace): {
  label: string;
  text: string;
} {
  if (trace.content.trim()) {
    return { label: "answer", text: trailingSnippet(trace.content) };
  }
  const latestTool = trace.tool_calls.at(-1);
  if (latestTool) {
    return {
      label: "tool call",
      text: latestTool.function.name || "unnamed function",
    };
  }
  if (trace.reasoning_content.trim()) {
    return {
      label: "reasoning",
      text: trailingSnippet(trace.reasoning_content),
    };
  }
  return { label: "stream", text: "Waiting for emitted content" };
}

function traceIsFresh(
  trace: LocalModelTrace,
  now: number,
  refreshFailed: boolean,
): boolean {
  const updated = Date.parse(trace.updated_at);
  const localAge = Number.isFinite(updated)
    ? Math.max(0, (now - updated) / 1000)
    : Number.POSITIVE_INFINITY;
  return !refreshFailed
    && trace.freshness.state === "live"
    && trace.freshness.age_s <= TRACE_FRESH_SECONDS
    && localAge <= TRACE_FRESH_SECONDS;
}

function traceState(trace: LocalModelTrace, fresh: boolean, paused = false): {
  label: string;
  className: string;
  generating: boolean;
} {
  if (paused) {
    return { label: "● paused snapshot", className: "text-[var(--status-idle)]", generating: false };
  }
  if (trace.status === "streaming" && fresh) {
    return { label: "● streaming", className: "text-[var(--status-ok)]", generating: true };
  }
  if (trace.status === "streaming") {
    return { label: "● stale stream", className: "text-[var(--status-warn)]", generating: false };
  }
  if (["transport_error", "parser_error", "interrupted"].includes(trace.status)) {
    return {
      label: `● ${trace.status.replaceAll("_", " ")}`,
      className: "text-[var(--status-bad)]",
      generating: false,
    };
  }
  const label = trace.status === "completed"
    ? "stream complete"
    : trace.status === "tool_call"
      ? "tool request emitted"
      : trace.status.replaceAll("_", " ");
  return { label: `● ${label}`, className: "text-[var(--status-idle)]", generating: false };
}

function LiveTrace({
  trace,
  now,
  refreshFailed,
}: {
  trace: LocalModelTrace;
  now: number;
  refreshFailed: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [following, setFollowing] = useState(true);
  const [displayTrace, setDisplayTrace] = useState(trace);
  const scrollRef = useRef<HTMLDivElement>(null);
  const shownTrace = following ? trace : displayTrace;
  const snippet = traceSnippet(shownTrace);
  const state = traceState(
    shownTrace,
    traceIsFresh(shownTrace, now, refreshFailed),
    !following,
  );
  useEffect(() => {
    if (following) setDisplayTrace(trace);
  }, [following, trace]);
  useEffect(() => {
    if (open && following && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [following, open, shownTrace]);
  const clipped = Object.entries(shownTrace.truncated)
    .filter(([, value]) => value)
    .map(([key]) => key.replaceAll("_", " "));
  if (shownTrace.usage_truncated) clipped.push("usage");
  if (shownTrace.prompt_truncated) clipped.push("request preview");
  return (
    <div className="rounded border border-[var(--border-2)] bg-[var(--surface-2)] p-3" data-testid="local-model-trace">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
        <span className={`font-mono ${state.className}`} data-testid="local-trace-state">
          {state.label}
        </span>
        <span className="font-mono text-[var(--identity-nemoclaw)]">{shownTrace.model}</span>
        <span className="ml-auto font-mono tabular-nums text-[var(--fg-muted)]">
          {shownTrace.elapsed_s.toFixed(1)}s
        </span>
      </div>
      <div className="mt-2 flex min-w-0 items-baseline gap-2">
        <span className="shrink-0 text-[9px] uppercase tracking-wide text-[var(--fg-muted)]">
          {snippet.label}
        </span>
        <p className="min-w-0 truncate font-mono text-xs text-[var(--fg)]" title={snippet.text}>
          {snippet.text}
        </p>
      </div>
      {!following && (
        <p className="mt-1 text-[11px] text-[var(--fg-muted)]">
          Paused snapshot · updated {relativeAge(shownTrace.updated_at, now)}.
          {trace.request_id !== shownTrace.request_id || trace.updated_at !== shownTrace.updated_at
            ? " Newer stream output is available."
            : ""}
        </p>
      )}
      {following && !state.generating && shownTrace.status === "streaming" && (
        <p className="mt-1 text-[11px] text-[var(--status-warn)]">
          No fresh stream output has arrived. Endpoint activity is reported separately.
        </p>
      )}
      <details
        className="mt-2 group"
        onToggle={(event) => {
          const nextOpen = event.currentTarget.open;
          setOpen(nextOpen);
          if (nextOpen && following) setDisplayTrace(trace);
        }}
      >
        <summary className="cursor-pointer list-none text-[11px] uppercase tracking-wide text-[var(--accent)] hover:text-[var(--accent-hover)]">
          <span className="group-open:hidden">open emitted trace ▸</span>
          <span className="hidden group-open:inline">close emitted trace ▾</span>
        </summary>
        {open && (
          <div className="mt-2" data-testid="local-trace-expanded">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="min-w-0 truncate font-mono text-[10px] text-[var(--fg-muted)]" title={`${shownTrace.source} · ${shownTrace.backend} · ${shownTrace.request_id}`}>
                source {shownTrace.source} · backend {shownTrace.backend}
              </p>
              <button
                type="button"
                aria-pressed={following}
                className="shrink-0 rounded border border-[var(--border-2)] bg-[var(--surface-1)] px-2 py-1 text-[10px] text-[var(--accent)]"
                onClick={() => {
                  setDisplayTrace(trace);
                  setFollowing(!following);
                }}
              >
                {following ? "Pause trace" : "Follow latest"}
              </button>
            </div>
            <div
              ref={scrollRef}
              className="max-h-[32rem] space-y-3 overflow-y-auto pr-1"
              onScroll={(event) => {
                const node = event.currentTarget;
                const fromBottom = node.scrollHeight - node.scrollTop - node.clientHeight;
                if (following && fromBottom > 24) {
                  setDisplayTrace(trace);
                  setFollowing(false);
                }
              }}
            >
            <section>
              <h4 className="mb-1 text-[9px] uppercase tracking-wide text-[var(--fg-muted)]">Request</h4>
              <MessageBody role="user" content={shownTrace.prompt_preview} />
            </section>
            {shownTrace.reasoning_content && (
              <section>
                <h4 className="mb-1 text-[9px] uppercase tracking-wide text-[var(--fg-muted)]">Emitted reasoning</h4>
                <div className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded border-l-2 border-[var(--identity-nemoclaw)] bg-[var(--surface-1)] px-3 py-2 font-mono text-xs leading-relaxed text-[var(--fg)]">
                  {shownTrace.reasoning_content}
                </div>
              </section>
            )}
            {shownTrace.tool_calls.length > 0 && (
              <section>
                <h4 className="mb-1 text-[9px] uppercase tracking-wide text-[var(--fg-muted)]">Tool calls</h4>
                <MessageBody role="assistant" content="" toolCalls={shownTrace.tool_calls} />
              </section>
            )}
            {shownTrace.content && (
              <section>
                <h4 className="mb-1 text-[9px] uppercase tracking-wide text-[var(--fg-muted)]">Answer</h4>
                <MessageBody role="assistant" content={shownTrace.content} />
              </section>
            )}
            {!shownTrace.reasoning_content && !shownTrace.content && shownTrace.tool_calls.length === 0 && (
              <p className="text-xs text-[var(--fg-muted)]">No emitted content in this snapshot.</p>
            )}
            {shownTrace.error && (
              <p className="rounded border border-[var(--status-bad)] bg-[var(--status-bad-bg)] p-2 font-mono text-xs text-[var(--status-bad)]">
                {shownTrace.error}
              </p>
            )}
            {clipped.length > 0 && (
              <p className="text-[11px] text-[var(--status-warn)]" data-testid="local-trace-clipped">
                Snapshot tail retained; cropped: {clipped.join(", ")}.
              </p>
            )}
            <p className="text-[10px] text-[var(--fg-muted)]">
              Stream status describes transport completion only; it does not grade the answer.
            </p>
            </div>
          </div>
        )}
      </details>
    </div>
  );
}

function RecordedCall({ call, now }: { call: ModelIOCall; now: number }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<ModelIOCallDetail | null>(null);
  const [failed, setFailed] = useState(false);
  const requestId = call.request_id;
  const load = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen || detail != null || requestId == null || failed) return;
    void getModelIODetail(requestId).then(
      (response) => setDetail(response.call),
      () => setFailed(true),
    );
  };
  const summary = readablePreview(call.completion_preview || call.prompt_preview);
  return (
    <details
      className="border-t border-zinc-800/60 py-2 first:border-0"
      onToggle={(event) => load(event.currentTarget.open)}
      data-testid="recorded-model-call"
    >
      <summary className="cursor-pointer list-none">
        <div className="flex min-w-0 items-center gap-2 text-xs">
          <span className="shrink-0 font-mono text-zinc-500">{relativeAge(call.ts, now)}</span>
          <span className="min-w-0 truncate font-mono text-sky-300">{call.model ?? "model unknown"}</span>
          <span className="ml-auto shrink-0 text-[10px] uppercase tracking-wide text-zinc-600">
            {open ? "close ▾" : requestId ? "open ▸" : "detail unavailable"}
          </span>
        </div>
        <p className="mt-1 truncate font-mono text-[11px] text-zinc-400" title={summary}>
          {summary}
        </p>
      </summary>
      {open && (
        <div className="mt-2">
          {detail ? (
            <MessageBody
              role="assistant"
              content={detail.completion ?? ""}
              toolCalls={detail.tool_calls}
            />
          ) : failed ? (
            <p className="text-xs text-amber-400">Exact recorded call is outside the readable window or unavailable.</p>
          ) : requestId ? (
            <p className="text-xs text-zinc-500">Loading exact recorded output…</p>
          ) : (
            <p className="text-xs text-zinc-500">This row has no request ID for exact retrieval.</p>
          )}
        </div>
      )}
    </details>
  );
}

export function ModelActivityPanelView({
  traceResponse,
  traceFailed = false,
  calls = [],
  callsFailed = false,
}: {
  traceResponse?: LocalModelTraceResponse;
  traceFailed?: boolean;
  calls?: ModelIOCall[];
  callsFailed?: boolean;
}) {
  const now = useNow(1000);
  const traces = traceResponse?.traces ?? [];
  const selected = useMemo(
    () => traces.find(
      (trace) => trace.status === "streaming"
        && traceIsFresh(trace, now, traceFailed),
    ) ?? traces[0] ?? null,
    [now, traceFailed, traces],
  );
  const liveCount = traces.filter(
    (trace) => trace.status === "streaming"
      && traceIsFresh(trace, now, traceFailed),
  ).length;

  return (
    <section
      className="mt-4 rounded border border-[var(--border-1)] bg-[var(--surface-1)] p-4"
      aria-labelledby="local-model-activity-title"
      data-testid="local-model-activity"
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 id="local-model-activity-title" className="text-sm font-semibold text-[var(--fg)]">
          Local model output
        </h3>
        {liveCount > 0 && (
          <span className="font-mono text-[10px] uppercase tracking-wide text-[var(--status-ok)]">
            {liveCount} live
          </span>
        )}
        <Link className="ml-auto text-[11px] text-[var(--accent)] hover:text-[var(--accent-hover)]" to="/model-io">
          Inspect Model I/O →
        </Link>
      </div>
      <p className="mt-1 text-[11px] text-[var(--fg-muted)]">
        Emitted local-model channels when opt-in capture is active; otherwise, completed calls from the bounded primary log.
      </p>

      <div className="mt-3">
        {traceResponse?.scan_truncated ? (
          <p className="rounded border border-[var(--status-warn)] bg-[var(--status-warn-bg)] p-3 text-xs text-[var(--status-warn)]" data-testid="trace-scan-truncated">
            The trace directory exceeded its bounded scan; current stream output is unknown.
          </p>
        ) : selected ? (
          <LiveTrace trace={selected} now={now} refreshFailed={traceFailed} />
        ) : traceResponse?.available === true ? (
          <p className="rounded border border-zinc-800/60 p-3 text-xs text-zinc-500">
            Live capture is enabled; no instrumented request has been observed.
          </p>
        ) : traceResponse?.available === false ? (
          <p className="rounded border border-zinc-800/60 p-3 text-xs text-zinc-500" data-testid="trace-not-enabled">
            Live stream capture is not enabled. Uninstrumented requests do not appear as live traces.
          </p>
        ) : traceFailed ? (
          <p className="rounded border border-amber-900/50 p-3 text-xs text-amber-400" data-testid="trace-unavailable">
            Live trace reader is unavailable; current stream state is unknown.
          </p>
        ) : (
          <p className="rounded border border-zinc-800/60 p-3 text-xs text-zinc-500">
            Checking live stream capture…
          </p>
        )}
        {traceFailed && selected && (
          <p className="mt-1 text-[11px] text-amber-400">
            Trace refresh failed; the snapshot above is retained and may be older than shown.
          </p>
        )}
      </div>

      <details className="mt-3 group" open={selected == null && calls.length > 0}>
        <summary className="cursor-pointer list-none text-[11px] uppercase tracking-wide text-zinc-500 hover:text-zinc-300">
          <span className="group-open:hidden">recent completed outputs ▸</span>
          <span className="hidden group-open:inline">recent completed outputs ▾</span>
        </summary>
        <div className="mt-1" data-testid="recorded-model-calls">
          {calls.slice(0, 4).map((call, index) => (
            <RecordedCall key={call.request_id ?? `${call.ts ?? "unknown"}-${index}`} call={call} now={now} />
          ))}
          {calls.length === 0 && (
            <p className="py-2 text-xs text-zinc-500">
              {callsFailed
                ? "Recorded call source is unavailable; recent output is unknown."
                : "No completed local model calls were found in the bounded primary log."}
            </p>
          )}
          {callsFailed && calls.length > 0 && (
            <p className="py-1 text-[11px] text-amber-400">
              Recorded-call refresh failed; retained rows may be stale.
            </p>
          )}
        </div>
      </details>
    </section>
  );
}

export default function ModelActivityPanel() {
  const tracePoll = usePolled(
    "pulse:model-traces",
    () => getModelTraces(6).then(admitModelTraces),
    { intervalMs: 1000, initialDelayMs: 150 },
  );
  const callsPoll = usePolled(
    "pulse:model-io-recent",
    () => getModelIO({}, 4).then(admitRecentCalls),
    { intervalMs: 15000, initialDelayMs: 250 },
  );
  return (
    <ModelActivityPanelView
      traceResponse={tracePoll.data}
      traceFailed={tracePoll.failing}
      calls={callsPoll.data?.calls ?? []}
      callsFailed={callsPoll.failing}
    />
  );
}
