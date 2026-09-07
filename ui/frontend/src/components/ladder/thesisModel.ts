// Pure presentation model for grouping Ladder clusters by recorded research
// topic. Association comes only from exact cluster-member -> iteration_id ->
// seed.topic joins. Retrieval papers remain searchable evidence; they never
// establish family membership.
import type { LadderCluster } from "../../types/schemas";

const REPRESENTATION_TOPIC =
  "Representation in Peer Selection: A Liquid Democracy Perspective";
const POWER_TOPIC =
  "Power in Liquid Democracy: A Network Centrality Approach";
const LIQUID_DEMOCRACY_TOPICS = new Set([
  REPRESENTATION_TOPIC,
  POWER_TOPIC,
]);

const ITERATION_ID = /^iter-[A-Za-z0-9][A-Za-z0-9._:-]*$/;

export type FamilyAssociation =
  | "exact-topic"
  | "curated-topic-collection"
  | "individual";

export interface RecordedIteration {
  id: string;
  topic: string;
  hypothesis?: string;
  paperText: string[];
  evidenceText: string[];
  /** The validated input object itself. It is neither cloned nor changed. */
  source: Readonly<Record<string, unknown>>;
}

export interface FamilyRecord {
  /** The exact Ladder object supplied by the caller. */
  cluster: LadderCluster;
  id: string;
  /** Presentation/selection identity, distinct from an ambiguous source ID. */
  key: string;
  /** Nonblank ID occurs once in this received payload; not authenticated identity. */
  hasUniqueSourceId: boolean;
  /** Accessible presentation label only; never a scientific/source ID. */
  unverifiedSnapshotNumber?: number;
  title: string;
  topics: string[];
  iterations: RecordedIteration[];
  association: FamilyAssociation;
  reason: string;
  /** String member IDs that could not participate in a trusted join. */
  missingMembers: string[];
}

export interface ThesisFamily {
  id: string;
  title: string;
  basis: string;
  topicLabels: string[];
  records: FamilyRecord[];
}

export interface ThesisModel {
  families: ThesisFamily[];
  records: FamilyRecord[];
  issues: string[];
}

type IterationIndexEntry =
  | { kind: "resolved"; iteration: RecordedIteration }
  | { kind: "invalid"; reason: string }
  | { kind: "conflict" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function nonBlankText(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0
    ? value
    : undefined;
}

function normalizeTopic(topic: string): string {
  return topic.trim().replace(/\s+/g, " ");
}

function compareText(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function appendDistinctText(target: string[], value: unknown): void {
  const text = nonBlankText(value);
  if (text !== undefined && !target.includes(text)) target.push(text);
}

/** Stable JSON comparison for deciding whether duplicate rows are identical. */
function canonicalJson(value: unknown, seen = new Set<object>()): string | null {
  if (value === null) return "null";
  // Local/legacy fixtures can carry an explicit undefined optional field.
  // Keep it distinct from a string and from an absent key when fingerprinting.
  if (value === undefined) return "undefined";
  if (typeof value === "string" || typeof value === "boolean") {
    const encoded = JSON.stringify(value);
    return typeof encoded === "string" ? encoded : null;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    const encoded = JSON.stringify(value);
    return typeof encoded === "string" ? encoded : null;
  }
  if (typeof value !== "object" || seen.has(value)) return null;

  seen.add(value);
  let encoded: string | null;
  if (Array.isArray(value)) {
    const parts = value.map((item) => canonicalJson(item, seen));
    encoded = parts.some((part) => part === null)
      ? null
      : `[${parts.join(",")}]`;
  } else {
    const record = value as Record<string, unknown>;
    const parts: string[] = [];
    encoded = "";
    for (const key of Object.keys(record).sort(compareText)) {
      const item = canonicalJson(record[key], seen);
      const encodedKey = JSON.stringify(key);
      if (item === null || typeof encodedKey !== "string") {
        encoded = null;
        break;
      }
      parts.push(`${encodedKey}:${item}`);
    }
    if (encoded !== null) encoded = `{${parts.join(",")}}`;
  }
  seen.delete(value);
  return encoded;
}

function collectKnownEvidence(value: unknown, target: string[]): void {
  if (typeof value === "string") {
    appendDistinctText(target, value);
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) collectKnownEvidence(item, target);
    return;
  }
  if (!isRecord(value)) return;
  for (const key of ["text", "summary", "detail", "rationale", "claim", "result"]) {
    appendDistinctText(target, value[key]);
  }
}

function parseIteration(
  id: string,
  row: Record<string, unknown>,
): RecordedIteration | string {
  const seed = isRecord(row.seed) ? row.seed : null;
  const rawTopic = seed?.topic;
  if (typeof rawTopic !== "string") {
    return `Iteration "${id}" has no valid seed.topic`;
  }
  const topic = normalizeTopic(rawTopic);
  if (topic.length === 0) {
    return `Iteration "${id}" has no valid seed.topic`;
  }

  const hypothesisBlock = isRecord(row.hypothesis) ? row.hypothesis : null;
  const hypothesis = nonBlankText(hypothesisBlock?.text);

  const paperText: string[] = [];
  const retrieval = isRecord(row.retrieval) ? row.retrieval : null;
  const neighbors = Array.isArray(retrieval?.neighbors)
    ? retrieval.neighbors
    : [];
  for (const neighbor of neighbors) {
    if (!isRecord(neighbor)) continue;
    appendDistinctText(paperText, neighbor.title);
    appendDistinctText(paperText, neighbor.chunk_text);
    appendDistinctText(paperText, neighbor.abstract);
  }

  const evidenceText: string[] = [];
  collectKnownEvidence(row.evidence, evidenceText);
  collectKnownEvidence(row.experiment, evidenceText);
  collectKnownEvidence(row.critique, evidenceText);
  collectKnownEvidence(row.redteam, evidenceText);
  collectKnownEvidence(row.novelty, evidenceText);
  appendDistinctText(evidenceText, row.nara_summary);

  return {
    id,
    topic,
    ...(hypothesis === undefined ? {} : { hypothesis }),
    paperText,
    evidenceText,
    source: row,
  };
}

function iterationRowsOf(input: unknown, issues: Set<string>): unknown[] {
  if (Array.isArray(input)) return input;
  if (isRecord(input) && Array.isArray(input.iterations)) {
    return input.iterations;
  }
  issues.add(
    "Iteration rows payload is malformed; expected an array or an iterations array.",
  );
  return [];
}

function countMessage(
  count: number,
  singular: string,
  plural: string,
): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

function buildIterationIndex(
  input: unknown,
  issues: Set<string>,
): Map<string, IterationIndexEntry> {
  const buckets = new Map<string, Record<string, unknown>[]>();
  let malformedRows = 0;
  let invalidIds = 0;

  for (const value of iterationRowsOf(input, issues)) {
    if (!isRecord(value)) {
      malformedRows += 1;
      continue;
    }
    const id = value.iteration_id;
    if (typeof id !== "string" || !ITERATION_ID.test(id)) {
      invalidIds += 1;
      continue;
    }
    const bucket = buckets.get(id);
    if (bucket) bucket.push(value);
    else buckets.set(id, [value]);
  }

  if (malformedRows > 0) {
    issues.add(
      `Ignored ${countMessage(
        malformedRows,
        "malformed iteration row.",
        "malformed iteration rows.",
      )}`,
    );
  }
  if (invalidIds > 0) {
    issues.add(
      `Ignored ${countMessage(
        invalidIds,
        "row with an invalid iteration_id.",
        "rows with an invalid iteration_id.",
      )}`,
    );
  }

  const index = new Map<string, IterationIndexEntry>();
  for (const id of [...buckets.keys()].sort(compareText)) {
    const rows = buckets.get(id) ?? [];
    if (rows.length > 1) {
      const signatures = rows.map((row) => canonicalJson(row));
      if (
        signatures.some((signature) => signature === null) ||
        new Set(signatures).size !== 1
      ) {
        index.set(id, { kind: "conflict" });
        issues.add(
          `Conflicting duplicate iteration_id "${id}"; no joins to that ID are trusted.`,
        );
        continue;
      }
    }

    const parsed = parseIteration(id, rows[0]);
    if (typeof parsed === "string") {
      index.set(id, { kind: "invalid", reason: parsed });
      issues.add(`${parsed}; joins to it are not trusted.`);
    } else {
      index.set(id, { kind: "resolved", iteration: parsed });
    }
  }
  return index;
}

function clusterIdentity(cluster: LadderCluster): { id: string; title: string } {
  const raw: Record<string, unknown> = isRecord(cluster) ? cluster : {};
  const clusterId = nonBlankText(raw.cluster_id);
  const id = clusterId ?? "(ID unavailable)";
  const title = nonBlankText(raw.stem) ?? clusterId ?? "(unnamed cluster)";
  return { id, title };
}

function buildFamilyRecord(
  cluster: LadderCluster,
  iterationIndex: Map<string, IterationIndexEntry>,
): FamilyRecord {
  const { id, title } = clusterIdentity(cluster);
  const raw: Record<string, unknown> = isRecord(cluster) ? cluster : {};
  const rawMembers = raw.members;
  if (!Array.isArray(rawMembers)) {
    return {
      cluster,
      id,
      key: id,
      hasUniqueSourceId: false,
      title,
      topics: [],
      iterations: [],
      association: "individual",
      reason: "Members metadata is missing or malformed.",
      missingMembers: [],
    };
  }
  if (rawMembers.length === 0) {
    return {
      cluster,
      id,
      key: id,
      hasUniqueSourceId: false,
      title,
      topics: [],
      iterations: [],
      association: "individual",
      reason: "No members were recorded.",
      missingMembers: [],
    };
  }

  const memberIds = new Set<string>();
  let malformedMembers = 0;
  for (const member of rawMembers) {
    if (typeof member === "string") memberIds.add(member);
    else malformedMembers += 1;
  }

  const reasons: string[] = [];
  const unresolved = new Set<string>();
  const iterations: RecordedIteration[] = [];
  const unsupported: string[] = [];
  const missing: string[] = [];
  const invalid: string[] = [];
  const conflicts: string[] = [];

  if (malformedMembers > 0) {
    reasons.push(
      countMessage(
        malformedMembers,
        "member value is malformed.",
        "member values are malformed.",
      ),
    );
  }

  for (const member of memberIds) {
    if (!ITERATION_ID.test(member)) {
      unsupported.push(member);
      unresolved.add(member);
      continue;
    }
    const entry = iterationIndex.get(member);
    if (entry === undefined) {
      missing.push(member);
      unresolved.add(member);
    } else if (entry.kind === "conflict") {
      conflicts.push(member);
      unresolved.add(member);
    } else if (entry.kind === "invalid") {
      invalid.push(entry.reason);
      unresolved.add(member);
    } else {
      iterations.push(entry.iteration);
    }
  }

  if (unsupported.length > 0) {
    reasons.push(
      `Unsupported member ID${unsupported.length === 1 ? "" : "s"}: ${unsupported.join(
        ", ",
      )}; only iter-* members can establish an association.`,
    );
  }
  if (missing.length > 0) {
    reasons.push(
      `Missing iteration record${missing.length === 1 ? "" : "s"}: ${missing.join(
        ", ",
      )}.`,
    );
  }
  if (conflicts.length > 0) {
    reasons.push(
      `Conflicting duplicate iteration row${
        conflicts.length === 1 ? "" : "s"
      }: ${conflicts.join(", ")}.`,
    );
  }
  for (const reason of invalid) reasons.push(`${reason}.`);

  const topics = [...new Set(iterations.map((iteration) => iteration.topic))].sort(
    compareText,
  );
  if (topics.length > 1) {
    reasons.push(`Distinct members resolve to multiple exact topics: ${topics.join("; ")}.`);
  }
  if (memberIds.size === 0) {
    reasons.push("No valid string member IDs were recorded.");
  }

  if (reasons.length > 0 || topics.length !== 1) {
    if (reasons.length === 0) {
      reasons.push("Members do not resolve to one exact topic.");
    }
    return {
      cluster,
      id,
      key: id,
      hasUniqueSourceId: false,
      title,
      topics,
      iterations,
      association: "individual",
      reason: reasons.join(" "),
      missingMembers: [...unresolved].sort(compareText),
    };
  }

  const topic = topics[0];
  const curated = LIQUID_DEMOCRACY_TOPICS.has(topic);
  return {
    cluster,
    id,
    key: id,
      hasUniqueSourceId: false,
    title,
    topics,
    iterations,
    association: curated ? "curated-topic-collection" : "exact-topic",
    reason: curated
      ? "curated topic collection — association only"
      : "all distinct members resolve to one exact normalized seed.topic",
    missingMembers: [],
  };
}

function compareFamilyRecords(a: FamilyRecord, b: FamilyRecord): number {
  return (
    compareText(a.id, b.id) ||
    compareText(a.title, b.title) ||
    compareText(canonicalJson(a.cluster) ?? "", canonicalJson(b.cluster) ?? "")
  );
}

/**
 * Build stable presentation families without changing any Ladder or iteration
 * truth. Every supplied cluster appears in exactly one FamilyRecord and family.
 */
export function buildThesisFamilies(
  clusters: LadderCluster[],
  iterationRows: unknown,
): ThesisModel {
  const issues = new Set<string>();
  const safeClusters: LadderCluster[] = Array.isArray(clusters) ? clusters : [];
  if (!Array.isArray(clusters)) {
    issues.add("Clusters payload is malformed; expected an array.");
  }
  const iterationIndex = buildIterationIndex(iterationRows, issues);
  const records = safeClusters
    .map((cluster) => buildFamilyRecord(cluster, iterationIndex))
    .sort(compareFamilyRecords);

  // The backend normally supplies unique IDs. Faulty or legacy payloads must
  // still preserve separate rows without minting a source identity. These
  // snapshot keys are internal: the original ID remains the displayed id.
  const idCounts = new Map<string, number>();
  for (const record of records) {
    const id = isRecord(record.cluster) ? nonBlankText(record.cluster.cluster_id) : undefined;
    if (id !== undefined) idCounts.set(id, (idCounts.get(id) ?? 0) + 1);
  }
  const usedKeys = new Set(idCounts.keys());
  let unverifiedSnapshotNumber = 0;
  for (const record of records) {
    const sourceId = isRecord(record.cluster) ? nonBlankText(record.cluster.cluster_id) : undefined;
    record.hasUniqueSourceId = sourceId !== undefined && idCounts.get(sourceId) === 1;
    if (record.hasUniqueSourceId) continue;
    record.unverifiedSnapshotNumber = ++unverifiedSnapshotNumber;
    const reason = sourceId === undefined
      ? "Missing or malformed cluster ID; this row has no verified source identity."
      : `Duplicate cluster ID "${sourceId}"; these rows have ambiguous source identity.`;
    issues.add(reason);
    record.association = "individual";
    record.reason = `${reason} ${record.reason}`;
    // Canonical bytes avoid hash collisions. A suffix distinguishes identical
    // copies without pretending that they carry different scientific IDs.
    const snapshot = canonicalJson(record.cluster) ?? "unserializable input";
    let ordinal = 0;
    let key = `unverified:${snapshot}:${ordinal}`;
    while (usedKeys.has(key)) key = `unverified:${snapshot}:${++ordinal}`;
    usedKeys.add(key);
    record.key = key;
  }

  const grouped = new Map<string, ThesisFamily>();
  const individual: ThesisFamily[] = [];
  for (const record of records) {
    if (record.association === "individual") {
      individual.push({
        id: `record:${record.key}`,
        title: record.title,
        basis: record.reason,
        topicLabels: [...record.topics],
        records: [record],
      });
      continue;
    }

    const topic = record.topics[0];
    const curated = record.association === "curated-topic-collection";
    const familyId = curated ? "collection:liquid-democracy" : `topic:${topic}`;
    const existing = grouped.get(familyId);
    if (existing) {
      existing.records.push(record);
      if (!existing.topicLabels.includes(topic)) existing.topicLabels.push(topic);
    } else {
      grouped.set(familyId, {
        id: familyId,
        title: curated ? "Liquid democracy" : topic,
        basis: curated
          ? "curated topic collection — association only"
          : "exact iteration seed.topic",
        topicLabels: [topic],
        records: [record],
      });
    }
  }

  const families = [...grouped.values(), ...individual];
  for (const family of families) {
    family.records.sort(compareFamilyRecords);
    family.topicLabels.sort(compareText);
  }
  families.sort(
    (a, b) =>
      compareText(a.id, b.id) ||
      compareText(a.records[0]?.id ?? "", b.records[0]?.id ?? ""),
  );

  return { families, records, issues: [...issues].sort(compareText) };
}

/** Match only recorded identity/topic/claim/paper text, case-insensitively. */
export function matchesFamilyRecord(
  record: FamilyRecord,
  query: string,
): boolean {
  const needle = query.trim().toLowerCase();
  if (needle.length === 0) return true;

  const searchable = [record.id, record.title, ...record.topics];
  for (const iteration of record.iterations) {
    searchable.push(iteration.id, iteration.topic);
    if (iteration.hypothesis !== undefined) searchable.push(iteration.hypothesis);
    searchable.push(...iteration.paperText);
  }
  return searchable.some((value) => value.toLowerCase().includes(needle));
}
