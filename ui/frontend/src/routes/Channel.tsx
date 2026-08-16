// Channel (/channel) — the always-on human ⇄ Nara ⇄ PI conversation surface
// (UI simplification plan §S4, the lab channel). One feed merges the stored
// transcript (human/nara/pi turns) with apparatus events the CLI derives at
// read time (cycles / ladder kills / promotions / loop alerts). Below it: a
// turn composer with a role selector (ask Nara = the operations voice / ask PI
// = the research voice), and a DELEGATE composer whose confirm card is the
// ONLY path that posts a delegation.
//
// CHAT LAYOUT (loop3h-ui-hotfix): the page is a viewport-bounded flex column
// — the feed scrolls in its own overflow container (chronological, NEWEST AT
// BOTTOM, auto-scroll pinned to the bottom while the reader stays there) and
// the composer dock is always visible below it. First load asks the seam for
// only the newest FIRST_LOAD_LIMIT rows; "load older" refetches with a larger
// limit and prepends (dedupe absorbs the overlap).
//
// R4 — the feed reads as a designed conversation rather than a log:
//   · turns are DOCUMENT-STYLE voice blocks (avatar mark · name · time, body
//     below, a 2px left rail in the voice's color; the human's own turns take
//     a surface tint). Not bubbles — bubbles stop scanning at length.
//   · events are compact single-line rows (16px glyph · label · text · time),
//     visually subordinate to speech, with the same >=3 same-chip run collapse
//     restyled as the timeline "N events — expand" affordance.
//   · filter chips (all / conversation / events) over the loaded rows, day
//     dividers in the feed, a jump-to-present affordance when scrolled up, and
//     a pending block on the turn in flight.
//   · ids the apparatus wrote (cl-* / iter-* / sf-*) render as reference chips
//     that PEEK (R0 PeekPanel) — the referenced object is never inlined here.
//
// THE FENCE: no disposition surface exists anywhere on this page — the
// blessed CLI behind it exposes exactly {timeline, turn, delegate} (no
// verdict verb), and this page renders no verdict/disposition form. The
// dossier reader's forms remain the only dispositions. The peek is read-only
// and carries no disposition either.
//
// ONE-MODEL HONESTY (D-033/D-036): "nara" and "pi" are perspectives of the
// SAME local model (Gemma) — never independent confirmation. The independent
// adversarial skeptic (Qwen) lives in the dossier reader's two-voice chat,
// not here; the note next to the role selector says so.
import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  getChannelAvailability,
  getChannelTimeline,
  postChannelDelegate,
  postChannelTurn,
} from "../api/channel";
import type { ChannelRow } from "../api/channel";
import EndpointMissingNote, {
  isVersionSkew404,
} from "../components/EndpointMissingNote";
import MiniMarkdown from "../components/MiniMarkdown";
import { RefChipRow, RefText } from "../components/channel/ChannelRefs";
import RefPeekBody from "../components/channel/RefPeekBody";
import {
  FILTERS,
  activityOf,
  collapseNoun,
  eventChip,
  groupFeed,
  hhmm,
  refsIn,
  rowKey,
  sortRows,
} from "../components/channel/channelModel";
import type {
  ChannelFilter,
  ChannelRef,
  FeedItem,
} from "../components/channel/channelModel";
import PeekPanel from "../design/PeekPanel";
import StatusDot from "../design/StatusDot";
import "../components/channel/channel.css";

const TIMELINE_ENDPOINT = "/api/channel/timeline";
// First load = the newest N rows only (the CLI's --limit keeps the NEWEST N;
// the old 400-row oldest-first wall is the bug this replaces).
const FIRST_LOAD_LIMIT = 40;
// Each "load older" click widens the full-fetch window by this much…
const OLDER_PAGE = 40;
// …capped at the seam's _MAX_LIMIT (lab_channel_seam.py rejects more).
const MAX_TIMELINE_LIMIT = 1000;

type Role = "nara" | "pi";
type DelegateKind = "research" | "improvement";

// ── voices ──────────────────────────────────────────────────────────────
// `accent` is a channel-local voice hue (see channel.css for why R0 has no
// token for speaker identity); `own` marks the reader's own turns, which take
// the surface tint instead of a hue.
const VOICE: Record<
  string,
  { label: string; mark: string; accent: string; own?: boolean }
> = {
  human: {
    label: "you",
    mark: "y",
    accent: "var(--voice-human)",
    own: true,
  },
  nara: {
    label: "nara · operations voice",
    mark: "n",
    accent: "var(--voice-nara)",
  },
  pi: {
    label: "pi · research voice",
    mark: "p",
    accent: "var(--voice-pi)",
  },
  // The ratified mission steward (2026-08-16): another session that talks to
  // the lab through the same CLI (`turn --as oracle`). It is an OBSERVER —
  // it holds no disposition and writes nothing here the owner does not.
  // Distinct hue so a steward turn is never misread as the owner's.
  oracle: {
    label: "oracle · mission steward",
    mark: "o",
    accent: "var(--voice-oracle)",
  },
};

const VOICE_FALLBACK = {
  label: "voice",
  mark: "?",
  accent: "var(--voice-other)",
  own: false,
};

function voiceOf(kind: string) {
  // Own-key lookup — a producer kind named "toString" must not resolve a
  // prototype member into the chrome (SourceBadge/chips idiom).
  return Object.prototype.hasOwnProperty.call(VOICE, kind)
    ? VOICE[kind]
    : VOICE_FALLBACK;
}

// What a delegation WRITES and WHERE — the confirm card renders this verbatim
// so the human confirms the actual side effect, not a paraphrase.
function delegateTargets(kind: DelegateKind, clusterId: string): string[] {
  if (kind === "research") {
    const target = clusterId.trim()
      ? `cluster ${clusterId.trim()}`
      : "the standing cluster cl-human-delegations (auto-created if absent)";
    return [
      `agenda_item_added event (source: human) → memory/idea_ledger.jsonl, on ${target}`,
      "DELEGATED[research] mirror row → memory/lab_channel.jsonl (the transcript)",
    ];
  }
  return [
    "one authorize_fix packet row (full spawn contract, status: enqueued) → memory/authorize_fix_queue.jsonl — the packet dispatcher's queue",
    "DELEGATED[improvement] mirror row → memory/lab_channel.jsonl (the transcript)",
  ];
}

interface Props {
  /** Fixture rows for tests (undefined = fetch live). Fixture mode never
   *  shows "load older" — that button belongs to the live limit-window. */
  initial?: ChannelRow[];
  /** Capability override for tests (undefined = probe live). */
  initialAvailable?: boolean;
  pollMs?: number;
}

export default function Channel({
  initial,
  initialAvailable,
  pollMs = 10_000,
}: Props) {
  const [rows, setRows] = useState<ChannelRow[]>(() =>
    sortRows(initial ?? []),
  );
  const [loaded, setLoaded] = useState(initial !== undefined);
  const [skew, setSkew] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [available, setAvailable] = useState<boolean>(
    initialAvailable === true,
  );
  const [mayHaveOlder, setMayHaveOlder] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [expandedWalls, setExpandedWalls] = useState<ReadonlySet<string>>(
    new Set(),
  );
  const [filter, setFilter] = useState<ChannelFilter>("all");
  const [peek, setPeek] = useState<ChannelRef | null>(null);
  const [atBottom, setAtBottom] = useState(true);

  // turn composer
  const [role, setRole] = useState<Role>("nara");
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [pending, setPending] = useState<{ role: Role; message: string } | null>(
    null,
  );
  const [sendError, setSendError] = useState<string | null>(null);

  // delegate composer
  const [dKind, setDKind] = useState<DelegateKind>("research");
  const [dText, setDText] = useState("");
  const [dClusterId, setDClusterId] = useState("");
  const [dObjective, setDObjective] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [delegating, setDelegating] = useState(false);
  const [delegateError, setDelegateError] = useState<string | null>(null);
  const [delegateDone, setDelegateDone] = useState<string | null>(null);

  const seenRef = useRef<Set<string>>(new Set(initial?.map(rowKey) ?? []));
  const sinceRef = useRef<string | null>(null);
  // The full-fetch window (--limit = newest N); widened by "load older".
  const limitRef = useRef(FIRST_LOAD_LIMIT);

  // Scroll pinning: the feed autoscrolls to the bottom on new rows while the
  // reader is at (or near) the bottom; a "load older" prepend instead keeps
  // the reader's distance-from-bottom (anchorRef) so the view doesn't jump.
  const feedRef = useRef<HTMLDivElement | null>(null);
  const pinnedRef = useRef(true);
  const anchorRef = useRef<number | null>(null);

  const merge = useCallback((incoming: ChannelRow[]): number => {
    const fresh = incoming.filter((r) => !seenRef.current.has(rowKey(r)));
    if (fresh.length === 0) return 0;
    for (const r of fresh) seenRef.current.add(rowKey(r));
    setRows((prev) => sortRows([...prev, ...fresh]));
    return fresh.length;
  }, []);

  const load = useCallback(async () => {
    try {
      const since = sinceRef.current;
      const resp =
        since === null
          ? await getChannelTimeline(undefined, limitRef.current)
          : await getChannelTimeline(since);
      merge(resp.rows);
      if (since === null) {
        // A full window that came back full probably truncated older rows.
        setMayHaveOlder(
          resp.rows.length >= limitRef.current &&
            limitRef.current < MAX_TIMELINE_LIMIT,
        );
      }
      for (const r of resp.rows) {
        if (r.ts && (sinceRef.current === null || r.ts > sinceRef.current)) {
          sinceRef.current = r.ts;
        }
      }
      setLoaded(true);
      setSkew(false);
      setError(null);
    } catch (e) {
      if (isVersionSkew404(e, TIMELINE_ENDPOINT)) {
        setSkew(true);
        setError(null);
      } else {
        setError(String(e));
      }
      setLoaded(true);
    }
  }, [merge]);

  const loadOlder = useCallback(async () => {
    if (loadingOlder) return;
    setLoadingOlder(true);
    const el = feedRef.current;
    anchorRef.current = el ? el.scrollHeight - el.scrollTop : null;
    const next = Math.min(limitRef.current + OLDER_PAGE, MAX_TIMELINE_LIMIT);
    limitRef.current = next;
    try {
      // Full refetch with a wider newest-N window — the already-seen newest
      // rows dedupe away; only the older tail lands (prepended by the sort).
      const resp = await getChannelTimeline(undefined, next);
      const freshCount = merge(resp.rows);
      if (freshCount === 0) anchorRef.current = null;
      setMayHaveOlder(
        resp.rows.length >= next && next < MAX_TIMELINE_LIMIT,
      );
    } catch (e) {
      anchorRef.current = null;
      if (isVersionSkew404(e, TIMELINE_ENDPOINT)) setSkew(true);
      else setError(String(e));
    } finally {
      setLoadingOlder(false);
    }
  }, [loadingOlder, merge]);

  // Keep the view pinned to the newest row (bottom) — unless the rows change
  // was a "load older" prepend, which instead restores the reader's
  // distance-from-bottom. Both are no-ops under jsdom (all heights are 0).
  useEffect(() => {
    const el = feedRef.current;
    if (!el) return;
    if (anchorRef.current !== null) {
      el.scrollTop = el.scrollHeight - anchorRef.current;
      anchorRef.current = null;
    } else if (pinnedRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [rows]);

  const onFeedScroll = useCallback(() => {
    const el = feedRef.current;
    if (!el) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
    pinnedRef.current = bottom;
    setAtBottom(bottom);
  }, []);

  const jumpToPresent = useCallback(() => {
    const el = feedRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    pinnedRef.current = true;
    setAtBottom(true);
  }, []);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const tick = () => {
      if (active) void load();
    };
    tick();
    const id = setInterval(tick, Math.max(5_000, pollMs));
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [initial, pollMs, load]);

  useEffect(() => {
    if (initialAvailable !== undefined) return;
    let active = true;
    getChannelAvailability()
      .then((cap) => {
        if (active) setAvailable(cap.available === true);
      })
      .catch(() => {
        /* probe unreachable — composers stay preview-only (available false) */
      });
    return () => {
      active = false;
    };
  }, [initialAvailable]);

  const sendDisabled = !available || sending || draft.trim().length === 0;

  const onSend = async () => {
    if (sendDisabled) return;
    const message = draft.trim();
    setSending(true);
    setPending({ role, message });
    setSendError(null);
    try {
      await postChannelTurn({ role, message });
      setDraft("");
      // The CLI appended the human + reply rows; pick them up now rather
      // than waiting a poll interval.
      await load();
    } catch (e) {
      const err = e as { stderr?: string | null; message?: string };
      setSendError(
        typeof err?.stderr === "string" && err.stderr.length > 0
          ? err.stderr
          : e instanceof Error
            ? e.message
            : "channel seam unavailable",
      );
    } finally {
      setSending(false);
      setPending(null);
    }
  };

  const reviewDisabled = !available || delegating || dText.trim().length === 0;

  // The ONLY code path that posts a delegation — reached exclusively from the
  // confirm card's confirm button.
  const onConfirmDelegate = async () => {
    if (!confirming || delegating) return;
    setDelegating(true);
    setDelegateError(null);
    setDelegateDone(null);
    try {
      const body: {
        kind: DelegateKind;
        text: string;
        cluster_id?: string;
        objective?: string;
      } = { kind: dKind, text: dText.trim() };
      if (dKind === "research" && dClusterId.trim()) {
        body.cluster_id = dClusterId.trim();
      }
      if (dKind === "improvement" && dObjective.trim()) {
        body.objective = dObjective.trim();
      }
      const result = await postChannelDelegate(body);
      setConfirming(false);
      setDText("");
      setDClusterId("");
      setDObjective("");
      setDelegateDone(
        result?.status === "preview"
          ? "preview only — the backend capability is off; nothing was written."
          : `delegation recorded (${dKind}).`,
      );
      await load(); // the DELEGATED[...] mirror row lands in the feed
    } catch (e) {
      const err = e as { stderr?: string | null };
      setDelegateError(
        typeof err?.stderr === "string" && err.stderr.length > 0
          ? err.stderr
          : e instanceof Error
            ? e.message
            : "channel seam unavailable",
      );
    } finally {
      setDelegating(false);
    }
  };

  // The selector names the voice you are addressing, so its active state takes
  // that VOICE's accent — the same hue as that voice's blocks in the feed
  // (it used to be emerald, which is the status set's "pass" color).
  const roleChip = (r: Role, label: string) => (
    <button
      key={r}
      type="button"
      data-testid={`channel-role-${r}`}
      aria-pressed={role === r}
      onClick={() => setRole(r)}
      className="chn-chip chn-chip--voice"
      style={{ "--voice-accent": VOICE[r].accent } as CSSProperties}
    >
      {label}
    </button>
  );

  const feedItems = groupFeed(rows, expandedWalls, filter);
  const openPeek = (r: ChannelRef) => setPeek(r);

  // ── one turn: a document-style voice block ────────────────────────────
  const renderTurn = (item: Extract<FeedItem, { type: "single" }>) => {
    const r = item.row;
    const voice = voiceOf(r.kind);
    // Model voices reply in markdown — render it, and collect the ids it
    // mentions into a chip row (MiniMarkdown is shared with the journal /
    // experiment readers; R4 does not fork it to inline chips). The human's
    // own turns (and unknown kinds) stay verbatim text with INLINE chips.
    const isModelVoice = r.kind === "nara" || r.kind === "pi";
    const activity = activityOf(r.message);
    const body = activity !== null ? activity.body : r.message;
    return (
      <article
        key={item.key}
        data-testid={`channel-turn-${r.kind}`}
        data-voice={r.kind}
        className={`chn-turn${voice.own ? " chn-turn--own" : ""}`}
        style={{ "--voice-accent": voice.accent } as CSSProperties}
      >
        <div className="chn-turn-head">
          <span
            className="chn-avatar"
            data-testid="channel-voice-avatar"
            aria-hidden="true"
          >
            {voice.mark}
          </span>
          <span className="chn-name" data-testid="channel-voice-name">
            {voice.label}
          </span>
          {activity !== null && (
            <span
              className="chn-ref"
              data-testid="channel-activity-chip"
              style={{ color: "var(--fg-muted)", cursor: "default" }}
            >
              {activity.label}
            </span>
          )}
          <time
            className="chn-time"
            data-testid="channel-voice-time"
            dateTime={r.ts}
          >
            {hhmm(r.ts)}
          </time>
        </div>
        {isModelVoice ? (
          <div className="chn-body" data-testid="channel-voice-body">
            <MiniMarkdown source={body} />
            <RefChipRow refs={refsIn(body)} onOpen={openPeek} />
          </div>
        ) : (
          <div
            className="chn-body chn-body--raw"
            data-testid="channel-voice-body"
          >
            <RefText text={body} onOpen={openPeek} />
          </div>
        )}
      </article>
    );
  };

  // ── one system event: a compact, subordinate single-line row ──────────
  const renderEvent = (item: Extract<FeedItem, { type: "single" }>) => {
    const r = item.row;
    const chip = eventChip(r.message);
    return (
      <div
        key={item.key}
        data-testid="channel-event-row"
        className="chn-event"
        style={
          { "--event-tone": `var(--status-${chip.tone})` } as CSSProperties
        }
      >
        <span className="chn-event-glyph" aria-hidden="true">
          {chip.glyph}
        </span>
        <span data-testid="channel-event-chip" className="chn-event-label">
          {chip.label}
        </span>
        <span className="chn-event-text">
          <RefText text={r.message} onOpen={openPeek} />
        </span>
        <time className="chn-event-time" dateTime={r.ts}>
          {hhmm(r.ts)}
        </time>
      </div>
    );
  };

  const renderRow = (item: Extract<FeedItem, { type: "single" }>) =>
    item.row.kind === "event" ? renderEvent(item) : renderTurn(item);

  // The timeline collapse affordance: same row grammar as an event line, the
  // count is the button ("N cluster kills — expand").
  const renderWall = (item: Extract<FeedItem, { type: "wall" }>) => (
    <div
      key={item.key}
      data-testid="channel-event-wall"
      className="chn-event"
      style={{ "--event-tone": `var(--status-${item.tone})` } as CSSProperties}
    >
      <span className="chn-event-glyph" aria-hidden="true">
        {item.glyph}
      </span>
      <span className="chn-event-label">{item.label}</span>
      <button
        type="button"
        data-testid="channel-event-wall-expand"
        className="chn-collapse"
        onClick={() => setExpandedWalls((prev) => new Set(prev).add(item.key))}
      >
        {item.rows.length} {collapseNoun(item.label)} — expand
      </button>
      <time className="chn-event-time">
        {hhmm(item.rows[0].ts)} → {hhmm(item.rows[item.rows.length - 1].ts)}
      </time>
    </div>
  );

  const renderItem = (item: FeedItem) => {
    if (item.type === "day") {
      return (
        <div key={item.key} data-testid="channel-day-divider" className="chn-day">
          <span>{item.label}</span>
        </div>
      );
    }
    return item.type === "wall" ? renderWall(item) : renderRow(item);
  };

  return (
    // Viewport-bounded chat column (56px ≈ the app header; the ActivityGraph
    // viewport-calc idiom): feed scrolls in its own overflow container, the
    // composer dock stays visible at the bottom of the page area. max-w-3xl
    // = 768px — the top of the ~720-768px reading band (R0's .page-prose is
    // not adopted here: it brings its own margins/padding, which fight the
    // full-height flex column this page needs).
    <div
      className="chn mx-auto flex h-[calc(100dvh-3.5rem)] max-w-3xl flex-col p-5 pb-3"
      data-testid="channel-page"
    >
      <header className="mb-2 shrink-0">
        <h1 className="text-sm font-semibold uppercase tracking-wide text-zinc-300">
          /channel · lab channel
        </h1>
        <p className="mt-0.5 text-[11px] text-zinc-500">
          The always-on conversation with the apparatus: your turns, the two
          voices, and the loop&apos;s own events (cycles · kills · promotions
          · alerts) in one feed. Nothing here disposes of anything — verdicts
          live in the dossier reader.
        </p>
        <div
          className="mt-2 flex flex-wrap items-center gap-1.5"
          data-testid="channel-filters"
        >
          {FILTERS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              className="chn-chip"
              data-testid={`channel-filter-${value}`}
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      {error !== null && (
        <div className="text-xs text-red-400" data-testid="channel-error">
          {error}
        </div>
      )}

      {skew && <EndpointMissingNote endpoint={TIMELINE_ENDPOINT} />}

      {/* ── the feed — its own scroll container, newest at the bottom ── */}
      {!skew && error === null && (
        <div className="relative flex min-h-0 flex-1 flex-col">
          <div
            ref={feedRef}
            onScroll={onFeedScroll}
            className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1"
            data-testid="channel-feed"
          >
            {mayHaveOlder && (
              <button
                type="button"
                disabled={loadingOlder}
                onClick={() => void loadOlder()}
                data-testid="channel-load-older"
                className="mx-auto block rounded border border-zinc-700 px-2 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400 hover:text-zinc-200 disabled:cursor-not-allowed disabled:text-zinc-600"
              >
                {loadingOlder ? "loading older…" : "load older"}
              </button>
            )}
            {loaded && rows.length === 0 && (
              <div className="text-xs text-zinc-600" data-testid="channel-empty">
                no channel activity yet — memory/lab_channel.jsonl has no turns
                and no events derive from the ledgers. Ask a voice below.
              </div>
            )}
            {rows.length > 0 && feedItems.length === 0 && (
              <div
                className="text-xs text-zinc-600"
                data-testid="channel-filter-empty"
              >
                no {filter} rows in the loaded window — the other rows are
                still there, the filter is hiding them.
              </div>
            )}
            {feedItems.map(renderItem)}
            {pending !== null && filter !== "events" && (
              <div
                data-testid="channel-pending-turn"
                className="chn-pending"
                style={
                  {
                    "--voice-accent": voiceOf(pending.role).accent,
                  } as CSSProperties
                }
              >
                <StatusDot status="info" pulse label={`${pending.role} is composing`} />
                <span>
                  {pending.role} is composing a reply — a live turn can take
                  minutes. The seam has no abort verb, so it cannot be stopped
                  from here; the reply lands in the transcript either way.
                </span>
              </div>
            )}
          </div>
          {!atBottom && (
            <button
              type="button"
              className="chn-jump"
              data-testid="channel-jump-present"
              onClick={jumpToPresent}
            >
              jump to present ↓
            </button>
          )}
        </div>
      )}

      {/* ── composer dock — always visible below the feed ── */}
      <div className="shrink-0">
        {/* turn composer */}
        <div
          className="mt-3 rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5"
          data-testid="channel-composer"
        >
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] uppercase tracking-wide text-zinc-600">
              ask
            </span>
            {roleChip("nara", "nara · operations")}
            {roleChip("pi", "pi · research")}
          </div>
          {/* ONE-MODEL HONESTY — rendered next to the selector, always. */}
          <div
            className="mt-1 text-[10px] text-zinc-500"
            data-testid="channel-honesty-note"
          >
            honesty: nara and pi are perspectives of the SAME local model
            (Gemma) — never treat one as independent confirmation of the other.
            The independent adversarial skeptic (Qwen) lives in the dossier
            reader&apos;s two-voice chat, not in this channel.
          </div>

          {!available && (
            <div
              className="mt-1 text-[10px] text-zinc-500"
              data-testid="channel-capability-off"
            >
              capability disabled — the lab-channel exec is not enabled on this
              backend. No model calls happen here; your message is not sent.
            </div>
          )}

          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            aria-label="channel turn input"
            placeholder={
              available
                ? `ask the ${role === "nara" ? "operations" : "research"} voice`
                : "channel disabled — not sent"
            }
            rows={2}
            className="mt-1.5 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
          />
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              disabled={sendDisabled}
              onClick={() => void onSend()}
              data-testid="channel-send"
              className="rounded border border-zinc-600 bg-zinc-900 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-zinc-300 hover:bg-zinc-800 disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-600"
            >
              send to {role}
            </button>
            {sending && (
              <span data-testid="channel-sending" className="text-[11px] text-zinc-500">
                asking {role}… (a live turn can take minutes)
              </span>
            )}
          </div>
          {sendError !== null && (
            <div
              data-testid="channel-send-error"
              className="mt-1 overflow-x-auto whitespace-pre-wrap rounded border border-red-900 bg-red-950/40 p-2 font-mono text-[11px] text-red-400"
            >
              {sendError}
            </div>
          )}
        </div>

        {/* ── delegate composer — a disclosure so the dock stays compact
            (everything inside is unchanged; the confirm card remains the
            ONLY path that posts) ── */}
        <details
          className="mt-2 rounded border border-sky-900/50 bg-sky-950/10 px-2 py-1.5"
          data-testid="channel-delegate"
        >
          <summary className="cursor-pointer list-none text-[10px] uppercase tracking-wide text-sky-400">
            delegate to the apparatus{" "}
            <span aria-hidden="true" className="text-zinc-600">
              ▾
            </span>
          </summary>
          <div className="mt-0.5 text-[10px] text-zinc-500">
            &quot;put it on your todo list&quot; — research goes on the idea
            ledger&apos;s agenda; improvement enqueues an authorize_fix packet.
            Nothing is written until you confirm the card.
          </div>

          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {(["research", "improvement"] as const).map((k) => (
              <button
                key={k}
                type="button"
                data-testid={`channel-delegate-kind-${k}`}
                aria-pressed={dKind === k}
                onClick={() => {
                  setDKind(k);
                  setConfirming(false); // an edit invalidates a pending confirm
                }}
                className={`rounded border px-2 py-0.5 text-[10px] uppercase tracking-wide ${
                  dKind === k
                    ? "border-sky-700 bg-sky-950/40 text-sky-300"
                    : "border-zinc-700 text-zinc-400 hover:text-zinc-200"
                }`}
              >
                {k}
              </button>
            ))}
          </div>

          <textarea
            value={dText}
            onChange={(e) => {
              setDText(e.target.value);
              setConfirming(false); // an edit invalidates a pending confirm
            }}
            aria-label="delegation text"
            data-testid="channel-delegate-text"
            placeholder={
              dKind === "research"
                ? "the research question / agenda topic"
                : "the improvement to authorize (spawn-contract task statement)"
            }
            rows={2}
            className="mt-1.5 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
          />
          {dKind === "research" && (
            <input
              value={dClusterId}
              onChange={(e) => {
                setDClusterId(e.target.value);
                setConfirming(false);
              }}
              aria-label="target cluster id (optional)"
              data-testid="channel-delegate-cluster"
              placeholder="cluster id (optional — defaults to cl-human-delegations)"
              className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[10px] text-zinc-300 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
            />
          )}
          {dKind === "improvement" && (
            <input
              value={dObjective}
              onChange={(e) => {
                setDObjective(e.target.value);
                setConfirming(false);
              }}
              aria-label="objective (optional)"
              data-testid="channel-delegate-objective"
              placeholder="objective (optional — defaults to the text above)"
              className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[10px] text-zinc-300 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
            />
          )}

          {!confirming && (
            <button
              type="button"
              disabled={reviewDisabled}
              onClick={() => setConfirming(true)}
              data-testid="channel-delegate-review"
              className="mt-1.5 rounded border border-sky-800 bg-sky-950/40 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-sky-300 hover:bg-sky-900/40 disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-600"
            >
              review delegation…
            </button>
          )}

          {/* CONFIRM CARD — shows exactly what will be written where; the
              confirm button below is the ONLY path that posts. */}
          {confirming && (
            <div
              className="mt-1.5 rounded border border-sky-800 bg-sky-950/30 px-2 py-1.5"
              data-testid="delegate-confirm-card"
            >
              <div className="text-[10px] uppercase tracking-wide text-sky-300">
                confirm delegation · {dKind}
              </div>
              <div className="mt-1 whitespace-pre-wrap font-mono text-[11px] text-zinc-200">
                {dText.trim()}
              </div>
              <div className="mt-1.5 text-[10px] text-zinc-400">
                confirming writes exactly:
              </div>
              <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-[10px] text-zinc-400">
                {delegateTargets(dKind, dClusterId).map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  disabled={delegating}
                  onClick={() => void onConfirmDelegate()}
                  data-testid="delegate-confirm"
                  className="rounded border border-sky-600 bg-sky-900/60 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-sky-200 hover:bg-sky-800/60 disabled:cursor-not-allowed disabled:text-zinc-600"
                >
                  confirm — write it
                </button>
                <button
                  type="button"
                  onClick={() => setConfirming(false)}
                  data-testid="delegate-cancel"
                  className="rounded border border-zinc-700 px-2 py-0.5 text-[11px] uppercase tracking-wide text-zinc-400 hover:text-zinc-200"
                >
                  cancel
                </button>
                {delegating && (
                  <span className="text-[11px] text-zinc-500">writing…</span>
                )}
              </div>
            </div>
          )}

          {delegateDone !== null && (
            <div
              data-testid="channel-delegate-result"
              className="mt-1 text-[11px] text-emerald-400"
            >
              {delegateDone}
            </div>
          )}
          {delegateError !== null && (
            <div
              data-testid="channel-delegate-error"
              className="mt-1 overflow-x-auto whitespace-pre-wrap rounded border border-red-900 bg-red-950/40 p-2 font-mono text-[11px] text-red-400"
            >
              {delegateError}
            </div>
          )}
        </details>
      </div>

      {/* Reference peek — read-only summary + the one link onward. The object
          is NEVER inlined into the thread. */}
      <PeekPanel
        open={peek !== null}
        onClose={() => setPeek(null)}
        title={peek?.id ?? ""}
        width={440}
      >
        {peek !== null && <RefPeekBody refItem={peek} />}
      </PeekPanel>
    </div>
  );
}
