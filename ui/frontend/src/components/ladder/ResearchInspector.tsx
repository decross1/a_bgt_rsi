import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import RungGlyph from "../../design/RungGlyph";
import { ageLabel } from "../../ladderBar";
import type { LadderAgendaItem } from "../../types/schemas";
import { asText, dossierIdOf, isKilled, membersOf } from "./ladderModel";
import {
  researchEntriesForFamily,
  researchEntriesForRecord,
  researchContextForEntry,
} from "./researchContext";
import type {
  ResearchClaimContext,
  ResearchClaimEntry,
  ResearchEvidenceLine,
} from "./researchContext";
import type { FamilyRecord, ThesisFamily } from "./thesisModel";

const META: React.CSSProperties = {
  margin: 0,
  color: "var(--fg-muted)",
  fontSize: "var(--text-meta)",
};

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section style={{ marginTop: "var(--space-4)" }}>
      <h3
        style={{
          margin: "0 0 var(--space-2)",
          color: "var(--fg-muted)",
          fontSize: "var(--text-meta)",
          fontWeight: "var(--weight-medium)",
          letterSpacing: "0.05em",
          textTransform: "uppercase",
        }}
      >
        {label}
      </h3>
      {children}
    </section>
  );
}

function Axis({
  testId,
  label,
  value,
}: {
  testId: string;
  label: string;
  value: string;
}) {
  return (
    <div
      data-testid={testId}
      style={{
        minWidth: 0,
        padding: "var(--space-2)",
        border: "1px solid var(--border-1)",
        borderRadius: "var(--radius-control)",
        background: "var(--surface-1)",
      }}
    >
      <p style={{ ...META, fontWeight: "var(--weight-medium)" }}>{label}</p>
      <p style={{ margin: "var(--space-1) 0 0", color: "var(--fg)", fontSize: "var(--text-ui)" }}>
        {value}
      </p>
    </div>
  );
}

function EvidenceList({
  empty,
  lines,
}: {
  empty: string;
  lines: ResearchEvidenceLine[];
}) {
  if (lines.length === 0) return <p style={META}>{empty}</p>;
  return (
    <ul style={{ margin: 0, paddingLeft: "var(--space-4)" }}>
      {lines.map((line, index) => (
        <li key={`${line.label}:${index}`} style={{ marginTop: index === 0 ? 0 : "var(--space-2)" }}>
          <span style={{ color: "var(--fg)", fontSize: "var(--text-ui)", fontWeight: "var(--weight-medium)" }}>
            {line.label}
          </span>
          <p style={{ ...META, marginTop: "var(--space-1)", overflowWrap: "anywhere" }}>{line.text}</p>
        </li>
      ))}
    </ul>
  );
}

function ClaimCard({
  context,
  legacyOwedTestId,
}: {
  context: ResearchClaimContext;
  legacyOwedTestId: boolean;
}) {
  const killed = isKilled(context.record.cluster);
  const domIdentity = context.record.hasUniqueSourceId
    ? `${context.record.id}:${context.iterationId}`
    : `snapshot-${context.record.unverifiedSnapshotNumber ?? context.key}:${context.iterationId}`;
  const safeKey = domIdentity.replace(/[^A-Za-z0-9_.:-]+/g, "-");
  const claimTestId = context.isPinnedExactClaim
    ? `research-claim-${context.iterationId}`
    : `research-claim-context-${safeKey}`;
  return (
    <article
      data-testid={claimTestId}
      style={{
        minWidth: 0,
        padding: "var(--space-3)",
        border: "1px solid var(--border-1)",
        borderRadius: "var(--radius-card)",
        background: "var(--surface-2)",
        overflowWrap: "anywhere",
      }}
    >
      <div className="flex min-w-0 flex-wrap items-start" style={{ gap: "var(--space-2)" }}>
        <span
          aria-hidden="true"
          style={{
            width: 9,
            height: 9,
            marginTop: 6,
            flex: "none",
            borderRadius: "50%",
            background: context.isPinnedExactClaim ? "var(--accent)" : "var(--status-idle)",
            boxShadow: "0 0 0 4px var(--accent-muted)",
          }}
        />
        <div style={{ minWidth: 0, flex: 1 }}>
          <h3 style={{ margin: 0, color: "var(--fg)", fontSize: "var(--text-title)", fontWeight: "var(--weight-semibold)" }}>
            {context.shortLabel}
          </h3>
          <p style={{ ...META, marginTop: "var(--space-1)" }}>{context.summary}</p>
        </div>
      </div>

      <p style={{ margin: "var(--space-3) 0 0", color: "var(--fg)", fontSize: "var(--text-prose)", lineHeight: 1.55 }}>
        {context.hypothesis}
      </p>
      <div className="font-mono" style={{ ...META, marginTop: "var(--space-2)", overflowWrap: "anywhere" }}>
        <div>{context.iterationId}</div>
        <div>Source row ended: {context.sourceEndedAt}</div>
        <div>Recorded cluster event: {context.recordedEventAt}</div>
        {context.latestReviewAt !== undefined && <div>Dated automated review: {context.latestReviewAt} · inspected 2026-09-07</div>}
      </div>

      <div
        className="grid min-w-0 grid-cols-1 sm:grid-cols-2"
        style={{ gap: "var(--space-2)", marginTop: "var(--space-3)" }}
        aria-label="Independent research states"
      >
        <Axis testId="axis-claim-standing" label="Recorded claim standing" value={context.claimStanding} />
        <Axis testId="axis-application-fit" label="Application fit" value={context.applicationFit} />
        <Axis testId="axis-evidence-validity" label="Evidence validity" value={context.evidenceValidity} />
        <Axis testId="axis-execution-mode" label="Execution mode" value={context.executionMode} />
      </div>

      <section
        data-testid="evidence-delta"
        style={{
          marginTop: "var(--space-3)",
          padding: "var(--space-2) var(--space-3)",
          borderLeft: "3px solid var(--status-warn)",
          background: "var(--status-warn-bg)",
        }}
      >
        <h4 style={{ ...META, color: "var(--fg)", fontWeight: "var(--weight-medium)" }}>Evidence delta</h4>
        <p style={{ ...META, marginTop: "var(--space-1)", color: "var(--fg)" }}>{context.evidenceDelta}</p>
      </section>

      {context.rawOutcome.length > 0 && (
        <section data-testid="raw-recorded-outcome" style={{ marginTop: "var(--space-3)" }}>
          <h4 style={{ ...META, fontWeight: "var(--weight-medium)" }}>Raw recorded outcome · validity not inferred</h4>
          <EvidenceList empty="No raw outcome details." lines={context.rawOutcome} />
        </section>
      )}

      <details style={{ marginTop: "var(--space-3)", borderTop: "1px solid var(--border-1)", paddingTop: "var(--space-2)" }}>
        <summary style={{ color: "var(--accent)", cursor: "pointer", fontSize: "var(--text-ui)" }}>
          Recorded evidence and source qualification
        </summary>
        <div style={{ marginTop: "var(--space-3)" }}>
          <div data-testid="raw-provenance-fields" style={{ overflowWrap: "anywhere" }}>
            <h4 style={META}>Supplied provenance fields · raw values, not validated</h4>
            <EvidenceList empty="No provenance fields supplied in this projection." lines={context.provenanceFields} />
          </div>
          <h4 style={{ ...META, fontWeight: "var(--weight-medium)" }}>Recorded producer review · direction not inferred</h4>
          <p style={{ ...META, marginTop: "var(--space-1)" }}>
            Retrieval, novelty and critic fields can support, contradict or reject a claim. They explain the historical record but do not establish experimental validity.
          </p>
          <div style={{ marginTop: "var(--space-2)" }}>
            <EvidenceList empty="No supporting review detail is available in the received source." lines={context.supportingEvidence} />
          </div>
        </div>
        <div style={{ marginTop: "var(--space-3)" }}>
          <h4 style={{ ...META, color: "var(--status-bad)", fontWeight: "var(--weight-medium)" }}>Negative or limiting record</h4>
          <div style={{ marginTop: "var(--space-2)" }}>
            <EvidenceList empty="No negative evidence detail is available in the received source." lines={context.limitingEvidence} />
          </div>
        </div>
        {context.claimHash !== undefined && (
          <div className="font-mono" style={{ ...META, marginTop: "var(--space-3)", overflowWrap: "anywhere" }}>
            <div>claim SHA-256: {context.claimHash}</div>
            <div>raw row {context.sourceLine}: {context.rawRowHash}</div>
          </div>
        )}
      </details>

      <section style={{ marginTop: "var(--space-3)" }}>
        <h4 style={{ ...META, color: "var(--fg)", fontWeight: "var(--weight-medium)" }}>
          {context.isPinnedExactClaim ? "Dated blocker assessment · 2026-09-07" : "Blocker recorded in this source"}
        </h4>
        <p style={{ ...META, marginTop: "var(--space-1)", color: "var(--fg)" }}>{context.blocker}</p>
      </section>

      <section style={{ marginTop: "var(--space-3)" }}>
        <h4 style={{ ...META, color: "var(--fg)", fontWeight: "var(--weight-medium)" }}>Next discriminating test</h4>
        {context.proposedTest === undefined ? (
          <p style={{ ...META, marginTop: "var(--space-1)", color: "var(--fg)" }}>
            No claim-specific accepted test is supplied in this projection. Open the dossier before selecting a design.
          </p>
        ) : (
          <>
            <p style={{ ...META, marginTop: "var(--space-1)", color: "var(--status-warn)" }}>
              Dated engineering proposal · 2026-09-07 · not adopted protocol
            </p>
            <p style={{ ...META, marginTop: "var(--space-1)", color: "var(--fg)" }}>{context.proposedTest}</p>
          </>
        )}
      </section>

      {!killed && context.stageRequirement !== undefined && (
        <section style={{ marginTop: "var(--space-3)" }}>
          <h4 style={{ ...META, color: "var(--fg)", fontWeight: "var(--weight-medium)" }}>
            Stage requirement (generic), not a claim-specific accepted test
          </h4>
          <p
            {...(legacyOwedTestId ? { "data-testid": "ladder-peek-owed" } : {})}
            style={{ ...META, marginTop: "var(--space-1)", color: "var(--fg)" }}
          >
            {context.stageRequirement}
          </p>
        </section>
      )}

      <section style={{ marginTop: "var(--space-3)" }}>
        <h4 style={{ ...META, color: "var(--fg)", fontWeight: "var(--weight-medium)" }}>
          {context.isPinnedExactClaim ? "Dated decision proposal · 2026-09-07 · not a ruling" : "Decision state in this source"}
        </h4>
        <p style={{ ...META, marginTop: "var(--space-1)", color: "var(--fg)" }}>{context.decision}</p>
      </section>

      {context.iteration !== undefined && (
        <div style={{ marginTop: "var(--space-3)" }}>
          <Link
            to={`/dossier/${context.iterationId}`}
            aria-label={`Open full dossier for ${context.iterationId}`}
            style={{ color: "var(--accent)", fontSize: "var(--text-ui)" }}
          >
            Open full dossier →
          </Link>
        </div>
      )}
    </article>
  );
}

function RecordHistory({
  record,
  agenda,
  nowMs,
}: {
  record: FamilyRecord;
  agenda: LadderAgendaItem[];
  nowMs: number;
}) {
  const cluster = record.cluster;
  const killed = isKilled(cluster);
  const level = asText(cluster.evidence_level);
  const clusterId = asText(cluster.cluster_id) ?? "";
  const kill = cluster.kill_reason !== null && typeof cluster.kill_reason === "object" && !Array.isArray(cluster.kill_reason)
    ? cluster.kill_reason : null;
  const reopen = cluster.reopening_condition !== null && typeof cluster.reopening_condition === "object" && !Array.isArray(cluster.reopening_condition)
    ? cluster.reopening_condition : null;
  const mine = record.hasUniqueSourceId
    ? agenda.filter((item) => asText(item.cluster_id) === clusterId)
    : [];
  const members = membersOf(cluster);

  return (
    <>
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "var(--space-2)", color: "var(--fg-muted)", fontSize: "var(--text-meta)" }}>
        <RungGlyph level={cluster.evidence_level} killed={killed} />
        <span>{level ?? "no rung"}</span><span>·</span>
        <span>{asText(cluster.status) ?? "unknown"}</span><span>·</span>
        <span>{asText(cluster.origin) ?? "unknown origin"}</span><span>·</span>
        <span className="tnum">{ageLabel(cluster.last_event_ts, nowMs)}</span>
      </div>
      <p className="font-mono" style={{ ...META, marginTop: "var(--space-1)", overflowWrap: "anywhere" }}>{clusterId}</p>

      {killed && (
        <Section label="Recorded negative result">
          <div data-testid="ladder-peek-kill" style={{ color: "var(--fg)", fontSize: "var(--text-ui)" }}>
            <p className="font-mono" style={{ margin: 0, color: "var(--status-bad)" }}>{asText(kill?.code) ?? "unspecified"}</p>
            {asText(kill?.detail) !== null && <p style={{ margin: "var(--space-1) 0 0" }}>{asText(kill?.detail)}</p>}
            {asText(kill?.evidence_key) !== null && <p className="font-mono" style={{ ...META, marginTop: "var(--space-1)" }}>{asText(kill?.evidence_key)}</p>}
            <p data-testid="ladder-peek-reopen" style={{ margin: "var(--space-2) 0 0" }}>
              <span style={{ color: "var(--fg-muted)" }}>reopen when: </span>
              {asText(reopen?.evidence_kind) ?? asText(reopen?.requires) ?? "none recorded"}
            </p>
          </div>
        </Section>
      )}

      <Section label="Agenda">
        {!record.hasUniqueSourceId ? (
          <p style={META}>Agenda attribution withheld: this snapshot has no unique source ID in the received records. ID-keyed suggestions cannot be assigned to this specific snapshot.</p>
        ) : mine.length === 0 ? (
          <p style={META}>no open agenda items.</p>
        ) : (
          <ul data-testid="ladder-peek-agenda" style={{ margin: 0, paddingLeft: "var(--space-4)" }}>
            {mine.map((item, index) => (
              <li key={`${asText(item.topic) ?? "topic"}-${index}`} style={{ color: "var(--fg)", fontSize: "var(--text-ui)" }}>
                {asText(item.topic) ?? "(untitled)"}
                <span style={{ marginLeft: "var(--space-2)", color: "var(--fg-muted)", fontSize: "var(--text-meta)" }}>
                  {asText(item.source) ?? "unknown"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section label={`Members (${members.length})`}>
        {members.length === 0 ? <p style={META}>no members recorded.</p> : (
          <ul data-testid="ladder-peek-members" style={{ margin: 0, padding: 0, listStyle: "none" }}>
            {members.map((member) => {
              const dossierId = dossierIdOf(member);
              return (
                <li key={member} className="font-mono" style={{ ...META, padding: "2px 0" }}>
                  {dossierId === null
                    ? <span>{member}</span>
                    : <Link to={`/dossier/${dossierId}`} style={{ color: "var(--accent)" }}>{member}</Link>}
                </li>
              );
            })}
          </ul>
        )}
      </Section>
    </>
  );
}

function ContextSummaryButton({
  context,
  expanded,
  onToggle,
  kind,
}: {
  context: ResearchClaimContext;
  expanded: boolean;
  onToggle: () => void;
  kind: "exact" | "history" | "generic";
}) {
  const detailId = `research-detail-${context.key.replace(/[^A-Za-z0-9_.:-]+/g, "-")}`;
  const prefix = kind === "exact" ? "Inspect exact claim" : kind === "history" ? "Inspect other history" : "Inspect recorded entry";
  const recordIdentity = context.record.hasUniqueSourceId
    ? `record ${context.record.id}`
    : `unverified snapshot ${context.record.unverifiedSnapshotNumber ?? context.record.key}`;
  const applicationSummary = context.applicationFit.startsWith("Recorded source:")
    ? "application fit supplied"
    : "application fit unmapped";
  const executionSummary = context.executionMode.startsWith("Recorded source:")
    ? "execution mode supplied"
    : "execution mode unknown";
  return (
    <button
      type="button"
      data-testid={kind === "exact" ? `research-claim-summary-${context.iterationId}` : undefined}
      aria-label={`${prefix} ${recordIdentity}, iteration ${context.iterationId}: ${context.shortLabel}`}
      aria-expanded={expanded}
      aria-controls={expanded ? detailId : undefined}
      onClick={onToggle}
      style={{
        width: "100%",
        padding: "var(--space-3)",
        border: "1px solid",
        borderColor: expanded ? "var(--accent)" : "var(--border-1)",
        borderRadius: "var(--radius-card)",
        background: expanded ? "var(--accent-muted)" : "var(--surface-2)",
        color: "var(--fg)",
        cursor: "pointer",
        textAlign: "left",
      }}
    >
      <span style={{ display: "block", fontSize: "var(--text-ui)", fontWeight: "var(--weight-semibold)" }}>
        {context.shortLabel}
      </span>
      <span style={{ ...META, display: "block", marginTop: "var(--space-1)" }}>{context.summary}</span>
      <span className="font-mono" style={{ ...META, display: "block", marginTop: "var(--space-2)", overflowWrap: "anywhere" }}>
        {context.iterationId} · ended {context.sourceEndedAt}
      </span>
      {kind === "exact" && (
        <span style={{ ...META, display: "block", marginTop: "var(--space-1)" }}>
          {context.claimStanding} · {applicationSummary} · evidence validity unknown · {executionSummary}
        </span>
      )}
      <span style={{ ...META, display: "block", marginTop: "var(--space-2)", color: "var(--accent)" }}>
        {expanded ? "Hide recorded details" : "Show recorded details"}
      </span>
    </button>
  );
}

function FamilyContextBrowser({
  entries,
  exactLiquidSet,
  nextOwed,
}: {
  entries: ResearchClaimEntry[];
  exactLiquidSet: boolean;
  nextOwed: Record<string, string>;
}) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [page, setPage] = useState(0);
  const exactEntries = useMemo(() => exactLiquidSet
    ? entries.filter((entry) => entry.isPinnedExactClaim) : [], [entries, exactLiquidSet]);
  const otherEntries = useMemo(() => exactLiquidSet
    ? entries.filter((entry) => !entry.isPinnedExactClaim) : entries, [entries, exactLiquidSet]);
  const pageSize = 10;
  const lastPage = Math.max(0, Math.ceil(otherEntries.length / pageSize) - 1);
  const currentPage = Math.min(page, lastPage);
  const exactContexts = useMemo(() => exactEntries.map((entry) => researchContextForEntry(entry, nextOwed)), [exactEntries, nextOwed]);
  const visibleContexts = useMemo(() => historyOpen
    ? otherEntries.slice(currentPage * pageSize, (currentPage + 1) * pageSize)
      .map((entry) => researchContextForEntry(entry, nextOwed)) : [],
    [historyOpen, otherEntries, currentPage, nextOwed]);
  const selectedEntry = entries.find((entry) => entry.key === selectedKey);
  const selected = useMemo(() => selectedEntry === undefined ? undefined
    : researchContextForEntry(selectedEntry, nextOwed), [selectedEntry, nextOwed]);
  const toggle = (key: string) => setSelectedKey((current) => current === key ? null : key);
  const changePage = (value: number) => { setPage(value); setSelectedKey(null); };

  return (
    <>
      {exactLiquidSet && (
        <div
          data-testid="research-exact-claim-summaries"
          className="flex min-w-0 flex-col"
          style={{ gap: "var(--space-2)", marginTop: "var(--space-3)" }}
        >
          {exactContexts.map((context) => (
            <ContextSummaryButton
              key={context.key}
              context={context}
              expanded={selectedKey === context.key}
              onToggle={() => toggle(context.key)}
              kind="exact"
            />
          ))}
        </div>
      )}

      {selected !== undefined && exactLiquidSet && selected.isPinnedExactClaim && (
        <div
          id={`research-detail-${selected.key.replace(/[^A-Za-z0-9_.:-]+/g, "-")}`}
          data-testid="research-selected-detail"
          style={{ marginTop: "var(--space-3)" }}
        >
          <ClaimCard context={selected} legacyOwedTestId={false} />
        </div>
      )}

      {otherEntries.length > 0 && (
        <section style={{ marginTop: "var(--space-3)" }}>
          <button
            type="button"
            aria-expanded={historyOpen}
            aria-controls={historyOpen ? "research-other-histories" : undefined}
            onClick={() => setHistoryOpen((open) => !open)}
            style={{
              width: "100%",
              padding: "var(--space-2) var(--space-3)",
              border: "1px solid var(--border-1)",
              borderRadius: "var(--radius-control)",
              background: "var(--surface-1)",
              color: "var(--accent)",
              cursor: "pointer",
              fontSize: "var(--text-ui)",
              textAlign: "left",
            }}
          >
            {historyOpen ? "Hide" : "Show"} {otherEntries.length} {exactLiquidSet ? "other recorded histories" : "recorded entries"}
          </button>
          {historyOpen && (
            <div
              id="research-other-histories"
              data-testid="research-other-histories"
              style={{
                maxHeight: "42vh",
                marginTop: "var(--space-2)",
                padding: "var(--space-2)",
                border: "1px solid var(--border-1)",
                borderRadius: "var(--radius-card)",
                overflowY: "auto",
              }}
            >
              <div className="flex min-w-0 flex-col" style={{ gap: "var(--space-2)" }}>
                {visibleContexts.map((context) => (
                  <ContextSummaryButton
                    key={context.key}
                    context={context}
                    expanded={selectedKey === context.key}
                    onToggle={() => toggle(context.key)}
                    kind={exactLiquidSet ? "history" : "generic"}
                  />
                ))}
              </div>
              <nav aria-label="History pages" className="flex flex-wrap items-center gap-2" style={{ marginTop: "var(--space-3)" }}>
                <button type="button" aria-label="First histories" disabled={currentPage === 0} onClick={() => changePage(0)}>First</button>
                <button type="button" aria-label="Previous histories" disabled={currentPage === 0} onClick={() => changePage(currentPage - 1)}>Previous</button>
                <span role="status" style={META}>Entries {currentPage * pageSize + 1}–{Math.min((currentPage + 1) * pageSize, otherEntries.length)} of {otherEntries.length}</span>
                <button type="button" aria-label="Next histories" disabled={currentPage === lastPage} onClick={() => changePage(currentPage + 1)}>Next</button>
                <button type="button" aria-label="Last histories" disabled={currentPage === lastPage} onClick={() => changePage(lastPage)}>Last</button>
              </nav>
            </div>
          )}
          {historyOpen && selected !== undefined && (!exactLiquidSet || !selected.isPinnedExactClaim) && (
                <div
                  id={`research-detail-${selected.key.replace(/[^A-Za-z0-9_.:-]+/g, "-")}`}
                  data-testid="research-selected-history-detail"
                  style={{ marginTop: "var(--space-3)" }}
                >
                  <ClaimCard context={selected} legacyOwedTestId={false} />
                </div>
          )}
        </section>
      )}
    </>
  );
}

export default function ResearchInspector({
  family,
  record,
  agenda,
  nextOwed,
  nowMs,
}: {
  family?: ThesisFamily;
  record?: FamilyRecord;
  agenda: LadderAgendaItem[];
  nextOwed: Record<string, string>;
  nowMs: number;
}) {
  const entries = useMemo(() => family !== undefined
    ? researchEntriesForFamily(family)
    : record === undefined ? [] : researchEntriesForRecord(record), [family, record]);
  const exactLiquidEntries = entries.filter((entry) => entry.isPinnedExactClaim);
  const exactLiquidSet = family?.id === "collection:liquid-democracy"
    && exactLiquidEntries.length === 3
    && new Set(exactLiquidEntries.map((entry) => entry.iteration?.id)).size === 3;

  const body = (
    <div data-testid="research-inspector">
      {record !== undefined && <RecordHistory record={record} agenda={agenda} nowMs={nowMs} />}
      {family !== undefined && (
        <div
          role="note"
          style={{
            padding: "var(--space-2) var(--space-3)",
            border: "1px solid var(--border-1)",
            borderRadius: "var(--radius-control)",
            background: "var(--accent-muted)",
            color: "var(--fg)",
            fontSize: "var(--text-ui)",
          }}
        >
          {family.basis}. This collection groups recorded topics for navigation; it does not establish scientific equivalence, causal linkage, evidence validity or progress.
          {exactLiquidSet && " The LAB022/LAB024 readiness notes below are dated 2026-09-07 and cannot authenticate later attempts from this thin projection."}
        </div>
      )}

      <section
        data-testid="research-claim-overview"
        data-claim-count={entries.length}
        data-family-record-count={family?.records.length}
        data-featured-claim-count={exactLiquidSet ? 3 : 0}
        style={{ marginTop: record === undefined ? "var(--space-3)" : "var(--space-4)" }}
      >
        <div className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "var(--space-2)" }}>
          <h2 style={{ margin: 0, color: "var(--fg)", fontSize: "var(--text-title)", fontWeight: "var(--weight-semibold)" }}>
            {exactLiquidSet
              ? "Three distinct recorded claims"
              : `${entries.length} recorded claim ${entries.length === 1 ? "entry" : "entries"}`}
          </h2>
          <span style={META}>contextual inspector</span>
        </div>
        {exactLiquidSet && (
          <p style={{ ...META, marginTop: "var(--space-1)" }}>
            {family?.records.length} family records · {entries.length} received claim entries · 3 pinned claim summaries · {entries.length - 3} other histories
          </p>
        )}
        {family !== undefined || entries.length > 1 ? (
          <FamilyContextBrowser key={family?.id ?? record?.key} entries={entries} exactLiquidSet={exactLiquidSet} nextOwed={nextOwed} />
        ) : (
          <div className="flex min-w-0 flex-col" style={{ gap: "var(--space-3)", marginTop: "var(--space-3)" }}>
            {entries.map((entry) => researchContextForEntry(entry, nextOwed)).map((context) => (
              <ClaimCard
                key={context.key}
                context={context}
                legacyOwedTestId={record !== undefined && entries.length === 1}
              />
            ))}
          </div>
        )}
      </section>

      <div style={{ marginTop: "var(--space-4)", paddingTop: "var(--space-3)", borderTop: "1px solid var(--border-1)" }}>
        <Link to="/model-io#research-suggestions" style={{ color: "var(--accent)", fontSize: "var(--text-ui)" }}>
          Pending suggestions and ruling history
        </Link>
        <p style={{ ...META, marginTop: "var(--space-1)" }}>
          Suggestions and recorded rulings remain a separate review source; opening this inspector does not poll or adopt them.
        </p>
      </div>
    </div>
  );

  return record === undefined ? body : <div data-testid="ladder-peek-body">{body}</div>;
}
