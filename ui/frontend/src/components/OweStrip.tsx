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
import { useEffect, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import RungGlyph from "../design/RungGlyph";
import StatusDot from "../design/StatusDot";
import "../design/primitives.css";
import { getHumanTodo } from "../api/http";
import { ageLabel, clearsLadderBar, evidenceLevelOf } from "../ladderBar";
import type { HumanTodoItem } from "../types/schemas";

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

interface Props {
  // Fixture injection (tests render synchronously, never fetch).
  initial?: HumanTodoItem[];
  pollMs?: number;
}

export default function OweStrip({ initial, pollMs = 10000 }: Props) {
  const [items, setItems] = useState<HumanTodoItem[]>(initial ?? []);
  const [loaded, setLoaded] = useState(initial !== undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getHumanTodo()
        .then((r) => {
          if (!active) return;
          setItems(Array.isArray(r?.items) ? r.items : []);
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
  const nowMs = Date.now();

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
                  {ageLabel(item.since, nowMs)}
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
    </section>
  );
}
