import { useEffect, useRef, useState } from "react";
import {
  DailyOpsError,
  type DailyOpsDecisionAction,
  type DailyOpsDecisionPriority,
  type DailyOpsDecisionReceipt,
  type DailyOpsDecisionTarget,
} from "../api/dailyOps";
import { cardHeadline, ownerWord, statusSentence } from "./dailyOpsCopy";

/** Live status of one plan item, derived from the lab mailbox and git (daily_ops_live.py). */
export type WorkStatus =
  | "not_started" | "awaiting_review" | "held" | "building" | "validated" | "failed"
  | "withdrawn" | "expired" | "amend_requested" | "accepted" | "rejected" | "merged"
  | "waiting_on_you" | "answered" | "resolved";

export type DailyWorkCard = {
  id: string;
  goal: string;
  owner: string;
  lane: string;
  repo: string;
  title: string;
  summary: string | null;
  whyToday: string | null;
  acceptance: string | null;
  dependsOn: string[];
  status: WorkStatus;
  detail: string;
  evidenceMsgId: string | null;
  evidenceSha: string | null;
  evidenceAt: string | null;
  actions: DailyOpsDecisionAction[];
};

export type DailyWaitingItem = {
  kind: "question" | "owner_decision";
  id: string;
  /** For a plan item, the plan item's own id (without the "<plan>:" prefix). */
  itemId: string;
  title: string;
  /** Exact prompt, separate from a short card label. */
  question: string;
  context: string | null;
  choices: string[];
  recommendation: string | null;
  consequence: string | null;
  askedBy: string;
  askedAt: string | null;
  msgId: string | null;
};

/** A non-action owner-question disposition, derived from an append-only mailbox row. */
export type DailyQuestionUpdate = {
  id: string;
  questionId: string;
  title: string;
  question: string;
  disposition: "withdrawn" | "superseded" | "prerequisite" | "informational";
  summary: string;
  reason: string;
  blockingArtifact: string | null;
  resolvedBy: string;
  resolvedAt: string;
  evidenceMsgIds: string[];
};

export type DailyDecisionRequest = {
  requestId: string;
  /** Bound when the request id is first made; retries must preserve it. */
  expectedPlanRevision: string;
  targetKind: DailyOpsDecisionTarget;
  targetId: string;
  action: DailyOpsDecisionAction;
  note?: string;
  priority?: DailyOpsDecisionPriority;
};

type EditorTarget = {
  kind: DailyOpsDecisionTarget;
  id: string;
  title: string;
  action: DailyOpsDecisionAction;
};

type SubmitState =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "failed"; message: string }
  | { kind: "queued"; receipt: DailyOpsDecisionReceipt };

const actionLabel: Record<DailyOpsDecisionAction, string> = {
  modify: "Ask to modify",
  skip: "Ask to skip",
  reprioritize: "Ask to reprioritize",
  approve: "Approve",
  decline: "Decline",
  defer: "Defer",
  reply: "Reply…",
};

const submitLabel: Record<DailyOpsDecisionAction, string> = {
  modify: "Queue modification request",
  skip: "Queue skip request",
  reprioritize: "Queue priority request",
  approve: "Send approval",
  decline: "Send decline",
  defer: "Send defer",
  reply: "Send reply",
};

const phrase = (value: string) => value.replaceAll("_", " ");

function requestId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

const statusLabel: Record<WorkStatus, string> = {
  not_started: "not started", awaiting_review: "awaiting review", held: "held", building: "building",
  validated: "validated", failed: "failed", withdrawn: "withdrawn", expired: "expired",
  amend_requested: "amend requested", accepted: "accepted", rejected: "rejected", merged: "merged",
  waiting_on_you: "waiting on you", answered: "answered", resolved: "resolved",
};

function badgeStyle(value: string): React.CSSProperties {
  if (["merged", "validated", "accepted", "answered", "resolved"].includes(value))
    return { color: "var(--status-ok)", background: "var(--status-ok-bg)" };
  if (["held", "failed", "rejected", "amend_requested", "waiting_on_you", "expired", "prerequisite"].includes(value))
    return { color: "var(--status-warn)", background: "var(--status-warn-bg)" };
  if (["building", "awaiting_review"].includes(value))
    return { color: "var(--status-info)", background: "var(--status-info-bg)" };
  return { color: "var(--status-idle)", background: "var(--status-idle-bg)" };
}

function Badge({ children, value }: { children?: React.ReactNode; value: string }) {
  return <span className="rounded-full px-2 py-0.5 text-[11px] font-medium"
    style={badgeStyle(value)}>{children ?? phrase(value)}</span>;
}

function timeLabel(value: string): string {
  return new Date(value).toLocaleString("en-US", {
    timeZone: "UTC", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  }) + " UTC";
}

function WorkCard({ card, requestAvailable, openEditor }: {
  card: DailyWorkCard;
  requestAvailable: boolean;
  openEditor: (target: EditorTarget, trigger: HTMLButtonElement) => void;
}) {
  const headline = cardHeadline(card.summary, card.title);
  const mergedAt = card.status === "merged" ? card.evidenceAt : null;
  return <article data-testid={`daily-work-card-${card.id}`}
    className="rounded border border-[var(--border-1)] bg-[var(--surface-1)] p-3">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">
          {card.goal} · {ownerWord(card.owner)}</p>
        <h4 className="mt-1 text-base font-semibold leading-snug" data-testid={`daily-work-card-${card.id}-headline`}>
          {headline}</h4>
      </div>
      <Badge value={card.status}>{statusLabel[card.status]}</Badge>
    </div>
    <p className="mt-2 text-sm text-[var(--fg-muted)]" data-testid={`daily-work-card-${card.id}-status`}>
      {statusSentence(card.status, mergedAt)}</p>

    <details className="mt-3 text-xs text-[var(--fg-muted)]">
      <summary className="cursor-pointer text-[var(--accent)]">Details</summary>
      <dl className="mt-2 grid gap-2">
        <div><dt className="font-semibold">Full title</dt><dd>{card.title}</dd></div>
        {card.whyToday && <div><dt className="font-semibold">Why today</dt><dd>{card.whyToday}</dd></div>}
        {card.acceptance && <div><dt className="font-semibold">Acceptance</dt><dd>{card.acceptance}</dd></div>}
        <div><dt className="font-semibold">Item · lane · repo</dt><dd>{card.id} · {phrase(card.lane)} · {card.repo}</dd></div>
        <div><dt className="font-semibold">Depends on</dt><dd>{card.dependsOn.length ? card.dependsOn.join(", ") : "None"}</dd></div>
        <div><dt className="font-semibold">Ledger status</dt><dd>{card.detail}</dd></div>
        {(card.evidenceSha || card.evidenceMsgId) && <div><dt className="font-semibold">Evidence</dt>
          <dd>{[card.evidenceSha && `sha ${card.evidenceSha}`, card.evidenceMsgId].filter(Boolean).join(" · ")}
            {card.evidenceAt ? ` · ${timeLabel(card.evidenceAt)}` : ""}</dd></div>}
      </dl>
    </details>

    {card.actions.length > 0 && <div className="mt-3 flex flex-wrap gap-2" aria-label={`Actions for ${headline}`}>
      {card.actions.map(action => <button key={action} type="button" disabled={!requestAvailable}
        aria-describedby={!requestAvailable ? "daily-decisions-readonly" : undefined}
        onClick={event => openEditor({ kind: "work_card", id: card.id, title: headline, action }, event.currentTarget)}
        className="rounded border border-[var(--border-2)] px-3 py-1.5 text-sm text-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50">
        {actionLabel[action]}
      </button>)}
    </div>}
  </article>;
}

const WAITING_ACTIONS: DailyOpsDecisionAction[] = ["approve", "decline", "defer", "reply"];

function WaitingOnYou({ items, requestAvailable, openEditor }: {
  items: DailyWaitingItem[];
  requestAvailable: boolean;
  openEditor: (target: EditorTarget, trigger: HTMLButtonElement) => void;
}) {
  return <section aria-labelledby="daily-waiting-heading" data-testid="daily-waiting-on-you"
    className="mt-4 rounded border border-[var(--status-warn)] p-3">
    <h3 id="daily-waiting-heading" className="text-base font-semibold">Waiting on you</h3>
    {items.length === 0 ? <p className="mt-1 text-sm text-[var(--fg-muted)]">
      No open owner question in the lab mailbox and no owner decision in today&apos;s plan.</p> :
      <ul className="mt-2 space-y-3">{items.map(item => {
        const headline = item.title;
        // A plan-linked card is still a reply to its concrete mailbox question.
        // Routing it as a work card creates an unrelated note and cannot close
        // the question that made the card actionable.
        const targetKind: DailyOpsDecisionTarget = "question";
        const targetId = item.msgId ?? item.id;
        const canAct = item.msgId != null;
        // Card kind controls the badge, while source shape controls the actions:
        // structured choices get one reply path; cards without choices retain
        // the established approve/decline/defer/reply decision affordances.
        const actions: DailyOpsDecisionAction[] = item.choices.length > 0 ? ["reply"] : WAITING_ACTIONS;
        return <li key={item.id} data-testid={`daily-waiting-${item.id}`}>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium">{headline}</span>
            <Badge value="waiting_on_you">{item.kind === "question" ? "question" : "plan decision"}</Badge>
          </div>
          <p className="mt-1 text-xs text-[var(--fg-muted)]">Asked by {ownerWord(item.askedBy)}
            {item.askedAt ? ` · ${timeLabel(item.askedAt)}` : ""}</p>
          {item.question !== headline && <p className="mt-2 text-sm"
            data-testid={`daily-waiting-${item.id}-question`}>{item.question}</p>}
          {item.context && <p className="mt-2 text-sm text-[var(--fg-muted)]">{item.context}</p>}
          {item.choices.length > 0 && <div className="mt-2 text-sm">
            <p className="font-medium">Choices</p>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-[var(--fg-muted)]">
              {item.choices.map((choice, index) => <li key={`${item.id}-${index}`}>{choice}</li>)}
            </ul>
          </div>}
          {item.recommendation && <p className="mt-2 text-sm"><span className="font-medium">Recommendation: </span>{item.recommendation}</p>}
          {item.consequence && <p className="mt-2 text-sm text-[var(--fg-muted)]"><span className="font-medium">If deferred: </span>{item.consequence}</p>}
          <details className="mt-1 text-xs text-[var(--fg-muted)]">
            <summary className="cursor-pointer text-[var(--accent)]">Details</summary>
            <dl className="mt-2 grid gap-1">
              <div><dt className="inline font-semibold">Card label: </dt><dd className="inline">{item.title}</dd></div>
              {item.msgId && <div><dt className="inline font-semibold">Message: </dt><dd className="inline">{item.msgId}</dd></div>}
            </dl>
          </details>
          {canAct ? <div className="mt-2 flex flex-wrap gap-2" aria-label={`Actions for ${headline}`}>
            {actions.map(action => <button key={action} type="button" disabled={!requestAvailable}
              aria-describedby={!requestAvailable ? "daily-decisions-readonly" : undefined}
              onClick={event => openEditor({ kind: targetKind, id: targetId, title: headline, action }, event.currentTarget)}
              className="rounded border border-[var(--border-2)] px-3 py-1.5 text-sm text-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50">
              {action === "reply" && item.choices.length > 0 ? "Choose / reply" : actionLabel[action]}
            </button>)}
          </div> : <p className="mt-2 text-xs text-[var(--fg-muted)]">No open mailbox question exists yet for this plan item; use the plan item&apos;s buttons above once one is asked, or send Oracle a note.</p>}
        </li>;
      })}</ul>}
  </section>;
}

function QuestionUpdates({ updates }: { updates: DailyQuestionUpdate[] }) {
  if (updates.length === 0) return null;
  return <section aria-labelledby="daily-question-updates-heading" data-testid="daily-question-updates"
    className="mt-4 rounded border border-[var(--border-1)] bg-[var(--surface-1)] p-3">
    <h3 id="daily-question-updates-heading" className="text-base font-semibold">Updated / prerequisites</h3>
    <ul className="mt-2 space-y-3">{updates.map(update => <li key={update.id}
      data-testid={`daily-question-update-${update.id}`} className="text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{update.title}</span>
        <Badge value={update.disposition}>{phrase(update.disposition)}</Badge>
      </div>
      <p className="mt-1">{update.summary}</p>
      <p className="mt-1 text-xs text-[var(--fg-muted)]">Why: {update.reason}</p>
      {update.blockingArtifact && <p className="mt-1 text-xs text-[var(--fg-muted)]">Blocking artifact: {update.blockingArtifact}</p>}
      <p className="mt-1 text-xs text-[var(--fg-muted)]">Updated by {ownerWord(update.resolvedBy)} · {timeLabel(update.resolvedAt)} · source {update.id}
        {update.evidenceMsgIds.length > 0 ? ` · evidence ${update.evidenceMsgIds.join(", ")}` : ""}</p>
    </li>)}</ul>
  </section>;
}

export function DailyDecisionCards({ cards, waiting, updates, planRevision, requestAvailable, readonlyReason, canRequest, blockedReason, onRequireAccess, onRequest }: {
  cards: DailyWorkCard[];
  waiting: DailyWaitingItem[];
  updates: DailyQuestionUpdate[];
  planRevision: string | null;
  requestAvailable: boolean;
  readonlyReason: string;
  canRequest: boolean;
  blockedReason: string | null;
  onRequireAccess: () => void;
  onRequest: (request: DailyDecisionRequest) => Promise<DailyOpsDecisionReceipt>;
}) {
  const [editor, setEditor] = useState<EditorTarget | null>(null);
  const [note, setNote] = useState("");
  const [priority, setPriority] = useState<DailyOpsDecisionPriority>("next");
  const [submit, setSubmit] = useState<SubmitState>({ kind: "idle" });
  const [retry, setRetry] = useState<{
    fingerprint: string;
    requestId: string;
    expectedPlanRevision: string;
  } | null>(null);
  const editorRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const editorGeneration = useRef(0);
  const inFlightGeneration = useRef<number | null>(null);

  useEffect(() => {
    if (editor) editorRef.current?.focus();
  }, [editor]);

  useEffect(() => () => {
    editorGeneration.current += 1;
  }, []);

  function openEditor(target: EditorTarget, trigger: HTMLButtonElement) {
    editorGeneration.current += 1;
    triggerRef.current = trigger;
    setEditor(target);
    setNote("");
    setPriority("next");
    setSubmit({ kind: "idle" });
    setRetry(null);
  }

  function closeEditor() {
    editorGeneration.current += 1;
    setEditor(null);
    setNote("");
    setSubmit({ kind: "idle" });
    setRetry(null);
    window.setTimeout(() => triggerRef.current?.focus(), 0);
  }

  async function send(event: React.FormEvent) {
    event.preventDefault();
    const generation = editorGeneration.current;
    if (!editor || !planRevision || !canRequest || ["submitting", "queued"].includes(submit.kind) ||
        inFlightGeneration.current === generation ||
        (["modify", "reply"].includes(editor.action) && !note.trim())) return;
    const normalizedNote = note.trim();
    const fingerprint = JSON.stringify([
      editor.kind, editor.id, editor.action, normalizedNote,
      editor.action === "reprioritize" ? priority : null,
    ]);
    const prior = retry?.fingerprint === fingerprint ? retry : null;
    // Keep the revision paired with its request id. A summary poll may observe
    // a newer plan after a lost response, but this click is still a retry of
    // the original durable request, not a new decision on the newer plan.
    const ident = prior?.requestId ?? requestId();
    const expectedPlanRevision = prior?.expectedPlanRevision ?? planRevision;
    inFlightGeneration.current = generation;
    setSubmit({ kind: "submitting" });
    try {
      const receipt = await onRequest({
        requestId: ident,
        expectedPlanRevision,
        targetKind: editor.kind,
        targetId: editor.id,
        action: editor.action,
        ...(normalizedNote ? { note: normalizedNote } : {}),
        ...(editor.action === "reprioritize" ? { priority } : {}),
      });
      if (editorGeneration.current !== generation) return;
      setRetry(null);
      setSubmit({ kind: "queued", receipt });
    } catch (error) {
      if (editorGeneration.current !== generation) return;
      const detail = error instanceof DailyOpsError ? error.detail : String(error);
      const uncertain = !(error instanceof DailyOpsError) || error.status >= 500;
      setRetry(uncertain ? { fingerprint, requestId: ident, expectedPlanRevision } : null);
      setSubmit({ kind: "failed", message: uncertain
        ? `Delivery unconfirmed; retry safely with the same request ID. ${detail}`
        : error instanceof DailyOpsError && error.status === 409
          ? `This decision is stale. Refresh and review the current card. ${detail}`
          : `Decision request rejected: ${detail}` });
    } finally {
      if (inFlightGeneration.current === generation) inFlightGeneration.current = null;
    }
  }

  return <section aria-labelledby="daily-work-heading" data-testid="daily-decision-cards">
    <div className="flex flex-wrap items-end justify-between gap-2">
      <div><h3 id="daily-work-heading" className="text-base font-semibold">Today&apos;s work</h3>
        <p className="mt-1 text-sm text-[var(--fg-muted)]">{cards.length > 0
          ? "Every item of the plan of record, with its live status from the lab mailbox and main."
          : "The plan of record has no items."}</p></div>
      <span className="text-xs text-[var(--fg-muted)]">{cards.length} item{cards.length === 1 ? "" : "s"}</span>
    </div>

    {cards.length > 0 && <div className="mt-3 grid gap-3 xl:grid-cols-2">
      {cards.map(card => <WorkCard key={card.id} card={card} requestAvailable={requestAvailable} openEditor={openEditor} />)}
    </div>}

    {!requestAvailable && <p id="daily-decisions-readonly" data-testid="daily-decisions-readonly" className="mt-3 rounded border border-[var(--border-2)] p-2 text-sm text-[var(--fg-muted)]">
      {readonlyReason}
    </p>}

      <WaitingOnYou items={waiting} requestAvailable={requestAvailable} openEditor={openEditor} />
      <QuestionUpdates updates={updates} />

    {editor && <section ref={editorRef} tabIndex={-1} data-testid="daily-decision-editor"
      aria-labelledby="daily-decision-editor-heading"
      className="mt-3 rounded border border-[var(--accent)] bg-[var(--surface-2)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><p className="text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">Owner direction · {phrase(editor.kind)}</p>
          <h4 id="daily-decision-editor-heading" className="mt-1 font-semibold">{actionLabel[editor.action]} · {editor.title}</h4></div>
        <button type="button" onClick={closeEditor} className="rounded px-2 py-1 text-sm text-[var(--accent)]">Cancel</button>
      </div>
      <form onSubmit={send} className="mt-3">
        {editor.action === "reprioritize" && <label className="block text-sm font-medium">Priority
          <select value={priority} onChange={event => setPriority(event.target.value as DailyOpsDecisionPriority)}
            className="mt-1 block rounded border border-[var(--border-2)] bg-[var(--surface-1)] px-3 py-2 text-sm">
            <option value="now">Now</option><option value="next">Next</option><option value="later">Later</option>
          </select></label>}
        <label htmlFor="daily-decision-note" className="block text-sm font-medium">
          {editor.action === "modify" ? "Required change" : editor.action === "reply" ? "Your reply" : "Note (optional)"}
        </label>
        <textarea id="daily-decision-note" rows={3} maxLength={3000} value={note}
          onChange={event => { setNote(event.target.value); setSubmit({ kind: "idle" }); }}
          placeholder={editor.action === "modify" ? "What should change?" : editor.action === "reply" ? "Write your reply…" : "Add context for Oracle…"}
          className="mt-1 w-full rounded border border-[var(--border-2)] bg-[var(--surface-1)] px-3 py-2 text-sm" />
        <p className="mt-2 text-xs text-[var(--fg-muted)]">This sends owner direction to Oracle. It does not execute work or create scientific credit.</p>
        {!canRequest && <div className="mt-2 rounded border border-[var(--status-warn)] bg-[var(--status-warn-bg)] p-2 text-sm">
          <p>{blockedReason ?? "Owner decision controls are unavailable."}</p>
          <button type="button" onClick={onRequireAccess} className="mt-1 text-[var(--accent)]">Open owner access controls ↓</button>
        </div>}
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button type="submit" disabled={!canRequest || ["submitting", "queued"].includes(submit.kind) ||
            (["modify", "reply"].includes(editor.action) && !note.trim())}
            className="rounded bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-fg)] disabled:cursor-not-allowed disabled:opacity-50">
            {submit.kind === "submitting" ? "Sending…" : submitLabel[editor.action]}
          </button>
          {["modify", "reply"].includes(editor.action) && !note.trim() && <span className="text-xs text-[var(--fg-muted)]">{editor.action === "modify" ? "Describe the change to continue." : "Write a reply to continue."}</span>}
        </div>
      </form>
      <div aria-live="polite" className="mt-2 min-h-5 text-sm">
        {submit.kind === "failed" && <p className="text-[var(--status-bad)]">{submit.message}</p>}
        {submit.kind === "queued" && <p className="text-[var(--status-info)]">
          {submit.receipt.duplicate ? "Already sent to Oracle" : "Sent to Oracle"}. No execution is implied.{" "}
          <details className="inline text-xs text-[var(--fg-muted)]">
            <summary className="inline cursor-pointer text-[var(--accent)]">Request id</summary>
            {" "}{submit.receipt.request_id}
          </details>
        </p>}
      </div>
    </section>}
  </section>;
}

export default DailyDecisionCards;
