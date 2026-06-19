// PAGE /coordinator — the missing cycle narrative. The autonomous coordinator
// loop ran "dark" (an unlabeled ad_hoc blip on the activity panel); this page
// is where a human auditor reads the whole arc of each cycle. One
// <CoordinatorCycleCard> per row of run_state/coordinator_cycles.jsonl,
// newest-first: the auto-chosen topic (+ its source) → the plan as per-action
// status chips (executed/skipped/errored+error) → the linked iteration →
// promoted findings → bubbles. See ui_plan.md §AUTONOMY OBSERVABILITY.
//
// Poll discipline mirrors ResolvedIterationsList: an `initial` prop bypasses
// polling (tests render synchronously from the fixture); otherwise it polls
// getCoordinatorCycles() at ~0.2 Hz, cleans up on unmount, and surfaces an
// error string rather than throwing. The data file is gitignored and may be
// absent → backend returns {cycles:[]} → a clean empty state, never a blank gap.
import { useEffect, useState } from "react";
import CoordinatorCycleCard from "../components/CoordinatorCycleCard";
import { getCoordinatorCycles } from "../api/http";
import { useNow } from "../time";
import type { CoordinatorCycle } from "../types/schemas";

// The two render-boundary filter axes. Defaults are range="all" +
// direction="newest" so the unfiltered view (every renderable row, newest
// first) matches the polled-sort contract and the existing hardening tests.
type Range = "all" | "today" | "week";
type Direction = "newest" | "oldest";

// True when `cycle`'s timestamp falls inside the selected window. "all" keeps
// everything (incl. NaN/unparseable timestamps); "today"/"week" key off the
// parsed ISO date and EXCLUDE a row whose timestamp won't parse — a coordinate
// with no legible date can't claim to be "today". `nowMs` is the live clock
// (useNow), never a module-top Date.now(), so the bucket boundary tracks the
// current render instead of import time.
function inRange(cycle: CoordinatorCycle, range: Range, nowMs: number): boolean {
  if (range === "all") return true;
  const t = Date.parse(timestampKey(cycle));
  if (Number.isNaN(t)) return false;
  if (range === "week") return nowMs - t <= 7 * 24 * 60 * 60 * 1000;
  // "today" = same calendar day in local time (matches the human's wall clock).
  const a = new Date(t);
  const b = new Date(nowMs);
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

interface Props {
  initial?: CoordinatorCycle[];
  pollMs?: number;
}

// run_state/coordinator_cycles.jsonl is producer-owned and append-only — a
// partial/legacy row could omit `plan`/`outcomes` (or write them as null).
// CoordinatorCycleCard reads `cycle.outcomes.length` / `cycle.plan.map(...)`
// unguarded, so one such row throws during render and — there is no error
// boundary — takes the WHOLE page down (a blank surface: the dark-loop failure
// this view exists to fix). Drop a structurally-unrenderable row rather than
// crash the list; a card needs both arrays present.
function isRenderableCycle(cycle: CoordinatorCycle | null | undefined): boolean {
  return (
    !!cycle &&
    Array.isArray((cycle as { plan?: unknown }).plan) &&
    Array.isArray((cycle as { outcomes?: unknown }).outcomes)
  );
}

// `timestamp` is producer-owned and TYPED `string`, but the on-disk JSONL is
// untyped: a legacy/serialization slip can write it as a NUMBER (a Unix epoch),
// null, or even an object. The newest-first sort compares timestamps with
// String.prototype.localeCompare, and calling it on a non-string RECEIVER throws
// "(...).localeCompare is not a function" — that rejects the load promise into
// the catch and blanks EVERY card (incl. the healthy rows) behind an error
// banner, so ONE bad-typed timestamp takes the whole narrative down (the
// dark-loop failure this view exists to fix). Coerce to a string so a malformed
// timestamp sorts by its stringified form instead of crashing the comparator (a
// numeric epoch still orders sanely; null/undefined → "").
//
// The comparator runs over the RAW rows BEFORE `isRenderableCycle` filters them
// (sort precedes the render-time filter), so the `cycle` arg itself can be a
// null/undefined element — a producer appending a blank/JSON-null line. Reading
// `cycle.timestamp` off that throws "Cannot read properties of null (reading
// 'timestamp')", crashing the comparator into the same catch-and-blank failure.
// Optional-chain `cycle?.timestamp` so a null/non-object row sorts as "" instead
// of taking the whole narrative down; it is dropped later by isRenderableCycle.
function timestampKey(cycle: CoordinatorCycle | null | undefined): string {
  return typeof cycle?.timestamp === "string"
    ? cycle.timestamp
    : String(cycle?.timestamp ?? "");
}

export default function Coordinator({ initial, pollMs = 5000 }: Props) {
  const [cycles, setCycles] = useState<CoordinatorCycle[]>(initial ?? []);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(initial !== undefined);
  // Defaults keep the unfiltered, newest-first view (the polled-sort contract).
  const [range, setRange] = useState<Range>("all");
  const [direction, setDirection] = useState<Direction>("newest");
  // Live clock for the date buckets; only consulted when range !== "all", so the
  // default view never depends on the tick.
  const now = useNow(60_000);

  // Filter at the render boundary so BOTH the `initial` (test) path and the
  // polled path get the same guard: a malformed row never reaches a card. Then
  // apply the time-range bucket and the sort direction — both composed HERE
  // rather than in the poll effect, so flipping a control re-derives the view
  // without re-fetching and the polled sort stays the single source of order.
  const renderable = cycles
    .filter(isRenderableCycle)
    .filter((c) => inRange(c, range, now))
    .sort((a, b) => {
      const cmp = timestampKey(b).localeCompare(timestampKey(a));
      return direction === "newest" ? cmp : -cmp;
    });

  const rangeCaption =
    range === "today" ? "today" : range === "week" ? "this week" : "all";
  const dirCaption = direction === "newest" ? "newest first" : "oldest first";

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getCoordinatorCycles()
        .then((r) => {
          if (!active) return;
          // Backend returns newest-first per the contract; sort defensively by
          // timestamp descending so a producer appending out-of-order can't
          // scramble the narrative order. `timestampKey` coerces a non-string
          // timestamp so the comparator never throws on a malformed value.
          // Guard the body too: the response is contractually {cycles:[...]},
          // but a malformed 200 could hand back `null`/`undefined` (a bare-null
          // body — getJSON returns it verbatim) or a non-array `cycles`. Reading
          // `r.cycles` off a null/undefined `r` throws "Cannot read properties
          // of null (reading 'cycles')", which rejects into .catch and paints a
          // raw TypeError in the red banner instead of the clean empty state
          // (the blank-gap-on-absent-data failure this view exists to fix).
          // `r?.cycles` short-circuits to undefined → not an array → [].
          const rows = Array.isArray(r?.cycles) ? r.cycles : [];
          const sorted = [...rows].sort((a, b) =>
            timestampKey(b).localeCompare(timestampKey(a)),
          );
          setCycles(sorted);
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
    <div className="mx-auto max-w-7xl p-5" data-testid="coordinator-page">
      <div className="flex items-baseline gap-3">
        <h1 className="text-base font-semibold text-zinc-100">Coordinator</h1>
        <span className="text-[10px] text-zinc-600">
          /api/coordinator/cycles · {rangeCaption} · {dirCaption}
        </span>
        <div className="ml-auto flex items-baseline gap-2">
          <select
            aria-label="time range"
            value={range}
            onChange={(e) => setRange(e.target.value as Range)}
            className="rounded border border-zinc-800 bg-zinc-950/60 px-1.5 py-0.5 text-[11px] text-zinc-300 focus:border-zinc-600 focus:outline-none"
          >
            <option value="all">all time</option>
            <option value="today">today</option>
            <option value="week">this week</option>
          </select>
          <button
            type="button"
            aria-label="sort direction"
            title="toggle newest/oldest first"
            onClick={() =>
              setDirection((d) => (d === "newest" ? "oldest" : "newest"))
            }
            className="rounded border border-zinc-800 bg-zinc-950/60 px-1.5 py-0.5 text-[11px] text-zinc-400 hover:text-zinc-200 focus:border-zinc-600 focus:outline-none"
          >
            {direction === "newest" ? "newest first" : "oldest first"}
          </button>
          <span className="text-[11px] text-zinc-500">{renderable.length}</span>
        </div>
      </div>
      <p className="mt-1 text-xs text-zinc-500">
        One cycle = one narrative: the auto-chosen topic, the plan and each
        action's outcome (a failed dispatch is an explicit red row), the linked
        iteration, promoted findings, and bubbles raised.
      </p>

      {error && <div className="mt-3 text-sm text-red-400">{error}</div>}

      {loaded && renderable.length === 0 && !error && (
        <div
          className="mt-4 rounded border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-500"
          data-testid="coordinator-empty"
        >
          No coordinator cycles yet. The loop has not run — or its cycle log is
          not present.
        </div>
      )}

      {renderable.length > 0 && (
        <div className="mt-4 space-y-4">
          {renderable.map((cycle, i) => (
            // Key must be unique. `run_id` is producer-owned in an append-only
            // JSONL, so it is NOT guaranteed unique across rows — a retry/re-emit
            // or a legacy collision can write the SAME run_id twice, and at scale
            // (1000+ rows) that grows likely. `run_id ?? cycle-${i}` only covers
            // a MISSING id; two rows sharing the same non-null run_id still
            // collide → React logs "Encountered two children with the same key"
            // (a console.error). Suffix the index so the key is unique regardless
            // (a missing/non-string id degrades to a bare index). Identity across
            // index shifts isn't a concern here: the list is re-sorted and
            // replaced wholesale each poll, never mutated in place.
            <CoordinatorCycleCard
              key={`${cycle.run_id ?? "cycle"}-${i}`}
              cycle={cycle}
            />
          ))}
        </div>
      )}
    </div>
  );
}
