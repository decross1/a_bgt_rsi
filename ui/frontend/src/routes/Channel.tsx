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
  channelRows,
  getChannelAvailability,
  getChannelTimeline,
  postChannelDelegate,
  postChannelTurn,
} from "../api/channel";
import type { ChannelRow, ChannelTimeline } from "../api/channel";
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
type ContextView = "guide" | "record" | "delegate";
type ReadState = NonNullable<ChannelTimeline["readState"]>;

interface ActionCapabilities {
  turn: boolean;
  delegate: boolean;
}

const NO_ACTIONS: ActionCapabilities = { turn: false, delegate: false };
const CONTEXT_FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function isFramedIntegrity(value: unknown): boolean {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const integrity = value as Record<string, unknown>;
  return (
    integrity.schema === "lab-channel-timeline/v1" &&
    integrity.framing === "json-envelope" &&
    integrity.status === "framed" &&
    integrity.actor_labels === "recorded_not_authenticated"
  );
}

function shortUtc(value: string | null): string {
  if (value === null || value === "") return "not available";
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(value);
  return match ? `${match[1]} · ${match[2]} UTC` : value;
}

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
  initialIntegrity?: unknown;
  /** Explicit read-shape fixture. Live reads receive this from the API seam. */
  initialReadState?: ReadState;
  /** Capability override for tests (undefined = probe live). */
  initialAvailable?: boolean;
  /** Exact action capabilities for partial-capability fixtures. */
  initialCapabilities?: Partial<ActionCapabilities>;
  pollMs?: number;
}

export default function Channel({
  initial,
  initialIntegrity,
  initialReadState,
  initialAvailable,
  initialCapabilities,
  pollMs = 10_000,
}: Props) {
  const [rows, setRows] = useState<ChannelRow[]>(() =>
    sortRows(channelRows({ rows: initial ?? [], integrity: initialIntegrity })),
  );
  const [loaded, setLoaded] = useState(initial !== undefined);
  const [readState, setReadState] = useState<ReadState | null>(() =>
    initial === undefined
      ? null
      : (initialReadState ??
        (isFramedIntegrity(initialIntegrity) ? "framed" : "unframed")),
  );
  const [invalidRowCount, setInvalidRowCount] = useState(0);
  const [skew, setSkew] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState<string | null>(
    initial === undefined ? null : new Date().toISOString(),
  );
  const [lastSuccessAt, setLastSuccessAt] = useState<string | null>(
    initial === undefined ? null : new Date().toISOString(),
  );
  const [actionCapabilities, setActionCapabilities] =
    useState<ActionCapabilities>(() =>
      initialCapabilities !== undefined
        ? {
            turn: initialCapabilities.turn === true,
            delegate: initialCapabilities.delegate === true,
          }
        : initialAvailable === true
          ? { turn: true, delegate: true }
          : NO_ACTIONS,
    );
  const [capabilitiesKnown, setCapabilitiesKnown] = useState(
    initialAvailable !== undefined || initialCapabilities !== undefined,
  );
  const [mayHaveOlder, setMayHaveOlder] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [expandedWalls, setExpandedWalls] = useState<ReadonlySet<string>>(
    new Set(),
  );
  const [filter, setFilter] = useState<ChannelFilter>("all");
  const [peek, setPeek] = useState<ChannelRef | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [contextView, setContextView] = useState<ContextView>("guide");
  const [contextOpen, setContextOpen] = useState(false);
  const [narrow, setNarrow] = useState(false);
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
  const contextRef = useRef<HTMLElement | null>(null);
  const contextOpenerRef = useRef<HTMLElement | null>(null);
  const restoreContextFocusRef = useRef(false);

  const merge = useCallback((incoming: ChannelRow[]): number => {
    const fresh = incoming.filter((r) => !seenRef.current.has(rowKey(r)));
    if (fresh.length === 0) return 0;
    for (const r of fresh) seenRef.current.add(rowKey(r));
    setRows((prev) => sortRows([...prev, ...fresh]));
    return fresh.length;
  }, []);

  const load = useCallback(async () => {
    const attemptedAt = new Date().toISOString();
    try {
      const since = sinceRef.current;
      const resp =
        since === null
          ? await getChannelTimeline(undefined, limitRef.current)
          : await getChannelTimeline(since);
      merge(channelRows(resp));
      setReadState(
        resp.readState ??
          (isFramedIntegrity(resp.integrity) ? "framed" : "unframed"),
      );
      setInvalidRowCount(resp.invalidRowCount ?? 0);
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
      setCheckedAt(attemptedAt);
      setLastSuccessAt(attemptedAt);
    } catch (e) {
      if (isVersionSkew404(e, TIMELINE_ENDPOINT)) {
        setSkew(true);
        setError(null);
      } else {
        setError(String(e));
      }
      setLoaded(true);
      setCheckedAt(attemptedAt);
    }
  }, [merge]);

  const loadOlder = useCallback(async () => {
    if (loadingOlder) return;
    setLoadingOlder(true);
    const el = feedRef.current;
    anchorRef.current = el ? el.scrollHeight - el.scrollTop : null;
    const next = Math.min(limitRef.current + OLDER_PAGE, MAX_TIMELINE_LIMIT);
    limitRef.current = next;
    const attemptedAt = new Date().toISOString();
    try {
      // Full refetch with a wider newest-N window — the already-seen newest
      // rows dedupe away; only the older tail lands (prepended by the sort).
      const resp = await getChannelTimeline(undefined, next);
      const freshCount = merge(channelRows(resp));
      setReadState(
        resp.readState ??
          (isFramedIntegrity(resp.integrity) ? "framed" : "unframed"),
      );
      setInvalidRowCount(resp.invalidRowCount ?? 0);
      if (freshCount === 0) anchorRef.current = null;
      setMayHaveOlder(
        resp.rows.length >= next && next < MAX_TIMELINE_LIMIT,
      );
      setSkew(false);
      setError(null);
      setCheckedAt(attemptedAt);
      setLastSuccessAt(attemptedAt);
    } catch (e) {
      anchorRef.current = null;
      if (isVersionSkew404(e, TIMELINE_ENDPOINT)) setSkew(true);
      else setError(String(e));
      setCheckedAt(attemptedAt);
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
    if (initialAvailable !== undefined || initialCapabilities !== undefined) {
      return;
    }
    let active = true;
    getChannelAvailability()
      .then((cap) => {
        if (!active) return;
        setActionCapabilities({
          turn: cap.available === true && cap.actions.turn === true,
          delegate: cap.available === true && cap.actions.delegate === true,
        });
        setCapabilitiesKnown(true);
      })
      .catch(() => {
        if (active) setCapabilitiesKnown(true);
      });
    return () => {
      active = false;
    };
  }, [initialAvailable, initialCapabilities]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(max-width: 899px)");
    const sync = () => setNarrow(query.matches);
    sync();
    query.addEventListener?.("change", sync);
    return () => query.removeEventListener?.("change", sync);
  }, []);

  const closeContext = useCallback(() => {
    restoreContextFocusRef.current = true;
    setContextOpen(false);
  }, []);

  useEffect(() => {
    // Restore only after React removes the main surface's inert attribute.
    // Focusing in the close event is refused by real browsers.
    if (!contextOpen && restoreContextFocusRef.current) {
      restoreContextFocusRef.current = false;
      contextOpenerRef.current?.focus();
    }
  }, [contextOpen]);

  useEffect(() => {
    if (!narrow || !contextOpen) return;
    contextRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeContext();
        return;
      }
      if (event.key !== "Tab" || contextRef.current === null) return;
      const focusable = Array.from(
        contextRef.current.querySelectorAll<HTMLElement>(CONTEXT_FOCUSABLE),
      );
      if (focusable.length === 0) {
        event.preventDefault();
        contextRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey &&
          (document.activeElement === first || document.activeElement === contextRef.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [contextOpen, narrow, closeContext]);

  const openContext = (view: ContextView) => {
    contextOpenerRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setContextView(view);
    setContextOpen(true);
  };

  const sendDisabled =
    !actionCapabilities.turn || sending || draft.trim().length === 0;

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

  const reviewDisabled =
    !actionCapabilities.delegate || delegating || dText.trim().length === 0;

  // The ONLY code path that posts a delegation — reached exclusively from the
  // confirm card's confirm button.
  const onConfirmDelegate = async () => {
    if (!confirming || delegating || !actionCapabilities.delegate) return;
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

  const framedCount = rows.filter((row) => row.recordedLabel === true).length;
  const rawCount = rows.length - framedCount;
  const integrityMode =
    rows.length === 0
      ? readState === "framed"
        ? "framed-empty"
        : readState === "malformed"
          ? "malformed"
          : "unframed-empty"
      : framedCount === rows.length
        ? "framed"
        : framedCount === 0
          ? readState === "malformed"
            ? "malformed"
            : "raw"
          : "mixed";
  const semanticFiltersAvailable = rows.length > 0 && rawCount === 0;
  const activeFilter = semanticFiltersAvailable ? filter : "all";
  const feedItems = groupFeed(rows, expandedWalls, activeFilter);
  const selectedRow =
    selectedKey === null
      ? null
      : (rows.find((row) => rowKey(row) === selectedKey) ?? null);
  const loadedThrough =
    [...rows].reverse().find((row) => row.ts !== "")?.ts ?? null;

  const integrityCopy = (() => {
    if (integrityMode === "framed") {
      return {
        label: "Framed records",
        detail: "Conversation and event kinds are recorded labels, not authenticated identities.",
        tone: "framed",
      };
    }
    if (integrityMode === "framed-empty") {
      return {
        label: "Framed empty window",
        detail: "The source returned no records in this read. Full-ledger completeness is not asserted.",
        tone: "framed",
      };
    }
    if (integrityMode === "mixed") {
      return {
        label: "Mixed integrity",
        detail: `${rawCount} record${rawCount === 1 ? " has" : "s have"} no trusted actor or type framing. Inspect each record.`,
        tone: "raw",
      };
    }
    if (integrityMode === "malformed") {
      return {
        label: "Malformed timeline",
        detail: "No actor or type is trusted; an empty-history conclusion cannot be made.",
        tone: "error",
      };
    }
    return {
      label: rows.length > 0 ? "Raw records" : "Unframed empty read",
      detail: rows.length > 0
        ? "Actor and type are unavailable. Text stays byte-for-byte and is not grouped by prose."
        : "No framed records were returned, so missing history and an empty history remain distinct.",
      tone: "raw",
    };
  })();

  const openPeek = (r: ChannelRef) => setPeek(r);
  const inspectRow = (row: ChannelRow) => {
    setSelectedKey(rowKey(row));
    openContext("record");
  };

  // Unframed records use one neutral rail. Their producer-supplied `kind`
  // field is available only in the exact context view; it never selects a
  // voice, color, event chip, Markdown renderer, or grouping behavior.
  const renderRawRecord = (item: Extract<FeedItem, { type: "single" }>) => {
    const row = item.row;
    return (
      <article
        key={item.key}
        data-testid="channel-turn-unverified"
        data-voice="unverified"
        className="chn-raw-record"
      >
        <button
          type="button"
          className="chn-raw-select"
          data-testid="channel-inspect-record"
          onClick={() => inspectRow(row)}
          aria-label={`inspect raw record at ${row.ts || "an unavailable time"}`}
        >
          <span className="chn-raw-meta">
            <span>raw record</span>
            <time dateTime={row.ts}>{hhmm(row.ts)}</time>
          </span>
          <span className="chn-raw-preview" data-testid="channel-voice-body">
            {row.message}
          </span>
          <span className="chn-inspect-label">inspect record</span>
        </button>
      </article>
    );
  };

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
            {r.kind === "human" ? "human" : voice.label}
          </span>
          <span className="text-xs text-zinc-500" data-testid="channel-label-provenance">
            recorded label · not authenticated
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
          <button
            type="button"
            className="chn-inspect"
            data-testid="channel-inspect-record"
            onClick={() => inspectRow(r)}
            aria-label={`inspect ${r.kind} record at ${r.ts}`}
          >
            inspect
          </button>
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
        <button
          type="button"
          className="chn-inspect"
          data-testid="channel-inspect-record"
          onClick={() => inspectRow(r)}
          aria-label={`inspect event record at ${r.ts}`}
        >
          inspect
        </button>
      </div>
    );
  };

  const renderRow = (item: Extract<FeedItem, { type: "single" }>) =>
    item.row.recordedLabel !== true
      ? renderRawRecord(item)
      : item.row.kind === "event"
        ? renderEvent(item)
        : renderTurn(item);

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
    <div
      className="chn flex h-[calc(100dvh-3.5rem)] flex-col"
      data-testid="channel-page"
    >
      <header className="chn-page-head">
        <div>
          <p className="chn-eyebrow">Operations</p>
          <h1>Channel</h1>
          <p className="chn-intro">
            Inspect recorded exchanges and their provenance, then choose a
            deliberate conversation or handoff. Scientific rulings stay in
            Dossier.
          </p>
        </div>
        <button
          type="button"
          className="chn-context-trigger"
          data-testid="channel-open-context"
          onClick={() => openContext(selectedRow === null ? "guide" : "record")}
        >
          Context &amp; handoff
        </button>
      </header>

      <div className="chn-canvas">
        <main
          className="chn-main"
          inert={narrow && contextOpen ? true : undefined}
        >
          <section
            className="chn-integrity"
            data-tone={integrityCopy.tone}
            data-testid="channel-integrity"
          >
            <div className="chn-integrity-copy">
              <span className="chn-integrity-label">{integrityCopy.label}</span>
              <span>{integrityCopy.detail}</span>
            </div>
            <dl className="chn-freshness">
              <div>
                <dt>loaded through</dt>
                <dd>{shortUtc(loadedThrough)}</dd>
              </div>
              <div>
                <dt>last checked</dt>
                <dd>{shortUtc(checkedAt)}</dd>
              </div>
            </dl>
          </section>

          <fieldset
            className="chn-filter-group"
            data-testid="channel-filters"
            aria-describedby={!semanticFiltersAvailable ? "channel-filter-note" : undefined}
          >
            <legend>Show recorded timeline rows</legend>
            {FILTERS.map(([value, label]) => {
              const semantic = value !== "all";
              const disabled = semantic && !semanticFiltersAvailable;
              return (
                <button
                  key={value}
                  type="button"
                  className="chn-chip"
                  data-testid={`channel-filter-${value}`}
                  aria-pressed={activeFilter === value}
                  disabled={disabled}
                  onClick={() => setFilter(value)}
                >
                  {value === "all"
                    ? "all records"
                    : value === "events"
                      ? "apparatus events"
                      : label}
                </button>
              );
            })}
            {!semanticFiltersAvailable && (
              <span id="channel-filter-note" data-testid="channel-filter-unavailable">
                semantic filters unavailable for this integrity state
              </span>
            )}
          </fieldset>

          {error !== null && rows.length === 0 && (
            <div className="chn-error" data-testid="channel-error">
              <strong>Channel history could not be read.</strong>
              <pre>{error}</pre>
            </div>
          )}
          {error !== null && rows.length > 0 && (
            <div className="chn-refresh-warning" data-testid="channel-refresh-warning">
              <div>
                <strong>Refresh failed at {shortUtc(checkedAt)}.</strong>{" "}
                History last loaded successfully at {shortUtc(lastSuccessAt)}
                remains visible.
              </div>
              <details>
                <summary>Exact refresh error</summary>
                <pre>{error}</pre>
              </details>
            </div>
          )}

          {skew && <EndpointMissingNote endpoint={TIMELINE_ENDPOINT} />}

          <div className="chn-feed-wrap relative flex min-h-0 flex-1 flex-col">
            <div
              ref={feedRef}
              onScroll={onFeedScroll}
              className="chn-feed min-h-0 flex-1 overflow-y-auto"
              data-testid="channel-feed"
            >
              {mayHaveOlder && (
                <button
                  type="button"
                  disabled={loadingOlder}
                  onClick={() => void loadOlder()}
                  data-testid="channel-load-older"
                  className="chn-load-older"
                >
                  {loadingOlder ? "loading older…" : "load older records"}
                </button>
              )}
              {!loaded && (
                <div className="chn-empty" data-testid="channel-loading">
                  Reading the newest recorded window…
                </div>
              )}
              {loaded && rows.length === 0 && error === null && !skew && (
                <div
                  className="chn-empty"
                  data-testid="channel-empty"
                  data-state={integrityMode}
                >
                  {readState === "framed" ? (
                    <>
                      <strong>No recorded channel activity in this framed read.</strong>
                      <span>This read does not establish full-ledger completeness.</span>
                    </>
                  ) : readState === "malformed" ? (
                    <>
                      <strong>The timeline response was malformed.</strong>
                      <span>
                        {invalidRowCount > 0
                          ? `${invalidRowCount} invalid row${invalidRowCount === 1 ? " was" : "s were"} excluded. `
                          : ""}
                        No empty-history or actor/type claim is shown.
                      </span>
                    </>
                  ) : (
                    <>
                      <strong>No framed channel records were returned.</strong>
                      <span>Empty history and unavailable history are not conflated.</span>
                    </>
                  )}
                </div>
              )}
              {rows.length > 0 && feedItems.length === 0 && (
                <div className="chn-empty" data-testid="channel-filter-empty">
                  No {filter} rows in the loaded window. Other records remain
                  loaded and are hidden by this filter.
                </div>
              )}
              {feedItems.map(renderItem)}
              {pending !== null && activeFilter !== "events" && (
                <div
                  data-testid="channel-pending-turn"
                  className="chn-pending"
                  style={{ "--voice-accent": voiceOf(pending.role).accent } as CSSProperties}
                >
                  <StatusDot status="info" pulse label={`${pending.role} is composing`} />
                  <span>
                    {pending.role} is composing. A live turn can take minutes;
                    this seam has no stop action and the reply still lands in
                    the transcript.
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

          <div className="chn-composer" data-testid="channel-composer">
            <fieldset className="chn-role-group">
              <legend>Perspective · same model</legend>
              {roleChip("nara", "nara · operations")}
              {roleChip("pi", "pi · research")}
            </fieldset>
            <div className="chn-compose-row">
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                aria-label="channel turn input"
                placeholder={
                  actionCapabilities.turn
                    ? `Ask the ${role === "nara" ? "operations" : "research"} perspective`
                    : "Turn capability unavailable — not sent"
                }
                rows={1}
              />
              <button
                type="button"
                disabled={sendDisabled}
                onClick={() => void onSend()}
                data-testid="channel-send"
                className="chn-primary-action"
              >
                send to {role}
              </button>
            </div>
            <div className="chn-composer-meta">
              <span data-testid="channel-honesty-note">
                Nara and PI are perspectives of the SAME local model (Gemma),
                so never treat one as independent confirmation of the other.
                The independent skeptic is in the dossier reader.
              </span>
              <button
                type="button"
                className="chn-text-action"
                data-testid="channel-open-delegate"
                onClick={() => openContext("delegate")}
              >
                review a delegation
              </button>
            </div>
            {capabilitiesKnown && !actionCapabilities.turn && (
              <div className="chn-capability-note" data-testid="channel-capability-off">
                Turn capability unavailable. No model call happens here; your
                message is not sent. Delegation availability is checked separately.
              </div>
            )}
            {sending && (
              <span data-testid="channel-sending" className="chn-working">
                asking {role}… a live turn can take minutes
              </span>
            )}
            {sendError !== null && (
              <pre className="chn-inline-error" data-testid="channel-send-error">
                {sendError}
              </pre>
            )}
          </div>
        </main>

        <button
          type="button"
          className="chn-context-backdrop"
          data-open={contextOpen}
          aria-label="close context sheet"
          onClick={closeContext}
        />

        <aside
          ref={contextRef}
          className="chn-context"
          data-open={contextOpen}
          data-testid="channel-context"
          role={narrow && contextOpen ? "dialog" : "complementary"}
          aria-modal={narrow && contextOpen ? true : undefined}
          aria-label="Channel context and handoff"
          tabIndex={narrow && contextOpen ? -1 : undefined}
        >
          <header className="chn-context-head">
            <div>
              <span className="chn-eyebrow">Context</span>
              <h2>
                {contextView === "record"
                  ? "Recorded source"
                  : contextView === "delegate"
                    ? "Review delegation"
                    : "Choose the next place"}
              </h2>
            </div>
            <button
              type="button"
              className="chn-context-close"
              data-testid="channel-close-context"
              onClick={closeContext}
            >
              Close
            </button>
          </header>

          {contextView === "record" && selectedRow !== null && (
            <section className="chn-context-section" data-testid="channel-selected-record">
              <div className="chn-source-state">
                {selectedRow.recordedLabel
                  ? "Recorded kind and actor label · identity not authenticated"
                  : "Raw record · actor and type unavailable"}
              </div>
              <dl className="chn-record-meta">
                <div>
                  <dt>timestamp field</dt>
                  <dd>{selectedRow.ts || "unavailable"}</dd>
                </div>
                <div>
                  <dt>{selectedRow.recordedLabel ? "recorded kind" : "reported kind field · unverified"}</dt>
                  <dd>{selectedRow.kind || "unavailable"}</dd>
                </div>
                <div>
                  <dt>source</dt>
                  <dd>channel timeline record</dd>
                </div>
              </dl>
              <h3>Exact recorded text</h3>
              <pre className="chn-record-raw" data-testid="channel-selected-raw">
                {selectedRow.message}
              </pre>
              {selectedRow.recordedLabel && (
                <RefChipRow refs={refsIn(selectedRow.message)} onOpen={openPeek} />
              )}
              <button type="button" className="chn-secondary-action" onClick={() => setContextView("guide")}>
                Choose a handoff
              </button>
            </section>
          )}

          {contextView === "record" && selectedRow === null && (
            <section className="chn-context-section">
              <p>The selected record is no longer in the loaded window.</p>
              <button type="button" className="chn-secondary-action" onClick={() => setContextView("guide")}>
                Choose a handoff
              </button>
            </section>
          )}

          {contextView === "guide" && (
            <div className="chn-context-section" data-testid="channel-handoff">
              <p>
                Select a timeline row to inspect its exact source fields, or
                continue to the workspace that owns the next decision.
              </p>
              <section className="chn-destination">
                <span className="chn-destination-kicker">Human scientific ruling</span>
                <h3>Dossier</h3>
                <p>Inspect evidence and use the existing governed decision boundary.</p>
                <a href="/dossier" data-testid="channel-dossier-link">Open Dossier →</a>
              </section>
              <section className="chn-destination">
                <span className="chn-destination-kicker">Engineering history</span>
                <h3>Development</h3>
                <p>Review delivery evidence and impediments without creating a reply.</p>
                <a href="/development" data-testid="channel-development-link">Open Development →</a>
              </section>
              <button
                type="button"
                className="chn-primary-action chn-full-action"
                data-testid="channel-context-delegate"
                onClick={() => setContextView("delegate")}
              >
                Review a delegation
              </button>
            </div>
          )}

          {contextView === "delegate" && (
            <section className="chn-context-section" data-testid="channel-delegate">
              <p>
                Research adds an agenda event; improvement enqueues an
                authorize_fix packet. Opening and reviewing do not write.
              </p>
              {!actionCapabilities.delegate && capabilitiesKnown && (
                <div className="chn-capability-note" data-testid="channel-delegate-capability-off">
                  Delegation capability unavailable. No ledger or queue write can
                  be confirmed. Turn availability is checked separately.
                </div>
              )}
              <fieldset className="chn-delegate-kind">
                <legend>Delegation kind</legend>
                {(["research", "improvement"] as const).map((kind) => (
                  <button
                    key={kind}
                    type="button"
                    data-testid={`channel-delegate-kind-${kind}`}
                    aria-pressed={dKind === kind}
                    onClick={() => {
                      setDKind(kind);
                      setConfirming(false);
                    }}
                    className="chn-chip"
                  >
                    {kind}
                  </button>
                ))}
              </fieldset>
              <label className="chn-field">
                <span>{dKind === "research" ? "Research question or agenda topic" : "Improvement task statement"}</span>
                <textarea
                  value={dText}
                  onChange={(event) => {
                    setDText(event.target.value);
                    setConfirming(false);
                  }}
                  aria-label="delegation text"
                  data-testid="channel-delegate-text"
                  rows={3}
                />
              </label>
              {dKind === "research" && (
                <label className="chn-field">
                  <span>Target cluster ID · optional</span>
                  <input
                    value={dClusterId}
                    onChange={(event) => {
                      setDClusterId(event.target.value);
                      setConfirming(false);
                    }}
                    aria-label="target cluster id (optional)"
                    data-testid="channel-delegate-cluster"
                    placeholder="defaults to cl-human-delegations"
                  />
                </label>
              )}
              {dKind === "improvement" && (
                <label className="chn-field">
                  <span>Objective · optional</span>
                  <input
                    value={dObjective}
                    onChange={(event) => {
                      setDObjective(event.target.value);
                      setConfirming(false);
                    }}
                    aria-label="objective (optional)"
                    data-testid="channel-delegate-objective"
                    placeholder="defaults to the task statement"
                  />
                </label>
              )}

              {!confirming && (
                <button
                  type="button"
                  disabled={reviewDisabled}
                  onClick={() => setConfirming(true)}
                  data-testid="channel-delegate-review"
                  className="chn-primary-action"
                >
                  review delegation…
                </button>
              )}

              {confirming && (
                <div className="chn-confirm-card" data-testid="delegate-confirm-card">
                  <span className="chn-destination-kicker">confirm delegation · {dKind}</span>
                  <pre>{dText.trim()}</pre>
                  <strong>Confirming writes exactly:</strong>
                  <ul>
                    {delegateTargets(dKind, dClusterId).map((target) => (
                      <li key={target}>{target}</li>
                    ))}
                  </ul>
                  <div className="chn-confirm-actions">
                    <button
                      type="button"
                      disabled={delegating || !actionCapabilities.delegate}
                      onClick={() => void onConfirmDelegate()}
                      data-testid="delegate-confirm"
                      className="chn-primary-action"
                    >
                      confirm — write it
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirming(false)}
                      data-testid="delegate-cancel"
                      className="chn-secondary-action"
                    >
                      cancel
                    </button>
                    {delegating && <span className="chn-working">writing…</span>}
                  </div>
                </div>
              )}

              {delegateDone !== null && (
                <div data-testid="channel-delegate-result" className="chn-success">
                  {delegateDone}
                </div>
              )}
              {delegateError !== null && (
                <pre data-testid="channel-delegate-error" className="chn-inline-error">
                  {delegateError}
                </pre>
              )}
              <button type="button" className="chn-text-action" onClick={() => setContextView("guide")}>
                Back to handoff choices
              </button>
            </section>
          )}
        </aside>
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
