// Ladder (/ladder) — "what's cooking" (UI simplification S1). The reduced
// idea-ledger state off GET /api/ladder (ui/backend/ladder.py runs the REAL
// reducer, workers/idea_ledger.py): counts header, a pure-div per-rung
// histogram labeled with the next test owed, status/rung filter chips, the
// cluster table (killed rows expand to their kill code + evidence-keyed
// reopening condition), and the open agenda. /ideas folds in here: the
// ideas.md markdown render (GET /api/ideas) is this page's FALLBACK body —
// shown when the backend predates /api/ladder (404 = version skew →
// EndpointMissingNote) or the ledger has never been written (204 → honest
// "no idea ledger yet"). Read-only throughout; nothing here is editable.
import { useEffect, useState } from "react";
import EndpointMissingNote, {
  isVersionSkew404,
} from "../components/EndpointMissingNote";
import MiniMarkdown from "../components/MiniMarkdown";
import { getIdeas, getLadder } from "../api/http";
import { ageLabel } from "../ladderBar";
import type {
  LadderCluster,
  LadderResponse,
} from "../types/schemas";

const LADDER_ENDPOINT = "/api/ladder";
// L5 first — the page reads top-of-ladder down, like the inbox histogram.
const LEVELS_DESC = ["L5", "L4", "L3", "L2", "L1", "L0"];
const STATUSES = ["open", "surfaced", "killed"] as const;

function asText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  if (typeof v === "boolean") return String(v);
  return null;
}

function asCount(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) && v >= 0
    ? Math.floor(v)
    : 0;
}

const STATUS_TONE: Record<string, string> = {
  open: "text-zinc-300",
  surfaced: "text-emerald-400",
  killed: "text-rose-400",
};

function statusTone(status: string): string {
  return Object.prototype.hasOwnProperty.call(STATUS_TONE, status)
    ? STATUS_TONE[status]
    : "text-zinc-500";
}

// One cluster row. Killed rows expand (<details>) to the kill detail +
// reopening condition; live rows are plain.
function ClusterRow({ c, nowMs }: { c: LadderCluster; nowMs: number }) {
  const stem = asText(c.stem) ?? asText(c.cluster_id) ?? "(unnamed)";
  const status = asText(c.status) ?? "unknown";
  const level = asText(c.evidence_level) ?? "—";
  const members = asCount(c.member_count);
  const agendaOpen = asCount(c.open_agenda_count);
  const killed = status === "killed";

  const head = (
    <>
      <span className="font-mono text-[10px] text-zinc-600">{level}</span>
      <span className="text-zinc-200">{stem}</span>
      <span className={`text-[10px] uppercase tracking-wide ${statusTone(status)}`}>
        {status}
      </span>
      {members > 0 && (
        <span className="text-[10px] text-zinc-600">
          {members} member{members === 1 ? "" : "s"}
        </span>
      )}
      {agendaOpen > 0 && (
        <span className="text-[10px] text-sky-400">{agendaOpen} agenda</span>
      )}
      <span className="ml-auto font-mono text-[10px] text-zinc-500">
        {ageLabel(c.last_event_ts, nowMs)}
      </span>
    </>
  );

  if (!killed) {
    return (
      <li
        data-testid={`ladder-cluster-${asText(c.cluster_id) ?? "unknown"}`}
        className="flex flex-wrap items-baseline gap-2 rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5 text-xs"
      >
        {head}
      </li>
    );
  }

  const kill =
    c.kill_reason != null &&
    typeof c.kill_reason === "object" &&
    !Array.isArray(c.kill_reason)
      ? c.kill_reason
      : null;
  const reopen =
    c.reopening_condition != null &&
    typeof c.reopening_condition === "object" &&
    !Array.isArray(c.reopening_condition)
      ? c.reopening_condition
      : null;
  return (
    <li data-testid={`ladder-cluster-${asText(c.cluster_id) ?? "unknown"}`}>
      <details className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5 text-xs">
        <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-2">
          {head}
        </summary>
        <div
          className="mt-1.5 space-y-0.5 border-t border-zinc-800/60 pt-1.5 text-[11px]"
          data-testid="ladder-kill-detail"
        >
          <div>
            <span className="text-zinc-500">killed: </span>
            <span className="font-mono text-rose-400">
              {asText(kill?.code) ?? "unspecified"}
            </span>
            {asText(kill?.detail) && (
              <span className="text-zinc-400"> — {asText(kill?.detail)}</span>
            )}
          </div>
          <div>
            <span className="text-zinc-500">reopen when: </span>
            <span className="text-zinc-300">
              {asText(reopen?.evidence_kind) ??
                asText(reopen?.requires) ??
                "none recorded"}
            </span>
          </div>
        </div>
      </details>
    </li>
  );
}

// The /ideas fallback body (the old routes/Ideas.tsx render, folded in).
function IdeasFallback({ initial }: { initial?: string | null }) {
  const [markdown, setMarkdown] = useState<string | null>(initial ?? null);
  const [loaded, setLoaded] = useState(initial !== undefined);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    getIdeas()
      .then((resp) => {
        if (!active) return;
        setMarkdown(
          resp !== null && typeof resp.markdown === "string"
            ? resp.markdown
            : null,
        );
        setLoaded(true);
      })
      .catch(() => {
        /* the fallback is best-effort — the note above carries the state */
      });
    return () => {
      active = false;
    };
  }, [initial]);

  if (!loaded || markdown === null) return null;
  return (
    <div
      className="mt-3 rounded border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="ladder-ideas-fallback"
    >
      <div className="mb-2 text-[10px] uppercase tracking-wide text-zinc-600">
        ideas.md projection (fallback)
      </div>
      <MiniMarkdown source={markdown} />
    </div>
  );
}

interface Props {
  // Fixture overrides for tests: `initial` undefined = fetch live; null =
  // the 204 no-ledger state; an object = the payload. `initialIdeas` feeds
  // the fallback body the same way (null = absent ideas.md).
  initial?: LadderResponse | null;
  initialIdeas?: string | null;
  pollMs?: number;
}

export default function Ladder({ initial, initialIdeas, pollMs = 30_000 }: Props) {
  const [data, setData] = useState<LadderResponse | null>(initial ?? null);
  const [loaded, setLoaded] = useState(initial !== undefined);
  const [skew, setSkew] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [rungFilter, setRungFilter] = useState<string | null>(null);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getLadder()
        .then((resp) => {
          if (!active) return;
          setData(resp);
          setLoaded(true);
          setSkew(false);
          setError(null);
        })
        .catch((e) => {
          if (!active) return;
          if (isVersionSkew404(e, LADDER_ENDPOINT)) {
            // Older backend binary without the endpoint — quiet note + the
            // ideas.md fallback body, never red.
            setSkew(true);
            setError(null);
          } else {
            setError(String(e));
          }
        });
    load();
    const id = setInterval(load, Math.max(5_000, pollMs));
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [initial, pollMs]);

  const nowMs = Date.now();

  // Producer-owned payload guards.
  const clusters = (Array.isArray(data?.clusters) ? data.clusters : []).filter(
    (c): c is LadderCluster =>
      c != null && typeof c === "object" && !Array.isArray(c),
  );
  const histogram =
    data?.histogram != null &&
    typeof data.histogram === "object" &&
    !Array.isArray(data.histogram)
      ? data.histogram
      : {};
  const nextOwed =
    data?.next_owed != null &&
    typeof data.next_owed === "object" &&
    !Array.isArray(data.next_owed)
      ? data.next_owed
      : {};
  const agenda = (Array.isArray(data?.agenda) ? data.agenda : []).filter(
    (a) => a != null && typeof a === "object" && !Array.isArray(a),
  );
  const counts = {
    open: asCount(data?.counts?.open),
    surfaced: asCount(data?.counts?.surfaced),
    killed: asCount(data?.counts?.killed),
  };
  const maxRung = Math.max(
    1,
    ...LEVELS_DESC.map((l) => asCount(histogram[l])),
  );

  const visible = clusters.filter((c) => {
    if (statusFilter !== null && asText(c.status) !== statusFilter) return false;
    if (rungFilter !== null && asText(c.evidence_level) !== rungFilter)
      return false;
    return true;
  });

  const chip = (active: boolean) =>
    `rounded border px-2 py-0.5 text-[10px] uppercase tracking-wide ${
      active
        ? "border-emerald-700 bg-emerald-950/40 text-emerald-300"
        : "border-zinc-700 text-zinc-400 hover:bg-zinc-800"
    }`;

  return (
    <div className="mx-auto max-w-5xl p-5" data-testid="ladder-page">
      <header className="mb-3">
        <h1 className="text-sm font-semibold uppercase tracking-wide text-zinc-300">
          /ladder · evidence ladder
        </h1>
        <p className="mt-0.5 text-[11px] text-zinc-500">
          The idea ledger reduced (memory/idea_ledger.jsonl — append-only;
          every state below is a deterministic reduction). Only L4+ surfaces
          to you (D-059); everything else is the machine&apos;s to advance or
          kill.
        </p>
      </header>

      {error !== null && (
        <div className="text-xs text-red-400" data-testid="ladder-error">
          {error}
        </div>
      )}

      {skew && (
        <>
          <EndpointMissingNote endpoint={LADDER_ENDPOINT} />
          <IdeasFallback initial={initialIdeas} />
        </>
      )}

      {!skew && error === null && loaded && data === null && (
        <>
          <div className="text-sm text-zinc-500" data-testid="ladder-empty">
            no idea ledger yet — memory/idea_ledger.jsonl has not been written
            on this checkout.
          </div>
          <IdeasFallback initial={initialIdeas} />
        </>
      )}

      {!skew && error === null && data !== null && (
        <>
          {/* Counts header. */}
          <div
            className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs"
            data-testid="ladder-counts-header"
          >
            <span className="text-zinc-300">{counts.open} open</span>
            <span className="text-emerald-400">
              {counts.surfaced} surfaced
            </span>
            <span className="text-rose-400">{counts.killed} killed</span>
            <span className="text-zinc-600">
              {clusters.length} cluster{clusters.length === 1 ? "" : "s"} total
            </span>
          </div>

          {/* Pure-div rung histogram, labeled with the next test owed. */}
          <div className="mt-3 space-y-1" data-testid="ladder-histogram">
            {LEVELS_DESC.map((level) => {
              const n = asCount(histogram[level]);
              const owedLabel = asText(nextOwed[level]);
              return (
                <div
                  key={level}
                  className="flex items-center gap-2 text-[11px]"
                  data-testid={`ladder-rung-${level}`}
                >
                  <span className="w-6 font-mono text-zinc-400">{level}</span>
                  <div className="w-40 shrink-0 rounded bg-zinc-900">
                    <div
                      className={`h-2.5 rounded ${n > 0 ? "bg-emerald-700" : "bg-zinc-800"}`}
                      style={{ width: `${Math.max(4, (n / maxRung) * 100)}%` }}
                      aria-hidden
                    />
                  </div>
                  <span className="w-6 text-right font-mono text-zinc-300">
                    {n}
                  </span>
                  {owedLabel && (
                    <span
                      className="truncate text-zinc-600"
                      title={owedLabel}
                    >
                      next: {owedLabel}
                    </span>
                  )}
                </div>
              );
            })}
          </div>

          {/* Filter chips: status + rung, each toggling (click again = all). */}
          <div
            className="mt-3 flex flex-wrap items-center gap-1.5"
            data-testid="ladder-filters"
          >
            {STATUSES.map((s) => (
              <button
                key={s}
                type="button"
                data-testid={`ladder-filter-${s}`}
                aria-pressed={statusFilter === s}
                onClick={() => setStatusFilter((v) => (v === s ? null : s))}
                className={chip(statusFilter === s)}
              >
                {s}
              </button>
            ))}
            <span className="mx-1 text-zinc-700">·</span>
            {LEVELS_DESC.map((l) => (
              <button
                key={l}
                type="button"
                data-testid={`ladder-filter-${l}`}
                aria-pressed={rungFilter === l}
                onClick={() => setRungFilter((v) => (v === l ? null : l))}
                className={chip(rungFilter === l)}
              >
                {l}
              </button>
            ))}
          </div>

          {/* Cluster table. */}
          <ul className="mt-2 space-y-1.5" data-testid="ladder-clusters">
            {visible.map((c, i) => (
              <ClusterRow
                key={asText(c.cluster_id) ?? `idx-${i}`}
                c={c}
                nowMs={nowMs}
              />
            ))}
          </ul>
          {visible.length === 0 && (
            <div
              className="mt-2 text-xs text-zinc-500"
              data-testid="ladder-no-match"
            >
              no clusters match the active filters.
            </div>
          )}

          {/* Agenda — open topics with provenance. */}
          <section className="mt-5" data-testid="ladder-agenda">
            <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
              Agenda
            </h2>
            {agenda.length === 0 ? (
              <div className="mt-1 text-xs text-zinc-600">
                no open agenda items.
              </div>
            ) : (
              <ul className="mt-1 space-y-1">
                {agenda.map((a, i) => (
                  <li
                    key={`${asText(a.cluster_id) ?? "agenda"}-${i}`}
                    className="flex flex-wrap items-baseline gap-2 text-xs"
                  >
                    <span className="text-zinc-200">
                      {asText(a.topic) ?? "(untitled)"}
                    </span>
                    <span className="text-[10px] text-zinc-500">
                      source: {asText(a.source) ?? "unknown"}
                    </span>
                    <span className="font-mono text-[10px] text-zinc-600">
                      {asText(a.cluster_id) ?? ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
