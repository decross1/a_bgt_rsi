// ResolveRail — the persistent right-side NAVIGATOR for the /todo cockpit
// (Part C, 2026-06-30 work order). The backlog is 25+ items and growing (the
// cron promotes near-duplicate findings every 12h), so a flat inbox stops
// scaling. The rail is a richer PRESENTATION of the SAME lifted todoItems list
// Todo.tsx owns — it fetches nothing, adds no endpoint. It groups open items by
// kind, collapses near-duplicate title clusters, and offers a kind filter + a
// free-text search; clicking a row drives the EXISTING workspace selection via
// the same `onSelect` contract HumanTodoPanel's selectMode uses.
//
// VERDICT-FENCE (D-053/D-054): the rail is selection-only navigation. It exposes
// NO verdict / disposition affordance — its only output is onSelect(id), which
// points the (already verdict-fenced) workspace at an item. It never writes.
//
// HOUSE ROBUSTNESS DOCTRINE: `items` is producer-derived and bypasses the
// fetch-path coercion, so it is re-coerced here — a non-object / id-less element
// is dropped, a non-string title coerces to "" (typeof-only). A raw object is
// never rendered as a React child, and a hostile item never crashes the rail.
import { useMemo, useState } from "react";
import type { HumanTodoItem } from "../../types/schemas";

// --- coercion (mirrors Todo.tsx safeItems / its typeof-only title rule) -------

// Drop non-array containers and any element that is not an object carrying a
// non-empty string `id` (the id is the selection key onSelect fires with — an
// item without one cannot be pointed at, so it is dropped, never rendered).
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

// Title is producer-owned and may be any type; only a string is renderable text
// (typeof-only — an object/number/null all degrade to "", never "[object
// Object]" and never a raw-object child).
function titleText(v: unknown): string {
  return typeof v === "string" ? v : "";
}

// --- kind grouping (the 3-way Todo.tsx classifyKind, copied per the work order:
// gate_verdict -> iteration, finding_review -> finding, else -> other) ---------
type KindClass = "iteration" | "finding" | "other";
function classifyKind(kind: unknown): KindClass {
  if (kind === "gate_verdict") return "iteration";
  if (kind === "finding_review") return "finding";
  return "other";
}

const GROUPS: { key: KindClass; label: string }[] = [
  { key: "iteration", label: "gate-verdicts" },
  { key: "finding", label: "findings" },
  { key: "other", label: "other" },
];

type KindFilter = "all" | KindClass;
const FILTERS: { key: KindFilter; label: string }[] = [
  { key: "all", label: "all" },
  { key: "iteration", label: "gate-verdicts" },
  { key: "finding", label: "findings" },
  { key: "other", label: "other" },
];

// --- near-dup clustering (v0 = frontend title-stem heuristic, in-file) ---------
// The cron promotes near-duplicate findings whose long titles share a long
// common prefix ("In repeated public goods games with noisy contribution
// observation…"). Normalize (lowercase, collapse whitespace, trim), then key on
// the first STEM_WORDS words: genuine near-dups share that prefix and collapse,
// while unrelated titles (which diverge inside the first few words) stay apart.
// An empty title yields an empty stem -> the item is bucketed by its own id, so
// it is always its own singleton (never merged, never crashed).
const STEM_WORDS = 6;
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

// One selectable item row (singleton, or an expanded cluster member). Clicking
// it fires onSelect(id); the selectedId row is marked with aria-current.
function ItemRow({
  item,
  selectedId,
  onSelect,
  nested,
}: {
  item: HumanTodoItem;
  selectedId: string | null;
  onSelect: (id: string) => void;
  nested?: boolean;
}) {
  const id = item.id; // safeItems guarantees a non-empty string
  const title = titleText(item.title).trim();
  const isSelected = selectedId != null && selectedId === id;
  return (
    <li>
      <button
        type="button"
        data-testid={`resolve-row-${id}`}
        onClick={() => onSelect(id)}
        aria-current={isSelected ? "true" : undefined}
        className={`flex w-full flex-col items-start gap-0.5 rounded border px-2 py-1 text-left ${
          isSelected
            ? "border-emerald-700 bg-emerald-950/30"
            : "border-transparent hover:border-zinc-700 hover:bg-zinc-900/40"
        } ${nested ? "pl-3" : ""}`}
      >
        <span className="text-[11px] text-zinc-200">
          {title || "(untitled)"}
        </span>
        <span className="font-mono text-[9px] text-zinc-500">{id}</span>
      </button>
    </li>
  );
}

// A collapsed near-dup cluster: a representative title + an ×N count badge. The
// header EXPANDS on click (it never selects — selection is per-member). A
// cluster holding the selected item is force-open + marked, so the selection is
// always visible.
function ClusterRow({
  rep,
  members,
  expanded,
  onToggle,
  selectedId,
  onSelect,
}: {
  rep: HumanTodoItem;
  members: HumanTodoItem[];
  expanded: boolean;
  onToggle: () => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const repTitle = titleText(rep.title).trim() || rep.id;
  const containsSelected =
    selectedId != null && members.some((m) => m.id === selectedId);
  const open = expanded || containsSelected;
  return (
    <li data-testid={`resolve-cluster-${rep.id}`}>
      <button
        type="button"
        data-testid={`resolve-cluster-header-${rep.id}`}
        onClick={onToggle}
        aria-expanded={open}
        aria-current={containsSelected ? "true" : undefined}
        className={`flex w-full items-center gap-1.5 rounded border px-2 py-1 text-left ${
          containsSelected
            ? "border-emerald-800 bg-emerald-950/20"
            : "border-zinc-800/60 bg-zinc-950/40 hover:border-zinc-700"
        }`}
      >
        <span className="text-[9px] text-zinc-600">{open ? "▾" : "▸"}</span>
        <span className="flex-1 truncate text-[11px] text-zinc-300">
          {repTitle}
        </span>
        <span
          data-testid={`resolve-cluster-count-${rep.id}`}
          className="shrink-0 rounded bg-zinc-800 px-1 py-0.5 font-mono text-[9px] text-zinc-400"
        >
          ×{members.length}
        </span>
      </button>
      {open && (
        <ul className="mt-1 space-y-1">
          {members.map((m) => (
            <ItemRow
              key={m.id}
              item={m}
              selectedId={selectedId}
              onSelect={onSelect}
              nested
            />
          ))}
        </ul>
      )}
    </li>
  );
}

export default function ResolveRail({
  items,
  selectedId,
  onSelect,
}: {
  items: HumanTodoItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const clean = useMemo(() => safeItems(items), [items]);

  // Filter by kind + free-text (title OR id, case-insensitive) BEFORE grouping,
  // so the search re-clusters on the narrowed set (a search that hits one member
  // of a cluster surfaces that member as a singleton).
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return clean.filter((it) => {
      if (kindFilter !== "all" && classifyKind(it.kind) !== kindFilter)
        return false;
      if (q === "") return true;
      return (
        titleText(it.title).toLowerCase().includes(q) ||
        it.id.toLowerCase().includes(q)
      );
    });
  }, [clean, kindFilter, query]);

  const toggleCluster = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const filterActive = kindFilter !== "all" || query.trim() !== "";

  return (
    <aside
      data-testid="resolve-rail"
      aria-label="Resolve rail — open items"
      className="w-72 shrink-0 self-start rounded border border-zinc-800 bg-zinc-900/40 p-3"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-[10px] font-semibold uppercase tracking-wide text-zinc-400">
          resolve rail
        </h2>
        <span className="text-[10px] text-zinc-600">navigate the backlog</span>
        <span
          data-testid="resolve-rail-total"
          className="ml-auto rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400"
        >
          {clean.length}
        </span>
      </div>

      {/* kind filter */}
      <div className="mt-2 flex flex-wrap gap-1" data-testid="resolve-filters">
        {FILTERS.map((f) => {
          const active = kindFilter === f.key;
          return (
            <button
              key={f.key}
              type="button"
              data-testid={`resolve-filter-${f.key}`}
              aria-pressed={active}
              onClick={() => setKindFilter(f.key)}
              className={`rounded border px-1.5 py-0.5 text-[10px] ${
                active
                  ? "border-sky-700 bg-sky-950 text-sky-300"
                  : "border-zinc-700 text-zinc-400 hover:border-zinc-600"
              }`}
            >
              {f.label}
            </button>
          );
        })}
      </div>

      {/* free-text search */}
      <input
        type="text"
        data-testid="resolve-search"
        aria-label="search open items by title or id"
        placeholder="search title or id…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="mt-2 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none"
      />

      {visible.length === 0 ? (
        <div
          data-testid="resolve-rail-empty"
          className="mt-3 text-[11px] text-zinc-500"
        >
          {filterActive
            ? "no items match — adjust the filter or search."
            : "nothing open — the backlog is clear."}
        </div>
      ) : (
        <div className="mt-2 space-y-3">
          {GROUPS.map((g) => {
            const groupItems = visible.filter(
              (it) => classifyKind(it.kind) === g.key,
            );
            if (groupItems.length === 0) return null;
            const cells = buildCells(groupItems);
            return (
              <div key={g.key} data-testid={`resolve-group-${g.key}`}>
                <div className="flex items-baseline gap-2">
                  <h3 className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
                    {g.label}
                  </h3>
                  <span
                    data-testid={`resolve-group-count-${g.key}`}
                    className="text-[10px] text-zinc-600"
                  >
                    {groupItems.length}
                  </span>
                </div>
                <ul className="mt-1 space-y-1">
                  {cells.map((cell) =>
                    cell.type === "single" ? (
                      <ItemRow
                        key={cell.item.id}
                        item={cell.item}
                        selectedId={selectedId}
                        onSelect={onSelect}
                      />
                    ) : (
                      <ClusterRow
                        key={cell.rep.id}
                        rep={cell.rep}
                        members={cell.members}
                        expanded={expanded.has(cell.rep.id)}
                        onToggle={() => toggleCluster(cell.rep.id)}
                        selectedId={selectedId}
                        onSelect={onSelect}
                      />
                    ),
                  )}
                </ul>
              </div>
            );
          })}
        </div>
      )}
    </aside>
  );
}
