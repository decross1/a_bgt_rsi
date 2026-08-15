// DossierIndex — the /dossier PICKER (UI simplification S2, the fetch-owning
// page evolution of the retired ResolveRail). Owe-first ordering under the
// 2026-08 selection-before-the-human inversion (D-059):
//
//   (1) YOU OWE          — gate_verdict + state_gate families (blocking).
//   (2) CLEARED THE BAR  — finding_review items at L4/L5 (the shared
//                          src/ladderBar.ts bar). Honest empty state: "Nothing
//                          cleared L4 this week." — never silence.
//   (3) EVERYTHING ELSE  — searchable: the below-bar/legacy findings (the
//                          pre-ladder 31), bubbles, stale runs, unknown kinds,
//                          and the resolved-iteration history (browse moved
//                          here from the Dashboard list).
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
}: {
  item: HumanTodoItem;
  nowMs: number;
  nested?: boolean;
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
        className={`flex flex-wrap items-baseline gap-2 rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5 text-xs hover:border-zinc-600 ${nested ? "ml-3" : ""}`}
      >
        <span className="text-zinc-200">{title}</span>
        {level && (
          <span className="rounded bg-emerald-950 px-1 py-0.5 text-[10px] text-emerald-400">
            {level}
          </span>
        )}
        <span className="text-[10px] uppercase tracking-wide text-zinc-600">
          {kind}
        </span>
        {item.deferred === true && (
          <span
            data-testid="todo-deferred-tag"
            className="rounded bg-sky-950 px-1.5 py-0.5 text-[10px] text-sky-400"
            title={deferralBits.join(" · ") || undefined}
          >
            deferred to dev session
            {deferralBits.length > 0 && (
              <span className="text-sky-600"> · {deferralBits.join(" · ")}</span>
            )}
          </span>
        )}
        <span className="ml-auto font-mono text-[10px] text-zinc-500">
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
function IterationRow({ row }: { row: IterationRecord }) {
  const id = typeof row.iteration_id === "string" ? row.iteration_id : "";
  if (id.length === 0) return null;
  return (
    <li data-testid={`dossier-iter-${id}`}>
      <Link
        to={`/dossier/${encodeURIComponent(id)}`}
        className="block rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5 text-xs hover:border-zinc-600"
      >
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="font-mono text-zinc-200">{id}</span>
          <Badge
            text={row.critique?.verdict}
            tone={toneFor(VERDICT_TONE, row.critique?.verdict, "bg-zinc-800 text-zinc-400")}
          />
          <Badge
            text={row.novelty?.class}
            tone={toneFor(NOVELTY_TONE, row.novelty?.class, "bg-zinc-800 text-zinc-400")}
          />
          <Badge text={row.gate_status} tone={toneFor(GATE_TONE, row.gate_status, "")} />
          <span className="ml-auto font-mono text-[10px] text-zinc-500">
            {shortTimestamp(row.ended_at)}
          </span>
        </div>
        {seedTopic(row) && (
          <div className="mt-1 truncate text-xs text-zinc-300" title={seedTopic(row)}>
            {seedTopic(row)}
          </div>
        )}
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
  count: number;
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
  const [iterRows, setIterRows] = useState<IterationRecord[]>(
    Array.isArray(iterations) ? iterations : [],
  );
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // /api/human_todo — the owe + findings feed (10s poll; the OweStrip idiom).
  useEffect(() => {
    if (items !== undefined) {
      setTodoItems(safeItems(items));
      return;
    }
    let active = true;
    const load = () =>
      getHumanTodo()
        .then((r) => {
          if (!active) return;
          setTodoItems(safeItems(r?.items));
          setTodoLoaded(true);
          setTodoError(null);
        })
        .catch((e) => {
          if (active) setTodoError(String(e));
        });
    load();
    const id = setInterval(load, Math.max(1000, todoPollMs));
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [items, todoPollMs]);

  // /api/loop_v0/iterations — the resolved history (30s poll; failures leave
  // the section empty-quiet — the todo feed is the load-bearing one).
  useEffect(() => {
    if (iterations !== undefined) {
      setIterRows(Array.isArray(iterations) ? iterations : []);
      return;
    }
    let active = true;
    const load = () =>
      getIterations()
        .then((r) => {
          if (!active) return;
          setIterRows(Array.isArray(r?.iterations) ? r.iterations : []);
        })
        .catch(() => {
          /* history feed down → the section just stays empty */
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

  const toggleCluster = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const endpointMissing = todoError !== null && /\b404\b/.test(todoError);
  const nowMs = Date.now();

  return (
    <div className="mx-auto max-w-5xl p-5" data-testid="dossier-index">
      <header className="mb-3">
        <h1 className="text-sm font-semibold uppercase tracking-wide text-zinc-300">
          /dossier · what deserves your attention
        </h1>
        <p className="mt-0.5 text-[11px] text-zinc-500">
          Owe-first: blocking decisions, then findings that cleared the L4
          evidence bar, then everything else. Each row opens its full dossier —
          the journey, the interrogation, and the verdict forms.
        </p>
      </header>

      {todoError &&
        (endpointMissing ? (
          <div className="mb-3 text-xs text-amber-400" data-testid="dossier-error">
            /api/human_todo returned 404 — the queue is UNKNOWN, not empty.
          </div>
        ) : (
          <div className="mb-3 text-xs text-red-400" data-testid="dossier-error">
            {todoError}
          </div>
        ))}

      {/* (1) YOU OWE */}
      <section data-testid="dossier-owe" className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
        <SectionHeader
          title="you owe"
          hint="gate verdicts + state gates — blocking"
          count={owe.length}
          testid="dossier-owe-count"
        />
        {todoLoaded && !todoError && owe.length === 0 && (
          <div className="mt-2 text-sm text-zinc-500" data-testid="dossier-owe-empty">
            You owe nothing — the loop is unblocked.
          </div>
        )}
        {owe.length > 0 && (
          <ul className="mt-2 space-y-1.5">
            {owe.map((it) => (
              <ItemRow key={it.id} item={it} nowMs={nowMs} />
            ))}
          </ul>
        )}
      </section>

      {/* (2) CLEARED THE BAR */}
      <section
        data-testid="dossier-cleared"
        className="mt-3 rounded border border-zinc-800 bg-zinc-900/40 p-4"
      >
        <SectionHeader
          title="cleared the bar"
          hint="findings at L4/L5 (D-059)"
          count={clearedBar.length}
          testid="dossier-cleared-count"
        />
        {todoLoaded && !todoError && clearedBar.length === 0 && (
          <div
            className="mt-2 text-sm text-zinc-500"
            data-testid="dossier-cleared-empty"
          >
            Nothing cleared L4 this week.
          </div>
        )}
        {clearedBar.length > 0 && (
          <ul className="mt-2 space-y-1.5">
            {clearedBar.map((it) => (
              <ItemRow key={it.id} item={it} nowMs={nowMs} />
            ))}
          </ul>
        )}
      </section>

      {/* (3) EVERYTHING ELSE — searchable */}
      <section
        data-testid="dossier-else"
        className="mt-3 rounded border border-zinc-800 bg-zinc-900/40 p-4"
      >
        <SectionHeader
          title="everything else"
          hint="below-bar findings · bubbles · stale runs · resolved iterations"
          count={visibleElse.length + visibleIters.length}
          testid="dossier-else-count"
        />
        <input
          type="text"
          data-testid="dossier-search"
          aria-label="search dossiers by title, topic, or id"
          placeholder="search title, topic, or id…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="mt-2 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none"
        />
        {visibleElse.length === 0 && visibleIters.length === 0 ? (
          <div
            className="mt-2 text-[11px] text-zinc-500"
            data-testid="dossier-else-empty"
          >
            {q !== ""
              ? "no dossiers match — adjust the search."
              : "nothing else pending."}
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
              <div className="mt-3" data-testid="dossier-iterations">
                <h3 className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
                  resolved iterations
                </h3>
                <ul className="mt-1 space-y-1.5">
                  {visibleIters.map((row, i) => (
                    <IterationRow
                      key={`${typeof row.iteration_id === "string" ? row.iteration_id : "iter"}-${i}`}
                      row={row}
                    />
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}
