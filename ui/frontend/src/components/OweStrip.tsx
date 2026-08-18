// OweStrip — Pulse's HERO (revamp R3): the human's real queue, and the first
// thing read on the page. ONE /api/human_todo poll, filtered to what the human
// actually OWES under the 2026-08 selection-before-the-human inversion (D-059):
// blocking decisions (gate_verdict + state_gate families) and finding_review
// items that CLEAR the evidence-ladder bar (L4/L5 — shared logic in
// src/ladderBar.ts). Rows link into the dossier reader (/dossier/:id).
//
// THE DEMOTED MASS IS NOT A QUEUE. Findings that did not clear the bar render
// as ONE muted one-liner ("N below-bar findings demoted to the ladder", linking
// to /ladder) — never as rows, never as a count the human could read as work.
// That line is derived CLIENT-SIDE from the same /api/human_todo items: the
// backend's `surfaced_below_bar` counter exists only in-memory in
// orchestrator/coordinator.py's assess_state() and is not on any wire today, so
// deriving it is the only honest option (see the R3 ui_plan entry).
//
// A 404 from the endpoint is an HONEST "queue UNKNOWN" — never a calm empty
// state off a dead endpoint.
import { memo, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import RungGlyph from "../design/RungGlyph";
import StatusDot from "../design/StatusDot";
import "../design/primitives.css";
import { getHumanTodo } from "../api/http";
import { usePolled } from "../api/pollhub";
import { ageLabel, clearsLadderBar, evidenceLevelOf } from "../ladderBar";
import { useNow } from "../time";
import type { HumanTodoItem, HumanTodoResponse } from "../types/schemas";

// Coerce a producer-owned display scalar to renderable text (the
// HumanTodoPanel idiom): object/array drop to null, never a throw.
function asText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  if (typeof v === "boolean") return String(v);
  return null;
}

// The owed kinds, folded across both label generations (the backend emits
// state_gate; the older TS union spelled it state_file_gate).
function isBlockingKind(kind: string | null): boolean {
  return (
    kind === "gate_verdict" ||
    kind === "state_gate" ||
    kind === "state_file_gate"
  );
}

function owed(item: HumanTodoItem): boolean {
  const kind = asText(item.kind);
  if (isBlockingKind(kind)) return true;
  return kind === "finding_review" && clearsLadderBar(item);
}

// Self-ticking age text (adversarial-review residual fix 4, 2026-08-18):
// under the pollhub's change detection + this strip's memo, the component
// re-renders ONLY when the queue payload changes — a Date.now()-at-render
// age therefore froze at the last data change ("2m" forever on an idle
// backend). The 30 s tick lives in this LEAF alone: a setState here
// re-renders just the age text, never the row list around it, so the rows
// stay effectively memoized against clock advances with no extra memo()
// plumbing. Deliberately a local useNow, not the hub's asOf notify —
// decoupled from the parallel pollhub work.
function LiveAge({ iso }: { iso: unknown }) {
  const now = useNow(30_000);
  return <>{ageLabel(iso, now)}</>;
}

interface Props {
  // Fixture injection (tests render synchronously, never fetch).
  initial?: HumanTodoItem[];
  pollMs?: number;
}

function OweStrip({ initial, pollMs = 30000 }: Props) {
  // pollhub (perf 2026-08-18): in-flight-guarded, change-detected, SWR — a
  // transient refetch failure keeps the last good queue rendered (with an
  // honest stale note below) instead of swapping the hero for an error line.
  const poll = usePolled<HumanTodoResponse>("human_todo", getHumanTodo, {
    intervalMs: pollMs,
    enabled: initial === undefined,
  });
  const items: HumanTodoItem[] =
    initial ?? (Array.isArray(poll.data?.items) ? poll.data.items : []);
  const loaded = initial !== undefined || poll.data !== undefined;
  // The red/404 error states are reserved for "no data at all" — once a
  // queue has rendered, a failing refetch is the muted stale note instead.
  const error =
    poll.failing && poll.data === undefined && initial === undefined
      ? String(poll.error)
      : null;
  const staleFailing = poll.failing && poll.data !== undefined;

  // Producer-owned rows: drop non-object entries (HumanTodoPanel idiom).
  const rows = (Array.isArray(items) ? items : []).filter(
    (it): it is HumanTodoItem =>
      typeof it === "object" && it !== null && !Array.isArray(it),
  );
  const owedRows = rows.filter(owed);

  // The demoted mass: finding rows that did NOT clear the bar. Counted so the
  // human knows it exists, rendered as information — not as work.
  const belowBar = rows.filter(
    (it) => asText(it.kind) === "finding_review" && !clearsLadderBar(it),
  ).length;

  const endpointMissing = error !== null && /\b404\b/.test(error);

  return (
    <section
      data-testid="owe-strip"
      style={{
        background: "var(--surface-1)",
        border: "1px solid var(--border-1)",
        borderRadius: "var(--radius-card)",
        padding: "var(--space-5)",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: "var(--space-3)",
          marginBottom: "var(--space-4)",
        }}
      >
        <h2
          style={{
            margin: 0,
            fontSize: "var(--text-title-lg)",
            fontWeight: "var(--weight-semibold)",
            color: "var(--fg)",
          }}
        >
          What you owe
        </h2>
        <span style={{ fontSize: "var(--text-meta)", color: "var(--fg-muted)" }}>
          gate verdicts + findings that cleared L4
        </span>
        <span
          data-testid="owe-count"
          className="tnum"
          style={{
            marginLeft: "auto",
            fontSize: "var(--text-title-lg)",
            fontWeight: "var(--weight-semibold)",
            color: owedRows.length > 0 ? "var(--status-warn)" : "var(--fg-muted)",
          }}
        >
          {owedRows.length}
        </span>
      </header>

      {error &&
        (endpointMissing ? (
          // Honest 404 state: the queue SOURCE is missing — say so, never
          // render the calm "you owe nothing" off a dead endpoint.
          <div
            data-testid="owe-error"
            style={{ fontSize: "var(--text-prose)", color: "var(--status-warn)" }}
          >
            /api/human_todo returned 404 — the queue is UNKNOWN, not empty.
          </div>
        ) : (
          <div
            data-testid="owe-error"
            style={{ fontSize: "var(--text-prose)", color: "var(--status-bad)" }}
          >
            {error}
          </div>
        ))}

      {loaded && !error && owedRows.length === 0 && (
        <div
          data-testid="owe-empty"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--space-3)",
            fontSize: "var(--text-prose-lg)",
            color: "var(--fg)",
          }}
        >
          <StatusDot status="ok" label="unblocked" />
          Nothing owed — the loop is unblocked.
        </div>
      )}

      {owedRows.length > 0 && (
        <ul
          style={{
            listStyle: "none",
            margin: 0,
            padding: 0,
            display: "flex",
            flexDirection: "column",
            gap: "var(--space-1)",
          }}
        >
          {owedRows.map((item, i) => {
            const id = asText(item.id);
            const kind = asText(item.kind) ?? "unknown";
            const title = asText(item.title) ?? id ?? "(untitled)";
            const level = evidenceLevelOf(item);
            const blocking = isBlockingKind(kind);
            const body = (
              <>
                <StatusDot
                  status={blocking ? "bad" : "ok"}
                  label={blocking ? "blocking" : "clears the bar"}
                />
                {level && <RungGlyph level={level} size={14} />}
                <span
                  style={{
                    fontSize: "var(--text-prose)",
                    fontWeight: "var(--weight-medium)",
                    color: "var(--fg)",
                  }}
                >
                  {title}
                </span>
                {level && (
                  <span
                    className="tnum"
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: "var(--text-meta)",
                      color: "var(--status-ok)",
                    }}
                  >
                    {level}
                  </span>
                )}
                <span
                  style={{
                    fontSize: "var(--text-meta)",
                    color: "var(--fg-muted)",
                  }}
                >
                  {kind}
                </span>
                <span
                  className="tnum"
                  style={{
                    marginLeft: "auto",
                    fontFamily: "var(--font-mono)",
                    fontSize: "var(--text-meta)",
                    color: "var(--fg-muted)",
                  }}
                >
                  <LiveAge iso={item.since} />
                </span>
              </>
            );
            const rowStyle: CSSProperties = {
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              gap: "var(--space-3)",
              minHeight: "var(--row-h)",
              paddingInline: "var(--space-3)",
              borderRadius: "var(--radius-control)",
              textDecoration: "none",
            };
            return (
              <li key={`${id ?? "owe"}-${i}`} data-testid={`owe-row-${i}`}>
                {id ? (
                  <Link
                    to={`/dossier/${encodeURIComponent(id)}`}
                    className="dsn-row dsn-row--interactive"
                    style={rowStyle}
                  >
                    {body}
                  </Link>
                ) : (
                  // No usable id — still listed (it still needs the human),
                  // just not linkable.
                  <div className="dsn-row" style={rowStyle}>
                    {body}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {belowBar > 0 && !error && (
        // INFORMATION, not a queue: one muted line, no count badge, no rows.
        <div
          data-testid="owe-below-bar"
          style={{
            marginTop: "var(--space-4)",
            fontSize: "var(--text-meta)",
            color: "var(--fg-muted)",
          }}
        >
          {belowBar} below-bar finding{belowBar === 1 ? "" : "s"} demoted to the{" "}
          <Link to="/ladder" style={{ color: "var(--fg-muted)" }}>
            ladder
          </Link>
        </div>
      )}

      {staleFailing && (
        // Honest staleness: the queue above is real data from the last good
        // read; this names its age instead of pretending freshness OR
        // blanking the hero.
        <div
          data-testid="owe-stale"
          style={{
            marginTop: "var(--space-3)",
            fontSize: "var(--text-meta)",
            color: "var(--status-warn)",
          }}
        >
          refresh failing — showing the queue as of{" "}
          {poll.asOf != null ? (
            <>
              <LiveAge iso={new Date(poll.asOf).toISOString()} /> ago
            </>
          ) : (
            "an unknown age"
          )}
        </div>
      )}
    </section>
  );
}

// Memoized: Pulse re-renders on its clock and telemetry ticks; this strip's
// props (fixture-injection only) never change on those.
export default memo(OweStrip);
