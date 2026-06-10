// LOOP_V0 resolved-iterations list. Polls /api/loop_v0/iterations at ~0.2 Hz
// and renders past iterations newest-first as CONDENSED cards (2026-06-10
// Task 4): line 1 = mono iteration_id + AT MOST four badges — critique
// verdict, novelty class, gate_status, and ONE alarm slot (priority
// low-evidence > redteam fatal/retries > experiment Verdict chip; first
// present wins) — plus the SourceBadge ONLY for the β `nemoclaw_agent`
// provenance, and the right-aligned timestamp. Line 2 = the topic clamped to
// one line (full text in the title attr). Everything else — NoveltyAxesChip,
// conditioning bullets, the process badge, non-nemoclaw source badges, the
// displaced alarm chips, the override provenance as visible text — lives in
// the IterationDetailModal, which a card click opens (the click ALSO keeps
// the existing `onSelect` journal behavior). Focus returns to the opening
// card when the modal closes.
//
// The shared chip primitives (tone maps, Badge, RedteamChip, ExperimentChip,
// the scalar guards) moved VERBATIM to IterationDetailModal.tsx and are
// imported back from there, keeping the dependency one-directional
// (list → modal).
//
// The endpoint returns ALL rows newest-first, which grows without bound. To
// keep the dashboard a high-level, scannable history this component paginates
// (default ~10 rows/page) and offers composable client-side filters: novelty
// class, critique verdict, and a free-text topic search over seed.topic.
//
// Poll discipline: polls refresh the underlying `rows` only. The user's
// filter and page live in their own state and are NEVER reset by a poll, so a
// background refresh cannot yank the current page/filter out from under the
// user. The page index is clamped against the filtered length at render time
// (so if rows shrink under the user the page stays in range), but it is not
// otherwise mutated by the poll.
//
// Selection across filtering: when the currently selected row is filtered or
// paged out it is NOT silently lost — a small banner surfaces it. The banner
// distinguishes the two ways a selection can be hidden and offers the action
// that actually resolves each: if the row survives the filter but sits on
// another page it offers "go to selected" (jumps to that page); if a filter
// excludes it entirely it offers "clear filters". onSelect / the selectedId
// highlight keep working on any visible row.
import { useEffect, useMemo, useRef, useState } from "react";
import { getIterations } from "../api/http";
import type { IterationRecord } from "../types/schemas";
import IterationDetailModal, {
  Badge,
  ExperimentChip,
  GATE_TONE,
  NOVELTY_TONE,
  RedteamChip,
  VERDICT_TONE,
  badgeText,
  overrideTooltip,
  redteamAlarm,
  seedTopic,
  shortTimestamp,
  toneFor,
} from "./IterationDetailModal";
import LowEvidenceBadge, { isLowEvidence } from "./LowEvidenceBadge";
import SourceBadge from "./SourceBadge";

const PAGE_SIZE = 10;

const NOVELTY_CLASSES = ["novel", "rediscovery", "unclear", "nonsense"] as const;
const VERDICT_CLASSES = [
  "survives",
  "restated",
  "falsified",
  "malformed",
  // Real producible verdict since the 2026-06-09 close-out (fails closed,
  // never promotes) — filterable so an auditor can pull the undecided rows.
  "undecidable",
] as const;

// T3.1 (close-out follow-up, Task-0 item 9): the tooltip alone made overrides
// invisible to a scanning eye. When a block carries a USABLE
// verdict_overridden_from, render a quiet inline hint ("overridden from
// survives") next to that block's badge, with the fuller story
// (override_reason / skeptic_verdict) in ITS title tooltip — the badge's own
// pinned two-part tooltip (test_undecidable_verdict exact-string pins) stays
// untouched, which is why `reason:` lives here and not there. The modal
// additionally shows all three as VISIBLE text. Garbled (object/array)
// fields drop via badgeText — no hint, never "[object Object]".
function OverriddenFromHint({
  block,
}: {
  block:
    | {
        verdict_overridden_from?: unknown;
        override_reason?: unknown;
        skeptic_verdict?: unknown;
      }
    | null
    | undefined;
}) {
  const from = badgeText(
    block?.verdict_overridden_from as string | null | undefined,
  );
  if (!from) return null;
  const reason = badgeText(block?.override_reason as string | null | undefined);
  const parts = [overrideTooltip(block) ?? `overridden from ${from}`];
  if (reason) parts.push(`reason: ${reason}`);
  return (
    <span
      data-testid="overridden-from-hint"
      title={parts.join("; ")}
      className="text-[10px] lowercase tracking-wide text-zinc-500"
    >
      overridden from {from}
    </span>
  );
}

// The condensed card's ONE alarm slot (handoff Task 4): priority
// low-evidence > redteam fatal/retries > experiment Verdict chip — the first
// present wins. The displaced chips are not lost; they render in the detail
// modal (sections 3/4/6). A clean redteam proceed/0 pass is NOT an alarm and
// is modal-only.
function AlarmSlot({ row }: { row: IterationRecord }) {
  if (isLowEvidence(row)) return <LowEvidenceBadge record={row} />;
  if (redteamAlarm(row.redteam)) return <RedteamChip redteam={row.redteam} />;
  if (
    row.experiment_outcome != null &&
    typeof row.experiment_outcome === "object" &&
    !Array.isArray(row.experiment_outcome)
  ) {
    return <ExperimentChip outcome={row.experiment_outcome} />;
  }
  return null;
}

// A small dark-mode select styled to match the panel idiom.
function FilterSelect({
  value,
  onChange,
  options,
  allLabel,
  ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  options: readonly string[];
  allLabel: string;
  ariaLabel: string;
}) {
  return (
    <select
      aria-label={ariaLabel}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded border border-zinc-800 bg-zinc-950/60 px-1.5 py-0.5 text-[11px] text-zinc-300 focus:border-zinc-600 focus:outline-none"
    >
      <option value="">{allLabel}</option>
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

interface Props {
  initial?: IterationRecord[];
  onSelect?: (iterationId: string) => void;
  selectedId?: string | null;
  pollMs?: number;
}

export default function ResolvedIterationsList({
  initial,
  onSelect,
  selectedId,
  pollMs = 5000,
}: Props) {
  const [rows, setRows] = useState<IterationRecord[]>(initial ?? []);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(initial !== undefined);

  // Filter + page state. Owned by the user, never touched by a poll.
  const [novelty, setNovelty] = useState("");
  const [verdict, setVerdict] = useState("");
  const [topic, setTopic] = useState("");
  const [page, setPage] = useState(0);

  // Detail-modal state: the clicked ROW SNAPSHOT (not just the id — duplicate
  // iteration_ids exist on the append-only log, and a poll may swap `rows`
  // under the open modal; the snapshot keeps the modal honest about what was
  // clicked). `openerRef` holds the opening card button so focus returns to
  // it when the modal closes (the Task-4 dialog contract).
  const [openRow, setOpenRow] = useState<IterationRecord | null>(null);
  const openerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getIterations()
        .then((r) => {
          if (!active) return;
          // Backend returns newest-first per the contract; if a producer
          // ever appends out-of-order, sort by ended_at descending here
          // to keep the panel stable. `ended_at` is producer-owned: a non-string
          // (number/object on a malformed row) has no `.localeCompare`, so coerce
          // to a comparable string first — one bad row must not throw the whole
          // sort (which would blank the list via the error path).
          // Guard the BODY too: the response is contractually {iterations:[...]},
          // but a malformed 200 could hand back `null`/`undefined` (a bare-null
          // body — getJSON returns it verbatim), a missing `iterations` key, or a
          // non-array `iterations`. A bare `[...r.iterations]` then throws
          // ("Cannot read properties of null" / "r.iterations is not iterable"),
          // which rejects into .catch and paints a raw TypeError in the red banner
          // instead of the clean empty state — the blank-gap-on-bad-data failure
          // the autonomy work exists to fix. `Array.isArray(r?.iterations)`
          // short-circuits every bad shape to [] (mirrors the sibling
          // Coordinator route's `r?.cycles` guard).
          const sortKey = (v: unknown): string =>
            typeof v === "string" ? v : "";
          const rows = Array.isArray(r?.iterations) ? r.iterations : [];
          const sorted = [...rows].sort((a, b) =>
            sortKey(b.ended_at).localeCompare(sortKey(a.ended_at)),
          );
          // Only `rows` is updated on poll. Filter/page state is deliberately
          // left alone so a background refresh does not reset the user's view.
          setRows(sorted);
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

  const topicQuery = topic.trim().toLowerCase();

  const filtered = useMemo(() => {
    return rows.filter((row) => {
      if (novelty && (row.novelty?.class ?? "") !== novelty) return false;
      if (verdict && (row.critique?.verdict ?? "") !== verdict) return false;
      if (topicQuery) {
        const t = seedTopic(row).toLowerCase();
        if (!t.includes(topicQuery)) return false;
      }
      return true;
    });
  }, [rows, novelty, verdict, topicQuery]);

  const total = rows.length;
  const filteredCount = filtered.length;
  const pageCount = Math.max(1, Math.ceil(filteredCount / PAGE_SIZE));
  // Clamp the page against the filtered length at render time so a shrinking
  // result set (or a freshly-applied filter) never strands the user on an
  // out-of-range page. We do not setState here — clamping is pure.
  const safePage = Math.min(page, pageCount - 1);
  const pageStart = safePage * PAGE_SIZE;
  const pageRows = filtered.slice(pageStart, pageStart + PAGE_SIZE);

  const hasFilter = Boolean(novelty || verdict || topicQuery);

  // Where does the selected row sit relative to the current view?
  // - selectedInRows: it exists in the (unfiltered) data set at all.
  // - selectedFilteredIndex: its index in `filtered` (-1 when a filter excludes
  //   it). This distinguishes "excluded by a filter" from "merely on another
  //   page", which the surfacing banner needs in order to offer an action that
  //   actually resolves the state.
  const selectedInRows =
    Boolean(selectedId) && rows.some((r) => r.iteration_id === selectedId);
  const selectedFilteredIndex = selectedId
    ? filtered.findIndex((r) => r.iteration_id === selectedId)
    : -1;
  const selectedOnPage = pageRows.some(
    (r) => r.iteration_id === selectedId,
  );

  // Is the selected row hidden by the current filter or pagination? If so we
  // surface it rather than letting the selection silently vanish.
  const selectedHidden = selectedInRows && !selectedOnPage;
  // The row survives the filter but lives on a different page → we can jump to
  // it. When it's -1 the filter itself excludes it and only clearing helps.
  const selectedHiddenByPageOnly = selectedHidden && selectedFilteredIndex >= 0;

  const applyFilter = (fn: () => void) => {
    fn();
    setPage(0); // any filter change resets to the first page of results
  };

  const clearFilters = () => {
    setNovelty("");
    setVerdict("");
    setTopic("");
    setPage(0);
  };

  // Navigate to the page that contains the selected row within `filtered`.
  // Only meaningful when selectedFilteredIndex >= 0 (the row survives the
  // current filter); otherwise the caller should clear filters instead.
  const jumpToSelected = () => {
    if (selectedFilteredIndex < 0) return;
    setPage(Math.floor(selectedFilteredIndex / PAGE_SIZE));
  };

  const countLabel = hasFilter
    ? `${filteredCount} of ${total}`
    : `${total}`;

  return (
    <div
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="resolved-iterations-list"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Resolved iterations
        </h2>
        <span className="text-[10px] text-zinc-600">
          /api/loop_v0/iterations · newest first
        </span>
        <span
          className="ml-auto text-[11px] text-zinc-500"
          data-testid="resolved-count"
        >
          {countLabel}
        </span>
      </div>

      {/* Filter controls — compose across all three dimensions. */}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <FilterSelect
          ariaLabel="filter by novelty class"
          value={novelty}
          onChange={(v) => applyFilter(() => setNovelty(v))}
          options={NOVELTY_CLASSES}
          allLabel="any novelty"
        />
        <FilterSelect
          ariaLabel="filter by critique verdict"
          value={verdict}
          onChange={(v) => applyFilter(() => setVerdict(v))}
          options={VERDICT_CLASSES}
          allLabel="any verdict"
        />
        <input
          type="text"
          aria-label="search topic"
          placeholder="search topic…"
          value={topic}
          onChange={(e) => applyFilter(() => setTopic(e.target.value))}
          className="min-w-[10rem] flex-1 rounded border border-zinc-800 bg-zinc-950/60 px-1.5 py-0.5 text-[11px] text-zinc-300 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
        />
        {hasFilter && (
          <button
            type="button"
            onClick={clearFilters}
            aria-label="clear filters"
            className="rounded border border-zinc-800 bg-zinc-950/60 px-1.5 py-0.5 text-[11px] text-sky-300 hover:border-zinc-600"
          >
            clear
          </button>
        )}
      </div>

      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}

      {loaded && total === 0 && !error && (
        <div className="mt-2 text-sm text-zinc-500">
          No iterations yet. Submit a topic above to start the first one.
        </div>
      )}

      {total > 0 && filteredCount === 0 && (
        <div
          className="mt-2 text-sm text-zinc-500"
          data-testid="resolved-empty-filter"
        >
          No iterations match the current filter.{" "}
          <button
            type="button"
            onClick={clearFilters}
            className="text-sky-300 underline hover:text-sky-200"
          >
            Clear filters
          </button>
          .
        </div>
      )}

      {selectedHidden && (
        <div
          className="mt-2 rounded border border-sky-900/60 bg-sky-950/30 px-2 py-1 text-[11px] text-sky-300"
          data-testid="resolved-selected-hidden"
        >
          <span className="font-mono text-sky-200">{selectedId}</span> is
          selected but{" "}
          {selectedHiddenByPageOnly
            ? "on another page."
            : "hidden by the current filter."}{" "}
          {selectedHiddenByPageOnly ? (
            <button
              type="button"
              onClick={jumpToSelected}
              className="underline hover:text-sky-200"
            >
              go to selected
            </button>
          ) : (
            <button
              type="button"
              onClick={clearFilters}
              className="underline hover:text-sky-200"
            >
              clear filters
            </button>
          )}
        </div>
      )}

      {pageRows.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {pageRows.map((row, i) => {
            const selected = row.iteration_id === selectedId;
            // `iteration_id` is producer-owned (loop_memory.jsonl, append-only):
            // a crash-and-retry or a re-dispatch can append the SAME id twice, so
            // a bare `key={row.iteration_id}` then collides → React logs
            // "Encountered two children with the same key" (a console.error) and
            // may omit/duplicate a row. Composite the index in so duplicate ids
            // stay distinct, mirroring the sibling panels (SurfacedFindingsPanel /
            // BubblesPanel / HealthSignalsPanel all key `${id ?? fallback}-${i}`).
            return (
              <li key={`${row.iteration_id || "iter"}-${i}`}>
                <button
                  type="button"
                  onClick={(e) => {
                    // The click keeps the existing journal behavior AND
                    // opens the detail modal (Task 4) — opening the modal
                    // selects the iteration.
                    onSelect?.(row.iteration_id);
                    openerRef.current = e.currentTarget;
                    setOpenRow(row);
                  }}
                  className={
                    selected
                      ? "block w-full rounded border border-emerald-700 bg-emerald-950/30 px-2 py-1.5 text-left hover:bg-emerald-950/50"
                      : "block w-full rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5 text-left hover:border-zinc-700"
                  }
                  aria-label={`load journal ${row.iteration_id}`}
                >
                  {/* LINE 1 — id + max 4 badges + β provenance + timestamp.
                      Override provenance stays tooltip-only here; the modal
                      shows it as visible text. */}
                  <div className="flex flex-wrap items-baseline gap-2 text-xs">
                    <span className="font-mono text-zinc-200">
                      {row.iteration_id}
                    </span>
                    <Badge
                      text={row.critique?.verdict}
                      tone={toneFor(
                        VERDICT_TONE,
                        row.critique?.verdict,
                        "bg-zinc-800 text-zinc-400",
                      )}
                      title={overrideTooltip(row.critique)}
                    />
                    <OverriddenFromHint block={row.critique} />
                    <Badge
                      text={row.novelty?.class}
                      tone={toneFor(
                        NOVELTY_TONE,
                        row.novelty?.class,
                        "bg-zinc-800 text-zinc-400",
                      )}
                      title={overrideTooltip(row.novelty)}
                    />
                    <OverriddenFromHint block={row.novelty} />
                    <Badge
                      text={row.gate_status}
                      tone={toneFor(GATE_TONE, row.gate_status, "")}
                    />
                    <AlarmSlot row={row} />
                    {/* β provenance is the ONE origin worth row-level ink:
                        the in-sandbox NemoClaw agent choosing its own thesis.
                        Every other source reads in the modal. */}
                    {row.seed?.source === "nemoclaw_agent" && (
                      <SourceBadge source={row.seed.source} />
                    )}
                    <span className="ml-auto font-mono text-[10px] text-zinc-500">
                      {shortTimestamp(row.ended_at)}
                    </span>
                  </div>
                  {/* LINE 2 — topic clamped to one line; full text in title. */}
                  {seedTopic(row) && (
                    <div
                      className="mt-1 truncate text-xs text-zinc-300"
                      title={seedTopic(row)}
                    >
                      {seedTopic(row)}
                    </div>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {/* Pager — only shown when the filtered set spills past one page. */}
      {filteredCount > PAGE_SIZE && (
        <div
          className="mt-3 flex items-center gap-2 text-[11px] text-zinc-500"
          data-testid="resolved-pager"
        >
          <button
            type="button"
            onClick={() => setPage(Math.max(0, safePage - 1))}
            disabled={safePage <= 0}
            aria-label="previous page"
            className="rounded border border-zinc-800 bg-zinc-950/60 px-2 py-0.5 text-zinc-300 hover:border-zinc-600 disabled:cursor-not-allowed disabled:text-zinc-700 disabled:hover:border-zinc-800"
          >
            prev
          </button>
          <span data-testid="resolved-page-indicator">
            page {safePage + 1} of {pageCount}
          </span>
          <button
            type="button"
            onClick={() => setPage(Math.min(pageCount - 1, safePage + 1))}
            disabled={safePage >= pageCount - 1}
            aria-label="next page"
            className="rounded border border-zinc-800 bg-zinc-950/60 px-2 py-0.5 text-zinc-300 hover:border-zinc-600 disabled:cursor-not-allowed disabled:text-zinc-700 disabled:hover:border-zinc-800"
          >
            next
          </button>
        </div>
      )}

      {/* Detail modal — mounted ONLY while open (its <dialog> calls
          showModal() on mount). Closing restores focus to the opening card. */}
      {openRow && (
        <IterationDetailModal
          row={openRow}
          onClose={() => {
            setOpenRow(null);
            openerRef.current?.focus();
            openerRef.current = null;
          }}
        />
      )}
    </div>
  );
}
