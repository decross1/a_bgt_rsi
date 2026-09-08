// DossierIndex — the /dossier PICKER (UI simplification S2, the fetch-owning
// page evolution of the retired ResolveRail). The default view keeps a compact
// producer-ordered decision queue and one time-qualified recorded context.
// Search stays immediately available; the rest of the mixed record library is
// disclosed in bounded pages:
//
//   (1) YOU OWE          — gate_verdict + state_gate families (blocking).
//   (2) LATEST CONTEXT   — newest parseable iteration timestamp, explicitly
//                          qualified as recorded context rather than progress.
//   (3) HISTORY          — cleared/below-bar findings, bubbles, stale runs,
//                          unknown kinds and bounded resolved iterations.
//
// Every row is a <Link> into the dossier reader (/dossier/:id) — the picker
// exposes NO disposition affordance (the verdict fence: forms live in the
// reader's footer only). Near-duplicate finding titles collapse via the
// 6-word title-stem clustering ported VERBATIM from ResolveRail (the cron
// promotes near-dup findings every 12h). Feeds: GET /api/human_todo (10s
// poll) + GET /api/loop_v0/iterations (30s poll). A 404 on the todo feed is
// an HONEST "queue UNKNOWN" — never a calm empty state off a dead endpoint.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getHumanTodo, getIterations } from "../api/http";
import { ageLabel, clearsLadderBar, evidenceLevelOf } from "../ladderBar";
import {
  Badge,
  GATE_TONE,
  NOVELTY_TONE,
  VERDICT_TONE,
  seedTopic,
  shortTimestamp,
  toneFor,
} from "../components/chips";
import type { HumanTodoItem, IterationRecord } from "../types/schemas";
import "./dossiers.css";

// --- coercion (the Todo.tsx safeItems idiom, ported) -------------------------

// Drop non-array containers and any element that is not an object carrying a
// non-empty string `id` (the id is the /dossier/:id link target — an item
// without one cannot be pointed at, so it is dropped, never rendered).
function safeItems(value: unknown): HumanTodoItem[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (it): it is HumanTodoItem =>
      it !== null &&
      typeof it === "object" &&
      !Array.isArray(it) &&
      typeof (it as { id?: unknown }).id === "string" &&
      (it as { id: string }).id.length > 0,
  );
}

function itemIntegrity(value: unknown): {
  items: HumanTodoItem[];
  partial: boolean;
} {
  if (!Array.isArray(value)) return { items: [], partial: true };
  const admitted = safeItems(value);
  return { items: admitted, partial: admitted.length !== value.length };
}

function safeIterations(value: unknown): IterationRecord[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (row): row is IterationRecord =>
      row !== null &&
      typeof row === "object" &&
      !Array.isArray(row) &&
      typeof (row as { iteration_id?: unknown }).iteration_id === "string" &&
      (row as { iteration_id: string }).iteration_id.length > 0,
  );
}

function iterationIntegrity(value: unknown): {
  rows: IterationRecord[];
  partial: boolean;
} {
  if (!Array.isArray(value)) return { rows: [], partial: true };
  const admitted = safeIterations(value);
  return { rows: admitted, partial: admitted.length !== value.length };
}

// Title is producer-owned and may be any type; only a string is renderable text
// (typeof-only — an object/number/null all degrade to "", never "[object
// Object]" and never a raw-object child).
function titleText(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function asText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  if (typeof v === "boolean") return String(v);
  return null;
}

// The blocking "you owe" kinds, folded across both label generations (the
// backend emits state_gate; the older TS union spelled it state_file_gate).
function isBlockingKind(kind: string | null): boolean {
  return (
    kind === "gate_verdict" ||
    kind === "state_gate" ||
    kind === "state_file_gate"
  );
}

function isFinding(item: HumanTodoItem): boolean {
  return asText(item.kind) === "finding_review";
}

// --- near-dup clustering (ported VERBATIM from ResolveRail) ------------------
// The cron promotes near-duplicate findings whose long titles share a long
// common prefix. Normalize (lowercase, collapse whitespace, trim), then key on
// the first STEM_WORDS words: genuine near-dups share that prefix and collapse,
// while unrelated titles (which diverge inside the first few words) stay apart.
// An empty title yields an empty stem -> the item is bucketed by its own id, so
// it is always its own singleton (never merged, never crashed).
// FUTURE: once the idea-ledger cluster_id join reaches /api/human_todo rows,
// key on cluster_id instead of this frontend stem heuristic (S3 follow-on).
const STEM_WORDS = 6;
const HISTORY_PAGE_SIZE = 50;
function titleStem(title: string): string {
  const norm = title.toLowerCase().replace(/\s+/g, " ").trim();
  if (norm === "") return "";
  return norm.split(" ").slice(0, STEM_WORDS).join(" ");
}

type Cell =
  | { type: "single"; item: HumanTodoItem }
  | { type: "cluster"; rep: HumanTodoItem; members: HumanTodoItem[] };

// Bucket a group's items by stem (insertion order preserved -> stable, first-
// appearance ordering). A bucket of one is a singleton; a bucket of many is a
// collapsed cluster whose representative is its first (i.e. first-seen) member.
function buildCells(groupItems: HumanTodoItem[]): Cell[] {
  const buckets = new Map<string, HumanTodoItem[]>();
  for (const it of groupItems) {
    const stem = titleStem(titleText(it.title));
    const key = stem === "" ? `id:${it.id}` : `stem:${stem}`;
    const bucket = buckets.get(key);
    if (bucket) bucket.push(it);
    else buckets.set(key, [it]);
  }
  const cells: Cell[] = [];
  for (const members of buckets.values()) {
    if (members.length === 1) cells.push({ type: "single", item: members[0] });
    else cells.push({ type: "cluster", rep: members[0], members });
  }
  return cells;
}

// --- rows --------------------------------------------------------------------

// One todo-item row: a Link into the reader carrying title, kind, ladder level
// (findings), the deferred sky chip (ported from the retired HumanTodoPanel —
// a deferral assigns the work, it does not resolve it), and the age.
function ItemRow({
  item,
  nowMs,
  nested,
  sourceLabel = "recorded source",
}: {
  item: HumanTodoItem;
  nowMs: number;
  nested?: boolean;
  sourceLabel?: string;
}) {
  const id = item.id; // safeItems guarantees a non-empty string
  const kind = asText(item.kind) ?? "unknown";
  const title = titleText(item.title).trim() || id;
  const level = evidenceLevelOf(item);
  const deferralRaw = item.deferral;
  const deferral =
    deferralRaw !== null &&
    typeof deferralRaw === "object" &&
    !Array.isArray(deferralRaw)
      ? (deferralRaw as Record<string, unknown>)
      : null;
  const deferralBits =
    deferral === null
      ? []
      : [asText(deferral.by), asText(deferral.note)].filter(
          (s): s is string => s !== null && s !== "",
        );
  return (
    <li data-testid={`dossier-row-${id}`}>
      <Link
        to={`/dossier/${encodeURIComponent(id)}`}
        className={`dossier-record-link ${nested ? "dossier-record-link--nested" : ""}`}
        aria-label={`Open dossier ${id}: ${title}`}
      >
        <span className="dossier-record-copy">
          <span className="dossier-record-title" title={title}>
            {title}
          </span>
          <span className="dossier-record-meta">
            <span className="dossier-source-label">{sourceLabel}</span>
            <span className="dossier-record-id">{id}</span>
            <span>{kind}</span>
            {level && <span className="dossier-level-chip">{level}</span>}
            {item.deferred === true && (
              <span
                data-testid="todo-deferred-tag"
                className="dossier-deferred-chip"
                title={deferralBits.join(" · ") || undefined}
              >
                deferred to dev session
                {deferralBits.length > 0 && ` · ${deferralBits.join(" · ")}`}
              </span>
            )}
          </span>
        </span>
        <span className="dossier-record-open">Open dossier</span>
        <span className="dossier-record-age">
          {ageLabel(item.since, nowMs)}
        </span>
      </Link>
    </li>
  );
}

// A collapsed near-dup cluster: a representative title + an ×N count badge.
// The header EXPANDS on click (it never navigates — navigation is per-member).
function ClusterRow({
  rep,
  members,
  expanded,
  onToggle,
  nowMs,
}: {
  rep: HumanTodoItem;
  members: HumanTodoItem[];
  expanded: boolean;
  onToggle: () => void;
  nowMs: number;
}) {
  const repTitle = titleText(rep.title).trim() || rep.id;
  return (
    <li data-testid={`dossier-cluster-${rep.id}`}>
      <button
        type="button"
        data-testid={`dossier-cluster-header-${rep.id}`}
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-center gap-1.5 rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1 text-left hover:border-zinc-700"
      >
        <span className="text-[9px] text-zinc-600">{expanded ? "▾" : "▸"}</span>
        <span className="flex-1 truncate text-[11px] text-zinc-300">
          {repTitle}
        </span>
        <span
          data-testid={`dossier-cluster-count-${rep.id}`}
          className="shrink-0 rounded bg-zinc-800 px-1 py-0.5 font-mono text-[9px] text-zinc-400"
        >
          ×{members.length}
        </span>
      </button>
      {expanded && (
        <ul className="mt-1 space-y-1">
          {members.map((m) => (
            <ItemRow key={m.id} item={m} nowMs={nowMs} nested />
          ))}
        </ul>
      )}
    </li>
  );
}

// One resolved-iteration row (the browse that moved here from the Dashboard
// list): id + verdict/novelty/gate chips + topic + timestamp, linking into the
// reader by iteration id.
function IterationRow({
  row,
  testid,
}: {
  row: IterationRecord;
  testid?: string;
}) {
  const id = typeof row.iteration_id === "string" ? row.iteration_id : "";
  if (id.length === 0) return null;
  return (
    <li data-testid={testid ?? `dossier-iter-${id}`}>
      <Link
        to={`/dossier/${encodeURIComponent(id)}`}
        className="dossier-record-link dossier-record-link--iteration"
        aria-label={`Open dossier ${id}`}
      >
        <span className="dossier-record-copy">
          <span className="dossier-record-title">{seedTopic(row) || id}</span>
          <span className="dossier-record-meta">
            <span className="dossier-source-label">recorded iteration</span>
            <span className="dossier-record-id">{id}</span>
            <Badge
              text={row.critique?.verdict}
              tone={toneFor(
                VERDICT_TONE,
                row.critique?.verdict,
                "bg-zinc-800 text-zinc-400",
              )}
            />
            <Badge
              text={row.novelty?.class}
              tone={toneFor(
                NOVELTY_TONE,
                row.novelty?.class,
                "bg-zinc-800 text-zinc-400",
              )}
            />
            <Badge
              text={row.gate_status}
              tone={toneFor(GATE_TONE, row.gate_status, "")}
            />
          </span>
        </span>
        <span className="dossier-record-open">Open dossier</span>
        <span className="dossier-record-age">{shortTimestamp(row.ended_at)}</span>
      </Link>
    </li>
  );
}

function SectionHeader({
  title,
  hint,
  count,
  testid,
}: {
  title: string;
  hint: string;
  count: number | string;
  testid: string;
}) {
  return (
    <div className="flex items-baseline gap-2">
      <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-400">
        {title}
      </h2>
      <span className="text-[10px] text-zinc-600">{hint}</span>
      <span
        data-testid={testid}
        className="ml-auto rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400"
      >
        {count}
      </span>
    </div>
  );
}

interface Props {
  /** Fixture injection (tests render synchronously, never fetch). */
  items?: HumanTodoItem[];
  iterations?: IterationRecord[];
  todoPollMs?: number;
  iterPollMs?: number;
}

export default function DossierIndex({
  items,
  iterations,
  todoPollMs = 10000,
  iterPollMs = 30000,
}: Props) {
  const [todoItems, setTodoItems] = useState<HumanTodoItem[]>(
    safeItems(items),
  );
  const [todoLoaded, setTodoLoaded] = useState(items !== undefined);
  const [todoError, setTodoError] = useState<string | null>(null);
  const [todoPartial, setTodoPartial] = useState(
    items !== undefined ? itemIntegrity(items).partial : false,
  );
  const [iterRows, setIterRows] = useState<IterationRecord[]>(
    safeIterations(iterations),
  );
  const [iterLoaded, setIterLoaded] = useState(iterations !== undefined);
  const [iterError, setIterError] = useState(false);
  const [iterPartial, setIterPartial] = useState(
    iterations !== undefined ? iterationIntegrity(iterations).partial : false,
  );
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [historyLimit, setHistoryLimit] = useState(HISTORY_PAGE_SIZE);

  // /api/human_todo — the owe + findings feed (10s poll; the OweStrip idiom).
  useEffect(() => {
    if (items !== undefined) {
      const inspected = itemIntegrity(items);
      setTodoItems(inspected.items);
      setTodoPartial(inspected.partial);
      setTodoLoaded(true);
      setTodoError(null);
      return;
    }
    let active = true;
    const load = () =>
      getHumanTodo()
        .then((r) => {
          if (!active) return;
          const inspected = itemIntegrity(r?.items);
          setTodoItems(inspected.items);
          setTodoPartial(inspected.partial);
          setTodoLoaded(true);
          setTodoError(null);
        })
        .catch((e) => {
          if (active) {
            setTodoLoaded(true);
            setTodoError(String(e));
          }
        });
    load();
    const id = setInterval(load, Math.max(1000, todoPollMs));
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [items, todoPollMs]);

  // /api/loop_v0/iterations — resolved history (30s poll). Failures keep any
  // last good rows and are named separately from a valid empty response.
  useEffect(() => {
    if (iterations !== undefined) {
      const inspected = iterationIntegrity(iterations);
      setIterRows(inspected.rows);
      setIterPartial(inspected.partial);
      setIterLoaded(true);
      setIterError(false);
      return;
    }
    let active = true;
    const load = () =>
      getIterations()
        .then((r) => {
          if (!active) return;
          const inspected = iterationIntegrity(r?.iterations);
          setIterRows(inspected.rows);
          setIterPartial(inspected.partial);
          setIterLoaded(true);
          setIterError(false);
        })
        .catch(() => {
          if (active) {
            setIterLoaded(true);
            setIterError(true);
          }
        });
    load();
    const id = setInterval(load, Math.max(1000, iterPollMs));
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [iterations, iterPollMs]);

  // --- the three sections ---
  const owe = todoItems.filter((it) => isBlockingKind(asText(it.kind)));
  const clearedBar = todoItems.filter(
    (it) => isFinding(it) && clearsLadderBar(it),
  );
  const everythingElseItems = todoItems.filter(
    (it) =>
      !isBlockingKind(asText(it.kind)) &&
      !(isFinding(it) && clearsLadderBar(it)),
  );

  // Section-3 search: title OR id (case-insensitive) over the leftover items,
  // topic OR id over the resolved iterations. Search BEFORE clustering, so a
  // hit inside a cluster surfaces its member as a singleton (ResolveRail rule).
  const q = query.trim().toLowerCase();
  const matchesItem = (item: HumanTodoItem) => q === "" ||
    titleText(item.title).toLowerCase().includes(q) || item.id.toLowerCase().includes(q);
  const visibleOwe = owe.filter(matchesItem);
  const visibleCleared = clearedBar.filter(matchesItem);
  const queueComplete = todoLoaded && !todoError && !todoPartial;
  const historyComplete = iterLoaded && !iterError && !iterPartial;
  const countText = (count: number, complete: boolean) => complete ? count
    : count > 0 ? `${count} received · total unknown` : "unknown";
  const visibleElse = useMemo(
    () =>
      everythingElseItems.filter((it) => {
        if (q === "") return true;
        return (
          titleText(it.title).toLowerCase().includes(q) ||
          it.id.toLowerCase().includes(q)
        );
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [todoItems, q],
  );
  const visibleIters = useMemo(
    () =>
      iterRows.filter((row) => {
        if (row === null || typeof row !== "object" || Array.isArray(row)) {
          return false;
        }
        if (q === "") return true;
        const id =
          typeof row.iteration_id === "string" ? row.iteration_id : "";
        return (
          seedTopic(row).toLowerCase().includes(q) ||
          id.toLowerCase().includes(q)
        );
      }),
    [iterRows, q],
  );
  const elseCells = useMemo(() => buildCells(visibleElse), [visibleElse]);
  const visibleIterationPage = visibleIters.slice(0, historyLimit);
  const remainingIterations = Math.max(
    0,
    visibleIters.length - visibleIterationPage.length,
  );
  const latestIteration = useMemo(() => {
    return iterRows.reduce<IterationRecord | null>((latest, row) => {
      const rowTime = Date.parse(asText(row.ended_at) ?? "");
      if (Number.isNaN(rowTime)) return latest;
      if (latest === null) return row;
      const latestTime = Date.parse(asText(latest.ended_at) ?? "");
      if (rowTime > latestTime) return row;
      return latest;
    }, null);
  }, [iterRows]);

  const toggleCluster = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const endpointMissing = todoError !== null && /\b404\b/.test(todoError);
  const queueState = todoError
    ? endpointMissing
      ? "unknown"
      : "error"
    : todoPartial
      ? "partial"
      : todoLoaded
        ? "ready"
        : "loading";
  const queueStateText = todoError
    ? todoItems.length > 0
      ? "Queue refresh unavailable · showing the last recorded response"
      : endpointMissing
        ? "Queue source unknown"
        : "Queue source unavailable"
    : todoPartial
      ? "Queue source partial · malformed records omitted"
      : todoLoaded
        ? "Queue source loaded"
        : "Loading queue source";
  const nowMs = Date.now();

  const updateQuery = (nextQuery: string) => {
    setQuery(nextQuery);
    setHistoryLimit(HISTORY_PAGE_SIZE);
  };

  return (
    <div className="dossier-index-page" data-testid="dossier-index">
      <header className="dossier-page-header">
        <div>
          <h1 className="dossier-page-title">Dossiers</h1>
          <p className="dossier-page-lede">
            Find the recorded evidence that needs human attention, then open one
            exact source-bound record.
          </p>
        </div>
        <span
          className="dossier-source-state"
          data-state={queueState}
          data-testid="dossier-source-state"
        >
          {queueStateText}
        </span>
      </header>

      {todoError &&
        (endpointMissing ? (
          <div className="mb-3 text-xs text-amber-600" data-testid="dossier-error">
            /api/human_todo returned 404 — the queue is UNKNOWN, not empty.
          </div>
        ) : (
          <div className="mb-3 text-xs text-red-600" data-testid="dossier-error">
            Queue refresh failed: {todoError}
          </div>
        ))}
      {todoPartial && !todoError && (
        <div className="mb-3 text-xs text-amber-600" data-testid="dossier-partial">
          The queue response contained malformed records. Valid records remain
          available below; the displayed counts are partial.
        </div>
      )}

      <div className="dossier-search" role="search">
        <label htmlFor="dossier-search-input">Find a dossier</label>
        <input
          id="dossier-search-input"
          type="search"
          data-testid="dossier-search"
          placeholder="Search title, topic, or exact id"
          value={query}
          onChange={(event) => updateQuery(event.target.value)}
          className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none"
        />
        <span>Search recorded requests and history. A listed request does not establish current eligibility.</span>
      </div>

      <section data-testid="dossier-owe" className="dossier-surface p-4">
        <SectionHeader
          title="Recorded requests"
          hint={q ? "matching requests · source order" : "source order · inspect date and authority"}
          count={countText(visibleOwe.length, queueComplete)}
          testid="dossier-owe-count"
        />
        {todoLoaded && !todoError && !todoPartial && owe.length === 0 && (
          <div className="mt-2 text-sm text-zinc-500" data-testid="dossier-owe-empty">
            You owe nothing listed by the current queue source. This does not
            establish overall loop or research status.
          </div>
        )}
        {visibleOwe.length > 0 && (
          <ul className="mt-2 space-y-1.5">
            {visibleOwe.map((it) => (
              <ItemRow
                key={it.id}
                item={it}
                nowMs={nowMs}
                sourceLabel="recorded request"
              />
            ))}
          </ul>
        )}
      </section>

      {q === "" && <section
        data-testid="dossier-latest"
        className="dossier-surface mt-3 p-4"
      >
        <SectionHeader
          title="Latest recorded context"
          hint="iteration history · not a live eligibility signal"
          count={countText(latestIteration === null ? 0 : 1, historyComplete)}
          testid="dossier-latest-count"
        />
        {!iterLoaded && (
          <div className="mt-2 text-sm text-zinc-500" data-testid="dossier-latest-loading">
            Loading recorded iteration history…
          </div>
        )}
        {iterLoaded && iterError && iterRows.length === 0 && (
          <div className="mt-2 text-sm text-red-600" data-testid="dossier-history-error">
            Recorded iteration history is unavailable.
          </div>
        )}
        {iterLoaded && iterPartial && (
          <div
            className="mt-2 text-sm text-amber-600"
            data-testid="dossier-history-partial"
          >
            Some iteration records were malformed; this context is partial.
          </div>
        )}
        {latestIteration !== null ? (
          <ul className="mt-2">
            <IterationRow
              row={latestIteration}
              testid={`dossier-latest-iter-${latestIteration.iteration_id}`}
            />
          </ul>
        ) : iterLoaded && !iterError && !iterPartial ? (
          <div className="mt-2 text-sm text-zinc-500" data-testid="dossier-latest-empty">
            {iterRows.length > 0
              ? "No iteration has a usable recorded end time."
              : "No recorded iterations are available from this source."}
          </div>
        ) : null}
        {iterError && iterRows.length > 0 && (
          <div className="mt-2 text-xs text-amber-600" data-testid="dossier-history-refresh-error">
            History refresh failed; showing the last recorded response.
          </div>
        )}
      </section>}

      <details
        data-testid="dossier-history-browser"
        className="dossier-history dossier-surface"
        open={q !== "" || undefined}
      >
        <summary>
          Browse history · {countText(everythingElseItems.length + clearedBar.length + iterRows.length, queueComplete && historyComplete)} recorded items
        </summary>
        <div className="dossier-history-body">
          <section data-testid="dossier-cleared" className="mt-4">
            <SectionHeader
              title="Recorded L4/L5 findings"
              hint="recorded findings at L4/L5 (D-059)"
              count={countText(visibleCleared.length, queueComplete)}
              testid="dossier-cleared-count"
            />
            {todoLoaded && !todoError && !todoPartial && clearedBar.length === 0 && (
              <div className="mt-2 text-sm text-zinc-500" data-testid="dossier-cleared-empty">
                No L4/L5 findings are listed in the loaded queue source.
              </div>
            )}
            {visibleCleared.length > 0 && (
              <ul className="mt-2 space-y-1.5">
                {visibleCleared.map((it) => (
                  <ItemRow key={it.id} item={it} nowMs={nowMs} sourceLabel="recorded finding" />
                ))}
              </ul>
            )}
          </section>

          <section className="mt-4" data-testid="dossier-else">
            <SectionHeader
              title="All other records"
              hint="below-bar findings · bubbles · stale runs · iterations"
              count={countText(visibleElse.length + visibleIters.length, queueComplete && historyComplete)}
              testid="dossier-else-count"
            />
            {visibleElse.length === 0 && visibleIters.length === 0 && queueComplete && historyComplete ? (
              <div className="mt-2 text-[11px] text-zinc-500" data-testid="dossier-else-empty">
                {q !== ""
                  ? "no dossiers match — adjust the search."
                  : "no other recorded dossiers are available."}
              </div>
            ) : (
              <>
                {elseCells.length > 0 && (
                  <ul className="mt-2 space-y-1.5">
                    {elseCells.map((cell) =>
                      cell.type === "single" ? (
                        <ItemRow key={cell.item.id} item={cell.item} nowMs={nowMs} />
                      ) : (
                        <ClusterRow
                          key={cell.rep.id}
                          rep={cell.rep}
                          members={cell.members}
                          expanded={expanded.has(cell.rep.id)}
                          onToggle={() => toggleCluster(cell.rep.id)}
                          nowMs={nowMs}
                        />
                      ),
                    )}
                  </ul>
                )}
                {visibleIters.length > 0 && (
                  <div className="mt-4" data-testid="dossier-iterations">
                    <h3 className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
                      Recorded iterations
                    </h3>
                    <ul className="mt-2 space-y-1.5">
                      {visibleIterationPage.map((row) => (
                        <IterationRow key={row.iteration_id} row={row} />
                      ))}
                    </ul>
                    <div className="dossier-history-progress">
                      <span data-testid="dossier-history-progress">
                        Showing {visibleIterationPage.length} of {visibleIters.length} matching iterations
                      </span>
                      {(visibleIters.length > HISTORY_PAGE_SIZE || historyLimit > HISTORY_PAGE_SIZE) && (
                        <button
                          type="button"
                          data-testid="dossier-history-more"
                          disabled={remainingIterations === 0}
                          onClick={() =>
                            setHistoryLimit((current) =>
                              Math.min(current + HISTORY_PAGE_SIZE, visibleIters.length),
                            )
                          }
                        >
                          {remainingIterations > 0
                            ? `Show next ${Math.min(HISTORY_PAGE_SIZE, remainingIterations)} · ${remainingIterations} remaining`
                            : "All matching iterations shown"}
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      </details>
    </div>
  );
}
