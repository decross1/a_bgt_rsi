// pollhub — the ONE page-level polling scheduler (Pulse perf work 2026-08-18).
//
// Before this existed the Pulse page ran TEN independent setInterval timers
// (measured: 49 requests/min at steady state), every poll setState'd a fresh
// object identity whether or not the payload changed, and a slow endpoint
// (/api/lab_todo was measured at >120s under load) kept being re-requested on
// its timer with the previous request still in flight — the requests stacked
// up and strangled the backend threadpool, which made EVERY endpoint slow,
// which made panels flip between content and error: the "page keeps
// refreshing" feeling.
//
// The hub replaces all of that with one scheduler:
//
//   - ONE heartbeat timer (1s) drives every source; each source declares its
//     own intervalMs (fast for cheap health reads, slow for heavy or
//     static-ish payloads) and an optional initialDelayMs so first paint is
//     not a thundering herd.
//   - IN-FLIGHT GUARD: a source whose previous fetch has not settled is never
//     re-fetched. A slow endpoint simply delays its own next poll; it can no
//     longer stack concurrent requests.
//   - CHANGE DETECTION: a fetch that returns a payload deep-equal (by JSON)
//     to the previous one notifies NOBODY — zero re-renders on a no-change
//     poll tick.
//   - STALE-WHILE-REVALIDATE: on failure the last good payload is KEPT and
//     `failing` flips true (one notify on the transition, not per failure).
//     Consumers keep rendering real data and annotate its age honestly via
//     `asOf` — content is never blanked by a transient refetch failure.
//   - FETCH DEADLINE: every fire races a per-source deadline (see
//     DEFAULT_DEADLINE_MS below) — a hung request fails the source honestly
//     at the deadline and the next tick retries; it can never wedge the
//     in-flight guard shut or read as fresh.
//   - AGE TICK: unchanged-payload settles advance `asOf` silently for data
//     subscribers but notify the age-only subscribers (subscribePollAge /
//     usePollAsOf), so rendered "as of Ns" ages stay honest for free.
//
// Subscribers sharing a key share one fetch loop (the page-level dedupe).
// The hub is deliberately NOT a cache across mounts: when the last
// subscriber of a source unmounts the source keeps its entry, but a
// re-subscribe always triggers an immediate refetch (in-flight-guarded), so
// remounted pages light up with fresh data while StrictMode's double-mount
// costs nothing extra. The exception is `evictOnZero` sources (one key per
// filter string): those are DELETED at zero subscribers so an always-on
// dashboard cannot leak an Entry per query ever typed.
import { useEffect, useRef, useState } from "react";

export interface PollSnapshot<T> {
  /** Last successfully fetched payload; kept across later failures (SWR).
   *  `undefined` = never succeeded; `null` is a real payload (e.g. a 204). */
  data: T | undefined;
  /** The current failure, or null when the latest fetch succeeded. */
  error: unknown;
  /** True while the most recent settled fetch failed. */
  failing: boolean;
  /** Epoch ms when `data` was fetched — the honest age of what is shown. */
  asOf: number | null;
}

interface PollOptions {
  intervalMs: number;
  /** Delay before the FIRST fetch (stagger; default 0 = immediate). */
  initialDelayMs?: number;
  /** Per-fetch deadline (default DEFAULT_DEADLINE_MS). At the deadline the
   *  source fails honestly — snapshot kept, failing=true — and retries. */
  deadlineMs?: number;
  /** Delete the entry when its last subscriber leaves. For PARAMETERIZED
   *  keys (one key per filter string): without this an always-on dashboard
   *  leaks one Entry per query ever typed. Default false — unparameterized
   *  sources keep the warm-remount snapshot. */
  evictOnZero?: boolean;
}

interface Entry {
  key: string;
  fetcher: () => Promise<unknown>;
  intervalMs: number;
  deadlineMs: number;
  evictOnZero: boolean;
  /** Epoch ms when the next fetch is due. */
  nextDueAt: number;
  inFlight: boolean;
  lastJson: string | null;
  snapshot: PollSnapshot<unknown>;
  subs: Set<() => void>;
  /** One-shot timer for a staggered FIRST fetch (precise, not heartbeat-
   *  granular — the heartbeat only paces steady-state repolls). */
  initialTimer: ReturnType<typeof setTimeout> | null;
}

const HEARTBEAT_MS = 1000;

// FETCH DEADLINE (adversarial review 2026-08-18): a hung request must never
// wedge its source — the in-flight guard would otherwise hold forever (the
// old pinned behavior: one fetch, then silence) and the page would read a
// frozen snapshot as fresh. Every fire() races the fetcher against this
// deadline; when it fires the source fails HONESTLY: snapshot kept (SWR),
// asOf frozen at the last real success (so the stale note tells the truth),
// failing=true (one notify on the transition), inFlight cleared so the next
// due tick RETRIES. A settlement arriving after its own deadline is IGNORED
// — a retry may already own the source, and adopting out-of-order data
// would lie about asOf. The page fetchers additionally carry real
// AbortController timeouts (api/modelIO.ts fetchWithDeadline, 15 s) that
// tear the network request down; this race is the hub-level backstop for
// any fetcher without one, so it sits slightly above.
const DEFAULT_DEADLINE_MS = 20_000;

const entries = new Map<string, Entry>();
let heartbeat: ReturnType<typeof setInterval> | null = null;

// PAUSE-ON-HIDDEN (ModelIO perf pass 2026-08-18): a background tab polls
// NOTHING — the heartbeat keeps beating but fires no fetch while the
// document is hidden. On return to visibility every overdue source fires
// immediately (their nextDueAt kept aging), so the page refreshes the
// moment it is looked at instead of waiting out a period. SWR semantics
// make this honest: the rendered data stays, and `asOf` carries its age.
function pageHidden(): boolean {
  return (
    typeof document !== "undefined" && document.visibilityState === "hidden"
  );
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (!pageHidden()) tick();
  });
}

const EMPTY_SNAPSHOT: PollSnapshot<unknown> = {
  data: undefined,
  error: null,
  failing: false,
  asOf: null,
};

function notify(entry: Entry): void {
  for (const cb of [...entry.subs]) cb();
}

// AGE-ONLY SUBSCRIBERS (review minor (a), 2026-08-18): the unchanged-payload
// path advances snapshot.asOf silently BY DESIGN (no data notify → zero
// re-renders on a no-change tick), but components that render the age
// ("as of 12s") still need to hear it or their staleness display lies.
// Every successful settle therefore also notifies the key's AGE-ONLY
// subscribers — a lightweight tick carrying no payload identity change.
// OweStrip/LabTodo/NowBoard can ride usePollAsOf without re-rendering
// their data trees. Kept in a separate map so an age sub neither creates
// nor retains an Entry.
const ageSubs = new Map<string, Set<() => void>>();

function notifyAge(key: string): void {
  const subs = ageSubs.get(key);
  if (subs == null) return;
  for (const cb of [...subs]) cb();
}

/** Subscribe to asOf advances only (fires on EVERY successful fetch,
 *  including unchanged-payload ticks that notify no data subscriber). */
export function subscribePollAge(key: string, cb: () => void): () => void {
  let subs = ageSubs.get(key);
  if (subs == null) {
    subs = new Set();
    ageSubs.set(key, subs);
  }
  subs.add(cb);
  return () => {
    subs.delete(cb);
    if (subs.size === 0) ageSubs.delete(key);
  };
}

function fire(entry: Entry): void {
  if (entry.inFlight) return;
  entry.inFlight = true;
  // The deadline race — see DEFAULT_DEADLINE_MS. `settled` makes deadline
  // vs settlement first-wins: whichever loses becomes a no-op.
  let settled = false;
  const deadline = setTimeout(() => {
    if (settled) return;
    settled = true;
    entry.inFlight = false; // the next due tick retries
    entry.nextDueAt = Date.now() + entry.intervalMs;
    const wasFailing = entry.snapshot.failing;
    // SWR: data and asOf survive — asOf stays frozen at the last real
    // success, so the rendered age is honest about the hang.
    entry.snapshot = {
      ...entry.snapshot,
      error: new Error(
        `poll deadline ${entry.deadlineMs}ms exceeded (${entry.key})`,
      ),
      failing: true,
    };
    if (!wasFailing) notify(entry);
  }, entry.deadlineMs);
  entry.fetcher().then(
    (result) => {
      if (settled) return; // past-deadline arrival: ignored (see above)
      settled = true;
      clearTimeout(deadline);
      entry.inFlight = false;
      entry.nextDueAt = Date.now() + entry.intervalMs;
      // JSON.stringify as deep-equality: every payload here is response JSON
      // (no functions/undefined members), so equal strings = equal payloads.
      let json: string | null = null;
      try {
        json = JSON.stringify(result) ?? "undefined";
      } catch {
        json = null; // unserializable payload: treat every fetch as changed
      }
      const changed = json === null || json !== entry.lastJson;
      const wasFailing = entry.snapshot.failing;
      entry.lastJson = json;
      if (changed || wasFailing) {
        entry.snapshot = {
          data: result,
          error: null,
          failing: false,
          asOf: Date.now(),
        };
        notify(entry);
      } else {
        // Unchanged payload: refresh the age silently (same data identity,
        // no data notify, no re-render)…
        entry.snapshot.asOf = Date.now();
      }
      // …but age-only subscribers hear EVERY successful settle.
      notifyAge(entry.key);
    },
    (err) => {
      if (settled) return; // past-deadline rejection: already reported
      settled = true;
      clearTimeout(deadline);
      entry.inFlight = false;
      entry.nextDueAt = Date.now() + entry.intervalMs;
      const wasFailing = entry.snapshot.failing;
      // SWR: data and asOf survive; only the error state changes.
      entry.snapshot = { ...entry.snapshot, error: err, failing: true };
      if (!wasFailing) notify(entry);
    },
  );
}

function tick(): void {
  if (pageHidden()) return;
  const now = Date.now();
  for (const entry of entries.values()) {
    if (entry.subs.size === 0) continue;
    if (!entry.inFlight && now >= entry.nextDueAt) fire(entry);
  }
}

function ensureHeartbeat(): void {
  if (heartbeat == null) heartbeat = setInterval(tick, HEARTBEAT_MS);
}

function stopHeartbeatIfIdle(): void {
  if (heartbeat == null) return;
  for (const entry of entries.values()) {
    if (entry.subs.size > 0) return;
  }
  clearInterval(heartbeat);
  heartbeat = null;
}

/** Subscribe a callback to a keyed poll source. Returns an unsubscriber. */
export function subscribePoll(
  key: string,
  fetcher: () => Promise<unknown>,
  opts: PollOptions,
  cb: () => void,
): () => void {
  let entry = entries.get(key);
  const now = Date.now();
  if (entry == null) {
    entry = {
      key,
      fetcher,
      intervalMs: opts.intervalMs,
      deadlineMs: opts.deadlineMs ?? DEFAULT_DEADLINE_MS,
      evictOnZero: opts.evictOnZero ?? false,
      nextDueAt: now + (opts.initialDelayMs ?? 0),
      inFlight: false,
      lastJson: null,
      snapshot: EMPTY_SNAPSHOT,
      subs: new Set(),
      initialTimer: null,
    };
    entries.set(key, entry);
  } else {
    // Last subscriber wins fetcher + cadence (in practice one source = one
    // owner; a re-mount just refreshes the binding).
    entry.fetcher = fetcher;
    entry.intervalMs = opts.intervalMs;
    entry.deadlineMs = opts.deadlineMs ?? DEFAULT_DEADLINE_MS;
    entry.evictOnZero = opts.evictOnZero ?? false;
  }
  const firstSub = entry.subs.size === 0;
  entry.subs.add(cb);
  ensureHeartbeat();
  // A (re)activated source fetches now; a deliberately staggered FIRST fetch
  // gets a precise one-shot timer (the 1s heartbeat only paces repolls). An
  // already-in-flight fetch makes both a no-op (StrictMode double-subscribe
  // costs nothing).
  if (firstSub) {
    const e = entry;
    if (e.nextDueAt <= now) {
      // Hidden tab: skip — nextDueAt stays past-due, so the first visible
      // tick fires it (pause-on-hidden).
      if (!pageHidden()) fire(e);
    } else if (e.initialTimer == null) {
      e.initialTimer = setTimeout(() => {
        e.initialTimer = null;
        if (e.subs.size > 0 && !pageHidden()) fire(e);
      }, e.nextDueAt - now);
    }
  }
  return () => {
    entry.subs.delete(cb);
    if (entry.subs.size === 0) {
      if (entry.initialTimer != null) {
        clearTimeout(entry.initialTimer);
        entry.initialTimer = null;
      }
      if (entry.evictOnZero) {
        // EVICTION (review fix 3, 2026-08-18): parameterized sources mint
        // one key per query string — an always-on dashboard would leak an
        // Entry per filter ever typed. Zero subscribers = delete outright;
        // a re-subscribe rebuilds and refetches from scratch (the SWR refs
        // in the consuming page carry the rendered rows across the gap).
        entries.delete(key);
      } else {
        // Next subscriber refetches immediately rather than waiting a
        // period.
        entry.nextDueAt = Date.now();
      }
      stopHeartbeatIfIdle();
    }
  };
}

/** Test seam: how many entries the hub currently holds. */
export function pollHubEntryCount(): number {
  return entries.size;
}

export function getPollSnapshot<T>(key: string): PollSnapshot<T> {
  return (entries.get(key)?.snapshot ?? EMPTY_SNAPSHOT) as PollSnapshot<T>;
}

/** Test seam: drop every source and stop the heartbeat. */
export function resetPollHub(): void {
  for (const entry of entries.values()) {
    if (entry.initialTimer != null) clearTimeout(entry.initialTimer);
  }
  entries.clear();
  ageSubs.clear();
  if (heartbeat != null) {
    clearInterval(heartbeat);
    heartbeat = null;
  }
}

/**
 * React binding. `enabled: false` (fixture-injection mode in tests) never
 * subscribes and returns the empty snapshot. The fetcher is captured on
 * subscription (per key/interval change), deliberately NOT per render —
 * inline arrow fetchers don't churn the subscription.
 */
export function usePolled<T>(
  key: string,
  fetcher: () => Promise<T>,
  opts: PollOptions & { enabled?: boolean },
): PollSnapshot<T> {
  const enabled = opts.enabled !== false;
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const [snap, setSnap] = useState<PollSnapshot<T>>(() =>
    enabled ? getPollSnapshot<T>(key) : (EMPTY_SNAPSHOT as PollSnapshot<T>),
  );
  const { intervalMs, initialDelayMs, deadlineMs, evictOnZero } = opts;
  useEffect(() => {
    if (!enabled) return;
    const unsub = subscribePoll(
      key,
      () => fetcherRef.current(),
      { intervalMs, initialDelayMs, deadlineMs, evictOnZero },
      () => setSnap(getPollSnapshot<T>(key)),
    );
    // The entry may already carry data (another subscriber fetched first).
    setSnap(getPollSnapshot<T>(key));
    return unsub;
  }, [key, enabled, intervalMs, initialDelayMs, deadlineMs, evictOnZero]);
  return snap;
}

/**
 * Age-only React binding: the latest successful-fetch instant for a key,
 * updated on EVERY successful settle — including the unchanged-payload
 * ticks that deliberately notify no data subscriber. Lets an "as of Ns"
 * display stay honest without re-rendering the data tree that renders it.
 */
export function usePollAsOf(key: string): number | null {
  const [asOf, setAsOf] = useState<number | null>(
    () => getPollSnapshot(key).asOf,
  );
  useEffect(() => {
    setAsOf(getPollSnapshot(key).asOf);
    return subscribePollAge(key, () =>
      setAsOf(getPollSnapshot(key).asOf),
    );
  }, [key]);
  return asOf;
}
