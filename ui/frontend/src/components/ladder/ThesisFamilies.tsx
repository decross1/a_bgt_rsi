import { useId, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import RungGlyph, { rungIndex } from "../../design/RungGlyph";
import { ageLabel } from "../../ladderBar";
import type { LadderCluster } from "../../types/schemas";
import { matchesFamilyRecord } from "./thesisModel";
import type {
  FamilyRecord,
  RecordedIteration,
  ThesisFamily,
  ThesisModel,
} from "./thesisModel";

type StatusFilter = "open" | "all" | "killed" | "surfaced" | "unknown";
type StageFilter = "all" | "L0" | "L1" | "L2" | "L3" | "L4" | "L5" | "unknown";

const CONTROL: React.CSSProperties = {
  width: "100%",
  minWidth: 0,
  height: 34,
  padding: "0 var(--space-2)",
  border: "1px solid var(--border-2)",
  borderRadius: "var(--radius-control)",
  background: "var(--surface-2)",
  color: "var(--fg)",
  font: "inherit",
};

const META: React.CSSProperties = {
  margin: 0,
  color: "var(--fg-muted)",
  fontSize: "var(--text-meta)",
};

const LEVELS = ["L0", "L1", "L2", "L3", "L4", "L5"] as const;
const KNOWN_STATUSES = ["open", "surfaced", "killed"] as const;

function textOf(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function recordStatus(cluster: LadderCluster): Exclude<StatusFilter, "all"> {
  const value = textOf(cluster.status);
  return value === "open" || value === "killed" || value === "surfaced"
    ? value
    : "unknown";
}

function statusLabel(cluster: LadderCluster): string {
  const value = textOf(cluster.status);
  return value && KNOWN_STATUSES.includes(value as (typeof KNOWN_STATUSES)[number])
    ? value
    : value
      ? `${value} (unrecognized)`
      : "unknown";
}

function recordStage(cluster: LadderCluster): Exclude<StageFilter, "all"> {
  const index = rungIndex(cluster.evidence_level);
  return index === null ? "unknown" : `L${index}` as Exclude<StageFilter, "all" | "unknown">;
}

function stageLabel(cluster: LadderCluster): string {
  const stage = recordStage(cluster);
  if (stage !== "unknown") return stage;
  const recorded = textOf(cluster.evidence_level)?.trim();
  return recorded ? `unknown (recorded: ${recorded})` : "unknown";
}

function timestampOf(cluster: LadderCluster): number {
  const value = textOf(cluster.last_event_ts);
  const timestamp = value === null ? Number.NaN : Date.parse(value);
  return Number.isNaN(timestamp) ? Number.NEGATIVE_INFINITY : timestamp;
}

function recordPriority(record: FamilyRecord): number {
  return recordStatus(record.cluster) === "open" && recordStage(record.cluster) === "L1" ? 1 : 0;
}

function compareRecords(a: FamilyRecord, b: FamilyRecord): number {
  const priority = recordPriority(b) - recordPriority(a);
  if (priority !== 0) return priority;
  const aTimestamp = timestampOf(a.cluster);
  const bTimestamp = timestampOf(b.cluster);
  if (aTimestamp !== bTimestamp) return bTimestamp > aTimestamp ? 1 : -1;
  const title = a.title.localeCompare(b.title);
  return title !== 0 ? title : a.id.localeCompare(b.id);
}

function compareFamilies(a: ThesisFamily, b: ThesisFamily): number {
  const aPriority = a.records.some((record) => recordPriority(record) === 1) ? 1 : 0;
  const bPriority = b.records.some((record) => recordPriority(record) === 1) ? 1 : 0;
  if (aPriority !== bPriority) return bPriority - aPriority;
  const aLatest = Math.max(Number.NEGATIVE_INFINITY, ...a.records.map((r) => timestampOf(r.cluster)));
  const bLatest = Math.max(Number.NEGATIVE_INFINITY, ...b.records.map((r) => timestampOf(r.cluster)));
  if (aLatest !== bLatest) return bLatest - aLatest;
  const title = a.title.localeCompare(b.title);
  return title !== 0 ? title : a.id.localeCompare(b.id);
}

function countLabel(shown: number, total: number): string {
  return shown === total
    ? `${total} record${total === 1 ? "" : "s"}`
    : `${shown} of ${total} records`;
}

function countsBy(
  records: readonly FamilyRecord[],
  valueOf: (record: FamilyRecord) => string,
  preferredOrder: readonly string[],
): Array<[string, number]> {
  const counts = new Map<string, number>();
  for (const record of records) {
    const value = valueOf(record);
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return [...counts].sort(([a], [b]) => {
    const ai = preferredOrder.indexOf(a);
    const bi = preferredOrder.indexOf(b);
    if (ai !== -1 || bi !== -1) {
      if (ai === -1) return 1;
      if (bi === -1) return -1;
      return ai - bi;
    }
    return a.localeCompare(b);
  });
}

function Distribution({
  label,
  values,
}: {
  label: string;
  values: Array<[string, number]>;
}) {
  return (
    <span className="flex min-w-0 flex-wrap items-center" style={{ gap: "var(--space-1)" }}>
      <span>{label}</span>
      {values.map(([value, count], index) => (
        <span key={value} className="tnum" style={{ color: "var(--fg)" }}>
          {index > 0 ? " · " : ""}{value} {count}
        </span>
      ))}
    </span>
  );
}

// This is a partition of current recorded classifications, not a progress bar.
// All-record counts stay fixed when a filter changes which cards are shown.
function ClassificationBar({
  kind,
  values,
  total,
  descriptionId,
}: {
  kind: "stages" | "statuses";
  values: Array<[string, number]>;
  total: number;
  descriptionId: string;
}) {
  const categories = kind === "stages" ? [...LEVELS, "unknown"] : [...KNOWN_STATUSES, "unknown"];
  const counts = new Map(values);
  const exactValues = [...categories, ...values.map(([value]) => value).filter((value) => !categories.includes(value))]
    .map((value) => `${value} ${counts.get(value) ?? 0} of ${total}`);
  const description = `Recorded ${kind} for all ${countLabel(total, total)}: ${exactValues.join("; ")}`;
  const colors: Record<string, string> = kind === "stages"
    ? { L0: "var(--neutral-500)", L1: "var(--status-info)", L2: "var(--status-warn)",
      L3: "var(--neutral-300)", L4: "var(--neutral-700)", L5: "var(--neutral-100)" }
    : { open: "var(--status-info)", surfaced: "var(--status-warn)", killed: "var(--status-idle)" };

  if (total === 0) return <span style={META}>No recorded {kind}.</span>;
  return (
    <span
      role="img"
      aria-label={description}
      title={description}
      className="flex min-w-0 flex-wrap items-center"
      style={{ gap: "var(--space-1) var(--space-2)", fontSize: "var(--text-meta)", color: "var(--fg-muted)" }}
    >
      <span id={descriptionId} className="sr-only">{description}</span>
      <span aria-hidden="true">{kind === "stages" ? "Stages" : "Status"}</span>
      <span aria-hidden="true" style={{ display: "flex", width: 72, height: 6, flexShrink: 0,
        overflow: "hidden", borderRadius: "var(--radius-pill)", background: "var(--surface-3)" }}>
        {values.filter(([, count]) => count > 0).map(([value, count]) => (
          <span key={value} data-classification={value} style={{ width: `${count / total * 100}%`,
            background: colors[value] ?? "var(--neutral-400)", boxShadow: "inset 1px 0 var(--surface-1)" }} />
        ))}
      </span>
      <span aria-hidden="true" className="flex min-w-0 flex-wrap" style={{ gap: "var(--space-1) var(--space-2)" }}>
        {values.map(([value, count]) => (
          <span key={value} className="tnum" style={{ color: "var(--fg)", overflowWrap: "anywhere" }}>
            {value} {count}
          </span>
        ))}
      </span>
    </span>
  );
}

interface TopicGroup {
  key: string;
  topics: string[];
  allRecords: FamilyRecord[];
  shownRecords: FamilyRecord[];
}

function topicKey(record: FamilyRecord): { key: string; topics: string[] } {
  const topics = [...new Set(record.topics.filter((topic) => topic.length > 0))]
    .sort((a, b) => a.localeCompare(b));
  if (topics.length === 0) return { key: "unavailable", topics: [] };
  return { key: `topics:${topics.join("\u0000")}`, topics };
}

function groupRecords(family: ThesisFamily, shownRecords: FamilyRecord[]): TopicGroup[] {
  const shownIds = new Set(shownRecords.map((record) => record.key));
  const groups = new Map<string, TopicGroup>();

  for (const record of family.records) {
    const { key, topics } = topicKey(record);
    const group = groups.get(key) ?? { key, topics, allRecords: [], shownRecords: [] };
    group.allRecords.push(record);
    if (shownIds.has(record.key)) group.shownRecords.push(record);
    groups.set(key, group);
  }

  // Preserve model-provided topic context even if a defensive/malformed record
  // omitted its local topic list. These groups intentionally contain no card.
  const represented = new Set([...groups.values()].flatMap((group) => group.topics));
  for (const topic of family.topicLabels) {
    if (!represented.has(topic)) {
      groups.set(`declared:${topic}`, {
        key: `declared:${topic}`,
        topics: [topic],
        allRecords: [],
        shownRecords: [],
      });
    }
  }

  return [...groups.values()].sort((a, b) => {
    if (a.topics.length === 0) return b.topics.length === 0 ? 0 : 1;
    if (b.topics.length === 0) return -1;
    return a.topics.join("\u0000").localeCompare(b.topics.join("\u0000"));
  });
}

function dossierMemberIds(record: FamilyRecord): string[] {
  const ids: string[] = [];
  const seen = new Set<string>();
  const add = (value: unknown) => {
    if (typeof value !== "string" || seen.has(value)) return;
    seen.add(value);
    ids.push(value);
  };
  // Ledger member traversal is chronology; attach metadata without reordering.
  if (Array.isArray(record.cluster.members)) {
    for (const member of record.cluster.members) add(member);
  }
  for (const iteration of record.iterations) add(iteration.id);
  return ids;
}

function isDossierMember(id: string): boolean {
  return /^(iter|sf)-/.test(id);
}

function matchingDossierText(iteration: RecordedIteration, query: string): {
  label: string;
  text: string;
} | null {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return null;
  const visible = [iteration.id, iteration.topic, iteration.hypothesis]
    .filter((value): value is string => typeof value === "string")
    .some((value) => value.toLocaleLowerCase().includes(needle));
  if (visible) return null;
  const paper = iteration.paperText.find((value) => value.toLocaleLowerCase().includes(needle));
  if (paper !== undefined) return { label: "Matching recorded source", text: paper };
  const evidence = iteration.evidenceText.find((value) => value.toLocaleLowerCase().includes(needle));
  return evidence === undefined ? null : { label: "Matching recorded evidence", text: evidence };
}

function RecordCard({
  record,
  nextOwed,
  onPick,
  nowMs,
  query,
}: {
  record: FamilyRecord;
  nextOwed: Record<string, string>;
  onPick: (cluster: LadderCluster) => void;
  nowMs: number;
  query: string;
}) {
  const status = recordStatus(record.cluster);
  const statusText = statusLabel(record.cluster);
  const stage = recordStage(record.cluster);
  const stageText = stageLabel(record.cluster);
  const hypotheses = record.iterations
    .map((iteration) => iteration.hypothesis)
    .filter((hypothesis): hypothesis is string => typeof hypothesis === "string" && hypothesis.length > 0);
  const showTitle = record.title !== record.id && !hypotheses.includes(record.title);
  const members = dossierMemberIds(record);
  const iterations = new Map(record.iterations.map((iteration) => [iteration.id, iteration]));
  const owed = stage === "unknown" ? undefined : nextOwed[stage];
  const kill = record.cluster.kill_reason;
  const reopen = record.cluster.reopening_condition;
  const sourceCount = record.iterations.reduce((sum, iteration) => sum + iteration.paperText.length, 0);
  const evidenceCount = record.iterations.reduce((sum, iteration) => sum + iteration.evidenceText.length, 0);

  return (
    <article
      data-testid={`thesis-record-${record.key}`}
      style={{
        minWidth: 0,
        padding: "var(--space-3)",
        border: "1px solid var(--border-1)",
        borderRadius: "var(--radius-control)",
        background: "var(--surface-2)",
        overflowWrap: "anywhere",
      }}
    >
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "var(--space-2)" }}>
        <RungGlyph
          level={record.cluster.evidence_level}
          killed={status === "killed"}
          title={`Recorded stage ${stageText}`}
          style={{ flex: "none" }}
        />
        <span className="tnum" style={{ color: "var(--fg)", fontWeight: "var(--weight-medium)" }}>
          {stageText}
        </span>
        <span
          style={{
            color: status === "killed" ? "var(--status-bad)" : "var(--fg-muted)",
            fontSize: "var(--text-meta)",
          }}
        >
          {statusText}
        </span>
        <span className="tnum" style={{ ...META, marginLeft: "auto" }}>
          {ageLabel(record.cluster.last_event_ts, nowMs)}
        </span>
        <button
          type="button"
          aria-label={`Open details for ${record.id}${record.hasUniqueSourceId ? "" : ` — unverified snapshot ${record.unverifiedSnapshotNumber}`}`}
          onClick={() => onPick(record.cluster)}
          style={{
            border: "1px solid var(--border-2)",
            borderRadius: "var(--radius-control)",
            background: "transparent",
            color: "var(--accent)",
            padding: "var(--space-1) var(--space-2)",
            cursor: "pointer",
            font: "inherit",
          }}
        >
          Inspect record
        </button>
      </div>

      {showTitle && (
        <h4
          style={{
            margin: "var(--space-2) 0 0",
            color: "var(--fg)",
            fontSize: "var(--text-prose)",
            fontWeight: "var(--weight-medium)",
          }}
        >
          {record.title}
        </h4>
      )}
      <p
        className="font-mono"
        style={{ ...META, marginTop: "var(--space-1)", overflowWrap: "anywhere" }}
      >
        {record.id}
      </p>

      {members.length > 0 && (
        <div style={{ marginTop: "var(--space-3)" }}>
          <h5
            style={{
              margin: "0 0 var(--space-1)",
              color: "var(--fg-muted)",
              fontSize: "var(--text-meta)",
              fontWeight: "var(--weight-medium)",
              letterSpacing: "0.04em",
              textTransform: "uppercase",
            }}
          >
            Recorded members and hypotheses
          </h5>
          <div className="flex flex-col" style={{ gap: "var(--space-2)" }}>
            {members.map((member) => {
              const iteration = iterations.get(member);
              const match = iteration ? matchingDossierText(iteration, query) : null;
              return (
                <div key={member} style={{ minWidth: 0 }}>
                  {isDossierMember(member) ? (
                    <Link
                      to={`/dossier/${member}`}
                      aria-label={`Open evidence for ${member}`}
                      className="font-mono"
                      style={{ color: "var(--accent)", fontSize: "var(--text-meta)", overflowWrap: "anywhere" }}
                    >
                      {member}
                    </Link>
                  ) : (
                    <span className="font-mono" style={META}>{member}</span>
                  )}
                  {iteration?.hypothesis && (
                    <p style={{ margin: "var(--space-1) 0 0", color: "var(--fg)", fontSize: "var(--text-prose)" }}>
                      {iteration.hypothesis}
                    </p>
                  )}
                  {match && (
                    <div style={{ marginTop: "var(--space-1)" }}>
                      <span style={META}>{match.label}</span>
                      <p style={{ margin: "var(--space-1) 0 0", color: "var(--fg)", fontSize: "var(--text-ui)" }}>
                        {match.text}
                      </p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {status === "killed" ? (
        <section
          aria-label="Recorded negative result"
          style={{
            marginTop: "var(--space-3)",
            paddingLeft: "var(--space-2)",
            borderLeft: "2px solid var(--status-bad)",
          }}
        >
          <h5 style={{ ...META, fontWeight: "var(--weight-medium)", textTransform: "uppercase" }}>
            Recorded negative result
          </h5>
          <p className="font-mono" style={{ margin: "var(--space-1) 0 0", color: "var(--fg)" }}>
            {textOf(kill?.code) ?? "unspecified code"}
          </p>
          {textOf(kill?.detail) && (
            <p style={{ margin: "var(--space-1) 0 0", color: "var(--fg)" }}>{textOf(kill?.detail)}</p>
          )}
          {textOf(kill?.evidence_key) && (
            <p className="font-mono" style={{ ...META, marginTop: "var(--space-1)" }}>
              evidence: {textOf(kill?.evidence_key)}
            </p>
          )}
          <p style={{ ...META, marginTop: "var(--space-1)" }}>
            reopen when: {textOf(reopen?.evidence_kind) ?? textOf(reopen?.requires) ?? "none recorded"}
          </p>
        </section>
      ) : (
        <section aria-label="Next test owed" style={{ marginTop: "var(--space-3)" }}>
          <h5 style={{ ...META, fontWeight: "var(--weight-medium)", textTransform: "uppercase" }}>
            Next test owed
          </h5>
          <p style={{ margin: "var(--space-1) 0 0", color: "var(--fg)" }}>
            {owed ?? "No test is recorded for this stage."}
          </p>
        </section>
      )}

      {record.association === "individual" && record.reason && (
        <p style={{ ...META, marginTop: "var(--space-2)" }}>
          Provenance: {record.reason}
        </p>
      )}
      {record.missingMembers.length > 0 && (
        <p style={{ ...META, marginTop: "var(--space-1)" }}>
          Unresolved members: {record.missingMembers.join(", ")}
        </p>
      )}
      <p style={{ ...META, marginTop: "var(--space-2)" }}>
        Dossier contains full recorded papers, evidence and decisions
        {sourceCount > 0 || evidenceCount > 0
          ? ` · ${sourceCount} source text ${sourceCount === 1 ? "entry" : "entries"} · ${evidenceCount} evidence ${evidenceCount === 1 ? "entry" : "entries"}`
          : ""}.
      </p>
    </article>
  );
}

function TopicHeading({ group }: { group: TopicGroup }) {
  if (group.topics.length === 0) {
    return <h3 style={{ margin: 0, fontSize: "var(--text-ui)", fontWeight: "var(--weight-medium)" }}>Recorded topic unavailable</h3>;
  }
  if (group.topics.length === 1) {
    return (
      <h3
        style={{
          margin: 0,
          color: "var(--fg)",
          fontSize: "var(--text-ui)",
          fontWeight: "var(--weight-medium)",
          overflowWrap: "anywhere",
        }}
      >
        {group.topics[0]}
      </h3>
    );
  }
  return (
    <div>
      <h3 style={{ margin: 0, color: "var(--fg)", fontSize: "var(--text-ui)", fontWeight: "var(--weight-medium)" }}>
        Mixed recorded topics
      </h3>
      <ul style={{ margin: "var(--space-1) 0 0", paddingLeft: "var(--space-4)", color: "var(--fg)" }}>
        {group.topics.map((topic) => <li key={topic} style={{ overflowWrap: "anywhere" }}>{topic}</li>)}
      </ul>
    </div>
  );
}

function FamilyCard({
  family,
  shownRecords,
  expanded,
  onToggle,
  nextOwed,
  onPick,
  nowMs,
  query,
}: {
  family: ThesisFamily;
  shownRecords: FamilyRecord[];
  expanded: boolean;
  onToggle: () => void;
  nextOwed: Record<string, string>;
  onPick: (cluster: LadderCluster) => void;
  nowMs: number;
  query: string;
}) {
  const reactId = useId();
  const regionId = `thesis-family-records-${reactId.replace(/:/g, "")}`;
  const statusCounts = countsBy(family.records, (record) => statusLabel(record.cluster), KNOWN_STATUSES);
  const stageCounts = countsBy(family.records, (record) => recordStage(record.cluster), [...LEVELS, "unknown"]);
  const groups = groupRecords(family, shownRecords);
  const individual = family.records.length === 1 && family.records[0].association === "individual"
    ? family.records[0] : undefined;
  const presentationKind = individual !== undefined ? "record"
    : family.records[0]?.association === "curated-topic-collection"
      ? "curated association" : "exact topic collection";
  const disclosureContext = individual === undefined ? "" : individual.hasUniqueSourceId
    ? ` — source ID ${individual.id}`
    : ` — unverified snapshot ${individual.unverifiedSnapshotNumber}`;

  return (
    <section
      data-testid={`thesis-family-${family.id}`}
      style={{
        minWidth: 0,
        border: "1px solid var(--border-1)",
        borderRadius: "var(--radius-card)",
        background: "var(--surface-1)",
        overflow: "hidden",
      }}
    >
      <button
        type="button"
        aria-label={`${expanded ? "Collapse" : "Expand"} ${presentationKind}: ${family.title}${disclosureContext}`}
        aria-expanded={expanded}
        aria-controls={regionId}
        aria-describedby={`${regionId}-total ${regionId}-stages ${regionId}-statuses`}
        onClick={onToggle}
        className="w-full text-left"
        style={{
          display: "block",
          minWidth: 0,
          padding: "var(--space-3) var(--space-4)",
          border: 0,
          background: "transparent",
          color: "var(--fg)",
          cursor: "pointer",
          font: "inherit",
        }}
      >
        <span className="flex min-w-0 flex-wrap items-start" style={{ gap: "var(--space-2)" }}>
          <span aria-hidden="true" style={{ color: "var(--fg-muted)", paddingTop: 1 }}>
            {expanded ? "▾" : "▸"}
          </span>
          <span style={{ minWidth: 0, flex: "1 1 220px" }}>
            <span
              style={{
                display: "block",
                fontSize: "var(--text-title)",
                fontWeight: "var(--weight-semibold)",
                overflowWrap: "anywhere",
              }}
            >
              {family.title}
            </span>
            <span style={{ ...META, display: "block", marginTop: "var(--space-1)" }}>
              {family.basis === "exact iteration seed.topic" ? "Same recorded topic — association only" : family.basis}
              {presentationKind === "curated association" && ` · ${family.topicLabels.length} topics`}
            </span>
          </span>
          <span className="tnum" style={{ color: "var(--fg-muted)", fontSize: "var(--text-meta)" }}>
            {countLabel(shownRecords.length, family.records.length)}
          </span>
        </span>

      </button>

      <div id={`${regionId}-classifications`} data-testid="family-classification-summary" className="flex min-w-0 flex-wrap items-center"
        style={{ gap: "var(--space-1) var(--space-4)", padding: "0 var(--space-4) var(--space-3)" }}>
        <span id={`${regionId}-total`} className="tnum" style={META}
          title="Classification bars include all records in this collection, including filtered-out and killed records.">
          All {countLabel(family.records.length, family.records.length)}
        </span>
        <ClassificationBar kind="stages" values={stageCounts} total={family.records.length} descriptionId={`${regionId}-stages`} />
        <ClassificationBar kind="statuses" values={statusCounts} total={family.records.length} descriptionId={`${regionId}-statuses`} />
      </div>

      {expanded && (
        <div
          id={regionId}
          style={{
            minWidth: 0,
            padding: "0 var(--space-4) var(--space-4)",
            borderTop: "1px solid var(--border-1)",
          }}
        >
          {groups.map((group) => (
            <section key={group.key} style={{ minWidth: 0, marginTop: "var(--space-3)" }}>
              {!(groups.length === 1 && group.topics.length === 1 && group.topics[0] === family.title && individual === undefined) && (
              <div className="flex min-w-0 flex-wrap items-start" style={{ gap: "var(--space-2)" }}>
                <div style={{ minWidth: 0, flex: "1 1 280px" }}><TopicHeading group={group} /></div>
                <span className="tnum" style={META}>
                  {countLabel(group.shownRecords.length, group.allRecords.length)}
                </span>
              </div>
              )}
              {group.shownRecords.length > 0 ? (
                <div className="grid min-w-0 grid-cols-1 lg:grid-cols-2" style={{ gap: "var(--space-2)", marginTop: "var(--space-2)" }}>
                  {[...group.shownRecords].sort(compareRecords).map((record) => (
                    <RecordCard
                      key={record.key}
                      record={record}
                      nextOwed={nextOwed}
                      onPick={onPick}
                      nowMs={nowMs}
                      query={query}
                    />
                  ))}
                </div>
              ) : (
                <p style={{ ...META, marginTop: "var(--space-2)" }}>No records in this topic match the current filters.</p>
              )}
            </section>
          ))}
        </div>
      )}
    </section>
  );
}

export default function ThesisFamilies({
  model,
  nextOwed,
  onPick,
  nowMs,
}: {
  model: ThesisModel;
  nextOwed: Record<string, string>;
  onPick: (cluster: LadderCluster) => void;
  nowMs: number;
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("open");
  const [stage, setStage] = useState<StageFilter>("all");
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());

  const allFamilyRecords = useMemo(
    () => model.families.flatMap((family) => family.records),
    [model.families],
  );
  const totalRecords = model.records.length;
  const filteredFamilies = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return [...model.families]
      .sort(compareFamilies)
      .map((family) => {
        const familyMatch = needle.length > 0 && [family.title, family.basis, ...family.topicLabels]
          .some((value) => value.toLocaleLowerCase().includes(needle));
        const records = family.records.filter((record) => {
          if (status !== "all" && recordStatus(record.cluster) !== status) return false;
          if (stage !== "all" && recordStage(record.cluster) !== stage) return false;
          return needle.length === 0 || familyMatch || matchesFamilyRecord(record, query);
        });
        return { family, records };
      })
      .filter(({ records }) => records.length > 0);
  }, [model.families, query, stage, status]);

  const shownRecords = filteredFamilies.reduce((sum, family) => sum + family.records.length, 0);
  const allStatusCounts = countsBy(allFamilyRecords, (record) => statusLabel(record.cluster), KNOWN_STATUSES);
  const allStageCounts = countsBy(allFamilyRecords, (record) => recordStage(record.cluster), [...LEVELS, "unknown"]);
  const hasUnverifiedRelationships = model.issues.length > 0 || allFamilyRecords.some(
    (record) => record.association === "individual" || record.missingMembers.length > 0,
  );
  const filtersCleared = query.length === 0 && status === "all" && stage === "all";

  const toggleFamily = (id: string) => {
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <section data-testid="thesis-families" style={{ minWidth: 0 }}>
      <div
        className="flex min-w-0 flex-wrap items-end"
        style={{ gap: "var(--space-2)", marginBottom: "var(--space-3)" }}
      >
        <label style={{ minWidth: 0, flex: "2 1 280px", color: "var(--fg-muted)", fontSize: "var(--text-meta)" }}>
          <span style={{ display: "block", marginBottom: "var(--space-1)" }}>Search topics, claims or record IDs</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Topic, hypothesis or ID"
            style={CONTROL}
          />
        </label>
        <label style={{ minWidth: 0, flex: "1 1 150px", color: "var(--fg-muted)", fontSize: "var(--text-meta)" }}>
          <span style={{ display: "block", marginBottom: "var(--space-1)" }}>Record status</span>
          <select value={status} onChange={(event) => setStatus(event.target.value as StatusFilter)} style={CONTROL}>
            <option value="open">Open</option>
            <option value="all">All statuses</option>
            <option value="killed">Killed</option>
            <option value="surfaced">Surfaced</option>
            <option value="unknown">Unknown</option>
          </select>
        </label>
        <label style={{ minWidth: 0, flex: "1 1 150px", color: "var(--fg-muted)", fontSize: "var(--text-meta)" }}>
          <span style={{ display: "block", marginBottom: "var(--space-1)" }}>Recorded stage</span>
          <select value={stage} onChange={(event) => setStage(event.target.value as StageFilter)} style={CONTROL}>
            <option value="all">All stages</option>
            {LEVELS.map((level) => <option key={level} value={level}>{level}</option>)}
            <option value="unknown">Unknown</option>
          </select>
        </label>
        <button
          type="button"
          onClick={() => {
            setQuery("");
            setStatus("all");
            setStage("all");
          }}
          disabled={filtersCleared}
          style={{
            height: 34,
            padding: "0 var(--space-3)",
            border: "1px solid var(--border-2)",
            borderRadius: "var(--radius-control)",
            background: "transparent",
            color: filtersCleared ? "var(--fg-muted)" : "var(--accent)",
            cursor: filtersCleared ? "default" : "pointer",
            font: "inherit",
            opacity: filtersCleared ? 0.65 : 1,
          }}
        >
          Clear filters
        </button>
      </div>

      <div
        aria-live="polite"
        className="flex min-w-0 flex-wrap"
        style={{ gap: "var(--space-2) var(--space-4)", marginBottom: "var(--space-2)", color: "var(--fg-muted)", fontSize: "var(--text-meta)" }}
      >
        <span className="tnum">
          {filteredFamilies.length} of {model.families.length} collections / individual records · {shownRecords} of {totalRecords} records
        </span>
        <Distribution label="recorded stages (including killed)" values={allStageCounts} />
        <Distribution label="all statuses" values={allStatusCounts} />
      </div>
      {status === "open" && (
        <p style={{ ...META, marginBottom: "var(--space-3)" }}>
          Showing open records by default. Family distributions retain filtered and negative-result context.
        </p>
      )}
      {hasUnverifiedRelationships && (
        <p
          role="note"
          style={{
            margin: "0 0 var(--space-3)",
            padding: "var(--space-2) var(--space-3)",
            border: "1px solid var(--border-1)",
            borderRadius: "var(--radius-control)",
            background: "var(--surface-1)",
            color: "var(--fg-muted)",
            fontSize: "var(--text-ui)",
          }}
        >
          Some source relationships are not verified. Those records remain separate and inspectable.
        </p>
      )}

      <div className="flex min-w-0 flex-col" style={{ gap: "var(--space-2)" }}>
        {filteredFamilies.map(({ family, records }) => (
          <FamilyCard
            key={family.id}
            family={family}
            shownRecords={records}
            expanded={expandedIds.has(family.id)}
            onToggle={() => toggleFamily(family.id)}
            nextOwed={nextOwed}
            onPick={onPick}
            nowMs={nowMs}
            query={query}
          />
        ))}
      </div>

      {filteredFamilies.length === 0 && (
        <p
          role="status"
          style={{
            margin: 0,
            padding: "var(--space-5)",
            border: "1px solid var(--border-1)",
            borderRadius: "var(--radius-card)",
            color: "var(--fg-muted)",
            textAlign: "center",
          }}
        >
          No records match the current filters.
        </p>
      )}
    </section>
  );
}
