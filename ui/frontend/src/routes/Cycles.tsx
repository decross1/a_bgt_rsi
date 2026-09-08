import { useEffect, useMemo, useState } from "react";
import CoordinatorCycleCard from "../components/CoordinatorCycleCard";
import CoordinatorPhases from "../components/CoordinatorPhases";
import { getActiveRuns, getCoordinatorCycles } from "../api/http";
import { useNow } from "../time";
import type { CoordinatorActiveRun, CoordinatorCycle } from "../types/schemas";
import "./traces.css";

type Range = "all" | "today" | "week";
type Direction = "newest" | "oldest";
type OutcomeFilter = "all" | "passed" | "errored" | "skipped" | "pending" | "other";

const PAGE_SIZE = 20;

interface Props {
  initial?: CoordinatorCycle[];
  pollMs?: number;
  initialPhasesRun?: CoordinatorActiveRun | null;
  initialPhasesError?: string | null;
}

function text(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return fallback;
}

function timestampKey(cycle: CoordinatorCycle | null | undefined): string {
  return typeof cycle?.timestamp === "string"
    ? cycle.timestamp
    : String(cycle?.timestamp ?? "");
}

function isRenderableCycle(cycle: CoordinatorCycle | null | undefined): cycle is CoordinatorCycle {
  return (
    !!cycle &&
    Array.isArray((cycle as { plan?: unknown }).plan) &&
    Array.isArray((cycle as { outcomes?: unknown }).outcomes)
  );
}

function inRange(cycle: CoordinatorCycle, range: Range, nowMs: number): boolean {
  if (range === "all") return true;
  const parsed = Date.parse(timestampKey(cycle));
  if (!Number.isFinite(parsed)) return false;
  if (range === "week") return nowMs - parsed <= 7 * 24 * 60 * 60 * 1000;
  const a = new Date(parsed);
  const b = new Date(nowMs);
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function outcomeFor(cycle: CoordinatorCycle): OutcomeFilter {
  const statuses = cycle.outcomes
    .map((item) => text(item?.status).toLowerCase())
    .filter(Boolean);
  if (statuses.includes("errored")) return "errored";
  if (statuses.includes("passed")) return "passed";
  if (statuses.includes("skipped")) return "skipped";
  if (statuses.length === 0 && cycle.plan.length > 0) return "pending";
  return "other";
}

function actionLabel(cycle: CoordinatorCycle): string {
  const source = cycle.outcomes.length > 0 ? cycle.outcomes : cycle.plan;
  const actions = source
    .map((item) => text(item?.action))
    .filter(Boolean)
    .filter((action, index, all) => all.indexOf(action) === index);
  if (actions.length === 0) return "No action recorded";
  return actions.length > 2
    ? `${actions.slice(0, 2).join(", ")} +${actions.length - 2}`
    : actions.join(", ");
}

function cycleIdentity(cycle: CoordinatorCycle): string {
  return [text(cycle.run_id), timestampKey(cycle), text(cycle.topic), text(cycle.agent)].join("\u001f");
}

function cycleSearchText(cycle: CoordinatorCycle): string {
  const fields: string[] = [
    text(cycle.run_id),
    timestampKey(cycle),
    text(cycle.agent),
    text(cycle.topic),
    text(cycle.topic_source),
    text(cycle.status),
    text(cycle.dispatched_iteration_id),
  ];
  for (const step of cycle.plan) fields.push(text(step?.action));
  for (const item of cycle.outcomes) {
    fields.push(text(item?.action), text(item?.status), text(item?.error));
  }
  return fields.join(" ").toLocaleLowerCase();
}

function isMeaningful(cycle: CoordinatorCycle): boolean {
  return (
    outcomeFor(cycle) === "errored" ||
    cycle.plan.some((item) => text(item?.action) !== "noop") ||
    cycle.outcomes.some((item) => text(item?.action) !== "noop") ||
    Boolean(text(cycle.dispatched_iteration_id)) ||
    (Array.isArray(cycle.promoted_finding_ids) && cycle.promoted_finding_ids.length > 0) ||
    (Array.isArray(cycle.bubble_run_ids) && cycle.bubble_run_ids.length > 0)
  );
}

function shortTime(value: unknown): string {
  if (typeof value !== "string" || !value) return "Time not reported";
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function canonicalValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, nested]) => [key, canonicalValue(nested)]),
    );
  }
  return value;
}

function exactNoopSignature(cycle: CoordinatorCycle): string | null {
  const clean =
    cycle.plan.length === 1 &&
    text(cycle.plan[0]?.action) === "noop" &&
    cycle.outcomes.length === 1 &&
    text(cycle.outcomes[0]?.action) === "noop" &&
    text(cycle.outcomes[0]?.status) === "passed" &&
    !text(cycle.outcomes[0]?.error) &&
    !text(cycle.dispatched_iteration_id) &&
    (!Array.isArray(cycle.promoted_finding_ids) || cycle.promoted_finding_ids.length === 0) &&
    (!Array.isArray(cycle.bubble_run_ids) || cycle.bubble_run_ids.length === 0);
  if (!clean) return null;
  const comparable: Record<string, unknown> = {
    ...(cycle as unknown as Record<string, unknown>),
  };
  delete comparable.timestamp;
  delete comparable.run_id;
  return `noop:${JSON.stringify(canonicalValue(comparable))}`;
}

interface PageGroup {
  signature: string | null;
  cycles: CoordinatorCycle[];
}

function groupPage(cycles: CoordinatorCycle[]): PageGroup[] {
  const groups: PageGroup[] = [];
  for (const cycle of cycles) {
    const signature = exactNoopSignature(cycle);
    const previous = groups[groups.length - 1];
    if (signature && previous?.signature === signature) previous.cycles.push(cycle);
    else groups.push({ signature, cycles: [cycle] });
  }
  return groups;
}

function CycleRow({
  cycle,
  selected,
  onSelect,
}: {
  cycle: CoordinatorCycle;
  selected: boolean;
  onSelect: () => void;
}) {
  const outcome = outcomeFor(cycle);
  const topic = text(cycle.topic, "Untitled recorded cycle");
  const exactTime = timestampKey(cycle);
  return (
    <button
      type="button"
      className="trace-cycle-row"
      data-testid="coordinator-cycle-row"
      data-selected={selected ? "true" : "false"}
      data-outcome={outcome}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="trace-cycle-time" title={exactTime || undefined}>
        {shortTime(cycle.timestamp)}
      </span>
      <span className="trace-cycle-main">
        <strong>{topic}</strong>
        <span>{actionLabel(cycle)}</span>
      </span>
      <span className="trace-outcome" data-tone={outcome}>
        {outcome === "other" ? text(cycle.status, "outcome unknown") : outcome}
      </span>
    </button>
  );
}

export default function Cycles({
  initial,
  pollMs = 5000,
  initialPhasesRun,
  initialPhasesError,
}: Props) {
  const [cycles, setCycles] = useState<CoordinatorCycle[]>(initial ?? []);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(initial !== undefined);
  const [phasesRun, setPhasesRun] = useState<CoordinatorActiveRun | null>(initialPhasesRun ?? null);
  const [phasesError, setPhasesError] = useState<string | null>(initialPhasesError ?? null);
  const [range, setRange] = useState<Range>("all");
  const [direction, setDirection] = useState<Direction>("newest");
  const [outcome, setOutcome] = useState<OutcomeFilter>("all");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [recordOpen, setRecordOpen] = useState(false);
  const now = useNow(60_000);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getCoordinatorCycles()
        .then((response) => {
          if (!active) return;
          const rows = Array.isArray(response?.cycles) ? response.cycles : [];
          setCycles([...rows].sort((a, b) => timestampKey(b).localeCompare(timestampKey(a))));
          setLoaded(true);
          setHistoryError(null);
        })
        .catch((error) => {
          if (active) setHistoryError(String(error));
        });
    load();
    const id = setInterval(load, pollMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [initial, pollMs]);

  useEffect(() => {
    if (initialPhasesRun !== undefined || initialPhasesError !== undefined) return;
    let active = true;
    const load = () =>
      getActiveRuns()
        .then((response) => {
          if (!active) return;
          const runs = Array.isArray(response?.runs) ? response.runs : [];
          const live = runs.find((run) => run != null && run.kind === "coordinator");
          setPhasesRun((live as CoordinatorActiveRun | undefined) ?? null);
          setPhasesError(null);
        })
        .catch((error) => {
          if (active) setPhasesError(String(error));
        });
    load();
    const id = setInterval(load, pollMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [initialPhasesError, initialPhasesRun, pollMs]);

  const admitted = useMemo(() => cycles.filter(isRenderableCycle), [cycles]);
  const excludedCount = cycles.length - admitted.length;
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filtered = useMemo(
    () =>
      admitted
        .filter((cycle) => inRange(cycle, range, now))
        .filter((cycle) => outcome === "all" || outcomeFor(cycle) === outcome)
        .filter((cycle) => !normalizedQuery || cycleSearchText(cycle).includes(normalizedQuery))
        .sort((a, b) => {
          const comparison = timestampKey(b).localeCompare(timestampKey(a));
          return direction === "newest" ? comparison : -comparison;
        }),
    [admitted, direction, normalizedQuery, now, outcome, range],
  );

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount);
  const pageRows = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const pageGroups = groupPage(pageRows);
  const selected =
    filtered.find((cycle) => cycleIdentity(cycle) === selectedKey) ??
    filtered.find(isMeaningful) ??
    filtered[0] ??
    null;

  useEffect(() => {
    setPage(1);
    setRecordOpen(false);
  }, [direction, normalizedQuery, outcome, range]);

  const selectCycle = (cycle: CoordinatorCycle) => {
    setSelectedKey(cycleIdentity(cycle));
    setRecordOpen(false);
  };

  const firstShown = filtered.length === 0 ? 0 : (safePage - 1) * PAGE_SIZE + 1;
  const lastShown = Math.min(safePage * PAGE_SIZE, filtered.length);

  return (
    <main className="trace-page" data-testid="coordinator-page">
      <header className="trace-page-header">
        <div>
          <p className="trace-kicker">Operations · recorded execution</p>
          <h1>Trace history</h1>
          <p>Find what the coordinator attempted, then open the exact recorded evidence.</p>
        </div>
        <nav className="trace-view-switch" aria-label="Trace view">
          <span aria-current="page">List</span>
          <a href="/graph">Map</a>
        </nav>
      </header>

      <CoordinatorPhases activeRun={phasesRun} sourceError={phasesError} />

      <section className="trace-history" aria-labelledby="trace-history-heading">
        <div className="trace-section-heading">
          <div>
            <h2 id="trace-history-heading">Recorded cycles</h2>
            <p>
              {admitted.length} readable of {cycles.length} loaded
              {excludedCount > 0 ? ` · ${excludedCount} malformed excluded` : ""}
            </p>
          </div>
        </div>

        <div className="trace-filters" role="search">
          <label className="trace-search">
            <span>Search records</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Topic, action, outcome or exact ID"
            />
          </label>
          <label>
            <span>Range</span>
            <select aria-label="time range" value={range} onChange={(event) => setRange(event.target.value as Range)}>
              <option value="all">All recorded</option>
              <option value="today">Today</option>
              <option value="week">This week</option>
            </select>
          </label>
          <label>
            <span>Outcome</span>
            <select aria-label="outcome filter" value={outcome} onChange={(event) => setOutcome(event.target.value as OutcomeFilter)}>
              <option value="all">All outcomes</option>
              <option value="errored">Errored</option>
              <option value="passed">Passed</option>
              <option value="skipped">Skipped</option>
              <option value="pending">Pending</option>
              <option value="other">Other / unknown</option>
            </select>
          </label>
          <button type="button" aria-label="sort direction" onClick={() => setDirection((value) => (value === "newest" ? "oldest" : "newest"))}>
            {direction === "newest" ? "Newest first" : "Oldest first"}
          </button>
        </div>

        {historyError && (
          <div className="trace-notice" data-tone="error" data-testid="coordinator-error">
            <strong>{loaded ? "History refresh failed" : "Cycle history unavailable"}</strong>
            {loaded && admitted.length > 0 && <span>Showing the last loaded records.</span>}
            <details>
              <summary>Read diagnostic</summary>
              <code>{historyError}</code>
            </details>
          </div>
        )}

        {excludedCount > 0 && (
          <div className="trace-notice" data-tone="warning" data-testid="coordinator-excluded">
            {excludedCount} malformed record{excludedCount === 1 ? " was" : "s were"} excluded from this view.
          </div>
        )}

        {!loaded && !historyError && <div className="trace-empty" data-testid="coordinator-loading">Loading recorded cycles…</div>}

        {loaded && cycles.length === 0 && !historyError && (
          <div className="trace-empty" data-testid="coordinator-empty">No coordinator cycles are recorded in the loaded source.</div>
        )}

        {loaded && cycles.length > 0 && admitted.length === 0 && (
          <div className="trace-empty" data-testid="coordinator-empty">
            No readable cycle records. {excludedCount} malformed record{excludedCount === 1 ? " was" : "s were"} excluded.
          </div>
        )}

        {admitted.length > 0 && filtered.length === 0 && (
          <div className="trace-empty" data-testid="coordinator-filtered-empty">
            No loaded cycle matches these filters. Clear a filter to return to the recorded history.
          </div>
        )}

        {pageRows.length > 0 && (
          <div className="trace-cycle-list" aria-label="Cycle history results">
            {pageGroups.map((group, groupIndex) => {
              if (group.signature && group.cycles.length > 1) {
                const newest = group.cycles[0];
                const oldest = group.cycles[group.cycles.length - 1];
                return (
                  <details className="trace-noop-group" key={`${group.signature}-${groupIndex}`}>
                    <summary>
                      <span>{group.cycles.length} equivalent recorded no-ops · {text(newest.topic, "Untitled cycle")}</span>
                      <small>{shortTime(oldest.timestamp)} – {shortTime(newest.timestamp)}</small>
                    </summary>
                    <div>
                      {group.cycles.map((cycle, index) => (
                        <CycleRow
                          key={`${cycleIdentity(cycle)}-${index}`}
                          cycle={cycle}
                          selected={selected === cycle}
                          onSelect={() => selectCycle(cycle)}
                        />
                      ))}
                    </div>
                  </details>
                );
              }
              const cycle = group.cycles[0];
              return (
                <CycleRow
                  key={`${cycleIdentity(cycle)}-${groupIndex}`}
                  cycle={cycle}
                  selected={selected === cycle}
                  onSelect={() => selectCycle(cycle)}
                />
              );
            })}
          </div>
        )}

        {filtered.length > 0 && (
          <div className="trace-pagination" aria-label="Cycle history pages">
            <span>{firstShown}–{lastShown} of {filtered.length} matching · {admitted.length} readable loaded</span>
            <div>
              <button type="button" disabled={safePage <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</button>
              <span>Page {safePage} of {pageCount}</span>
              <button type="button" disabled={safePage >= pageCount} onClick={() => setPage((value) => Math.min(pageCount, value + 1))}>Next</button>
            </div>
          </div>
        )}
      </section>

      {selected && (
        <section className="trace-selected" aria-labelledby="selected-cycle-heading">
          <div className="trace-section-heading">
            <div>
              <p className="trace-kicker">Selected recorded cycle</p>
              <h2 id="selected-cycle-heading">Cycle evidence</h2>
              <p>{text(selected.run_id, "Run ID not reported")} · {actionLabel(selected)} · {outcomeFor(selected)} · exact time {timestampKey(selected) || "not reported"}</p>
            </div>
          </div>
          <div className="trace-evidence-disclosure">
            <button type="button" className="trace-disclosure-toggle" aria-expanded={recordOpen} onClick={() => setRecordOpen((value) => !value)}>
              Complete recorded cycle evidence
            </button>
            {recordOpen && <CoordinatorCycleCard cycle={selected} />}
          </div>
        </section>
      )}
    </main>
  );
}
