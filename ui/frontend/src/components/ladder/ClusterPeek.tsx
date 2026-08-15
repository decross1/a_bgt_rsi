// ClusterPeek — the body of the /ladder PeekPanel: everything the board card
// deliberately does NOT carry. Dead clusters lead with why they died and what
// would reopen them; live ones lead with the next test owed. Then this
// cluster's agenda items and its members, with the iteration-shaped members
// linking onward to their dossier — the one path from the board into the
// reader.
import { Link } from "react-router-dom";

import RungGlyph from "../../design/RungGlyph";
import { ageLabel } from "../../ladderBar";
import { asText, dossierIdOf, isKilled, membersOf } from "./ladderModel";
import type { LadderAgendaItem, LadderCluster } from "../../types/schemas";

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section style={{ marginTop: "var(--space-4)" }}>
      <h3
        style={{
          margin: "0 0 var(--space-1)",
          fontSize: "var(--text-meta)",
          fontWeight: "var(--weight-medium)",
          textTransform: "uppercase",
          letterSpacing: "0.04em",
          color: "var(--fg-muted)",
        }}
      >
        {label}
      </h3>
      {children}
    </section>
  );
}

const META: React.CSSProperties = {
  margin: 0,
  fontSize: "var(--text-ui)",
  color: "var(--fg)",
};

export default function ClusterPeek({
  cluster,
  agenda,
  nextOwed,
  nowMs,
}: {
  cluster: LadderCluster;
  /** The whole page agenda; this component takes its own cluster's slice. */
  agenda: LadderAgendaItem[];
  /** next_owed keyed by rung (the backend's per-rung "test owed" wording). */
  nextOwed: Record<string, string>;
  nowMs: number;
}) {
  const killed = isKilled(cluster);
  const level = asText(cluster.evidence_level);
  const cid = asText(cluster.cluster_id) ?? "";
  const kill =
    cluster.kill_reason != null &&
    typeof cluster.kill_reason === "object" &&
    !Array.isArray(cluster.kill_reason)
      ? cluster.kill_reason
      : null;
  const reopen =
    cluster.reopening_condition != null &&
    typeof cluster.reopening_condition === "object" &&
    !Array.isArray(cluster.reopening_condition)
      ? cluster.reopening_condition
      : null;
  const mine = agenda.filter((a) => asText(a.cluster_id) === cid);
  const members = membersOf(cluster);
  const owed = level !== null ? nextOwed[level] : undefined;

  return (
    // The stem is NOT repeated here — the panel header already carries it.
    <div data-testid="ladder-peek-body">
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--space-2)",
          fontSize: "var(--text-meta)",
          color: "var(--fg-muted)",
        }}
      >
        <RungGlyph level={cluster.evidence_level} killed={killed} />
        <span>{level ?? "no rung"}</span>
        <span>·</span>
        <span>{asText(cluster.status) ?? "unknown"}</span>
        <span>·</span>
        <span>{asText(cluster.origin) ?? "unknown origin"}</span>
        <span>·</span>
        <span className="tnum">{ageLabel(cluster.last_event_ts, nowMs)}</span>
      </div>
      <p
        style={{
          margin: "var(--space-1) 0 0",
          fontSize: "var(--text-meta)",
          color: "var(--fg-muted)",
          fontFamily: "var(--font-mono)",
        }}
      >
        {cid}
      </p>

      {killed ? (
        <Section label="killed">
          <div data-testid="ladder-peek-kill" style={META}>
            <p style={{ margin: 0, color: "var(--status-bad)" }}>
              <span style={{ fontFamily: "var(--font-mono)" }}>
                {asText(kill?.code) ?? "unspecified"}
              </span>
            </p>
            {asText(kill?.detail) !== null && (
              <p style={{ margin: "var(--space-1) 0 0" }}>
                {asText(kill?.detail)}
              </p>
            )}
            {asText(kill?.evidence_key) !== null && (
              <p
                style={{
                  margin: "var(--space-1) 0 0",
                  fontSize: "var(--text-meta)",
                  color: "var(--fg-muted)",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {asText(kill?.evidence_key)}
              </p>
            )}
            <p
              style={{ margin: "var(--space-2) 0 0" }}
              data-testid="ladder-peek-reopen"
            >
              <span style={{ color: "var(--fg-muted)" }}>reopen when: </span>
              {asText(reopen?.evidence_kind) ??
                asText(reopen?.requires) ??
                "none recorded"}
            </p>
          </div>
        </Section>
      ) : (
        <Section label="next test owed">
          <p style={META} data-testid="ladder-peek-owed">
            {owed ?? "no test recorded for this rung"}
          </p>
        </Section>
      )}

      <Section label="agenda">
        {mine.length === 0 ? (
          <p style={{ ...META, color: "var(--fg-muted)" }}>
            no open agenda items.
          </p>
        ) : (
          <ul
            style={{ margin: 0, paddingLeft: "var(--space-4)" }}
            data-testid="ladder-peek-agenda"
          >
            {mine.map((a, i) => (
              <li key={`${asText(a.topic) ?? "topic"}-${i}`} style={META}>
                {asText(a.topic) ?? "(untitled)"}
                <span
                  style={{
                    marginLeft: "var(--space-2)",
                    fontSize: "var(--text-meta)",
                    color: "var(--fg-muted)",
                  }}
                >
                  {asText(a.source) ?? "unknown"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section label={`members (${members.length})`}>
        {members.length === 0 ? (
          <p style={{ ...META, color: "var(--fg-muted)" }}>
            no members recorded.
          </p>
        ) : (
          <ul
            style={{ margin: 0, padding: 0, listStyle: "none" }}
            data-testid="ladder-peek-members"
          >
            {members.map((m) => {
              const to = dossierIdOf(m);
              return (
                <li
                  key={m}
                  style={{
                    ...META,
                    fontFamily: "var(--font-mono)",
                    fontSize: "var(--text-meta)",
                    padding: "2px 0",
                  }}
                >
                  {to !== null ? (
                    <Link to={`/dossier/${to}`} style={{ color: "var(--accent)" }}>
                      {m}
                    </Link>
                  ) : (
                    <span style={{ color: "var(--fg-muted)" }}>{m}</span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Section>
    </div>
  );
}
