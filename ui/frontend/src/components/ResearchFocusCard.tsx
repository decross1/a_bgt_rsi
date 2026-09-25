import { useId } from "react";
import { Link } from "react-router-dom";

const SHA = /^[0-9a-f]{64}$/;
const GIT_HEAD = /^[0-9a-f]{40}$/;
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/;
const LEVELS = new Set(["L0", "L1", "L2", "L3", "L4", "L5"]);
const STAGES = new Set([
  "needs_clean_refinement",
  "blocked",
]);

const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown, maximum: number): value is string =>
  typeof value === "string" && value.trim().length > 0 && value.length <= maximum;
const timestamp = (value: unknown): value is string =>
  typeof value === "string" && value.length <= 48 && Number.isFinite(Date.parse(value));

export interface SelectedResearchFocus {
  status: "selected";
  focusId: string;
  receiptSha256: string;
  title: string;
  sourceIterationId: string | null;
  sourceCampaignId: string | null;
  sourceEvidenceLevel: string | null;
  sourceRecordOrdinal: number | null;
  stage: string;
  nextAction: string;
  blockers: string[];
  sourceQuality: string;
  selectedAt: string;
  selectedBy: string;
  nextGate: {
    from: string;
    to: string;
    artifact: string;
    status: string;
    owner: string;
  };
  intakePolicy: string;
}

export type ResearchFocusView =
  | SelectedResearchFocus
  | { status: "none" }
  | { status: "source_invalid"; reason: string | null }
  | { status: "malformed" };

/**
 * Admit the receipt-bound focus projection without letting an arbitrary API
 * object become research truth in the UI. A malformed selection remains an
 * explicit unavailable state; it never falls back to a plausible-looking
 * title or rung.
 */
export function admitResearchFocus(value: unknown): ResearchFocusView {
  if (!object(value) || value.execution_authorized !== false) {
    return { status: "malformed" };
  }
  if (value.status === "none") return { status: "none" };
  if (value.status === "source_invalid") {
    return {
      status: "source_invalid",
      reason: text(value.reason, 240) ? value.reason : null,
    };
  }
  const gate = object(value.next_gate) ? value.next_gate : null;
  const blockers = value.blockers;
  const refs = value.evidence_refs;
  const sourceRef = Array.isArray(refs) && refs.length === 1 && object(refs[0])
    ? refs[0]
    : null;
  const commonInvalid = (
    value.status !== "selected" ||
    !ID.test(String(value.focus_id)) ||
    !SHA.test(String(value.receipt_sha256)) ||
    !text(value.title, 180) ||
    !(value.source_evidence_level === null || LEVELS.has(String(value.source_evidence_level))) ||
    !STAGES.has(String(value.stage)) ||
    !text(value.next_action, 900) ||
    !timestamp(value.selected_at) ||
    !text(value.selected_by, 120) ||
    !["focus_before_new_topics", "observe_only"].includes(String(value.intake_policy)) ||
    value.scientific_credit !== "none_selection_only" ||
    !Array.isArray(blockers) || blockers.length > 12 ||
    !blockers.every((item) => text(item, 600)) ||
    gate === null ||
    !text(gate.from, 80) || !text(gate.to, 80) ||
    !text(gate.artifact, 400) || !text(gate.owner, 400) ||
    !["pending", "blocked"].includes(String(gate.status))
  );
  if (commonInvalid) return { status: "malformed" };

  if (value.schema_version === "research-focus/v1") {
    if (!ID.test(String(value.source_iteration_id)) || !ID.test(String(value.source_campaign_id)) ||
        !SHA.test(String(value.source_row_sha256)) || !SHA.test(String(value.source_campaign_manifest_sha256)) ||
        typeof value.source_record_ordinal !== "number" || !Number.isInteger(value.source_record_ordinal) ||
        value.source_record_ordinal < 1 || sourceRef === null || sourceRef.path !== "memory/loop_memory.jsonl" ||
        sourceRef.iteration_id !== value.source_iteration_id || sourceRef.row_sha256 !== value.source_row_sha256 ||
        sourceRef.record_ordinal !== value.source_record_ordinal ||
        !["raw_structured_hypothesis", "plain_hypothesis", "missing_hypothesis"].includes(String(value.source_quality)) ||
        (value.source_quality === "plain_hypothesis") !== (value.source_evidence_level !== null)) return { status: "malformed" };
    return selected(value, String(value.source_iteration_id), String(value.source_campaign_id), value.source_record_ordinal);
  }
  if (value.schema_version !== "research-focus/v2" || value.source_quality !== "thesis_candidate_screen" ||
      value.source_evidence_level !== null || !SHA.test(String(value.candidate_set_sha256)) ||
      !SHA.test(String(value.screen_sha256)) || !SHA.test(String(value.meta_accept_sha256)) ||
      !GIT_HEAD.test(String(value.selection_head)) || !ID.test(String(value.chosen_candidate_id)) ||
      !text(value.selection_reason, 1800) || value.selected_by !== "oracle" ||
      !text(value.review_msg_id, 160) || !text(value.proposal_msg_id, 160) ||
      !SHA.test(String(value.review_row_sha256)) || !SHA.test(String(value.proposal_row_sha256)) ||
      !Number.isInteger(value.mailbox_cutoff_seq) || Number(value.mailbox_cutoff_seq) < 1 ||
      !SHA.test(String(value.mailbox_cutoff_sha256)) || !validGeneration(value.focus_generation) ||
      !validConvictions(value.initial_conviction_rows) || !validThesisRefs(refs, value)) return { status: "malformed" };
  return selected(value, null, null, null);
}

function validGeneration(value: unknown): boolean {
  if (!object(value) || Object.keys(value).length !== 2 ||
      !("active_receipt_sha256" in value) || !("last_closure_sha256" in value)) return false;
  const active = value.active_receipt_sha256;
  const closure = value.last_closure_sha256;
  if (active !== null && closure !== null) return false;
  return (active === null || SHA.test(String(active))) && (closure === null || SHA.test(String(closure)));
}

function validConvictions(value: unknown): boolean {
  if (!Array.isArray(value) || value.length !== 3) return false;
  const names = new Set<string>();
  for (const row of value) {
    if (!object(row) || Object.keys(row).length !== 2 || !["nara", "oracle", "claude"].includes(String(row.forecaster)) ||
        !SHA.test(String(row.row_sha256)) || names.has(String(row.forecaster))) return false;
    names.add(String(row.forecaster));
  }
  return names.size === 3;
}

function validThesisRefs(value: unknown, focus: Record<string, unknown>): boolean {
  if (!Array.isArray(value) || value.length !== 5 || !value.every(object)) return false;
  const [candidate, screen, acceptance, proposal, review] = value;
  return exactShaRef(candidate, "nara_candidate_set", focus.candidate_set_sha256)
    && exactShaRef(screen, "oracle_screen", focus.screen_sha256)
    && exactShaRef(acceptance, "meta_accept", focus.meta_accept_sha256)
    && exactMailboxRef(proposal, "oracle_proposal", focus.proposal_msg_id, focus.proposal_row_sha256)
    && exactMailboxRef(review, "meta_review", focus.review_msg_id, focus.review_row_sha256);
}

function exactShaRef(row: Record<string, unknown>, kind: string, digest: unknown): boolean {
  return Object.keys(row).length === 2 && row.kind === kind && row.sha256 === digest;
}

function exactMailboxRef(row: Record<string, unknown>, kind: string, messageId: unknown, digest: unknown): boolean {
  return Object.keys(row).length === 3 && row.kind === kind && row.msg_id === messageId && row.row_sha256 === digest;
}

function selected(value: Record<string, unknown>, sourceIterationId: string | null,
                  sourceCampaignId: string | null, sourceRecordOrdinal: number | null): SelectedResearchFocus {
  const blockers = value.blockers as string[];
  const gate = value.next_gate as Record<string, string>;
  return {
    status: "selected",
    focusId: String(value.focus_id),
    receiptSha256: String(value.receipt_sha256),
    title: String(value.title),
    sourceIterationId,
    sourceCampaignId,
    sourceEvidenceLevel: value.source_evidence_level === null
      ? null
      : String(value.source_evidence_level),
    sourceRecordOrdinal,
    stage: String(value.stage),
    nextAction: String(value.next_action),
    blockers: blockers as string[],
    sourceQuality: String(value.source_quality),
    selectedAt: String(value.selected_at),
    selectedBy: String(value.selected_by),
    nextGate: {
      from: String(gate.from),
      to: String(gate.to),
      artifact: String(gate.artifact),
      status: String(gate.status),
      owner: String(gate.owner),
    },
    intakePolicy: String(value.intake_policy),
  };
}

export function researchFocusFromStatus(value: unknown): unknown {
  return object(value) && value.schema === "research-ops-status/v1"
    ? value.research_focus
    : undefined;
}

function phrase(value: string): string {
  return value.replaceAll("_", " ");
}

function stageBadge(stage: string): string {
  return ({
    needs_clean_refinement: "Claim refinement",
    blocked: "Blocked",
  } as Record<string, string>)[stage] ?? phrase(stage);
}

export function ResearchFocusCard({ focus, className = "" }: {
  focus: unknown;
  className?: string;
}) {
  const headingId = useId();
  const view = admitResearchFocus(focus);

  if (view.status !== "selected") {
    const invalid = view.status === "source_invalid" || view.status === "malformed";
    return (
      <section
        data-testid="research-focus-card"
        data-focus-status={view.status}
        aria-labelledby={headingId}
        className={`${className} rounded-lg border border-[var(--border-1)] bg-[var(--surface-1)] p-4`}
      >
        <p className="text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">Research focus</p>
        <h2 id={headingId} className="mt-1 text-lg font-semibold">
          {invalid ? "Focus source needs review" : "No durable research focus selected"}
        </h2>
        <p className={`mt-2 text-sm ${invalid ? "text-[var(--status-warn)]" : "text-[var(--fg-muted)]"}`}>
          {view.status === "source_invalid"
            ? "The selected focus could not be verified against its source receipt. Research evidence and execution authority remain unchanged."
            : view.status === "malformed"
              ? "The focus projection did not match its contract. No title, stage, or authorization was inferred."
              : "Recorded theses remain available to browse, but none is adopted as the lab's next progression target."}
        </p>
        {view.status === "source_invalid" && view.reason !== null && (
          <p className="mt-2 font-mono text-xs text-[var(--fg-muted)]">Source note: {view.reason}</p>
        )}
      </section>
    );
  }

  const rawHypothesis = view.sourceQuality === "raw_structured_hypothesis";
  return (
    <section
      data-testid="research-focus-card"
      data-focus-status="selected"
      aria-labelledby={headingId}
      className={`${className} rounded-lg border border-[var(--group-research)] bg-[var(--surface-1)] p-4`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--group-research)]">Research focus · selected seed</p>
          <h2 id={headingId} className="mt-1 text-lg font-semibold leading-snug">{view.title}</h2>
          <p className="mt-2 text-sm text-[var(--fg-muted)]">
            {phrase(view.stage)} · {view.sourceEvidenceLevel === null
              ? view.sourceQuality === "thesis_candidate_screen" ? "receipt-bound thesis screen; no rung credit" : "no source rung"
              : `${view.sourceEvidenceLevel} historical derived source only`}
            {rawHypothesis ? " · historical seed unverified; no credit inherited" : ""}
          </p>
        </div>
        <span className="rounded border border-[var(--border-2)] px-2 py-1 text-xs text-[var(--fg-muted)]">
          {stageBadge(view.stage)}
        </span>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <div className="rounded border border-[var(--border-1)] p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">Next gate</p>
          <p className="mt-1 font-semibold">{phrase(view.nextGate.from)} → {phrase(view.nextGate.to)}</p>
          <p className="mt-2 text-sm">Produce: {view.nextGate.artifact}</p>
          <p className="mt-1 text-xs text-[var(--fg-muted)]">
            {phrase(view.nextGate.status)} · owner: {view.nextGate.owner}
          </p>
        </div>
        <div className="rounded border border-[var(--border-1)] p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">Next action</p>
          <p className="mt-1 text-sm">{view.nextAction}</p>
        </div>
      </div>

      {view.blockers.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">Blockers</p>
          <ul className="mt-1 list-disc pl-5 text-sm">
            {view.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}
          </ul>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-[var(--border-1)] pt-3 text-xs text-[var(--fg-muted)]">
        {view.sourceIterationId !== null && <Link
          className="text-[var(--accent)]"
          to={`/dossier/${encodeURIComponent(view.sourceIterationId)}?research_scope=all`}
        >
          Open source dossier →
        </Link>}
        {view.sourceIterationId !== null
          ? <><span>{view.sourceIterationId}</span><span>source record #{view.sourceRecordOrdinal}</span><span>source campaign {view.sourceCampaignId}</span></>
          : <span>candidate, screen, and meta-review receipts are bound; no legacy dossier is inferred.</span>}
        <span>Selecting a focus does not advance evidence or inherit source credit.</span>
        {view.intakePolicy === "focus_before_new_topics" && <span>focus before new topics</span>}
      </div>
    </section>
  );
}
