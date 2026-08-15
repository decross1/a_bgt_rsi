// LadderTable — the SAME dataset as the board, dense and sortable. One data
// set, two views (Notion-style): the board is for shape, the table is for
// scanning and for being the board's WCAG-clean twin — every value the funnel
// and the chart encode as geometry is readable here as text.
//
// Rows are the R0 ListRow at dense density; every numeric column carries
// tabular figures so the columns line up. A row opens the same peek panel a
// card does.
import { useMemo, useState } from "react";

import ListRow from "../../design/ListRow";
import RungGlyph, { rungIndex } from "../../design/RungGlyph";
import { ageLabel } from "../../ladderBar";
import { asCount, asText, isKilled, killCodeOf, stemOf } from "./ladderModel";
import type { LadderCluster } from "../../types/schemas";

type SortKey = "rung" | "stem" | "status" | "members" | "agenda" | "age";

const COLUMNS: { key: SortKey; label: string; width: number }[] = [
  { key: "rung", label: "rung", width: 56 },
  { key: "stem", label: "idea", width: 0 }, // flexes
  { key: "status", label: "status", width: 150 },
  { key: "members", label: "members", width: 72 },
  { key: "agenda", label: "agenda", width: 64 },
  { key: "age", label: "age", width: 56 },
];

function tsOf(c: LadderCluster): number {
  const s = asText(c.last_event_ts);
  const t = s === null ? NaN : Date.parse(s);
  return Number.isNaN(t) ? -Infinity : t;
}

function compare(a: LadderCluster, b: LadderCluster, key: SortKey): number {
  switch (key) {
    case "rung":
      return (rungIndex(a.evidence_level) ?? -1) - (rungIndex(b.evidence_level) ?? -1);
    case "stem":
      return stemOf(a).localeCompare(stemOf(b));
    case "status":
      return (asText(a.status) ?? "").localeCompare(asText(b.status) ?? "");
    case "members":
      return asCount(a.member_count) - asCount(b.member_count);
    case "agenda":
      return asCount(a.open_agenda_count) - asCount(b.open_agenda_count);
    case "age":
      return tsOf(a) - tsOf(b);
  }
}

export default function LadderTable({
  clusters,
  nowMs,
  onPick,
}: {
  clusters: LadderCluster[];
  nowMs: number;
  onPick: (c: LadderCluster) => void;
}) {
  const [sort, setSort] = useState<SortKey>("rung");
  const [desc, setDesc] = useState(true);

  const rows = useMemo(() => {
    const sorted = [...clusters].sort((a, b) => compare(a, b, sort));
    return desc ? sorted.reverse() : sorted;
  }, [clusters, sort, desc]);

  const toggle = (key: SortKey) => {
    if (key === sort) setDesc((v) => !v);
    else {
      setSort(key);
      setDesc(true);
    }
  };

  const cell = (w: number): React.CSSProperties =>
    w === 0
      ? { flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }
      : { width: w, flex: "none" };

  return (
    <div data-density="dense" data-testid="ladder-table">
      <div
        className="flex items-center"
        style={{
          gap: "var(--space-3)",
          padding: "0 var(--space-3) var(--space-1)",
          borderBottom: "1px solid var(--border-1)",
        }}
      >
        {COLUMNS.map((col) => (
          <button
            key={col.key}
            type="button"
            data-testid={`ladder-sort-${col.key}`}
            aria-pressed={sort === col.key}
            onClick={() => toggle(col.key)}
            style={{
              ...cell(col.width),
              textAlign: "left",
              background: "none",
              border: "none",
              padding: 0,
              cursor: "pointer",
              fontSize: "var(--text-meta)",
              color: sort === col.key ? "var(--fg)" : "var(--fg-muted)",
            }}
          >
            {col.label}
            {sort === col.key ? (desc ? " ↓" : " ↑") : ""}
          </button>
        ))}
      </div>
      {rows.map((c, i) => {
        const killed = isKilled(c);
        return (
          <ListRow
            key={asText(c.cluster_id) ?? `idx-${i}`}
            testId={`ladder-row-${asText(c.cluster_id) ?? "unknown"}`}
            onClick={() => onPick(c)}
          >
            <span style={{ ...cell(56), display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
              <RungGlyph level={c.evidence_level} killed={killed} size={14} />
              <span
                className="tnum"
                style={{ fontSize: "var(--text-meta)", color: "var(--fg-muted)" }}
              >
                {asText(c.evidence_level) ?? "—"}
              </span>
            </span>
            <span style={cell(0)}>{stemOf(c)}</span>
            <span
              style={{
                ...cell(150),
                fontSize: "var(--text-meta)",
                color: killed ? "var(--status-bad)" : "var(--fg-muted)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={killed ? killCodeOf(c) : undefined}
            >
              {killed ? killCodeOf(c) : asText(c.status) ?? "unknown"}
            </span>
            <span className="tnum" style={{ ...cell(72), color: "var(--fg-muted)" }}>
              {asCount(c.member_count)}
            </span>
            <span className="tnum" style={{ ...cell(64), color: "var(--fg-muted)" }}>
              {asCount(c.open_agenda_count)}
            </span>
            <span className="tnum" style={{ ...cell(56), color: "var(--fg-muted)" }}>
              {ageLabel(c.last_event_ts, nowMs)}
            </span>
          </ListRow>
        );
      })}
      {rows.length === 0 && (
        <p
          data-testid="ladder-table-empty"
          style={{
            margin: "var(--space-3)",
            fontSize: "var(--text-ui)",
            color: "var(--fg-muted)",
          }}
        >
          no clusters in the ledger.
        </p>
      )}
    </div>
  );
}
