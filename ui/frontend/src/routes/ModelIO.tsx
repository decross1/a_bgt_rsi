// PAGE /model-io — the searchable record of calls in logs/calls.jsonl.
//
// The scan layer stays compact: recorded time, exact model/backend and caller,
// neutral Recorded/EMPTY state, cost, a short summary, and an explicit native
// button to open the record. One selected call owns the context pane. At narrow
// widths that pane replaces the feed and provides Back to calls; closing it
// restores focus to the opener. The exact endpoint payload remains available
// behind a native Raw record disclosure.
//
// Calls owns one filter-keyed pollhub source. Runtime and dispatch history live
// on /cycles; human review controls live on /development. Filter input is
// debounced (350 ms), the superseded source key is evicted, and unchanged
// payloads do not trigger rerenders. Stale-while-revalidate keeps loaded calls
// and the selected exact record through refresh, pause, failure, and re-key.
//
// Honesty rules carried from the rest of the dashboard:
//  - everything is backend-passthrough; a missing field renders as "—",
//    never a guess (backend is never derived from the model name);
//  - a failed poll says the table is UNKNOWN, keeping the last rows,
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
// chip that opens the same selected-call context. The list is therefore a
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
import EmptyCompletionNote from "../components/payload/EmptyCompletionNote";
import EndpointMissingNote, {
  isVersionSkew404,
} from "../components/EndpointMissingNote";
import {
  fetchWithDeadline,
  getModelIO,
  getModelIODetail,
  type ModelIOCall,
  type ModelIOCallDetail,
  type ModelIOFilters,
  type ModelIOResponse,
} from "../api/modelIO";
import { usePolled } from "../api/pollhub";
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
import "./modelIO.css";

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
// Local source identity; never inferred from the current render key.
type QueryTableData = TableData & { queryKey: string };

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

/** Retain the preceding live slices before committing a replacement page.
 * The same transition is used by rendering and passive persistence. Keep the
 * existing gap heuristic and merge identities; no boundary is inferred here. */
function retainPage(fresh: FeedItem[], previous: FeedItem[], older: FeedItem[]) {
  const current = new Map(fresh.map(item => [item.key, item]));
  const dropped = previous.filter(item => {
    if (item.key == null) return false; // unchanged anonymous-call policy
    const next = current.get(item.key);
    if (next === undefined) return true;
    if (item.kind !== "thread" || next.kind !== "thread") return false;
    // A still-visible session may now carry a shorter slice. Preserve its
    // known missing turns too; foldThread retains the established identity
    // rule (request_id, with anonymous turns never deduplicated).
    const ids = new Set(turnsOf(next.thread).map(turn => turn.request_id));
    return turnsOf(item.thread).some(turn =>
      turn.request_id != null && !ids.has(turn.request_id));
  });
  return {
    older: dropped.length === 0 ? older : mergeFeed(dropped, older),
    gap: previous.length > 0 && fresh.length >= PAGE_SIZE &&
      !previous.some(item => item.key != null && current.has(item.key)),
  };
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

const RUNTIME_API_PORT = import.meta.env.VITE_API_PORT ?? "8700";
const RUNTIME_API_BASE = `http://${window.location.hostname}:${RUNTIME_API_PORT}`;
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

// ─── the expanded full prompt/completion reader ─────────────────────────

function RawRecord({ detail }: { detail: ModelIOCallDetail }) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="modelio-raw-record"
      data-testid="raw-record"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Raw record</summary>
      {open && (
        <div data-testid="raw-record-content">
          <p>
            Untouched fields returned by the exact-record endpoint. This is a
            recorded call payload, not a runtime or scientific verdict.
          </p>
          <pre>{JSON.stringify(detail, null, 2)}</pre>
        </div>
      )}
    </details>
  );
}

function CallExpansion({
  detail,
}: {
  detail: ModelIOCallDetail | "loading" | "error";
}) {
  if (detail === "loading") {
    return (
      <div className="modelio-context-state" data-testid="detail-loading">
        Loading the exact recorded input and output…
      </div>
    );
  }
  if (detail === "error") {
    return (
      <div className="modelio-context-state modelio-context-state--warning">
        full record unavailable — it may have aged out of the
        bounded scan window, or the calls source may be unreachable. The row
        in the loaded feed is retained.
      </div>
    );
  }
  const messages = Array.isArray(detail.prompt_messages)
    ? detail.prompt_messages
    : [];
  return (
    <div className="modelio-call-context" data-testid="call-expansion">
      <section className="modelio-context-section" aria-labelledby="modelio-input-heading">
        <h3 id="modelio-input-heading">Recorded input</h3>
        {messages.length === 0 ? (
          <p className="modelio-context-empty">
            No legible prompt-message array was supplied for this record.
          </p>
        ) : (
          <div className="modelio-message-stack">
            {messages.map((m, i) => (
              <article key={i} className="modelio-message">
                <div className="modelio-message-role">
                  <RoleChip role={m.role} />
                </div>
                <MessageBody
                  role={m.role}
                  content={m.content}
                  toolCalls={(m as { tool_calls?: unknown }).tool_calls}
                  testId={`message-${m.role}-${i}`}
                />
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="modelio-context-section" aria-labelledby="modelio-output-heading">
        <h3 id="modelio-output-heading">Recorded output</h3>
        <article className="modelio-message">
          <div className="modelio-message-role">
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
        </article>
      </section>

      <section className="modelio-context-section" aria-labelledby="modelio-metadata-heading">
        <h3 id="modelio-metadata-heading">Exact call metadata</h3>
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
      </section>

      <RawRecord detail={detail} />
    </div>
  );
}

// ─── the page ───────────────────────────────────────────────────────────

interface SelectedCallSummary {
  requestId: string;
  ts: string | null;
  model: string | null;
  backend: string | null;
  callerTag: string | null;
  runId: string | null;
  condition: "Recorded" | "EMPTY";
  context: "call" | "session turn";
}

function summariesByRequest(feed: FeedItem[]): Map<string, SelectedCallSummary> {
  const out = new Map<string, SelectedCallSummary>();
  for (const item of feed) {
    if (item.kind === "call") {
      const requestId = item.call.request_id;
      if (!requestId) continue;
      out.set(requestId, {
        requestId,
        ts: item.call.ts,
        model: item.call.model,
        backend: item.call.backend,
        callerTag: item.call.caller_tag,
        runId: item.call.run_id,
        condition: item.call.empty ? "EMPTY" : "Recorded",
        context: "call",
      });
      continue;
    }
    for (const turn of turnsOf(item.thread)) {
      const requestId = turn.request_id;
      if (!requestId) continue;
      out.set(requestId, {
        requestId,
        ts: turn.ts,
        model: turn.model,
        backend: turn.backend,
        callerTag: turn.caller_tag,
        runId: item.thread.run_id,
        condition: turn.empty ? "EMPTY" : "Recorded",
        context: "session turn",
      });
    }
  }
  return out;
}

function exactUtcTime(ms: number | null): string | null {
  if (ms == null || !Number.isFinite(ms)) return null;
  return `${new Date(ms).toISOString().slice(11, 19)} UTC`;
}

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
  const [selectedSummary, setSelectedSummary] =
    useState<SelectedCallSummary | null>(null);
  const [details, setDetails] = useState<
    Record<string, ModelIOCallDetail | "loading" | "error">
  >({});
  const expandedRef = useRef<string | null>(null);
  const summaryMapRef = useRef(new Map<string, SelectedCallSummary>());
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const contextCloseRef = useRef<HTMLButtonElement | null>(null);
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
  const newestPayloadRef = useRef<QueryTableData | undefined>(undefined);
  const pagingGenerationRef = useRef(0);

  useEffect(() => {
    const id = setTimeout(
      () => setApplied((prev) => (sameFilters(prev, inputs) ? prev : inputs)),
      FILTER_DEBOUNCE_MS,
    );
    return () => clearTimeout(id);
  }, [inputs]);

  // The applied filter IS the Calls source's identity: a changed query is a
  // different pollhub key and fetches immediately after the debounce.
  const appliedKey = JSON.stringify([
    applied.model ?? "",
    applied.callerTag ?? "",
    applied.runId ?? "",
  ]);

  const retentionKeyRef = useRef(appliedKey);

  const tablePoll = usePolled<QueryTableData>(
    `modelio:calls:${appliedKey}`,
    () => getModelIO(applied, PAGE_SIZE).then(response => ({
      ...stripVolatile(response), queryKey: appliedKey,
    })),
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

  // Stale-while-revalidate ACROSS re-keys and pause: a filter change or a
  // pause must never blank rendered content, so the last good payload of
  // each source is kept and shown until fresher data lands.
  // usePolled can return the prior key's snapshot during its rekey commit.
  // The result's originating key prevents relabeling that old page as new.
  const payload = tablePoll.data?.queryKey === appliedKey ? tablePoll.data : undefined;
  const lastTableRef = useRef<QueryTableData | null>(null);
  if (payload !== undefined) lastTableRef.current = payload;
  const data = payload ?? lastTableRef.current;
  const pagingReady = data?.queryKey === appliedKey;
  const sameRetentionKey = retentionKeyRef.current === appliedKey;
  const pendingRetention = useMemo(() => {
    if (!sameRetentionKey) return { older: [], gap: false };
    if (!hasPagedRef.current || payload === undefined || payload === newestPayloadRef.current)
      return { older, gap: false };
    return retainPage(toFeed(payload), newestRef.current, older);
  }, [payload, older, appliedKey, sameRetentionKey]);
  const visibleGap = sameRetentionKey && (pageGap || pendingRetention.gap);

  const error = tablePoll.error;
  const stale = tablePoll.failing;

  // A filter change invalidates the appended pages (they were fetched
  // under the OLD filter); pause/resume deliberately does not.
  useEffect(() => {
    retentionKeyRef.current = appliedKey;
    pagingGenerationRef.current += 1;
    newestRef.current = [];
    newestPayloadRef.current = undefined;
    setOlder([]);
    setPager("idle");
    setNextBoundary(null);
    setPageGap(false);
    hasPagedRef.current = false;
  }, [appliedKey]);

  // Persist the already-visible coherent transition. Rendering does not wait
  // for this effect, so no committed frame loses previously loaded slices.
  useEffect(() => {
    if (payload === undefined || !Array.isArray(payload.calls)) return;
    const fresh = toFeed(payload);
    if (hasPagedRef.current) {
      const previous = newestRef.current;
      if (retainPage(fresh, previous, []).gap) setPageGap(true);
      setOlder(held => retainPage(fresh, previous, held).older);
    }
    newestRef.current = fresh;
    newestPayloadRef.current = payload;
  }, [payload, appliedKey]);

  // Row identity cache: calls.jsonl rows are immutable once written, so a
  // request_id seen before IS the same row — reusing the first-seen object
  // keeps row identities stable across polls and lets React.memo skip every
  // unchanged CallRow when a new arrival re-renders the list. Reset per
  // filter so the cache stays bounded to one query's session.
  const rowCacheRef = useRef(new Map<string, ModelIOCall>());
  useEffect(() => {
    rowCacheRef.current.clear();
  }, [appliedKey]);

  // Details and summaries are read inside the stable toggleRow callback via
  // refs. This keeps CallRow identities stable while preserving the exact
  // selected request across refreshes, filter transitions and late replies.
  const detailsRef = useRef(details);
  detailsRef.current = details;
  expandedRef.current = expanded;

  const closeContext = useCallback(() => {
    expandedRef.current = null;
    setExpanded(null);
    const opener = returnFocusRef.current;
    window.setTimeout(() => opener?.focus(), 0);
  }, []);

  const toggleRow = useCallback(
    (requestId: string | null) => {
      if (!requestId) return;
      if (expandedRef.current === requestId) {
        closeContext();
        return;
      }
      const active = document.activeElement;
      if (active instanceof HTMLElement) returnFocusRef.current = active;
      setSelectedSummary(summaryMapRef.current.get(requestId) ?? null);
      expandedRef.current = requestId;
      setExpanded(requestId);
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
    },
    [closeContext],
  );

  useEffect(() => {
    if (expanded == null) return;
    const id = window.setTimeout(() => contextCloseRef.current?.focus(), 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeContext();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(id);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [expanded, closeContext]);

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
    return { feed: mergeFeed(newest, pendingRetention.older), newestCount: newest.length };
  }, [data, pendingRetention.older]);
  summaryMapRef.current = summariesByRequest(feed);

  const skew = isVersionSkew404(error, "/api/model_io") && feed.length === 0;

  // One exact request owns the context surface. Detail replies remain keyed
  // by request id, so a late response for a previously selected row cannot
  // replace the current record.
  const selectedDetail =
    expanded != null ? (details[expanded] ?? "loading") : null;
  const loadedSelectedDetail =
    selectedDetail != null &&
    selectedDetail !== "loading" &&
    selectedDetail !== "error"
      ? selectedDetail
      : null;
  const expansionNode =
    expanded != null ? (
      <CallExpansion detail={selectedDetail ?? "loading"} />
    ) : null;
  const selectedModel =
    loadedSelectedDetail?.model ?? selectedSummary?.model ?? null;
  const selectedBackend =
    loadedSelectedDetail?.backend ?? selectedSummary?.backend ?? null;
  const selectedCaller =
    loadedSelectedDetail?.caller_tag ?? selectedSummary?.callerTag ?? null;
  const selectedRun =
    loadedSelectedDetail?.run_id ?? selectedSummary?.runId ?? null;
  const selectedTimestamp =
    loadedSelectedDetail?.timestamp ?? selectedSummary?.ts ?? null;
  const refreshedAt = exactUtcTime(tablePoll.asOf);

  // The gap marker's "refresh": drop the paged rows and start over from
  // the live page — the only honest way to close a hole whose middle rows
  // were never fetched.
  const resetPaging = () => {
    pagingGenerationRef.current += 1;
    setOlder([]);
    setPager("idle");
    setNextBoundary(null);
    setPageGap(false);
    hasPagedRef.current = false;
  };

  // The boundary for the next click: the oldest fetched page's stated fill
  // point, else the live page's. NEVER the oldest rendered timestamp.
  const boundary = (sameRetentionKey ? nextBoundary : null) ?? pageBoundary(data);
  const canPage = pagingReady && boundary.supported && boundary.ts != null;
  // What the pager control actually shows. A settled ("idle") pager still
  // has to answer the live page honestly: it may already say the scan
  // reached the file start, or name no boundary at all.
  const pagerState: PagerState =
    !pagingReady ? "idle" : pager !== "idle"
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
    const generation = pagingGenerationRef.current;
    const currentRequest = () => retentionKeyRef.current === appliedKey &&
      pagingGenerationRef.current === generation;
    hasPagedRef.current = true;
    setPager("loading");
    getOlderModelIO(applied, boundary.ts)
      .then((r) => {
        if (!currentRequest()) return;
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
      .catch(() => { if (currentRequest()) setPager("error"); });
  };

  return (
    <div className="page-full" data-testid="modelio-page">
      <header className="modelio-page-header">
        <p>Operations</p>
        <h1>Model I/O</h1>
        <div>
          Find and inspect recorded model call attempts. A recorded call is
          not a scientific result.
        </div>
      </header>

      <section className="modelio-scope" aria-label="Calls source and related views">
        <div className="modelio-scope-main">
          <div>
            <h2>Main calls log</h2>
            <code>{data?.source ?? "logs/calls.jsonl"}</code>
          </div>
          <span data-testid="modelio-result-count" aria-live="polite">
            {data == null
              ? "Count unavailable"
              : `${feed.length} visible ${feed.length === 1 ? "record" : "records"}`}
          </span>
          <span data-testid="modelio-freshness">
            {paused
              ? refreshedAt
                ? `Updates paused · as of ${refreshedAt}`
                : "Updates paused · no snapshot received"
              : stale
                ? refreshedAt
                  ? `Refresh failed · last received ${refreshedAt}`
                  : "Refresh failed · no snapshot received"
                : refreshedAt
                  ? `Updated ${refreshedAt}`
                  : "Awaiting first read"}
          </span>
        </div>
        <div className="modelio-related" aria-label="Related Operations views">
          <a href="/cycles">Trace history</a>
          <a href="/development">Operations status</a>
          <span id="research-suggestions">
            Research suggestions and ruling history:{" "}
            <a
              aria-label="Open existing human review controls"
              href={`/development${window.location.search}#frontier-reviews`}
            >
              Human reviews
            </a>
          </span>
        </div>
        <details className="modelio-source-disclosure" data-testid="modelio-footnote">
          <summary>Source scope</summary>
          <p>
            This view reads the main log <code>logs/calls.jsonl</code> only.
            Experiment and benchmark runs redirect calls to their own{" "}
            <code>runs/*.calls.jsonl</code> through LOOP_V0_CALLS_LOG and are
            not represented by an empty result here.
          </p>
        </details>
      </section>

      {/* Filters + live-state controls. */}
      <div className="modelio-controls">
        <div className="modelio-filters" aria-label="Filter recorded calls">
          <label>
            <span>Model contains</span>
            <input
              className={INPUT_CLS}
              aria-label="filter by model"
              value={inputs.model ?? ""}
              onChange={(e) =>
                setInputs((f) => ({
                  ...f,
                  model: e.target.value || undefined,
                }))
              }
            />
          </label>
          <label>
            <span>Caller tag contains</span>
            <input
              className={INPUT_CLS}
              aria-label="filter by caller tag"
              value={inputs.callerTag ?? ""}
              onChange={(e) =>
                setInputs((f) => ({
                  ...f,
                  callerTag: e.target.value || undefined,
                }))
              }
            />
          </label>
          <label>
            <span>Run ID equals</span>
            <input
              className={INPUT_CLS}
              aria-label="filter by run id"
              value={inputs.runId ?? ""}
              onChange={(e) =>
                setInputs((f) => ({
                  ...f,
                  runId: e.target.value || undefined,
                }))
              }
            />
          </label>
          {(inputs.model || inputs.callerTag || inputs.runId) && (
            <button
              type="button"
              className="modelio-clear-filters"
              onClick={() => setInputs({})}
            >
              Clear filters
            </button>
          )}
        </div>
        <button
          type="button"
          className="modelio-pause"
          aria-pressed={paused}
          onClick={() => setPaused((p) => !p)}
        >
          {paused ? "Resume updates" : "Pause updates"}
        </button>
        <span className="modelio-poll-scope">
          {paused
            ? "Only this page is paused"
            : `This page refreshes every ${Math.round(pollMs / 1000)}s`}
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

          <div
            className="modelio-workspace"
            data-context-open={expanded != null ? "true" : "false"}
          >
            <div className="modelio-feed-pane">
          <Card className="modelio-feed-card" testId="modelio-table">
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
              <div className="modelio-feed">
                <div className="modelio-feed-header" aria-hidden="true">
                  <span>Time</span>
                  <span>Model / backend</span>
                  <span>Caller / run</span>
                  <span>Recorded</span>
                  <span>Latency / tokens</span>
                  <span>Summary</span>
                  <span>Record</span>
                </div>
                {feed.map((item, i) => (
                  <Fragment key={item.key ?? `${item.ts ?? "row"}-${i}`}>
                    {/* Explicit hole between the live page and the rows
                        retained below it — never a silent misordering. */}
                    {visibleGap && i === newestCount && i > 0 && (
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
                      <div className="modelio-session-record">
                        <SessionThreadCard
                          thread={item.thread}
                          expandedRequestId={expanded}
                          onToggleContext={toggleRow}
                        />
                      </div>
                    ) : (
                      <CallRow
                        call={item.call}
                        expanded={
                          expanded != null && expanded === item.call.request_id
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
                  disabled={!pagingReady || pagerState === "loading"}
                  className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:border-zinc-500 disabled:opacity-50"
                  onClick={loadOlder}
                >
                  {!pagingReady ? "waiting for current filter…" : pagerState === "loading" ? "loading…" : "load older ▾"}
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
            </div>

            {expanded != null && (
              <aside
                id="modelio-selected-context"
                className="modelio-context-pane"
                data-testid="modelio-context"
                aria-labelledby="modelio-context-title"
              >
                <header className="modelio-context-header">
                  <button
                    ref={contextCloseRef}
                    type="button"
                    className="modelio-context-close"
                    onClick={closeContext}
                  >
                    <span className="modelio-context-back-label">
                      Back to calls
                    </span>
                    <span className="modelio-context-close-label">
                      Close record
                    </span>
                  </button>
                  <p>
                    Selected {selectedSummary?.context ?? "recorded call"}
                  </p>
                  <h2 id="modelio-context-title">
                    {selectedCaller ?? "Recorded call"}
                  </h2>
                  <code>{expanded}</code>
                </header>

                {!summaryMapRef.current.has(expanded) && (
                  <p
                    className="modelio-selection-retained"
                    data-testid="selection-retained"
                  >
                    This exact record remains selected while the current feed
                    query shows a different set.
                  </p>
                )}

                <dl className="modelio-context-summary">
                  <div>
                    <dt>Recorded time</dt>
                    <dd>
                      {selectedTimestamp ? (
                        <time dateTime={selectedTimestamp}>
                          {selectedTimestamp}
                        </time>
                      ) : (
                        "Not supplied"
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>Model / backend</dt>
                    <dd>
                      {selectedModel ?? "Not supplied"}
                      {selectedBackend ? ` / ${selectedBackend}` : ""}
                    </dd>
                  </div>
                  <div>
                    <dt>Run ID</dt>
                    <dd>{selectedRun ?? "Not supplied"}</dd>
                  </div>
                  <div>
                    <dt>Recorded condition</dt>
                    <dd>{selectedSummary?.condition ?? "Unknown field"}</dd>
                  </div>
                </dl>

                <div className="modelio-context-body">{expansionNode}</div>
              </aside>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// Memoized row: with identity-stable `call` objects (rowCacheRef), a stable
// `onToggle` (useCallback) and per-row `detail` values, a poll tick that
// changes the payload re-renders ONLY the genuinely new/changed rows — an
// open exact context (full MessageBody parse of a multi-KB record) no longer
// re-parses on every arrival elsewhere in the table.
const CallRow = memo(function CallRow({
  call,
  expanded,
  onToggle,
}: {
  call: ModelIOCall;
  expanded: boolean;
  onToggle: (requestId: string | null) => void;
}) {
  // Sanitized preview: completion first, prompt as the fallback (both run
  // through the channel-grammar splitter — raw <|channel> tokens never
  // reach the row). The tag chips above are untouched.
  const preview =
    sanitizePreview(call.completion_preview) ??
    sanitizePreview(call.prompt_preview);
  const structuredPreview =
    preview != null &&
    /^(?:\s*[\[{]|\s*```json|\s*<\|?tool_call)/i.test(preview.text);
  const summary = structuredPreview
    ? "Structured payload recorded"
    : preview?.text || "No summary supplied";
  const canOpen = call.request_id != null && call.request_id !== "";
  return (
      <button
        type="button"
        data-testid="modelio-row"
        data-selected={expanded ? "true" : "false"}
        className="modelio-row"
        aria-label={
          canOpen
            ? `Open record ${call.request_id}, ${call.caller_tag ?? "caller not supplied"}, ${clockTime(call.ts)} UTC`
            : `Recorded call from ${call.caller_tag ?? "unknown caller"}; exact request ID unavailable`
        }
        aria-expanded={canOpen ? expanded : undefined}
        aria-controls={canOpen ? "modelio-selected-context" : undefined}
        disabled={!canOpen}
        onClick={() => onToggle(call.request_id)}
      >
        <span className="modelio-row-cell modelio-row-time">
          <span className="modelio-field-label">Time</span>
          <time className="font-mono" dateTime={call.ts ?? undefined}>
            {clockTime(call.ts)}
          </time>
        </span>
        <span className="modelio-row-cell modelio-row-model">
          <span className="modelio-field-label">Model / backend</span>
          <span className="modelio-inline-values">
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
          </span>
        </span>
        <span className="modelio-row-cell modelio-row-caller">
          <span className="modelio-field-label">Caller / run</span>
          <span className={`font-mono ${callerTagTone(call.caller_tag)}`}>
            {call.caller_tag ?? "—"}
          </span>
          <span className="modelio-run-id font-mono">
            {call.run_id ?? "Run not supplied"}
          </span>
        </span>
        <span className="modelio-row-cell modelio-row-condition">
          <span className="modelio-field-label">Recorded</span>
          {call.empty ? (
            <span className="modelio-condition modelio-condition--empty" data-testid="empty-flag">
              EMPTY
            </span>
          ) : (
            <span className="modelio-condition">Recorded</span>
          )}
        </span>
        <span className="modelio-row-cell modelio-row-cost">
          <span className="modelio-field-label">Latency / tokens</span>
          <span className="font-mono tabular-nums">
            {call.latency_ms != null ? `${fmt(call.latency_ms, 0)}ms` : "—"}
          </span>
          <span className="font-mono tabular-nums">
            {call.input_tokens ?? "—"}→{call.output_tokens ?? "—"} tok
          </span>
        </span>
        <span className="modelio-row-cell modelio-row-summary">
          <span className="modelio-field-label">Summary</span>
          <span className="modelio-summary-line">
          {preview?.thought && !structuredPreview && (
            <span
              data-testid="thought-chip"
              className="modelio-thought-chip"
            >
              thought
            </span>
          )}
          <span
            data-testid="row-preview"
          >
            {summary}
          </span>
          </span>
        </span>
        <span className="modelio-row-cell modelio-row-open">
          <span>{canOpen ? (expanded ? "Selected" : "Open record") : "ID unavailable"}</span>
        </span>
      </button>
  );
});
