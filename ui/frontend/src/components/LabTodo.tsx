// LabTodo — "The lab's queue": what Nara and the PI advance on their own.
//
// Pulse's SECONDARY zone, mounted directly below the OweStrip hero. The visual
// rule is the whole point of the panel: the HUMAN's queue is the hero (big
// type, high contrast, a count that means "act"); the LAB's queue is the
// quieter zone under it. This panel never competes with the hero and never
// restates it — the human_gaps it receives render as ONE muted line pointing
// back UP at the OweStrip, never as a second todo list.
//
// One /api/lab_todo poll (ui/backend/lab_todo.py). Every number here comes
// from the apparatus's own derivations — coordinator.assess_state's gaps split
// by nara_daemon's own agent/human rule, and the idea ledger's owed tests /
// agenda / refine candidates via workers/idea_projection. Nothing is computed
// a second way in the browser.
//
// READ-ONLY, and visibly so: `refine_idea` (D-064) is a COORDINATOR action the
// planner spends budget on. The refine section names the candidates and says
// so; there is no button, because the UI does not dispatch coordinator actions.
//
// A 404 is version skew (the running :8700 binary predates the endpoint) and
// renders as the quiet EndpointMissingNote; any other failure says so out loud
// rather than rendering a calm "the lab has nothing queued" off a dead read.
import { memo } from "react";
import { Link } from "react-router-dom";
import RungGlyph from "../design/RungGlyph";
import EndpointMissingNote, { isVersionSkew404 } from "./EndpointMissingNote";
import { getLabTodo } from "../api/http";
import { usePolled } from "../api/pollhub";
import { ageLabel } from "../ladderBar";
import { useNow } from "../time";
import type {
  LabTodoOwedCluster,
  LabTodoOwedGroup,
  LabTodoRefineCandidate,
  LabTodoResponse,
  LadderAgendaItem,
} from "../types/schemas";

const LAB_TODO_ENDPOINT = "/api/lab_todo";
// The anchor the hero carries on Pulse (routes/Pulse.tsx) — the blocked-on-you
// line points back up at it instead of listing the same work again.
const OWE_HERO_ANCHOR = "#what-you-owe";
const RUNGS = ["L0", "L1", "L2", "L3", "L4", "L5"];

// Producer-owned display scalar -> renderable text (the OweStrip idiom):
// object/array drop to null, never a throw.
function asText(v: unknown): string | null {
  if (typeof v === "string") return v.trim() ? v : null;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  return null;
}

function asArray<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}

// MIRRORS ui/backend/lab_todo.py CACHE_FRESH_S (90 s). The backend serves
// this endpoint stale-while-revalidate and stamps `cache_age_s` +
// `refresh_error` on EVERY response ("stale is always legible as stale");
// past this window the payload is legibly a cached read and the panel must
// say so rather than implying a live one.
const CACHE_FRESH_S = 90;

// Self-ticking age text (adversarial-review residual fix 4, 2026-08-18):
// this panel re-renders ONLY when its payload changes (pollhub change
// detection) — a Date.now()-at-render age therefore froze at whatever
// instant the last data change happened to paint. The 30 s tick lives in
// these leaves ALONE (deliberately a local useNow, not the hub's asOf
// notify — decoupled from the pollhub work happening in parallel), so the
// owed/agenda/refine lists never re-render for a mere clock advance.
function LiveAge({ iso }: { iso: unknown }) {
  const now = useNow(30_000);
  return <>{ageLabel(iso, now)}</>;
}

// "as of Xs ago" for the backend's cache age: the server-stamped age at
// response time PLUS how long the response has sat in the hub since
// (poll.asOf). Seconds below 2 minutes — the fresh window is 90 s, so the
// interesting values are second-scale.
function CacheAge({
  serverAgeS,
  fetchedAtMs,
}: {
  serverAgeS: number;
  fetchedAtMs: number | null;
}) {
  const now = useNow(30_000);
  const total =
    serverAgeS +
    (fetchedAtMs != null ? Math.max(0, (now - fetchedAtMs) / 1000) : 0);
  const s = Math.round(total);
  const text =
    s < 120
      ? `${s}s`
      : s < 7200
        ? `${Math.floor(s / 60)}m`
        : `${Math.floor(s / 3600)}h`;
  return <>{text}</>;
}

const sectionTitle: React.CSSProperties = {
  margin: 0,
  fontSize: "var(--text-meta)",
  fontWeight: "var(--weight-semibold)",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  color: "var(--fg-muted)",
};

const emptyStyle: React.CSSProperties = {
  fontSize: "var(--text-meta)",
  color: "var(--fg-muted)",
};

export interface LabTodoProps {
  /** Fixture injection: tests render synchronously, never fetch. */
  initial?: LabTodoResponse;
  pollMs?: number;
}

function LabTodo({ initial, pollMs = 120000 }: LabTodoProps) {
  // pollhub (perf 2026-08-18). /api/lab_todo is THE slow endpoint on the
  // live backend (assess_state loads the BGE-M3 embedder + queries Chroma
  // inside the request; measured >120 s under load on 2026-08-18): the old
  // 30 s bare setInterval kept stacking concurrent requests onto it, which
  // strangled the whole backend and flipped this panel between content and
  // error — the "keeps refreshing" feeling. Now: slow cadence, in-flight
  // guard (never two concurrent reads), and SWR (a failing refetch keeps the
  // last good queue rendered, with an honest stale note).
  const poll = usePolled<LabTodoResponse>("lab_todo", getLabTodo, {
    intervalMs: pollMs,
    initialDelayMs: 250,
    enabled: initial === undefined,
  });
  const data: LabTodoResponse | null =
    initial ?? (poll.data === undefined ? null : poll.data);
  // The loud error states are reserved for "nothing ever loaded" — once the
  // queue has rendered, a failing refetch degrades to the stale note below.
  const error = poll.failing && data === null ? poll.error : null;
  const staleFailing = poll.failing && data !== null;

  const owed = asArray<LabTodoOwedGroup>(data?.owed).filter(
    (g) => g != null && typeof g === "object" && !Array.isArray(g),
  );
  const agenda = asArray<LadderAgendaItem>(data?.agenda).filter(
    (a) => a != null && typeof a === "object" && !Array.isArray(a),
  );
  const refine = asArray<LabTodoRefineCandidate>(data?.refine_candidates).filter(
    (c) => c != null && typeof c === "object" && !Array.isArray(c),
  );
  // A gap is a SENTENCE (assess_state's own words), so the coercion here is
  // stricter than asText: a stray number would render as a meaningless "42"
  // row and — worse — inflate the "N of the loop's gaps wait on you" count.
  const isGap = (g: unknown): g is string =>
    typeof g === "string" && g.trim().length > 0;
  const agentGaps = asArray<unknown>(data?.agent_gaps).filter(isGap);
  const humanGaps = asArray<unknown>(data?.human_gaps).filter(isGap);
  // Which of the two gap paths answered (rule 7: the fallback is named, not
  // silent). An unrecognized value is treated as the live case rather than
  // inventing a fourth state.
  const gapsSource = asText(data?.gaps_source);
  // Backend cache honesty (residual fix 3): lab_todo.py stamps cache_age_s
  // + refresh_error on every response. Coerced defensively — an older
  // backend binary omits both, which renders neither note.
  const cacheAgeS =
    typeof data?.cache_age_s === "number" && Number.isFinite(data.cache_age_s)
      ? data.cache_age_s
      : null;
  const refreshError = asText(data?.refresh_error);

  return (
    <section
      id="lab-queue"
      data-testid="lab-todo"
      style={{
        background: "var(--surface-1)",
        border: "1px solid var(--border-1)",
        borderRadius: "var(--radius-card)",
        padding: "var(--space-4)",
      }}
    >
      <header
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "baseline",
          gap: "var(--space-3)",
          marginBottom: "var(--space-4)",
        }}
      >
        <h2
          style={{
            margin: 0,
            // Deliberately a step BELOW the OweStrip hero's title-lg: the
            // human's queue outranks the lab's.
            fontSize: "var(--text-title)",
            fontWeight: "var(--weight-medium)",
            color: "var(--fg)",
          }}
        >
          The lab&apos;s queue
        </h2>
        <span style={{ fontSize: "var(--text-meta)", color: "var(--fg-muted)" }}>
          what Nara and the PI advance on their own — not your queue
        </span>
      </header>

      {error !== null &&
        (isVersionSkew404(error, LAB_TODO_ENDPOINT) ? (
          <EndpointMissingNote endpoint={LAB_TODO_ENDPOINT} />
        ) : (
          <div
            data-testid="lab-todo-error"
            style={{ fontSize: "var(--text-prose)", color: "var(--status-bad)" }}
          >
            {LAB_TODO_ENDPOINT} unreadable — the lab&apos;s queue is UNKNOWN,
            not empty. {String(error)}
          </div>
        ))}

      {staleFailing && (
        // Honest staleness (SWR): the sections below are the last good read,
        // named as such — never blanked by a transient refetch failure.
        <div
          data-testid="lab-todo-stale"
          style={{
            marginBottom: "var(--space-3)",
            fontSize: "var(--text-meta)",
            color: "var(--status-warn)",
          }}
        >
          refresh failing — showing the lab&apos;s queue as of{" "}
          {poll.asOf != null ? (
            <>
              <LiveAge iso={new Date(poll.asOf).toISOString()} /> ago
            </>
          ) : (
            "an unknown age"
          )}
        </div>
      )}

      {/* The backend's OWN staleness signals (residual fix 3): the endpoint
          serves stale-while-revalidate and stamps every response with its
          cache age and any failed rebuild. Both render WITH the sections
          below — a stale or refresh-failing queue is still the queue; the
          list is never blanked. */}
      {data !== null && cacheAgeS != null && cacheAgeS > CACHE_FRESH_S && (
        <div
          data-testid="lab-todo-cache-age"
          style={{ marginBottom: "var(--space-3)", ...emptyStyle }}
        >
          as of <CacheAge serverAgeS={cacheAgeS} fetchedAtMs={poll.asOf} /> ago
          — served from the backend&apos;s cache
        </div>
      )}
      {data !== null && refreshError !== null && (
        <div
          data-testid="lab-todo-refresh-error"
          style={{
            marginBottom: "var(--space-3)",
            fontSize: "var(--text-meta)",
            color: "var(--status-warn)",
          }}
        >
          refresh failing on the backend — showing its last good build:{" "}
          {refreshError}
        </div>
      )}

      {data !== null && (
        <div
          style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}
        >
          {/* ── owed tests ─────────────────────────────────────────────── */}
          <div data-testid="lab-todo-owed">
            <h3 style={sectionTitle}>Owed tests</h3>
            {owed.length === 0 ? (
              <div data-testid="lab-todo-owed-empty" style={emptyStyle}>
                no open cluster is parked on a rung
              </div>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {owed.map((group, i) => {
                  const rung = asText(group.rung) ?? "unknown";
                  const test = asText(group.test) ?? "(no test named)";
                  const clusters = asArray<LabTodoOwedCluster>(
                    group.clusters,
                  ).filter(
                    (c) => c != null && typeof c === "object" && !Array.isArray(c),
                  );
                  return (
                    <li
                      key={`${rung}-${i}`}
                      data-testid={`lab-todo-owed-${rung}`}
                      data-count={clusters.length}
                      style={{ marginTop: i === 0 ? "var(--space-2)" : "var(--space-1)" }}
                    >
                      <details>
                        <summary
                          style={{
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            gap: "var(--space-2)",
                            minHeight: "var(--row-h)",
                            fontSize: "var(--text-prose)",
                            color: "var(--fg)",
                          }}
                        >
                          {/* Off-enum rungs light nothing (RungGlyph's own
                              normalization) — never coerced onto a rung. */}
                          {RUNGS.includes(rung) && (
                            <RungGlyph level={rung} size={14} />
                          )}
                          <span
                            className="tnum"
                            style={{
                              fontFamily: "var(--font-mono)",
                              fontSize: "var(--text-meta)",
                              color: "var(--fg-muted)",
                            }}
                          >
                            {rung}
                          </span>
                          <span>
                            {clusters.length} cluster
                            {clusters.length === 1 ? "" : "s"} owe
                            {clusters.length === 1 ? "s" : ""} {test}
                          </span>
                        </summary>
                        <ul
                          style={{
                            listStyle: "none",
                            margin: "var(--space-1) 0 0",
                            padding: "0 0 0 var(--space-6)",
                            display: "flex",
                            flexDirection: "column",
                            gap: "var(--space-1)",
                          }}
                        >
                          {clusters.map((c, j) => {
                            const cid = asText(c.cluster_id);
                            const stem = asText(c.stem);
                            return (
                              <li
                                key={`${cid ?? "cluster"}-${j}`}
                                style={{
                                  fontSize: "var(--text-meta)",
                                  color: "var(--fg-muted)",
                                }}
                              >
                                <Link
                                  to="/ladder"
                                  style={{
                                    fontFamily: "var(--font-mono)",
                                    color: "var(--accent)",
                                  }}
                                >
                                  {cid ?? "(no id)"}
                                </Link>
                                {stem && <span> · {stem}</span>}
                              </li>
                            );
                          })}
                        </ul>
                      </details>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {/* ── agenda ─────────────────────────────────────────────────── */}
          <div data-testid="lab-todo-agenda">
            <h3 style={sectionTitle}>Agenda</h3>
            {agenda.length === 0 ? (
              <div data-testid="lab-todo-agenda-empty" style={emptyStyle}>
                nothing queued
              </div>
            ) : (
              <ul
                style={{
                  listStyle: "none",
                  margin: "var(--space-2) 0 0",
                  padding: 0,
                  display: "flex",
                  flexDirection: "column",
                  gap: "var(--space-1)",
                }}
              >
                {agenda.map((item, i) => {
                  const topic = asText(item.topic) ?? "(untitled topic)";
                  const source = asText(item.source);
                  const cid = asText(item.cluster_id);
                  return (
                    <li
                      key={`${cid ?? "agenda"}-${i}`}
                      data-testid={`lab-todo-agenda-${i}`}
                      style={{
                        display: "flex",
                        flexWrap: "wrap",
                        alignItems: "baseline",
                        gap: "var(--space-2)",
                        fontSize: "var(--text-prose)",
                        color: "var(--fg)",
                      }}
                    >
                      <span>{topic}</span>
                      {source && (
                        <span
                          style={{
                            fontSize: "var(--text-meta)",
                            color: "var(--fg-muted)",
                          }}
                        >
                          source: {source}
                        </span>
                      )}
                      {cid && (
                        <Link
                          to="/ladder"
                          style={{
                            fontFamily: "var(--font-mono)",
                            fontSize: "var(--text-meta)",
                            color: "var(--accent)",
                          }}
                        >
                          {cid}
                        </Link>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {/* ── refine candidates ──────────────────────────────────────── */}
          <div data-testid="lab-todo-refine">
            <h3 style={sectionTitle}>Refine candidates</h3>
            {refine.length === 0 ? (
              <div data-testid="lab-todo-refine-empty" style={emptyStyle}>
                no killed cluster is still improvable
              </div>
            ) : (
              <>
                <div
                  data-testid="lab-todo-refine-count"
                  style={{
                    marginTop: "var(--space-2)",
                    fontSize: "var(--text-prose)",
                    color: "var(--fg)",
                  }}
                >
                  {refine.length} killed cluster{refine.length === 1 ? "" : "s"}{" "}
                  a refine cycle could still improve
                </div>
                <ul
                  style={{
                    listStyle: "none",
                    margin: "var(--space-1) 0 0",
                    padding: 0,
                    display: "flex",
                    flexWrap: "wrap",
                    gap: "var(--space-1) var(--space-3)",
                  }}
                >
                  {refine.map((c, i) => {
                    const cid = asText(c.cluster_id);
                    const code = asText(c.kill_code);
                    return (
                      <li
                        key={`${cid ?? "refine"}-${i}`}
                        data-testid={`lab-todo-refine-${i}`}
                        style={{
                          fontSize: "var(--text-meta)",
                          color: "var(--fg-muted)",
                        }}
                        title={asText(c.stem) ?? undefined}
                      >
                        <Link
                          to="/ladder"
                          style={{
                            fontFamily: "var(--font-mono)",
                            color: "var(--accent)",
                          }}
                        >
                          {cid ?? "(no id)"}
                        </Link>
                        {code && <span> · {code}</span>}
                      </li>
                    );
                  })}
                </ul>
              </>
            )}
            <div
              data-testid="lab-todo-refine-note"
              style={{ marginTop: "var(--space-2)", ...emptyStyle }}
            >
              refine_idea is a coordinator action (cost 2) — the planner spends
              a slot on it. This surface does not trigger it.
            </div>
          </div>

          {/* ── the coordinator's own gap list ─────────────────────────── */}
          {/* assess_state's words, verbatim: the sentences the planner plans
              from. Muted, and last, because the sections above are the same
              facts in a form you can act on. */}
          <div data-testid="lab-todo-gaps">
            <h3 style={sectionTitle}>On the coordinator&apos;s list</h3>
            {gapsSource === "unavailable" ? (
              // NOT the idle state: the backend could neither read assess_state
              // nor find a cycle that recorded its gaps. Unknown, not empty.
              <div
                data-testid="lab-todo-gaps-unknown"
                style={{ ...emptyStyle, color: "var(--status-warn)" }}
              >
                gaps UNKNOWN — no coordinator read and no cycle has recorded
                one on this backend
              </div>
            ) : agentGaps.length === 0 ? (
              <div data-testid="lab-todo-gaps-empty" style={emptyStyle}>
                no agent-actionable gap — the loop is honestly idle
              </div>
            ) : (
              <ul
                style={{
                  listStyle: "none",
                  margin: "var(--space-2) 0 0",
                  padding: 0,
                  display: "flex",
                  flexDirection: "column",
                  gap: "var(--space-1)",
                  ...emptyStyle,
                }}
              >
                {agentGaps.map((gap, i) => (
                  <li key={`${gap}-${i}`} data-testid={`lab-todo-gap-${i}`}>
                    {gap}
                  </li>
                ))}
              </ul>
            )}
            {gapsSource === "last_cycle" && (
              // The gaps came from the last cycle's PERSISTED planner_state,
              // not a live read (the production backend cannot import the
              // coordinator). Say so, and date it — never imply "live".
              <div
                data-testid="lab-todo-gaps-asof"
                style={{ marginTop: "var(--space-1)", ...emptyStyle }}
              >
                as of the coordinator&apos;s last cycle,{" "}
                <LiveAge iso={data?.gaps_as_of} /> ago — not a live read
              </div>
            )}
          </div>

          {/* ── blocked on you (ONE line, pointing at the hero) ─────────── */}
          {humanGaps.length > 0 && (
            <div
              data-testid="lab-todo-blocked"
              style={{
                paddingTop: "var(--space-3)",
                borderTop: "1px solid var(--border-1)",
                ...emptyStyle,
              }}
            >
              {humanGaps.length} of the loop&apos;s gaps wait on you — see{" "}
              <a href={OWE_HERO_ANCHOR} style={{ color: "var(--fg-muted)" }}>
                what you owe
              </a>{" "}
              above.
            </div>
          )}
        </div>
      )}
    </section>
  );
}

// Memoized: mounted directly on Pulse, which re-renders on clock/telemetry
// ticks; this panel's props (fixture-injection only) never change on those.
export default memo(LabTodo);
