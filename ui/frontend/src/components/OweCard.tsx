// OweCard — Pulse's HERO, redesigned (owner ask 2026-08-18: the owed queue
// was "REALLY verbose", mixed 70-day-old fossils with live asks, and never
// said what an approval actually DOES; second pass same day: "the text and
// font is all over the place" — the full hypothesis + stats blob rendered as
// a row's TITLE).
//
// Typography contract (owner polish 2026-08-18, ONE type scale):
//   row title     14px/600, the SHORT claim head — first sentence of the
//                 title, ~120 chars — clamped to 2 lines; the full text
//                 lives in WHAT YOU'RE DOING, never in the header
//   section label 11px uppercase letter-spaced muted — IDENTICAL for all
//                 five sections (DOING / VET / MEANS / WHY / RESOLVE)
//   body          13px regular normal-case
//   mono          ONLY ids, metrics, and the resolve command (one line,
//                 expand on click, with a copy affordance)
//   chips         one size (10px caps): declarative statements — "LIKELY
//                 SUPERSEDED", never a question mark — plus the age chip
//                 (amber >14d, rose >45d); tone colors kept
// Reading order per row: title -> chips (triage + age) -> WHAT YOU'RE DOING
// -> VET FIRST -> WHAT APPROVAL MEANS -> WHY THE TAG (collapsed by default;
// the triage_reason runs long) -> RESOLVE. Vertical rhythm rides one
// spacing token (--space-3 between sections, --space-1 label-to-content).
//
// The derived fields (`action`/`doing`/`approval_means`/`vet`/`triage`/
// `triage_reason`) are computed SERVER-SIDE in backend/owe_triage.py from the
// same stores the queue is composed from — the heuristics are documented
// there and NEVER auto-dismiss: a "LIKELY SUPERSEDED" tag is information for
// the human, who alone closes items. Since 2026-08-18 #2 the backend's
// human_todo._point_gate_verdicts sharpens gate_verdict items' three answers
// into record-joined, item-specific copy (hypothesis + experiment + cluster;
// real verdict consequences; pointed probes with values inline) — this card
// just renders whatever the server derived. Against an older backend the
// card falls back to kind-generic phrasing (endpoint-skew discipline).
//
// Inherited pins from OweStrip (R3), unchanged: only blocking kinds
// (gate_verdict + state_gate families) and L4/L5 findings render; the
// below-bar mass is ONE muted line, never a queue; a 404 is an HONEST
// "queue UNKNOWN"; a failing refetch keeps the last good queue with a stale
// note. Shares OweStrip's testids (owe-strip / owe-count / owe-empty /
// owe-error / owe-below-bar / owe-stale) — the Pulse-level pins carry over.
import { memo, useState, type CSSProperties } from "react";
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

// Producer-owned string array (the `vet` bullets): keep only string members.
function asStrings(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v.filter((x): x is string => typeof x === "string" && x.length > 0);
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

// Short claim head (owner feedback 2026-08-18: the full hypothesis + stats
// blob rendered as the TITLE). First sentence of the title, capped ~120
// chars — the CSS 2-line clamp on the title span is the backstop for
// un-sentenced walls. The full text still reaches the reader through
// WHAT YOU'RE DOING.
const TITLE_HEAD_MAX = 120;
function claimHead(text: string): string {
  const compact = text.replace(/\s+/g, " ").trim();
  const sentence = compact.match(/^.*?[.!?](?=\s|$)/);
  let head = sentence ? sentence[0] : compact;
  if (head.length > TITLE_HEAD_MAX) {
    head = head.slice(0, TITLE_HEAD_MAX - 1).trimEnd() + "…";
  }
  return head;
}

// --- endpoint-skew fallbacks: an older backend has no derived fields -------

function actionPhrase(item: HumanTodoItem): string {
  const fromServer = asText(item.action);
  if (fromServer) return fromServer;
  const kind = asText(item.kind);
  const id = asText(item.id) ?? "(no id)";
  if (kind === "state_gate" || kind === "state_file_gate")
    return `Clear blocking human gate '${id}'`;
  if (kind === "gate_verdict") return `Record a gate verdict on ${id}`;
  if (kind === "finding_review") return `Review + disposition finding ${id}`;
  return `Resolve ${id}`;
}

function fallbackMeans(kind: string | null): string {
  if (kind === "gate_verdict")
    return "Your verdict is appended to loop_feedback.jsonl (last-row-wins) — the iteration stops counting as pending.";
  if (kind === "state_gate" || kind === "state_file_gate")
    return "The entry is removed from run_state/week1.state.json human_gates_pending and the halted work resumes.";
  if (kind === "finding_review")
    return "A status row is appended to surfaced_findings.status.jsonl — the finding leaves the review queue.";
  return "See the resolve command — it names the exact state change.";
}

// --- age chip: amber past 14 days, rose past 45 ----------------------------

const AMBER_AFTER_DAYS = 14;
const ROSE_AFTER_DAYS = 45;

type AgeTone = "fresh" | "amber" | "rose";

function ageTone(sinceIso: unknown, nowMs: number): AgeTone {
  const s = asText(sinceIso);
  if (!s) return "fresh"; // unknown age renders "—", never a false alarm
  const t = Date.parse(s);
  if (Number.isNaN(t)) return "fresh";
  const days = (nowMs - t) / 86_400_000;
  if (days > ROSE_AFTER_DAYS) return "rose";
  if (days > AMBER_AFTER_DAYS) return "amber";
  return "fresh";
}

const AGE_TONE_COLOR: Record<AgeTone, string> = {
  fresh: "var(--fg-muted)",
  amber: "var(--status-warn)",
  rose: "var(--status-bad)",
};

// --- ONE type scale (owner polish 2026-08-18) -------------------------------

// Row title: 14px/600, clamped to 2 lines — never a wall in the header.
const titleStyle: CSSProperties = {
  fontSize: "14px",
  fontWeight: 600,
  color: "var(--fg)",
  lineHeight: 1.35,
  display: "-webkit-box",
  WebkitLineClamp: 2,
  WebkitBoxOrient: "vertical",
  overflow: "hidden",
  overflowWrap: "anywhere",
};

// Section label: 11px caps, letter-spaced, muted — identical for all five.
const labelStyle: CSSProperties = {
  fontSize: "11px",
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  color: "var(--fg-muted)",
  whiteSpace: "nowrap",
};

// Body: 13px regular, normal case.
const bodyStyle: CSSProperties = {
  fontSize: "13px",
  fontWeight: 400,
  color: "var(--fg)",
  lineHeight: 1.5,
};

// Mono: ids, metrics, and the resolve command ONLY.
const monoStyle: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "12px",
};

// Chips: one size for triage statements and the age chip; tone via color.
const chipStyle = (color: string): CSSProperties => ({
  fontSize: "10px",
  fontWeight: 600,
  letterSpacing: "0.06em",
  color,
  border: `1px solid ${color}`,
  borderRadius: "var(--radius-control)",
  paddingInline: "var(--space-2)",
  lineHeight: 1.8,
  whiteSpace: "nowrap",
});

// Self-ticking age leaves (frozen-age fix, 2026-08-18 — the OweStrip LiveAge
// pattern, deliberately copied and kept LOCAL to this card): under the
// pollhub's change detection + this card's memo(), the component re-renders
// ONLY when the queue payload changes — a Date.now()-at-render age therefore
// froze at the last data change ("2m" forever on an idle backend). The 30 s
// tick lives in these leaves alone: a setState here re-renders just the age
// text/chip, never the row list around it. `nowMs` stays the tests'
// fixed-clock seam and wins over the tick when provided.
function LiveAgeChip({
  iso,
  nowMs,
  testid,
}: {
  iso: unknown;
  nowMs?: number;
  testid: string;
}) {
  const ticked = useNow(30_000);
  const now = nowMs ?? ticked;
  const tone = ageTone(iso, now);
  return (
    <span
      data-testid={testid}
      data-tone={tone}
      className="tnum"
      style={chipStyle(AGE_TONE_COLOR[tone])}
    >
      {ageLabel(iso, now)}
    </span>
  );
}

function LiveAge({ iso, nowMs }: { iso: unknown; nowMs?: number }) {
  const ticked = useNow(30_000);
  return <>{ageLabel(iso, nowMs ?? ticked)}</>;
}

interface Props {
  // Fixture injection (tests render synchronously, never fetch).
  initial?: HumanTodoItem[];
  pollMs?: number;
  // Test seam for the age chips: pins the clock when provided; otherwise the
  // LiveAge leaves self-tick every 30 s (frozen-age fix, 2026-08-18).
  nowMs?: number;
}

function OweCard({ initial, pollMs = 30000, nowMs }: Props) {
  const poll = usePolled<HumanTodoResponse>("human_todo", getHumanTodo, {
    intervalMs: pollMs,
    enabled: initial === undefined,
  });
  const [open, setOpen] = useState<Record<string, boolean>>({});
  // WHY THE TAG is collapsed by default (the triage_reason runs long); the
  // resolve command collapses to one line, expanding on click.
  const [whyOpen, setWhyOpen] = useState<Record<string, boolean>>({});
  const [cmdOpen, setCmdOpen] = useState<Record<string, boolean>>({});

  const items: HumanTodoItem[] =
    initial ?? (Array.isArray(poll.data?.items) ? poll.data.items : []);
  const loaded = initial !== undefined || poll.data !== undefined;
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
          gate verdicts, blocking state gates + findings that cleared L4 ·
          expand a row for what approving means
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
          <div
            data-testid="owe-error"
            style={{ ...bodyStyle, color: "var(--status-warn)" }}
          >
            /api/human_todo returned 404 — the queue is UNKNOWN, not empty.
          </div>
        ) : (
          <div
            data-testid="owe-error"
            style={{ ...bodyStyle, color: "var(--status-bad)" }}
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
            const key = id ?? `owe-${i}`;
            const kind = asText(item.kind) ?? "unknown";
            const title = asText(item.title) ?? id ?? "(untitled)";
            const action = actionPhrase(item);
            const level = evidenceLevelOf(item);
            const triage = asText(item.triage);
            const isOpen = open[key] === true;
            const isWhyOpen = whyOpen[key] === true;
            const isCmdOpen = cmdOpen[key] === true;
            const vet = asStrings(item.vet);
            const doing = asText(item.doing) ?? asText(item.detail);
            const means = asText(item.approval_means) ?? fallbackMeans(kind);
            const triageReason = asText(item.triage_reason);
            const resolve = asText(item.resolve_command);

            // Reading order: title (short claim head, 2-line clamp) first;
            // the action phrase rides below it as one muted body line.
            const lead = (
              <span
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "var(--space-1)",
                  flex: "1 1 0",
                  minWidth: 0,
                }}
              >
                <span
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "var(--space-2)",
                    minWidth: 0,
                  }}
                >
                  {level && <RungGlyph level={level} size={14} />}
                  <span style={titleStyle}>{claimHead(title)}</span>
                </span>
                <span
                  style={{
                    ...bodyStyle,
                    color: "var(--fg-muted)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {action}
                </span>
              </span>
            );

            return (
              <li key={key} data-testid={`owe-row-${i}`}>
                <div
                  className="dsn-row"
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: "var(--space-3)",
                    padding: "var(--space-2) var(--space-3)",
                    borderRadius: "var(--radius-control)",
                  }}
                >
                  <button
                    type="button"
                    data-testid={`owe-expand-${i}`}
                    aria-expanded={isOpen}
                    aria-label={`details for ${key}`}
                    onClick={() =>
                      setOpen((prev) => ({ ...prev, [key]: !isOpen }))
                    }
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      color: "var(--fg-muted)",
                      fontSize: "var(--text-meta)",
                      padding: 0,
                      marginTop: "3px",
                      lineHeight: 1,
                    }}
                  >
                    {isOpen ? "▾" : "▸"}
                  </button>
                  {id ? (
                    <Link
                      to={`/dossier/${encodeURIComponent(id)}`}
                      style={{
                        display: "flex",
                        flex: "1 1 0",
                        minWidth: 0,
                        textDecoration: "none",
                      }}
                    >
                      {lead}
                    </Link>
                  ) : (
                    <span style={{ display: "flex", flex: "1 1 0", minWidth: 0 }}>
                      {lead}
                    </span>
                  )}
                  {/* Chips: declarative statements, one size, tone colors. */}
                  {triage === "likely_superseded" && (
                    <span
                      data-testid={`owe-tag-${i}`}
                      data-triage="likely_superseded"
                      style={chipStyle("var(--status-warn)")}
                    >
                      LIKELY SUPERSEDED
                    </span>
                  )}
                  {triage === "observable" && (
                    <span
                      data-testid={`owe-tag-${i}`}
                      data-triage="observable"
                      style={chipStyle("var(--fg-muted)")}
                    >
                      OBSERVABLE
                    </span>
                  )}
                  <LiveAgeChip
                    iso={item.since}
                    nowMs={nowMs}
                    testid={`owe-age-${i}`}
                  />
                </div>

                {isOpen && (
                  <div
                    data-testid={`owe-detail-${i}`}
                    style={{
                      margin:
                        "var(--space-1) var(--space-3) var(--space-3) var(--space-6)",
                      padding: "var(--space-3)",
                      border: "1px solid var(--border-1)",
                      borderRadius: "var(--radius-control)",
                      display: "flex",
                      flexDirection: "column",
                      gap: "var(--space-3)",
                      ...bodyStyle,
                    }}
                  >
                    <div>
                      <div style={labelStyle}>WHAT YOU&apos;RE DOING</div>
                      <div style={{ ...bodyStyle, marginTop: "var(--space-1)" }}>
                        {doing ?? "—"}
                      </div>
                    </div>

                    <div>
                      <div style={labelStyle}>VET FIRST</div>
                      {vet.length > 0 ? (
                        <ul
                          style={{
                            ...bodyStyle,
                            margin: "var(--space-1) 0 0",
                            paddingLeft: "1.1em",
                            display: "flex",
                            flexDirection: "column",
                            gap: "var(--space-1)",
                          }}
                        >
                          {vet.map((bullet, j) => (
                            <li key={j}>{bullet}</li>
                          ))}
                        </ul>
                      ) : (
                        <div
                          style={{
                            ...bodyStyle,
                            color: "var(--fg-muted)",
                            marginTop: "var(--space-1)",
                          }}
                        >
                          no record-derived checks — open the dossier
                        </div>
                      )}
                    </div>

                    <div>
                      <div style={labelStyle}>WHAT APPROVAL MEANS</div>
                      <div style={{ ...bodyStyle, marginTop: "var(--space-1)" }}>
                        {means}
                      </div>
                    </div>

                    {triageReason && (
                      <div>
                        {/* Collapsed by default — the triage_reason is long. */}
                        <button
                          type="button"
                          data-testid={`owe-why-${i}`}
                          aria-expanded={isWhyOpen}
                          onClick={() =>
                            setWhyOpen((prev) => ({
                              ...prev,
                              [key]: !isWhyOpen,
                            }))
                          }
                          style={{
                            ...labelStyle,
                            background: "none",
                            border: "none",
                            cursor: "pointer",
                            padding: 0,
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "var(--space-1)",
                          }}
                        >
                          <span aria-hidden="true">{isWhyOpen ? "▾" : "▸"}</span>
                          WHY THE TAG
                        </button>
                        {isWhyOpen && (
                          <div
                            style={{
                              ...bodyStyle,
                              color: "var(--fg-muted)",
                              marginTop: "var(--space-1)",
                            }}
                          >
                            {triageReason}
                          </div>
                        )}
                      </div>
                    )}

                    <div>
                      <div style={labelStyle}>RESOLVE</div>
                      {resolve && (
                        <div
                          style={{
                            display: "flex",
                            alignItems: "flex-start",
                            gap: "var(--space-2)",
                            marginTop: "var(--space-1)",
                            minWidth: 0,
                          }}
                        >
                          {/* One line until clicked; mono is earned here. */}
                          <code
                            data-testid={`owe-resolve-${i}`}
                            data-expanded={isCmdOpen}
                            title={
                              isCmdOpen
                                ? "click to collapse"
                                : "click to expand"
                            }
                            onClick={() =>
                              setCmdOpen((prev) => ({
                                ...prev,
                                [key]: !isCmdOpen,
                              }))
                            }
                            style={{
                              ...monoStyle,
                              color: "var(--fg-muted)",
                              cursor: "pointer",
                              flex: "1 1 0",
                              minWidth: 0,
                              display: "block",
                              ...(isCmdOpen
                                ? {
                                    whiteSpace: "pre-wrap",
                                    overflowWrap: "anywhere",
                                  }
                                : {
                                    whiteSpace: "nowrap",
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                  }),
                            }}
                          >
                            {resolve}
                          </code>
                          <button
                            type="button"
                            data-testid={`owe-copy-${i}`}
                            aria-label="copy resolve command"
                            onClick={() =>
                              void navigator.clipboard?.writeText(resolve)
                            }
                            style={{
                              ...chipStyle("var(--fg-muted)"),
                              background: "none",
                              cursor: "pointer",
                            }}
                          >
                            COPY
                          </button>
                        </div>
                      )}
                      {id && (
                        <div style={{ marginTop: "var(--space-1)" }}>
                          <Link
                            to={`/dossier/${encodeURIComponent(id)}`}
                            style={{
                              ...bodyStyle,
                              color: "var(--fg-muted)",
                            }}
                          >
                            open dossier →
                          </Link>
                        </div>
                      )}
                    </div>
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
              <LiveAge iso={new Date(poll.asOf).toISOString()} nowMs={nowMs} />{" "}
              ago
            </>
          ) : (
            "an unknown age"
          )}
        </div>
      )}
    </section>
  );
}

// Memoized: Pulse re-renders on its clock and telemetry ticks; this card's
// props (fixture/test seams only) never change on those.
export default memo(OweCard);
