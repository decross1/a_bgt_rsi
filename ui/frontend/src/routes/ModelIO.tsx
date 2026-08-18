// PAGE /model-io — the Model I/O viewer (owner request 2026-08-18).
//
// The health panels show THAT gemma/qwen are alive (KV usage, MTP, decode
// tok/s) but nothing of what actually passes THROUGH them. This page is the
// missing half: ONE compact runtime-activity strip up top, and below it a
// live, filterable table of wrapper calls out of the MAIN call log —
// model, caller, latency, tokens in/out, an EMPTY flag when a completion
// came back blank, and a click-to-expand full prompt/completion reader.
//
// The strip (owner feedback 2026-08-18: "is that ACTUALLY spawned agents?")
// separates the two planes the old top cards conflated:
//  - RUNTIME plane (primary): Nara's latest chain tasks (orchestrator.jsonl
//    triples) + recent SUBAGENT WORK grouped by caller_tag family out of
//    calls.jsonl (/api/runtime_activity — grouping is caller_tag /
//    parent_request_id / run_id evidence, never invented);
//  - DEV plane (collapsed by default): the Claude-Code build-agent spawn
//    ledger (run_state/spawn.jsonl via /api/dispatch_trace), explicitly
//    labelled as dev-side, one line per entry, no contract prose.
//
// Honesty rules carried from the rest of the dashboard:
//  - everything is backend-passthrough; a missing field renders as "—",
//    never a guess (backend is never derived from the model name);
//  - a failed poll says the table is STALE/UNKNOWN, keeping the last rows,
//    and a version-skew 404 degrades to the quiet EndpointMissingNote;
//  - the footnote states the ONE log this reads: experiments/bench redirect
//    their calls to runs/*.calls.jsonl (LOOP_V0_CALLS_LOG) and are NOT here.
//
// Owner feedback 2026-08-18 on the list rows ("love the tags, the preview
// subtext is basically jibberish" + "show only last 20"): row previews are
// sanitized through parse.ts's channel grammar (see sanitizePreview), and
// the table pages — newest 20 live, a "load older ▾" walk via before_ts
// that reports the byte cap honestly when it stops the scan.
import { useEffect, useRef, useState } from "react";
import Card from "../design/Card";
import EmptyCompletionNote from "../components/payload/EmptyCompletionNote";
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
import MessageBody from "../components/payload/MessageBody";
import RoleChip from "../components/payload/RoleChip";
import { splitThought } from "../components/payload/parse";
import { CHIP_CLS } from "../components/payload/bits";

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

// The same status families as dots (the chain lines carry a dot, not a
// status word — one-line density; the word rides the title attribute).
function statusDotTone(status: string | null): string {
  switch (status) {
    case "passed":
    case "completed":
      return "bg-emerald-400";
    case "failed":
    case "error":
    case "rejected":
    case "escalated":
      return "bg-rose-400";
    case "dispatched":
    case "running":
    case "spawned":
      return "bg-sky-300";
    default:
      return "bg-zinc-600";
  }
}

function StatusDot({ status }: { status: string | null }) {
  return (
    <span
      aria-hidden
      className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${statusDotTone(status)}`}
    />
  );
}

// Compact age ("3m") from an ISO timestamp. Exported for unit tests; the
// nowMs parameter exists so tests never race the clock.
export function ageOf(
  ts: string | null | undefined,
  nowMs: number = Date.now(),
): string {
  if (!ts) return "—";
  const t = Date.parse(ts);
  if (Number.isNaN(t)) return "—";
  const s = Math.max(0, Math.floor((nowMs - t) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
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

// ─── preview sanitization ───────────────────────────────────────────────
//
// Owner feedback 2026-08-18 on the list rows: the tags are right but the
// preview subtext "is basically jibberish" — raw channel markup
// (`thought <|channel>thought <channel|>This iteration investigated…`)
// leaked into completion_preview. parse.ts owns the thought/channel grammar
// (ported from agent_wrapper/cleanup.py); this helper only adapts it to the
// backend's 200-char TRUNCATED preview slices. Rules:
//  - visible (non-thought) text exists → show ONLY that;
//  - ONLY thought text exists → mark it (dim "thought" chip in the row) and
//    show the cleaned prose — a raw <|channel> token never renders;
//  - the truncation can cut a token mid-way → a trailing "<" fragment is
//    stripped defensively before parsing.

export interface PreviewView {
  text: string;
  /** True when the ONLY content is thought-channel prose (the chip case). */
  thought: boolean;
}

// A trailing "<" fragment that looks like the START of a channel token cut
// by the 200-char preview truncation: "<", "<|", "<chan", "<|channel",
// "<channel|". The letter-only body keeps legit prose like "x < 5" intact
// (a space or digit after "<" never matches).
const PARTIAL_TOKEN_RE = /<\|?[a-z]*\|?$/i;
// parse.ts's channel-token shape (kept private there); used here only to
// recognize a preview that is NOTHING BUT markup → no preview at all.
const TOKEN_RE = /<\|?(?:channel|analysis|final|message)\|?>/i;
// A lone channel-label word is markup residue, not prose. splitThought
// keeps pre-token prose visible by design (cleanup.py's stance), but a
// preview whose "visible" part is ONLY the label word (the
// `thought\n<|channel>…` shape the owner pasted) reads as junk — label-only
// chunks are dropped from the preview here (display-only; the expanded
// reader still shows everything).
const LONE_LABEL_RE = /^(thought|analysis|final|commentary|message)$/i;

export function sanitizePreview(
  raw: string | null | undefined,
): PreviewView | null {
  if (!raw) return null;
  const cut = raw.replace(PARTIAL_TOKEN_RE, "");
  const split = splitThought(cut);
  if (split == null) {
    // Either no channel markup at all (plain prose passes through), or
    // nothing but markup remained — which is no preview, not raw tokens.
    if (TOKEN_RE.test(cut)) return null;
    const text = cut.trim();
    return text === "" ? null : { text, thought: false };
  }
  const answer = split.answer
    .split("\n\n")
    .filter((c) => c.trim() !== "" && !LONE_LABEL_RE.test(c.trim()))
    .join("\n\n");
  if (answer !== "") return { text: answer, thought: false };
  if (split.thought !== "") return { text: split.thought, thought: true };
  return null;
}

// ─── runtime activity strip ─────────────────────────────────────────────
//
// Local types + fetcher for /api/runtime_activity: this build owns only
// this route file, so the endpoint's client lives here rather than widening
// api/modelIO.ts (same API_BASE derivation).

interface ChainTask {
  task_id: string;
  task_type: string | null;
  status: string | null;
  stage: string | null;
  duration_ms: number | null;
  ts: string | null;
  run_id: string | null;
}

interface SubagentGroup {
  family: string;
  label: string;
  group_key: string | null;
  key_source: string | null;
  calls: number;
  models: string[];
  caller_tags: string[];
  first_ts: string | null;
  last_ts: string | null;
}

interface RuntimeActivityResponse {
  orchestrator_available: boolean;
  calls_available: boolean;
  chain: ChainTask[];
  subagent_groups: SubagentGroup[];
  window_truncated: boolean;
  generated_at: string;
}

const RUNTIME_API_PORT = import.meta.env.VITE_API_PORT ?? "8700";
const RUNTIME_API_BASE = `http://${window.location.hostname}:${RUNTIME_API_PORT}`;

async function getRuntimeActivity(): Promise<RuntimeActivityResponse> {
  const resp = await fetch(`${RUNTIME_API_BASE}/api/runtime_activity`);
  if (!resp.ok) throw new Error(`runtime_activity ${resp.status}`);
  return (await resp.json()) as RuntimeActivityResponse;
}

// ─── pagination (owner 2026-08-18: "show only last 20 interactions" +
//     a load-older walk) ────────────────────────────────────────────────

const PAGE_SIZE = 20;

// Older pages go through a LOCAL fetcher (the getRuntimeActivity reasoning:
// this build owns only this route file, so the before_ts param does not
// widen the shared api/modelIO.ts client).
async function getOlderModelIO(
  filters: ModelIOFilters,
  beforeTs: string,
): Promise<ModelIOResponse> {
  const params = new URLSearchParams({
    limit: String(PAGE_SIZE),
    before_ts: beforeTs,
  });
  if (filters.model) params.set("model", filters.model);
  if (filters.callerTag) params.set("caller_tag", filters.callerTag);
  if (filters.runId) params.set("run_id", filters.runId);
  const resp = await fetch(
    `${RUNTIME_API_BASE}/api/model_io?${params.toString()}`,
  );
  if (!resp.ok) throw new Error(`model_io ${resp.status}`);
  return (await resp.json()) as ModelIOResponse;
}

// The load-older control's state machine: idle (button) → loading →
// idle | end (file start reached) | capped (byte cap stopped the scan —
// reported honestly, never a silent stop) | error (button retries).
type PagerState = "idle" | "loading" | "end" | "capped" | "error";

const CHAIN_LINES = 6;
const PLANE_LABEL_CLS =
  "text-[10px] uppercase tracking-wide text-zinc-500";

function RuntimeStrip({
  activity,
  trace,
}: {
  activity: RuntimeActivityResponse | null;
  trace: DispatchTraceResponse | null;
}) {
  // The dev-side build-agent ledger is a DIFFERENT plane — collapsed by
  // default so the strip reads as runtime-only unless explicitly opened.
  const [devOpen, setDevOpen] = useState(false);
  // Defensive: an old backend (version skew) answers with a foreign body;
  // render placeholders rather than crash.
  const chain = Array.isArray(activity?.chain) ? activity.chain : [];
  const groups = Array.isArray(activity?.subagent_groups)
    ? activity.subagent_groups
    : [];
  const spawns = trace?.spawns ?? [];
  return (
    <Card title="Runtime activity" testId="modelio-runtime-strip">
      {activity == null ? (
        <div className="text-xs text-zinc-500">
          /api/runtime_activity not loaded — runtime state UNKNOWN, not idle.
        </div>
      ) : (
        <>
          {/* (a) Nara's chain: latest orchestrator tasks, one line each —
              status dot + station name + age. */}
          <div
            className="flex flex-wrap items-center gap-x-4 gap-y-1"
            data-testid="runtime-chain"
          >
            <span className={PLANE_LABEL_CLS}>nara chain</span>
            {!activity.orchestrator_available ? (
              <span className="text-xs text-zinc-600">
                orchestrator.jsonl absent
              </span>
            ) : chain.length === 0 ? (
              <span className="text-xs text-zinc-600">
                no recent dispatches in the log tail
              </span>
            ) : (
              chain.slice(0, CHAIN_LINES).map((t) => (
                <span
                  key={t.task_id}
                  data-testid="chain-line"
                  className="flex items-center gap-1.5 font-mono text-xs text-zinc-300"
                  title={`${t.task_id} — ${t.status ?? "?"}${
                    t.stage ? ` (${t.stage})` : ""
                  }`}
                >
                  <StatusDot status={t.status} />
                  {t.task_type ?? t.task_id}
                  <span className="text-zinc-600">{ageOf(t.ts)}</span>
                </span>
              ))
            )}
          </div>

          {/* (b) Subagent work: one compact card per caller_tag-family
              group — label + model badge(s) + call count + age. */}
          <div
            className="mt-2 flex flex-wrap items-center gap-2"
            data-testid="runtime-subagents"
          >
            <span className={PLANE_LABEL_CLS}>subagent work</span>
            {groups.length === 0 ? (
              <span className="text-xs text-zinc-600">
                no subagent work in the recent log tail
              </span>
            ) : (
              groups.map((g) => (
                <span
                  key={`${g.family}-${g.group_key ?? "?"}`}
                  data-testid="subagent-group"
                  className="flex items-center gap-1.5 rounded border border-zinc-800 bg-zinc-900/50 px-2 py-0.5 text-xs"
                  title={`${(g.caller_tags ?? []).join(", ")}${
                    g.group_key ? ` — ${g.group_key}` : ""
                  }`}
                >
                  <span className="text-zinc-200">{g.label}</span>
                  {(g.models ?? []).map((m) => (
                    <span
                      key={m}
                      className={`rounded px-1 font-mono text-[10px] ${modelTone(m)}`}
                    >
                      {m}
                    </span>
                  ))}
                  <span className="font-mono text-zinc-500">
                    {g.calls} calls
                  </span>
                  <span className="font-mono text-zinc-600">
                    {ageOf(g.last_ts)}
                  </span>
                </span>
              ))
            )}
          </div>
        </>
      )}

      {/* DEV plane: the Claude-Code build-agent spawn ledger, explicitly
          labelled and collapsed by default. One line per entry; the
          contract statement rides the title attribute only — no prose. */}
      <div className="mt-2 border-t border-zinc-800/60 pt-1.5">
        <button
          type="button"
          data-testid="dev-spawn-toggle"
          aria-expanded={devOpen}
          className="text-[11px] text-zinc-500 hover:text-zinc-300"
          onClick={() => setDevOpen((o) => !o)}
        >
          {devOpen ? "▾" : "▸"} build agents (dev — Claude Code workflow
          ledger)
        </button>
        {devOpen &&
          (trace == null || !trace.spawn_available ? (
            <div className="mt-1 text-xs text-zinc-600">
              spawn ledger unavailable.
            </div>
          ) : spawns.length === 0 ? (
            <div className="mt-1 text-xs text-zinc-600">
              spawn ledger is empty.
            </div>
          ) : (
            <div className="mt-1">
              {spawns.map((s, i) => (
                <div
                  key={`${s.spawn_id ?? "?"}-${s.status ?? "?"}-${i}`}
                  data-testid="dev-spawn-row"
                  className="flex items-baseline gap-2 py-0.5 text-xs"
                  title={s.task_statement ?? undefined}
                >
                  <span
                    className="truncate font-mono text-zinc-400"
                    style={{ maxWidth: "18rem" }}
                  >
                    {s.spawn_id ?? "—"}
                  </span>
                  <span className={`font-mono ${statusTone(s.status)}`}>
                    {s.status ?? "—"}
                  </span>
                  <span
                    className="ml-auto font-mono text-zinc-600"
                    title={s.ts ?? ""}
                  >
                    {ageOf(s.ts)}
                  </span>
                </div>
              ))}
            </div>
          ))}
      </div>
    </Card>
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
    <div className="flex flex-col gap-1.5 py-2" data-testid="call-expansion">
      {messages.map((m, i) => (
        <div
          key={i}
          className="rounded border border-zinc-800/60 bg-zinc-950/40 p-1.5"
        >
          <div className="mb-1">
            <RoleChip role={m.role} />
          </div>
          <MessageBody
            role={m.role}
            content={m.content}
            toolCalls={(m as { tool_calls?: unknown }).tool_calls}
            testId={`message-${m.role}-${i}`}
          />
        </div>
      ))}
      <div className="rounded border border-zinc-800/60 bg-zinc-950/40 p-1.5">
        <div className="mb-1">
          <RoleChip role="completion" />
        </div>
        {typeof detail.completion === "string" &&
        detail.completion.trim() !== "" ? (
          <MessageBody
            role="assistant"
            content={detail.completion}
            testId="completion-body"
          />
        ) : (
          <EmptyCompletionNote messages={detail.prompt_messages} />
        )}
      </div>
      {/* Metadata as ONE compact chip row (density pass) — only fields the
          backend actually handed over ever render. */}
      <div className="flex flex-wrap items-center gap-1.5" data-testid="meta-chips">
        {detail.latency_ms != null && (
          <span className={CHIP_CLS}>lat {fmt(detail.latency_ms, 0)}ms</span>
        )}
        {detail.usage?.input_tokens != null && (
          <span className={CHIP_CLS}>in {detail.usage.input_tokens} tok</span>
        )}
        {detail.usage?.output_tokens != null && (
          <span className={CHIP_CLS}>out {detail.usage.output_tokens} tok</span>
        )}
        {detail.temperature != null && (
          <span className={CHIP_CLS}>temp {detail.temperature}</span>
        )}
        {detail.seed != null && (
          <span className={CHIP_CLS}>seed {String(detail.seed)}</span>
        )}
        {detail.request_id && (
          <span className={CHIP_CLS}>req {detail.request_id}</span>
        )}
        {detail.parent_request_id && (
          <span className={CHIP_CLS}>parent {detail.parent_request_id}</span>
        )}
      </div>
    </div>
  );
}

// ─── the page ───────────────────────────────────────────────────────────

export default function ModelIO({ pollMs = 5000 }: { pollMs?: number }) {
  const [data, setData] = useState<ModelIOResponse | null>(null);
  const [trace, setTrace] = useState<DispatchTraceResponse | null>(null);
  const [activity, setActivity] = useState<RuntimeActivityResponse | null>(
    null,
  );
  const [error, setError] = useState<unknown>(null);
  const [stale, setStale] = useState(false);
  const [paused, setPaused] = useState(false);
  const [filters, setFilters] = useState<ModelIOFilters>({});
  const [expanded, setExpanded] = useState<string | null>(null);
  const [details, setDetails] = useState<
    Record<string, ModelIOCallDetail | "loading" | "error">
  >({});
  // Paged-older rows (appended, poll-stable) + the load-older control's
  // state. hasPagedRef gates the poll's dropped-row retention; newestRef
  // mirrors the last newest page so the retention never re-sorts.
  const [older, setOlder] = useState<ModelIOCall[]>([]);
  const [pager, setPager] = useState<PagerState>("idle");
  const hasPagedRef = useRef(false);
  const newestRef = useRef<ModelIOCall[]>([]);

  // A filter change invalidates the appended pages (they were fetched
  // under the OLD filter); pause/resume deliberately does not.
  useEffect(() => {
    setOlder([]);
    setPager("idle");
    hasPagedRef.current = false;
  }, [filters]);

  // One effect owns both polls; pausing tears the interval down (the last
  // rows stay on screen, labelled paused). A filter change re-runs the
  // effect → immediate refetch with the new params. The poll refreshes the
  // NEWEST page only — paged-older rows stay appended untouched.
  useEffect(() => {
    if (paused) return;
    let on = true;
    const load = () => {
      getModelIO(filters, PAGE_SIZE)
        .then((r) => {
          if (!on) return;
          // Once older pages are appended, rows that new arrivals push out
          // of the newest page are RETAINED by moving them onto the older
          // list — no gap between the pages, no re-sort (they were already
          // in newest-first order directly below the fresh page).
          if (hasPagedRef.current) {
            const freshIds = new Set(
              r.calls
                .map((c) => c.request_id)
                .filter((id): id is string => id != null),
            );
            const dropped = newestRef.current.filter(
              (c) => c.request_id != null && !freshIds.has(c.request_id),
            );
            if (dropped.length > 0) {
              setOlder((prev) => {
                const seen = new Set(prev.map((c) => c.request_id));
                return [
                  ...dropped.filter((c) => !seen.has(c.request_id)),
                  ...prev,
                ];
              });
            }
          }
          newestRef.current = r.calls;
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
      getRuntimeActivity()
        .then((r) => {
          if (on) setActivity(r);
        })
        .catch(() => {
          /* same quiet degradation: the strip keeps its last state (or its
             honest "not loaded" line) on 404/skew/unreachable */
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

  // Newest page first, then the appended older pages, deduped by
  // request_id (newest page wins) — never re-sorted.
  const newest = data?.calls ?? [];
  const newestIds = new Set(
    newest.map((c) => c.request_id).filter((id): id is string => id != null),
  );
  const calls = [
    ...newest,
    ...older.filter(
      (c) => c.request_id == null || !newestIds.has(c.request_id),
    ),
  ];
  const skew =
    isVersionSkew404(error, "/api/model_io") && calls.length === 0;

  const loadOlder = () => {
    if (pager === "loading") return;
    // The boundary is the OLDEST visible row that carries a timestamp —
    // the backend pages rows strictly older than it.
    let boundary: string | null = null;
    for (let i = calls.length - 1; i >= 0; i--) {
      const ts = calls[i].ts;
      if (ts) {
        boundary = ts;
        break;
      }
    }
    if (boundary == null) return;
    hasPagedRef.current = true;
    setPager("loading");
    getOlderModelIO(filters, boundary)
      .then((r) => {
        setOlder((prev) => {
          const seen = new Set(
            [...newestRef.current, ...prev]
              .map((c) => c.request_id)
              .filter((id): id is string => id != null),
          );
          const fresh = r.calls.filter(
            (c) => c.request_id == null || !seen.has(c.request_id),
          );
          return [...prev, ...fresh];
        });
        if (r.window_truncated) setPager("capped");
        else if (r.calls.length < PAGE_SIZE) setPager("end");
        else setPager("idle");
      })
      .catch(() => setPager("error"));
  };

  return (
    <div className="page-full" data-testid="modelio-page">
      <div className="mb-3 flex flex-wrap items-baseline gap-3">
        <h2 className="text-sm font-medium text-zinc-200">Model I/O</h2>
        <span className="text-xs text-zinc-500">
          what is actually passing through gemma & qwen — live off{" "}
          <span className="font-mono">logs/calls.jsonl</span>
        </span>
      </div>

      {/* Top strip: ONE runtime-activity card — nara chain + subagent
          work, with the dev spawn ledger behind a collapsed toggle. */}
      <RuntimeStrip activity={activity} trace={trace} />

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

          {/* Load-older pager: appends the next PAGE_SIZE rows strictly
              older than the oldest visible row. The end states are
              HONEST: file start = "beginning of log", byte cap = "older
              rows beyond scan window" — never a silent stop. */}
          {calls.length > 0 && (
            <div
              className="mt-2 flex flex-wrap items-center gap-2"
              data-testid="modelio-pager"
            >
              {pager === "capped" ? (
                <span
                  className="text-xs text-zinc-500"
                  data-testid="pager-capped"
                >
                  older rows beyond scan window — the bounded backward scan
                  stopped at its byte cap
                  {data ? ` (${data.max_scan_bytes} bytes)` : ""}.
                </span>
              ) : pager === "end" ? (
                <span
                  className="text-xs text-zinc-600"
                  data-testid="pager-end"
                >
                  beginning of log reached — no older rows.
                </span>
              ) : (
                <button
                  type="button"
                  data-testid="load-older"
                  disabled={pager === "loading"}
                  className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:border-zinc-500 disabled:opacity-50"
                  onClick={loadOlder}
                >
                  {pager === "loading" ? "loading…" : "load older ▾"}
                </button>
              )}
              {pager === "error" && (
                <span className="text-xs text-amber-400/80">
                  older-page fetch failed — the button retries.
                </span>
              )}
              <span className="text-[11px] text-zinc-600">
                showing {calls.length} rows — newest {PAGE_SIZE} refresh
                live, paged rows stay appended
              </span>
            </div>
          )}
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
  // Sanitized preview: completion first, prompt as the fallback (both run
  // through the channel-grammar splitter — raw <|channel> tokens never
  // reach the row). The tag chips above are untouched.
  const preview =
    sanitizePreview(call.completion_preview) ??
    sanitizePreview(call.prompt_preview);
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
        <span className="flex w-full min-w-0 items-baseline gap-1.5">
          {preview?.thought && (
            <span
              data-testid="thought-chip"
              className="shrink-0 rounded bg-zinc-900 px-1 font-mono text-[10px] text-zinc-500"
            >
              thought
            </span>
          )}
          <span
            className="min-w-0 flex-1 truncate text-zinc-600"
            data-testid="row-preview"
          >
            {preview?.text ?? ""}
          </span>
        </span>
      </div>
      {expanded && <CallExpansion detail={detail ?? "loading"} />}
    </div>
  );
}
