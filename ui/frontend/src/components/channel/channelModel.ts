// channelModel — the /channel feed's pure derivations (revamp R4). One module
// so the feed, the filter chips, the day dividers, the event rows and the
// reference chips are five renderings of ONE derivation (the R1 ladderModel
// discipline), and every one of them is testable without a DOM.
//
// Nothing here fabricates: an event's chip keys off the CLI's stable message
// prefixes (lab_channel.py's _*_events builders), an activity chip exists ONLY
// for the DELEGATED[...] mirror row the CLI really writes, and a row whose ts
// does not parse lands under an "undated" divider rather than a guessed day.
import type { ChannelRow } from "../../api/channel";

// ── filters (client-side, over the rows already loaded) ─────────────────
export type ChannelFilter = "all" | "conversation" | "events";

export const FILTERS: ReadonlyArray<readonly [ChannelFilter, string]> = [
  ["all", "all"],
  ["conversation", "conversation"],
  ["events", "events"],
];

export function matchesFilter(row: ChannelRow, filter: ChannelFilter): boolean {
  if (filter === "conversation") return row.kind !== "event";
  if (filter === "events") return row.kind === "event";
  return true;
}

// ── event chips ─────────────────────────────────────────────────────────
// The CLI's derived events carry no source field through the printed line,
// but their messages open with stable prefixes — the chip keys off those.
// Unknown shapes fall back to a quiet generic "event" chip, never dropped.
// Tone rides the R0 SEMANTIC STATUS SET, which is legitimate here: these
// rows ARE run status (a cycle ran, a cluster died, a finding was promoted).
export type EventTone = "ok" | "warn" | "bad" | "info" | "idle";

const EVENT_CHIPS: ReadonlyArray<readonly [string, string, EventTone, string]> = [
  ["cycle:", "cycle", "info", "⟳"],
  ["cluster killed", "kill", "bad", "✕"],
  ["promoted:", "promotion", "ok", "↑"],
  ["loop alert", "alert", "warn", "!"],
  ["cluster created", "ladder", "idle", "•"],
  ["clusters created", "ladder", "idle", "•"],
  ["cluster reopened", "ladder", "idle", "•"],
];

export interface EventChip {
  label: string;
  tone: EventTone;
  glyph: string;
}

export function eventChip(message: string): EventChip {
  for (const [prefix, label, tone, glyph] of EVENT_CHIPS) {
    if (message.startsWith(prefix)) return { label, tone, glyph };
  }
  return { label: "event", tone: "idle", glyph: "·" };
}

// Collapsed-run nouns per chip label ("6 cluster kills — expand").
const COLLAPSE_NOUN: Record<string, string> = {
  cycle: "cycles",
  kill: "cluster kills",
  promotion: "promotions",
  alert: "loop alerts",
  ladder: "ladder events",
  event: "events",
};

export function collapseNoun(label: string): string {
  return Object.prototype.hasOwnProperty.call(COLLAPSE_NOUN, label)
    ? COLLAPSE_NOUN[label]
    : "events";
}

// ── activity chips ──────────────────────────────────────────────────────
// The seam's row shape is exactly {ts, kind, message} — there is NO tool-use
// / cycle-context field to key a general activity chip off, so none is
// invented. The ONE activity a turn really carries is the delegation mirror
// row the CLI writes verbatim as `DELEGATED[<kind>]: <text>` (lab_channel.py
// delegate()); that prefix becomes a chip and leaves the body as prose.
const DELEGATED_RE = /^DELEGATED\[([a-z_]+)\]:\s*/;

export interface Activity {
  label: string;
  /** The message with the activity prefix removed (the chip replaces it). */
  body: string;
}

export function activityOf(message: string): Activity | null {
  const m = DELEGATED_RE.exec(message);
  if (m === null) return null;
  return { label: `delegated · ${m[1]}`, body: message.slice(m[0].length) };
}

// ── reference ids (cl-* / iter-* / sf-*) ────────────────────────────────
export type RefKind = "cluster" | "iteration" | "finding";

export interface ChannelRef {
  id: string;
  kind: RefKind;
}

const REF_RE = /\b(cl|iter|sf)-[A-Za-z0-9][A-Za-z0-9._:-]*/g;
const REF_KIND: Record<string, RefKind> = {
  cl: "cluster",
  iter: "iteration",
  sf: "finding",
};

export type RefSegment =
  | { t: "text"; value: string }
  | { t: "ref"; ref: ChannelRef };

/** Split plain text into text/ref segments so ids render as inline chips.
 *  Trailing sentence punctuation is NOT swallowed into the id. */
export function refSegments(text: string): RefSegment[] {
  const out: RefSegment[] = [];
  let last = 0;
  REF_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = REF_RE.exec(text)) !== null) {
    const id = m[0].replace(/[.:_-]+$/, "");
    const prefix = m[1];
    if (id.length <= prefix.length + 1) {
      REF_RE.lastIndex = m.index + m[0].length;
      continue;
    }
    if (m.index > last) out.push({ t: "text", value: text.slice(last, m.index) });
    out.push({ t: "ref", ref: { id, kind: REF_KIND[prefix] } });
    last = m.index + id.length;
    REF_RE.lastIndex = last; // re-scan the trimmed punctuation as text
  }
  if (last < text.length) out.push({ t: "text", value: text.slice(last) });
  return out;
}

/** The distinct ids a message mentions, in first-mention order. */
export function refsIn(text: string): ChannelRef[] {
  const seen = new Set<string>();
  const out: ChannelRef[] = [];
  for (const seg of refSegments(text)) {
    if (seg.t !== "ref" || seen.has(seg.ref.id)) continue;
    seen.add(seg.ref.id);
    out.push(seg.ref);
  }
  return out;
}

// ── time ────────────────────────────────────────────────────────────────
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** The UTC day an ISO ts belongs to ("2026-08-15"); "" when unparseable. */
export function dayKeyOf(ts: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T/.exec(ts);
  return m ? `${m[1]}-${m[2]}-${m[3]}` : "";
}

/** "Aug 15, 2026 · UTC" — the ts IS UTC (the CLI writes _utcnow_iso), and
 *  the divider says so rather than implying a local day. */
export function dayLabel(key: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(key);
  if (m === null) return "undated";
  const month = MONTHS[Number(m[2]) - 1] ?? m[2];
  return `${month} ${Number(m[3])}, ${m[1]} · UTC`;
}

/** "10:05" — the day lives on the divider, so a row only needs its time. */
export function hhmm(ts: string): string {
  const m = /T(\d{2}:\d{2})/.exec(ts);
  return m ? m[1] : ts;
}

// ── the feed: filter → day dividers → same-chip event runs ──────────────
export const COLLAPSE_MIN = 3;

export type FeedItem =
  | { type: "day"; key: string; label: string }
  | { type: "single"; row: ChannelRow; key: string }
  | {
      type: "wall";
      rows: ChannelRow[];
      label: string;
      tone: EventTone;
      glyph: string;
      key: string;
    };

export function rowKey(r: ChannelRow): string {
  // `since` is INCLUSIVE (ts >= since), so the poll re-receives boundary
  // rows — dedupe on the full identity. The NUL separator stays an ESCAPED
  // backslash-u0000 sequence — a raw NUL byte in this source once made git
  // treat the whole file as binary (the loop3h-ui-hotfix encoding bug).
  return `${r.ts}\u0000${r.kind}\u0000${r.message}`;
}

export function sortRows(rows: ChannelRow[]): ChannelRow[] {
  // Chronological, newest last — the feed's bottom is "now".
  return [...rows].sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0));
}

export function groupFeed(
  rows: ChannelRow[],
  expanded: ReadonlySet<string>,
  filter: ChannelFilter = "all",
): FeedItem[] {
  const kept = rows.filter((r) => matchesFilter(r, filter));
  const items: FeedItem[] = [];
  let day: string | null = null;
  const openDay = (ts: string) => {
    const key = dayKeyOf(ts);
    if (key === day) return;
    day = key;
    items.push({ type: "day", key: `day-${key}`, label: dayLabel(key) });
  };

  let i = 0;
  while (i < kept.length) {
    const r = kept[i];
    if (r.kind !== "event") {
      openDay(r.ts);
      items.push({ type: "single", row: r, key: `${rowKey(r)}-${i}` });
      i++;
      continue;
    }
    const chip = eventChip(r.message);
    const runDay = dayKeyOf(r.ts);
    let j = i + 1;
    // A run never crosses a day divider — the divider would have to sit
    // inside the collapsed line, which is a lie about when things happened.
    while (
      j < kept.length &&
      kept[j].kind === "event" &&
      eventChip(kept[j].message).label === chip.label &&
      dayKeyOf(kept[j].ts) === runDay
    ) {
      j++;
    }
    const run = kept.slice(i, j);
    // Keyed off the run's FIRST row identity (not its index) so an expanded
    // wall stays expanded when "load older" prepends rows.
    const wallKey = rowKey(run[0]);
    openDay(r.ts);
    if (run.length >= COLLAPSE_MIN && !expanded.has(wallKey)) {
      items.push({
        type: "wall",
        rows: run,
        label: chip.label,
        tone: chip.tone,
        glyph: chip.glyph,
        key: wallKey,
      });
    } else {
      run.forEach((rr, k) =>
        items.push({ type: "single", row: rr, key: `${rowKey(rr)}-${i + k}` }),
      );
    }
    i = j;
  }
  return items;
}
