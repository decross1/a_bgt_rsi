// LadderBoard — the kanban body of /ladder: one column per rung L0..L5 plus a
// Graveyard column that is collapsed by default (the dead are context, not the
// headline; expanded they group by kill code, tombstones keeping the rung they
// died at).
//
// A card carries FOUR things and nothing else — stem (2 lines), its RungGlyph,
// age, and ONE metric. Everything a reader might also want lives one click
// away in the peek panel. That restraint is the point of the rebuild: the old
// page put every field on every row.
import RungGlyph from "../../design/RungGlyph";
import { ageLabel } from "../../ladderBar";
import { LEVELS, asCount, asText, stemOf } from "./ladderModel";
import type { LadderModel } from "./ladderModel";
import type { LadderCluster } from "../../types/schemas";

const COL: React.CSSProperties = {
  background: "var(--surface-1)",
  border: "1px solid var(--border-1)",
  borderRadius: "var(--radius-card)",
  padding: "var(--space-2)",
};

const HEAD: React.CSSProperties = {
  fontSize: "var(--text-ui)",
  fontWeight: "var(--weight-medium)",
  color: "var(--fg)",
};

function ClusterCard({
  c,
  nowMs,
  onPick,
}: {
  c: LadderCluster;
  nowMs: number;
  onPick: (c: LadderCluster) => void;
}) {
  const killed = asText(c.status) === "killed";
  const agendaOpen = asCount(c.open_agenda_count);
  const members = asCount(c.member_count);
  // ONE metric: an open agenda is the live signal; otherwise cluster size.
  const metric =
    agendaOpen > 0
      ? `${agendaOpen} agenda`
      : `${members} member${members === 1 ? "" : "s"}`;

  return (
    <button
      type="button"
      data-testid={`ladder-card-${asText(c.cluster_id) ?? "unknown"}`}
      onClick={() => onPick(c)}
      className="w-full text-left"
      style={{
        display: "block",
        background: "var(--surface-2)",
        border: "1px solid var(--border-1)",
        borderRadius: "var(--radius-control)",
        padding: "var(--space-2)",
        cursor: "pointer",
        transition: "opacity var(--motion-hover) ease-out",
        opacity: killed ? 0.75 : 1,
      }}
    >
      <span
        className="flex items-start"
        style={{ gap: "var(--space-2)" }}
      >
        <RungGlyph
          level={c.evidence_level}
          killed={killed}
          style={{ flex: "none", marginTop: 1 }}
        />
        <span
          className="line-clamp-2"
          style={{ fontSize: "var(--text-ui)", color: "var(--fg)" }}
        >
          {stemOf(c)}
        </span>
      </span>
      <span
        className="flex items-center justify-between"
        style={{
          marginTop: "var(--space-2)",
          fontSize: "var(--text-meta)",
          color: "var(--fg-muted)",
        }}
      >
        <span className="tnum">{ageLabel(c.last_event_ts, nowMs)}</span>
        <span className="tnum">{metric}</span>
      </span>
    </button>
  );
}

export default function LadderBoard({
  model,
  nowMs,
  graveyardOpen,
  onToggleGraveyard,
  onPick,
}: {
  model: LadderModel;
  nowMs: number;
  graveyardOpen: boolean;
  onToggleGraveyard: () => void;
  onPick: (c: LadderCluster) => void;
}) {
  return (
    <div
      className="flex overflow-x-auto"
      style={{ gap: "var(--space-3)", paddingBottom: "var(--space-2)" }}
      data-testid="ladder-board"
    >
      {LEVELS.map((level, k) => {
        const cs = model.live[k];
        return (
          <section
            key={level}
            data-testid={`ladder-column-${level}`}
            data-count={cs.length}
            className="shrink-0"
            // 6 rungs + the collapsed graveyard must all fit a ~1400px
            // viewport, or the graveyard lands off-screen behind a scroll.
            style={{ ...COL, width: 180 }}
          >
            <header
              className="flex items-center"
              style={{
                gap: "var(--space-2)",
                padding: "var(--space-1) var(--space-1) var(--space-2)",
              }}
            >
              <RungGlyph level={level} style={{ flex: "none" }} />
              <span style={HEAD}>{level}</span>
              <span
                className="tnum"
                style={{
                  marginLeft: "auto",
                  fontSize: "var(--text-meta)",
                  color: "var(--fg-muted)",
                }}
              >
                {cs.length}
              </span>
            </header>
            <div className="flex flex-col" style={{ gap: "var(--space-2)" }}>
              {cs.map((c, i) => (
                <ClusterCard
                  key={asText(c.cluster_id) ?? `idx-${i}`}
                  c={c}
                  nowMs={nowMs}
                  onPick={onPick}
                />
              ))}
            </div>
          </section>
        );
      })}

      {/* Graveyard: collapsed by default, grouped by kill code when open. */}
      <section
        data-testid="ladder-column-graveyard"
        data-count={model.killed.length}
        data-open={graveyardOpen || undefined}
        className="shrink-0"
        style={{ ...COL, width: graveyardOpen ? 230 : 132 }}
      >
        <button
          type="button"
          data-testid="ladder-graveyard-toggle"
          aria-expanded={graveyardOpen}
          onClick={onToggleGraveyard}
          className="flex w-full items-center"
          style={{
            gap: "var(--space-2)",
            padding: "var(--space-1)",
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "var(--fg)",
          }}
        >
          <span style={{ color: "var(--fg-muted)" }}>
            {graveyardOpen ? "▾" : "▸"}
          </span>
          <span style={HEAD}>Graveyard</span>
          <span
            className="tnum"
            style={{
              marginLeft: "auto",
              fontSize: "var(--text-meta)",
              color: "var(--fg-muted)",
            }}
          >
            {model.killed.length}
          </span>
        </button>
        {graveyardOpen && (
          <div
            className="flex flex-col"
            style={{ gap: "var(--space-3)", marginTop: "var(--space-2)" }}
          >
            {model.graveyard.length === 0 && (
              <p
                data-testid="ladder-graveyard-empty"
                style={{
                  margin: 0,
                  fontSize: "var(--text-meta)",
                  color: "var(--fg-muted)",
                }}
              >
                nothing killed yet.
              </p>
            )}
            {model.graveyard.map((g) => (
              <div key={g.code} data-testid={`ladder-graveyard-group-${g.code}`}>
                <h3
                  style={{
                    margin: "0 0 var(--space-1)",
                    fontSize: "var(--text-meta)",
                    fontWeight: "var(--weight-normal)",
                    fontFamily: "var(--font-mono)",
                    color: "var(--fg-muted)",
                  }}
                >
                  {g.code} · {g.clusters.length}
                </h3>
                <div
                  className="flex flex-col"
                  style={{ gap: "var(--space-2)" }}
                >
                  {g.clusters.map((c, i) => (
                    <ClusterCard
                      key={asText(c.cluster_id) ?? `idx-${i}`}
                      c={c}
                      nowMs={nowMs}
                      onPick={onPick}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
