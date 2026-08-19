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
// PERF (2026-08-18, owner: the page "is really struggling to load
// anything"): five build lanes each added their own fetching here and
// nobody consolidated — measured 40 requests/min at steady state (three
// endpoints every 5s + frontier every 15s), every keystroke in a filter box
// refetched ALL THREE page sources (a no-match filter costs the backend a
// full 16 MiB backward scan, measured 0.85–1.83 s per keystroke), and every
// poll setState'd fresh identities so the whole table re-rendered ~12–36
// times/min even when nothing changed. Now every poll runs through the
// pollhub scheduler (src/api/pollhub.ts): one heartbeat, per-source cadences
// (table = pollMs, strip 20s, dev trace 60s, frontier 45s), in-flight
// guards, JSON change detection (fetchers strip the volatile generated_at /
// scanned_bytes fields so an unchanged payload really is unchanged — zero
// re-renders on a no-change tick), stale-while-revalidate (rendered rows
// NEVER blank on a failed refetch), and pause-on-hidden (a background tab
// polls nothing). Filter input is debounced (350 ms) and only re-keys the
// TABLE source — the strip/trace/frontier polls never see a keystroke. Rows
// are identity-stable across polls (immutable log rows, cached by
// request_id) and memoized, so a changed payload re-renders only the rows
// that actually changed; expanded rows and their fetched details survive
// every tick.
//
// Adversarial-review pass (2026-08-18): every fetcher carries a 15 s
// AbortController deadline (api/modelIO.ts fetchWithDeadline) with the
// pollhub's own deadline race as backstop — a hung request fails its
// source honestly (rows kept, STALE note, retry next tick) instead of
// wedging the in-flight guard; the filter-keyed table source is
// evictOnZero so typed queries never leak hub entries; the four sources'
// first fetches stagger 0/150/300/450 ms (the Pulse idiom); and a poll
// that advances the newest page by more than one page while older pages
// are appended renders an explicit gap marker rather than silently
// omitting the middle rows.
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
//
// Owner feedback 2026-08-19 ("I posed 3 questions … but it shows up as 6
// cards instead of maybe 1 or 2 (since it goes to 2 models)"): chat-session
// rows no longer render one card per wrapper call. The backend groups them
// into `threads` (see backend/model_io.py) and the page renders each thread
// as ONE SessionThreadCard — questions printed once, both voices' answers
// under them, the replayed prefix reduced to a "context: N prior messages"
// chip that opens the same expanded-call reader. The list is therefore a
// FEED of two item kinds; a thread costs ONE of the 20 rows (stamped with
// its latest turn), and every non-session call keeps its CallRow exactly as
// before — nothing about iteration chains / batteries / subagents changed.
//
// PAGING IS A CONTRACT, NOT AN INFERENCE (fix 2026-08-19). "load older" used
// to take its boundary from the oldest rendered item — a thread's `started`.
// A page's guaranteed coverage ends at its FILL POINT, and the backend's
// thread backfill walks up to 60 rows past that point to finish an open
// session, so `started` could sit far older than the fill point and every
// plain row in between landed on NEITHER page — after which this page said
// "beginning of log reached". No arrangement of rendered rows can recover a
// fill point, so the scan states it: `next_before_ts` (the exclusive older
// edge of the span the response covers) and `end_of_log` (the walk reached
// the start of the file), read here verbatim. When a response states no
// boundary and carries threads, the pager stops and SAYS so rather than
// guessing one. Threads then merge by session key across the WHOLE feed —
// live page and every appended older page — folding turns by request_id, so
// one session is one card and no slice is ever dropped.
import {
  Fragment,
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Card from "../design/Card";
import FrontierReviews from "../components/FrontierReviews";
import EmptyCompletionNote from "../components/payload/EmptyCompletionNote";
import EndpointMissingNote, {
  isVersionSkew404,
} from "../components/EndpointMissingNote";
import {
  fetchWithDeadline,
  getDispatchTrace,
  getModelIO,
  getModelIODetail,
  type DispatchTraceResponse,
  type ModelIOCall,
  type ModelIOCallDetail,
  type ModelIOFilters,
  type ModelIOResponse,
} from "../api/modelIO";
import { usePolled } from "../api/pollhub";
import { useNow } from "../time";
import { backendTone, callerTagTone, TONE_QUIET } from "../roles";
import { fmt } from "../format";
import MessageBody from "../components/payload/MessageBody";
import RoleChip from "../components/payload/RoleChip";
import { splitThought } from "../components/payload/parse";
import { CHIP_CLS } from "../components/payload/bits";
import SessionThreadCard, {
  threadComplete,
  type SessionThread,
  type SessionTurn,
} from "../components/SessionThreadCard";

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

// ─── fetchers (pollhub sources) ─────────────────────────────────────────
//
// Every polled fetcher strips the per-response volatile fields
// (generated_at always churns; scanned_bytes jitters with the file tail) so
// the pollhub's JSON change detection compares MEANING, not wall clocks —
// an unchanged payload notifies nobody and re-renders nothing. The honest
// data age lives in the hub's `asOf`, not in a field nothing rendered.

function stripVolatile<
  T extends { generated_at?: unknown; scanned_bytes?: unknown },
>(resp: T): Omit<T, "generated_at" | "scanned_bytes"> {
  const { generated_at: _g, scanned_bytes: _s, ...rest } = resp;
  return rest;
}

type TableData = Omit<ModelIOResponse, "generated_at" | "scanned_bytes"> & {
  /** Session threads (added 2026-08-19). OPTIONAL on purpose: a backend
   * that predates the grouping answers without the key and the page still
   * renders its calls — version skew degrades, never crashes. */
  threads?: SessionThread[];
  /** THE PAGING BOUNDARY, stated by the scan that produced the page: the
   * exclusive older edge of the contiguous span this response covers. Feed
   * it straight back as before_ts. Optional for the same version-skew
   * reason — see pageBoundary(), which refuses to guess when a guess could
   * skip rows. */
  next_before_ts?: string | null;
  /** True only when the scan reached the START OF THE FILE. Replaces the
   * client's old "short page must mean the log ended" inference. */
  end_of_log?: boolean;
};
type TraceData = Omit<DispatchTraceResponse, "generated_at">;

// ─── the feed: calls and session threads in one newest-first list ───────
//
// A thread is ONE row of the page's 20 (the backend budgets it that way
// too), stamped with its LATEST turn for ordering.
//
// A feed item carries NO paging boundary of its own any more (fix
// 2026-08-19). It used to: a thread's boundary was its `started`, and
// "load older" took the oldest boundary on screen. But a page's guaranteed
// coverage ends at its FILL POINT, and the backend's thread backfill walks
// up to 60 rows PAST that point to finish an open session — so `started`
// could sit far older than the fill point and every plain row in between
// landed on NEITHER page, after which this page announced "beginning of log
// reached". No arrangement of rendered timestamps can recover a fill point;
// only the scan knows it, so the scan states it (`next_before_ts`).

type FeedItem =
  | {
      kind: "call";
      /** Dedupe/retention identity; null when the row carries no
       * request_id (the pre-existing tolerance — such rows never dedupe). */
      key: string | null;
      ts: string | null;
      call: ModelIOCall;
    }
  | {
      kind: "thread";
      key: string;
      ts: string | null;
      thread: SessionThread;
    };

const tsMs = (ts: string | null): number => {
  const t = ts ? Date.parse(ts) : NaN;
  // Unparseable/absent cannot claim a position — it sinks, never floats to
  // the top of a newest-first list.
  return Number.isNaN(t) ? -Infinity : t;
};

/** One payload → one newest-first feed. Both source lists arrive newest-first
 * already, so this is a stable merge (Array.sort is stable), not a re-sort. */
export function toFeed(data: TableData | null | undefined): FeedItem[] {
  const calls = Array.isArray(data?.calls) ? data!.calls : [];
  const threads = Array.isArray(data?.threads) ? data!.threads : [];
  const items: FeedItem[] = [
    ...calls.map(
      (c): FeedItem => ({
        kind: "call",
        key: c.request_id,
        ts: c.ts,
        call: c,
      }),
    ),
    ...threads.map(
      (t): FeedItem => ({
        kind: "thread",
        key: `thread:${t.session_id}`,
        ts: t.ended,
        thread: t,
      }),
    ),
  ];
  return items.sort((a, b) => tsMs(b.ts) - tsMs(a.ts));
}

const turnsOf = (t: SessionThread): SessionTurn[] =>
  Array.isArray(t.turns) ? t.turns : [];

/** min / max of two ISO stamps, "unparseable or absent loses" (tsMs). */
const olderTs = (a: string | null, b: string | null): string | null =>
  a == null ? b : b == null ? a : tsMs(b) < tsMs(a) ? b : a;
const newerTs = (a: string | null, b: string | null): string | null =>
  a == null ? b : b == null ? a : tsMs(b) > tsMs(a) ? b : a;

/** Fold one more slice of a session into the thread already held.
 *
 * The feed is newest-first and folded left to right, so `next` is always
 * the OLDER slice and its turns PREPEND. Turns dedupe by request_id — an
 * overlapping page must never double a turn — and NOTHING is dropped: two
 * cards for one session is the duplication this grouping exists to remove,
 * and dropping a slice loses every turn in it. (Both were live bugs before
 * 2026-08-19: loadOlder dropped a whole slice whose session was already in
 * the older list, and mergeFeed only ever compared older slices against the
 * NEWEST page, so two older slices of one session never met.) */
export function foldThread(
  held: SessionThread,
  next: SessionThread,
): SessionThread {
  const heldTurns = turnsOf(held);
  const seen = new Set(
    heldTurns
      .map((t) => t.request_id)
      .filter((id): id is string => id != null),
  );
  const extra = turnsOf(next).filter(
    (t) => t.request_id == null || !seen.has(t.request_id),
  );
  const turns = extra.length === 0 ? heldTurns : [...extra, ...heldTurns];
  return {
    ...held,
    turns,
    turn_count: turns.length,
    started: olderTs(held.started, next.started),
    ended: newerTs(held.ended, next.ended),
    // A card folded from N slices is bounded by whichever slice was still
    // bounded — but only while its older turns are genuinely missing.
    turns_truncated: Boolean(held.turns_truncated || next.turns_truncated),
    // Completeness is a property of the MERGED turns, never of one slice:
    // a slice holding the attacker's opener says nothing about a defender
    // it never carried. (The old code took the older slice's flag whole.)
    turns_complete: threadComplete(turns),
  };
}

/** The WHOLE feed — the live page followed by every appended older page —
 * folded into one newest-first list.
 *
 * Session threads merge by session key ACROSS THE WHOLE FEED, not just
 * against the newest page: two slices that both live in the older list must
 * still land in one card. Plain calls dedupe by request_id, the first
 * (newest) occurrence winning — log rows are immutable, so they are the
 * same row. Every item keeps the position of its first occurrence, so the
 * newest-first ordering of the concatenation is preserved. */
export function mergeFeed(newest: FeedItem[], older: FeedItem[]): FeedItem[] {
  const out: FeedItem[] = [];
  const slot = new Map<string, number>();
  for (const item of [...newest, ...older]) {
    if (item.key == null) {
      out.push(item); // no identity: never deduped, never merged
      continue;
    }
    const at = slot.get(item.key);
    if (at === undefined) {
      slot.set(item.key, out.length);
      out.push(item);
      continue;
    }
    const held = out[at];
    if (held.kind === "thread" && item.kind === "thread") {
      out[at] = { ...held, thread: foldThread(held.thread, item.thread) };
    }
  }
  return out;
}

/** The next page's `before_ts`, taken from the BACKEND's stated fill point.
 *
 * `supported` is false when this page cannot honestly name a boundary —
 * then the pager reports itself blocked rather than paging from a guess.
 * The one guess allowed is the version-skew case where it is provably safe:
 * a payload with NO threads had no backfill walk, so its oldest call IS its
 * fill point. With threads present, that inference is exactly the bug. */
export function pageBoundary(page: TableData | null | undefined): {
  ts: string | null;
  supported: boolean;
} {
  if (page == null) return { ts: null, supported: false };
  if (page.next_before_ts !== undefined) {
    return { ts: page.next_before_ts, supported: true };
  }
  const threads = Array.isArray(page.threads) ? page.threads : [];
  if (threads.length > 0) return { ts: null, supported: false };
  const calls = Array.isArray(page.calls) ? page.calls : [];
  let oldest: string | null = null;
  for (const c of calls) {
    if (c.ts && (oldest == null || tsMs(c.ts) < tsMs(oldest))) oldest = c.ts;
  }
  return { ts: oldest, supported: true };
}

// Local types + fetcher for /api/runtime_activity: this page owns the
// endpoint's client rather than widening api/modelIO.ts (same API_BASE
// derivation).

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

interface ActivityData {
  orchestrator_available: boolean;
  calls_available: boolean;
  chain: ChainTask[];
  subagent_groups: SubagentGroup[];
  window_truncated: boolean;
}

const RUNTIME_API_PORT = import.meta.env.VITE_API_PORT ?? "8700";
const RUNTIME_API_BASE = `http://${window.location.hostname}:${RUNTIME_API_PORT}`;

async function getRuntimeActivity(): Promise<ActivityData> {
  // fetchWithDeadline: a hung request rejects at 15 s — the pollhub keeps
  // the rendered strip (SWR, failing=true) and retries on its next tick.
  const resp = await fetchWithDeadline(
    `${RUNTIME_API_BASE}/api/runtime_activity`,
  );
  if (!resp.ok) throw new Error(`runtime_activity ${resp.status}`);
  return stripVolatile(
    (await resp.json()) as ActivityData & {
      generated_at?: unknown;
      scanned_bytes?: unknown;
    },
  );
}

const fetchTrace = (): Promise<TraceData> =>
  getDispatchTrace().then(stripVolatile);

// Per-source cadences. The table is the page's live primary (owner watches
// calls arrive) — it keeps the fast pollMs. The strip summarizes minutes of
// activity; the dev spawn ledger changes on the timescale of build sessions.
const ACTIVITY_POLL_MS = 20_000;
const TRACE_POLL_MS = 60_000;
// Mount stagger (the Pulse idiom): the four sources' FIRST fetches land
// 150 ms apart — table (the live primary) immediately, then strip, trace,
// frontier — so first paint is not a 4-request thundering herd.
const ACTIVITY_STAGGER_MS = 150;
const TRACE_STAGGER_MS = 300;
const FRONTIER_STAGGER_MS = 450;
// A keystroke in a filter box must not hit the backend (a no-match filter
// costs a full 16 MiB scan, measured 0.85–1.83 s); the query re-keys only
// after typing pauses.
const FILTER_DEBOUNCE_MS = 350;

// ─── pagination (owner 2026-08-18: "show only last 20 interactions" +
//     a load-older walk) ────────────────────────────────────────────────

const PAGE_SIZE = 20;

// Older pages go through a LOCAL fetcher (the getRuntimeActivity reasoning:
// this page owns the before_ts param rather than widening the shared
// api/modelIO.ts client). One-shot, not polled — no volatile-strip needed.
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
  const resp = await fetchWithDeadline(
    `${RUNTIME_API_BASE}/api/model_io?${params.toString()}`,
  );
  if (!resp.ok) throw new Error(`model_io ${resp.status}`);
  return (await resp.json()) as ModelIOResponse;
}

// The load-older control's state machine: idle (button) → loading →
// idle | end (file start reached) | capped (byte cap stopped the scan —
// reported honestly, never a silent stop) | blocked (the page states no
// usable boundary, so walking further would have to GUESS one) | error
// (button retries). `end` and `capped` are now the BACKEND's own answers
// (end_of_log / window_truncated), not a short-page inference.
type PagerState =
  | "idle"
  | "loading"
  | "end"
  | "capped"
  | "blocked"
  | "error";

const CHAIN_LINES = 6;
const PLANE_LABEL_CLS =
  "text-[10px] uppercase tracking-wide text-zinc-500";

// Memoized: the strip re-renders only when its payload actually changed
// (pollhub identities are stable on no-change ticks) or on its own 30s age
// clock — never because the table polled.
const RuntimeStrip = memo(function RuntimeStrip({
  activity,
  trace,
}: {
  activity: ActivityData | null;
  trace: TraceData | null;
}) {
  // The dev-side build-agent ledger is a DIFFERENT plane — collapsed by
  // default so the strip reads as runtime-only unless explicitly opened.
  const [devOpen, setDevOpen] = useState(false);
  // 30s age clock: keeps the "3m" ages honest between payload changes
  // without re-rendering anything else on the page.
  const now = useNow(30_000);
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
                  <span className="text-zinc-600">{ageOf(t.ts, now)}</span>
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
                    {ageOf(g.last_ts, now)}
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
                    {ageOf(s.ts, now)}
                  </span>
                </div>
              ))}
            </div>
          ))}
      </div>
    </Card>
  );
});

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

// Same-set filter equality, so the debounce timer never re-applies an
// unchanged query (and never re-keys the table source).
function sameFilters(a: ModelIOFilters, b: ModelIOFilters): boolean {
  return (
    (a.model ?? "") === (b.model ?? "") &&
    (a.callerTag ?? "") === (b.callerTag ?? "") &&
    (a.runId ?? "") === (b.runId ?? "")
  );
}

export default function ModelIO({ pollMs = 5000 }: { pollMs?: number }) {
  const [paused, setPaused] = useState(false);
  // `inputs` follows every keystroke (controlled inputs stay live);
  // `applied` is what actually queries the backend, applied only after
  // FILTER_DEBOUNCE_MS of quiet.
  const [inputs, setInputs] = useState<ModelIOFilters>({});
  const [applied, setApplied] = useState<ModelIOFilters>({});
  const [expanded, setExpanded] = useState<string | null>(null);
  const [details, setDetails] = useState<
    Record<string, ModelIOCallDetail | "loading" | "error">
  >({});
  // Paged-older rows (appended, poll-stable) + the load-older control's
  // state. hasPagedRef gates the poll's dropped-row retention; newestRef
  // mirrors the last newest page so the retention never re-sorts.
  const [older, setOlder] = useState<FeedItem[]>([]);
  const [pager, setPager] = useState<PagerState>("idle");
  // The boundary for the NEXT older page, as STATED by the oldest page
  // loaded so far. null = no older page fetched yet, so the live page owns
  // it (its own next_before_ts). Never derived from rendered rows.
  const [nextBoundary, setNextBoundary] = useState<{
    ts: string | null;
    supported: boolean;
  } | null>(null);
  // True when a poll advanced the newest page by MORE than one page while
  // older pages were appended: the rows between the fresh page and the
  // retained ones were never fetched, and hiding that hole would silently
  // misorder history — the gap is marked explicitly instead (minor (b),
  // adversarial review 2026-08-18).
  const [pageGap, setPageGap] = useState(false);
  const hasPagedRef = useRef(false);
  const newestRef = useRef<FeedItem[]>([]);

  useEffect(() => {
    const id = setTimeout(
      () => setApplied((prev) => (sameFilters(prev, inputs) ? prev : inputs)),
      FILTER_DEBOUNCE_MS,
    );
    return () => clearTimeout(id);
  }, [inputs]);

  // The applied filter IS the table source's identity: a changed query is a
  // different pollhub key (immediate fetch on re-key), while the strip /
  // trace / frontier sources never see a filter change at all.
  const appliedKey = JSON.stringify([
    applied.model ?? "",
    applied.callerTag ?? "",
    applied.runId ?? "",
  ]);

  const tablePoll = usePolled<TableData>(
    `modelio:calls:${appliedKey}`,
    () => getModelIO(applied, PAGE_SIZE).then(stripVolatile),
    // evictOnZero: the key is parameterized by the filter — every query
    // ever typed would otherwise leave a hub Entry behind on an always-on
    // dashboard. The lastTableRef below carries the rendered rows across
    // the eviction, so a re-key still never blanks.
    {
      intervalMs: pollMs,
      initialDelayMs: 0,
      evictOnZero: true,
      enabled: !paused,
    },
  );
  const activityPoll = usePolled<ActivityData>(
    "modelio:runtime_activity",
    getRuntimeActivity,
    {
      intervalMs: ACTIVITY_POLL_MS,
      initialDelayMs: ACTIVITY_STAGGER_MS,
      enabled: !paused,
    },
  );
  const tracePoll = usePolled<TraceData>("modelio:dispatch_trace", fetchTrace, {
    intervalMs: TRACE_POLL_MS,
    initialDelayMs: TRACE_STAGGER_MS,
    enabled: !paused,
  });

  // Stale-while-revalidate ACROSS re-keys and pause: a filter change or a
  // pause must never blank rendered content, so the last good payload of
  // each source is kept and shown until fresher data lands.
  const lastTableRef = useRef<TableData | null>(null);
  if (tablePoll.data !== undefined) lastTableRef.current = tablePoll.data;
  const data = tablePoll.data ?? lastTableRef.current;
  const lastActivityRef = useRef<ActivityData | null>(null);
  if (activityPoll.data !== undefined)
    lastActivityRef.current = activityPoll.data;
  const activity = activityPoll.data ?? lastActivityRef.current;
  const lastTraceRef = useRef<TraceData | null>(null);
  if (tracePoll.data !== undefined) lastTraceRef.current = tracePoll.data;
  const trace = tracePoll.data ?? lastTraceRef.current;

  const error = tablePoll.error;
  const stale = tablePoll.failing;

  // A filter change invalidates the appended pages (they were fetched
  // under the OLD filter); pause/resume deliberately does not.
  useEffect(() => {
    setOlder([]);
    setPager("idle");
    setNextBoundary(null);
    setPageGap(false);
    hasPagedRef.current = false;
  }, [appliedKey]);

  // Newest-page bookkeeping, run only when the payload actually changed
  // (pollhub identity): once older pages are appended, rows that new
  // arrivals push out of the newest page are RETAINED by moving them onto
  // the older list — no gap between the pages, no re-sort (they were
  // already in newest-first order directly below the fresh page).
  useEffect(() => {
    const payload = tablePoll.data;
    if (payload === undefined || !Array.isArray(payload.calls)) return;
    const fresh = toFeed(payload);
    if (hasPagedRef.current) {
      const freshIds = new Set(
        fresh.map((i) => i.key).filter((id): id is string => id != null),
      );
      const prev = newestRef.current;
      const dropped = prev.filter(
        (i) => i.key != null && !freshIds.has(i.key),
      );
      // GAP DETECTION (count discontinuity): a FULL fresh page sharing no
      // row with the previous newest page means at least a whole page of
      // rows arrived in one tick — anything between the fresh page's
      // oldest row and the retained rows below was never fetched. The
      // exact count is unknowable client-side (the backend caps at
      // PAGE_SIZE); the hole itself is what must not be silent.
      if (
        prev.length > 0 &&
        fresh.length >= PAGE_SIZE &&
        !prev.some((i) => i.key != null && freshIds.has(i.key))
      ) {
        setPageGap(true);
      }
      if (dropped.length > 0) {
        setOlder((prev) => {
          // Same rule as loadOlder's append: a CALL already held is the
          // same immutable row and drops, but a THREAD is never dropped —
          // this slice's turns are the session's newest half and mergeFeed
          // folds them into the one card. (Dropping it here would lose the
          // live turns the moment a paged slice of the same session was
          // already appended.)
          const seen = new Set(
            prev.filter((i) => i.kind === "call").map((i) => i.key),
          );
          return [
            ...dropped.filter((i) => i.kind === "thread" || !seen.has(i.key)),
            ...prev,
          ];
        });
      }
    }
    newestRef.current = fresh;
  }, [tablePoll.data]);

  // Row identity cache: calls.jsonl rows are immutable once written, so a
  // request_id seen before IS the same row — reusing the first-seen object
  // keeps row identities stable across polls and lets React.memo skip every
  // unchanged CallRow when a new arrival re-renders the list. Reset per
  // filter so the cache stays bounded to one query's session.
  const rowCacheRef = useRef(new Map<string, ModelIOCall>());
  useEffect(() => {
    rowCacheRef.current.clear();
  }, [appliedKey]);

  // details is read inside the stable toggleRow callback via a ref.
  const detailsRef = useRef(details);
  detailsRef.current = details;
  const toggleRow = useCallback((requestId: string | null) => {
    if (!requestId) return;
    setExpanded((prev) => (prev === requestId ? null : requestId));
    if (detailsRef.current[requestId] === undefined) {
      setDetails((d) => ({ ...d, [requestId]: "loading" }));
      getModelIODetail(requestId)
        .then((r) =>
          setDetails((d) => ({ ...d, [requestId]: r.call ?? "error" })),
        )
        .catch(() =>
          setDetails((d) => ({ ...d, [requestId]: "error" })),
        );
    }
  }, []);

  // Newest page first, then the appended older pages (duplicate calls drop,
  // duplicate threads merge) — never re-sorted across pages.
  const { feed, newestCount } = useMemo(() => {
    const cache = rowCacheRef.current;
    // calls.jsonl ROWS are immutable once written, so a request_id seen
    // before IS the same row — reuse it and React.memo skips the CallRow.
    // THREADS are deliberately NOT cached: a live session grows a turn at a
    // time, so a cached thread would freeze mid-conversation.
    const stable = (item: FeedItem): FeedItem => {
      if (item.kind !== "call" || item.key == null) return item;
      const hit = cache.get(item.key);
      if (hit != null) return hit === item.call ? item : { ...item, call: hit };
      cache.set(item.key, item.call);
      return item;
    };
    const newest = toFeed(data).map(stable);
    return { feed: mergeFeed(newest, older), newestCount: newest.length };
  }, [data, older]);

  const skew = isVersionSkew404(error, "/api/model_io") && feed.length === 0;

  // The expanded full-record reader, rendered wherever the open turn lives:
  // inline under its CallRow, or inside the session card that owns it (one
  // expansion at a time, page-wide — the table's existing rule).
  const expansionNode =
    expanded != null ? (
      <CallExpansion detail={details[expanded] ?? "loading"} />
    ) : null;

  // The gap marker's "refresh": drop the paged rows and start over from
  // the live page — the only honest way to close a hole whose middle rows
  // were never fetched.
  const resetPaging = () => {
    setOlder([]);
    setPager("idle");
    setNextBoundary(null);
    setPageGap(false);
    hasPagedRef.current = false;
  };

  // The boundary for the next click: the oldest fetched page's stated fill
  // point, else the live page's. NEVER the oldest rendered timestamp.
  const boundary = nextBoundary ?? pageBoundary(data);
  const canPage = boundary.supported && boundary.ts != null;
  // What the pager control actually shows. A settled ("idle") pager still
  // has to answer the live page honestly: it may already say the scan
  // reached the file start, or name no boundary at all.
  const pagerState: PagerState =
    pager !== "idle"
      ? pager
      : data == null
        ? "idle"
        : data.end_of_log === true && nextBoundary == null
          ? "end"
          : canPage
            ? "idle"
            : "blocked";

  const loadOlder = () => {
    if (pager === "loading" || !canPage || boundary.ts == null) return;
    hasPagedRef.current = true;
    setPager("loading");
    getOlderModelIO(applied, boundary.ts)
      .then((r) => {
        const body = r as TableData;
        const page = toFeed(body);
        setOlder((prev) => {
          const appended = new Set(
            prev
              .filter((i) => i.kind === "call")
              .map((i) => i.key)
              .filter((k): k is string => k != null),
          );
          const live = new Set(
            newestRef.current
              .filter((i) => i.kind === "call")
              .map((i) => i.key)
              .filter((k): k is string => k != null),
          );
          const fresh = page.filter((i) => {
            // A THREAD slice is NEVER dropped, wherever its session already
            // sits: these are that session's older turns and mergeFeed
            // folds them into the one card. The old dedupe ran BEFORE this
            // exemption, so a session already in the older list lost the
            // whole slice — every turn in it.
            if (i.kind === "thread") return true;
            if (i.key == null) return true; // no identity: never deduped
            return !appended.has(i.key) && !live.has(i.key);
          });
          return [...prev, ...fresh];
        });
        const next = pageBoundary(body);
        setNextBoundary(next);
        // The BACKEND's own answers, in order of finality. A short page is
        // no longer read as "the log ended" — it can equally mean the byte
        // cap stopped the scan, which is a different sentence to the owner.
        if (body.end_of_log === true) setPager("end");
        else if (body.window_truncated) setPager("capped");
        else if (body.end_of_log === false)
          setPager(next.supported && next.ts != null ? "idle" : "blocked");
        // Version skew only (no coverage contract on the wire): fall back
        // to the old short-page inference.
        else if (page.length < PAGE_SIZE) setPager("end");
        else setPager(next.supported && next.ts != null ? "idle" : "blocked");
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

      {/* Frontier tier (D-061), sibling section: its poll rides the same
          page scheduler — see components/FrontierReviews.tsx. */}
      <FrontierReviews paused={paused} initialDelayMs={FRONTIER_STAGGER_MS} />

      {/* Filters + live-state controls. */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <input
          className={INPUT_CLS}
          placeholder="model (substring)"
          aria-label="filter by model"
          value={inputs.model ?? ""}
          onChange={(e) =>
            setInputs((f) => ({ ...f, model: e.target.value || undefined }))
          }
        />
        <input
          className={INPUT_CLS}
          placeholder="caller_tag (substring)"
          aria-label="filter by caller tag"
          value={inputs.callerTag ?? ""}
          onChange={(e) =>
            setInputs((f) => ({
              ...f,
              callerTag: e.target.value || undefined,
            }))
          }
        />
        <input
          className={INPUT_CLS}
          placeholder="run_id (exact)"
          aria-label="filter by run id"
          value={inputs.runId ?? ""}
          onChange={(e) =>
            setInputs((f) => ({ ...f, runId: e.target.value || undefined }))
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
            {data == null && !stale ? (
              // First load only — once any payload has rendered, refetches
              // and re-keys keep the previous rows (SWR), never a blank.
              <div className="text-xs text-zinc-500" data-testid="table-loading">
                loading the newest {PAGE_SIZE} calls…
              </div>
            ) : feed.length === 0 && data != null ? (
              <div className="text-xs text-zinc-500">
                no calls match in the log tail.
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                {feed.map((item, i) => (
                  <Fragment key={item.key ?? `${item.ts ?? "row"}-${i}`}>
                    {/* Explicit hole between the live page and the rows
                        retained below it — never a silent misordering. */}
                    {pageGap && i === newestCount && i > 0 && (
                      <div
                        className="flex flex-wrap items-center gap-2 border-y border-amber-900/40 bg-amber-950/20 px-2 py-1 text-xs text-amber-400/90"
                        data-testid="page-gap"
                      >
                        newer rows arrived faster than one page — rows
                        between the live page above and the older rows below
                        are NOT shown.
                        <button
                          type="button"
                          data-testid="page-gap-refresh"
                          className="rounded border border-amber-800/60 px-1.5 py-0.5 text-amber-300 hover:border-amber-600"
                          onClick={resetPaging}
                        >
                          refresh
                        </button>
                      </div>
                    )}
                    {item.kind === "thread" ? (
                      // ONE card for the whole session (owner 2026-08-19):
                      // questions once, both voices' answers under them.
                      <SessionThreadCard
                        thread={item.thread}
                        expandedRequestId={expanded}
                        expansion={expansionNode}
                        onToggleContext={toggleRow}
                      />
                    ) : (
                      <CallRow
                        call={item.call}
                        expanded={
                          expanded != null && expanded === item.call.request_id
                        }
                        detail={
                          item.call.request_id
                            ? details[item.call.request_id]
                            : undefined
                        }
                        onToggle={toggleRow}
                      />
                    )}
                  </Fragment>
                ))}
              </div>
            )}
          </Card>

          {/* Load-older pager: appends the next PAGE_SIZE rows strictly
              older than the oldest visible row. The end states are
              HONEST: file start = "beginning of log", byte cap = "older
              rows beyond scan window" — never a silent stop. */}
          {feed.length > 0 && (
            <div
              className="mt-2 flex flex-wrap items-center gap-2"
              data-testid="modelio-pager"
            >
              {pagerState === "capped" ? (
                <span
                  className="text-xs text-zinc-500"
                  data-testid="pager-capped"
                >
                  older rows beyond scan window — the bounded backward scan
                  stopped at its byte cap
                  {data ? ` (${data.max_scan_bytes} bytes)` : ""}.
                </span>
              ) : pagerState === "end" ? (
                <span
                  className="text-xs text-zinc-600"
                  data-testid="pager-end"
                >
                  beginning of log reached — no older rows.
                </span>
              ) : pagerState === "blocked" ? (
                // The page states no usable boundary. Walking on would mean
                // GUESSING one from the rendered rows — the guess that
                // silently lost rows before 2026-08-19. Stop and say so.
                <span
                  className="text-xs text-amber-400/80"
                  data-testid="pager-blocked"
                >
                  paging stopped — this response states no page boundary, and
                  guessing one from the rows on screen can skip rows silently.
                </span>
              ) : (
                <button
                  type="button"
                  data-testid="load-older"
                  disabled={pagerState === "loading"}
                  className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:border-zinc-500 disabled:opacity-50"
                  onClick={loadOlder}
                >
                  {pagerState === "loading" ? "loading…" : "load older ▾"}
                </button>
              )}
              {pagerState === "error" && (
                <span className="text-xs text-amber-400/80">
                  older-page fetch failed — the button retries.
                </span>
              )}
              <span className="text-[11px] text-zinc-600">
                showing {feed.length} rows — newest {PAGE_SIZE} refresh
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

// Memoized row: with identity-stable `call` objects (rowCacheRef), a stable
// `onToggle` (useCallback) and per-row `detail` values, a poll tick that
// changes the payload re-renders ONLY the genuinely new/changed rows — an
// open expansion (full MessageBody parse of a multi-KB record) no longer
// re-parses on every arrival elsewhere in the table.
const CallRow = memo(function CallRow({
  call,
  expanded,
  detail,
  onToggle,
}: {
  call: ModelIOCall;
  expanded: boolean;
  detail: ModelIOCallDetail | "loading" | "error" | undefined;
  onToggle: (requestId: string | null) => void;
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
        onClick={() => onToggle(call.request_id)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggle(call.request_id);
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
});
