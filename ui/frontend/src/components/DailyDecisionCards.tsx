import { useEffect, useRef, useState } from "react";
import {
  DailyOpsError,
  type DailyOpsDecisionAction,
  type DailyOpsDecisionPriority,
  type DailyOpsDecisionReceipt,
  type DailyOpsDecisionTarget,
} from "../api/dailyOps";

export type EvidenceKind = "estimate" | "measured" | "unrated";
export type WorkCardStatus = "authorized" | "in_progress" | "blocked" | "done" | "draft";

export type DailyWorkCard = {
  id: string;
  title: string;
  what: string;
  benefit: string;
  cost: { summary: string; kind: EvidenceKind; basis: string };
  conviction: { score: number | null; kind: EvidenceKind; basis: string };
  worthTime: {
    recommendation: "do_now" | "after_dependency" | "hold" | "unrated";
    basis: string;
  };
  status: WorkCardStatus;
  owner: "codex" | "oracle" | "nara" | "lab";
  dependsOn: string[];
  source: string;
  observedAt: string;
  actions: DailyOpsDecisionAction[];
};

export type DailyAgendaDecision = {
  id: string;
  agendaId: string;
  revision: string;
  title: string;
  what: string;
  reason: string;
  disposition: "amend_required" | "review_required";
  approveEnabled: boolean;
  actions: Exclude<DailyOpsDecisionAction, "reprioritize">[];
  taskTitles: string[];
  source: string;
  observedAt: string;
};

export type DailyDecisionRequest = {
  requestId: string;
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
};

const submitLabel: Record<DailyOpsDecisionAction, string> = {
  modify: "Queue modification request",
  skip: "Queue skip request",
  reprioritize: "Queue priority request",
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

function badgeStyle(value: string): React.CSSProperties {
  if (value === "done")
    return { color: "var(--status-ok)", background: "var(--status-ok-bg)" };
  if (["blocked", "amend_required", "review_required"].includes(value))
    return { color: "var(--status-warn)", background: "var(--status-warn-bg)" };
  if (["authorized", "in_progress"].includes(value))
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
  return <article data-testid={`daily-work-card-${card.id}`}
    className="rounded border border-[var(--border-1)] bg-[var(--surface-1)] p-3">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">{phrase(card.owner)}</p>
        <h4 className="mt-1 text-base font-semibold leading-snug">{card.title}</h4>
      </div>
      <div className="flex flex-wrap gap-1.5"><Badge value={card.status} />
        <Badge value={card.worthTime.recommendation}>{phrase(card.worthTime.recommendation)}</Badge></div>
    </div>

    <dl className="mt-3 grid gap-3 sm:grid-cols-2">
      <div className="sm:col-span-2"><dt className="text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">What</dt>
        <dd className="mt-1 text-sm">{card.what}</dd></div>
      <div className="sm:col-span-2"><dt className="text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">Benefit</dt>
        <dd className="mt-1 text-sm">{card.benefit}</dd></div>
      <div className="rounded bg-[var(--surface-2)] p-2.5"><dt className="text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">Cost</dt>
        <dd className="mt-1 text-sm font-medium">{card.cost.summary}</dd>
        <dd className="mt-1 text-xs text-[var(--fg-muted)]">{phrase(card.cost.kind)}</dd></div>
      <div className="rounded bg-[var(--surface-2)] p-2.5"><dt className="text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">Conviction</dt>
        <dd className="mt-1 text-sm font-medium">{card.conviction.score === null ? "Unrated" : `${card.conviction.score}/10`}</dd>
        <dd className="mt-1 text-xs text-[var(--fg-muted)]">{phrase(card.conviction.kind)}</dd></div>
    </dl>

    <details className="mt-3 text-xs text-[var(--fg-muted)]">
      <summary className="cursor-pointer text-[var(--accent)]">Basis, dependencies, and source</summary>
      <dl className="mt-2 grid gap-2">
        <div><dt className="font-semibold">Cost basis</dt><dd>{card.cost.basis}</dd></div>
        <div><dt className="font-semibold">Conviction basis</dt><dd>{card.conviction.basis} Conviction measures confidence that this work is worth doing, not the probability of scientific success.</dd></div>
        <div><dt className="font-semibold">Timing basis</dt><dd>{card.worthTime.basis}</dd></div>
        <div><dt className="font-semibold">Dependencies</dt><dd>{card.dependsOn.length ? card.dependsOn.join(" → ") : "None"}</dd></div>
        <div><dt className="font-semibold">Source</dt><dd>{card.source} · {timeLabel(card.observedAt)}</dd></div>
      </dl>
    </details>

    {card.actions.length > 0 && <div className="mt-3 flex flex-wrap gap-2" aria-label={`Actions for ${card.title}`}>
      {card.actions.map(action => <button key={action} type="button" disabled={!requestAvailable}
        aria-describedby={!requestAvailable ? "daily-decisions-readonly" : undefined}
        onClick={event => openEditor({ kind: "work_card", id: card.id, title: card.title, action }, event.currentTarget)}
        className="rounded border border-[var(--border-2)] px-3 py-1.5 text-sm text-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50">
        {actionLabel[action]}
      </button>)}
    </div>}
  </article>;
}

function AgendaCard({ agenda, requestAvailable, openEditor }: {
  agenda: DailyAgendaDecision;
  requestAvailable: boolean;
  openEditor: (target: EditorTarget, trigger: HTMLButtonElement) => void;
}) {
  return <article data-testid="daily-agenda-decision"
    className="mt-3 rounded border border-[var(--status-warn)] bg-[var(--status-warn-bg)] p-3">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div><p className="text-xs font-semibold uppercase tracking-wide text-[var(--status-warn)]">Agenda decision</p>
        <h4 className="mt-1 font-semibold">{agenda.title}</h4></div>
      <Badge value={agenda.disposition} />
    </div>
    <p className="mt-2 text-sm">{agenda.what}</p>
    <p className="mt-2 text-sm text-[var(--fg-muted)]"><span className="font-semibold text-[var(--fg)]">Why:</span> {agenda.reason}</p>
    <p id="agenda-approval-state" className="mt-2 text-xs text-[var(--fg-muted)]">
      This agenda cannot be approved. You can request a corrected draft or ask Oracle to skip it. Neither action executes work.
    </p>
    <details className="mt-2 text-xs text-[var(--fg-muted)]">
      <summary className="cursor-pointer text-[var(--accent)]">Revision, superseded proposal titles, and source</summary>
      <p className="mt-2 font-mono">revision {agenda.revision}</p>
      {agenda.taskTitles.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-5">
        {agenda.taskTitles.map(title => <li key={title}>{title}</li>)}
      </ul>}
      <p className="mt-2">{agenda.source} · {timeLabel(agenda.observedAt)}</p>
    </details>
    <div className="mt-3 flex flex-wrap gap-2" aria-label="Agenda actions">
      {agenda.actions.map(action => <button key={action} type="button" disabled={!requestAvailable}
        aria-describedby={!requestAvailable ? "daily-decisions-readonly" : undefined}
        onClick={event => openEditor({ kind: "agenda", id: agenda.id, title: agenda.title, action }, event.currentTarget)}
        className="rounded border border-[var(--border-2)] px-3 py-1.5 text-sm text-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50">
        {action === "modify" ? "Request corrected draft" : actionLabel[action]}
      </button>)}
    </div>
  </article>;
}

export function DailyDecisionCards({ cards, agenda, requestAvailable, canRequest, blockedReason, onRequireAccess, onRequest }: {
  cards: DailyWorkCard[];
  agenda: DailyAgendaDecision | null;
  requestAvailable: boolean;
  canRequest: boolean;
  blockedReason: string | null;
  onRequireAccess: () => void;
  onRequest: (request: DailyDecisionRequest) => Promise<DailyOpsDecisionReceipt>;
}) {
  const [editor, setEditor] = useState<EditorTarget | null>(null);
  const [note, setNote] = useState("");
  const [priority, setPriority] = useState<DailyOpsDecisionPriority>("next");
  const [submit, setSubmit] = useState<SubmitState>({ kind: "idle" });
  const [retry, setRetry] = useState<{ fingerprint: string; requestId: string } | null>(null);
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
    if (!editor || !canRequest || ["submitting", "queued"].includes(submit.kind) ||
        inFlightGeneration.current === generation ||
        (editor.action === "modify" && !note.trim())) return;
    const normalizedNote = note.trim();
    const fingerprint = JSON.stringify([
      editor.kind, editor.id, editor.action, normalizedNote,
      editor.action === "reprioritize" ? priority : null,
    ]);
    const ident = retry?.fingerprint === fingerprint ? retry.requestId : requestId();
    inFlightGeneration.current = generation;
    setSubmit({ kind: "submitting" });
    try {
      const receipt = await onRequest({
        requestId: ident,
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
      setRetry(uncertain ? { fingerprint, requestId: ident } : null);
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
          ? cards.every(card => ["authorized", "in_progress"].includes(card.status))
            ? "These steps are already authorized. No owner approval is needed."
            : "Review each card's recorded status before changing the plan."
          : "No reviewed work steps are available."}</p></div>
      <span className="text-xs text-[var(--fg-muted)]">{cards.length}/3 cards shown</span>
    </div>

    {cards.length > 0 ? <div className="mt-3 grid gap-3 xl:grid-cols-3">
      {cards.map(card => <WorkCard key={card.id} card={card} requestAvailable={requestAvailable} openEditor={openEditor} />)}
    </div> : <p className="mt-3 text-sm text-[var(--fg-muted)]">No source-bound work cards are available.</p>}

    {!requestAvailable && <p id="daily-decisions-readonly" data-testid="daily-decisions-readonly" className="mt-3 rounded border border-[var(--border-2)] p-2 text-sm text-[var(--fg-muted)]">
      Decision requests are read-only right now. The work plan remains visible.
    </p>}

    {agenda && <AgendaCard agenda={agenda} requestAvailable={requestAvailable} openEditor={openEditor} />}

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
          {editor.action === "modify" ? "Required change" : "Note (optional)"}
        </label>
        <textarea id="daily-decision-note" rows={3} maxLength={3000} value={note}
          onChange={event => { setNote(event.target.value); setSubmit({ kind: "idle" }); }}
          placeholder={editor.action === "modify" ? "What should change?" : "Add context for Oracle…"}
          className="mt-1 w-full rounded border border-[var(--border-2)] bg-[var(--surface-1)] px-3 py-2 text-sm" />
        <p className="mt-2 text-xs text-[var(--fg-muted)]">This sends owner direction to Oracle. It does not execute work or create scientific credit.</p>
        {!canRequest && <div className="mt-2 rounded border border-[var(--status-warn)] bg-[var(--status-warn-bg)] p-2 text-sm">
          <p>{blockedReason ?? "Owner decision controls are unavailable."}</p>
          <button type="button" onClick={onRequireAccess} className="mt-1 text-[var(--accent)]">Open owner access controls ↓</button>
        </div>}
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button type="submit" disabled={!canRequest || ["submitting", "queued"].includes(submit.kind) ||
            (editor.action === "modify" && !note.trim())}
            className="rounded bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-fg)] disabled:cursor-not-allowed disabled:opacity-50">
            {submit.kind === "submitting" ? "Sending…" : submitLabel[editor.action]}
          </button>
          {editor.action === "modify" && !note.trim() && <span className="text-xs text-[var(--fg-muted)]">Describe the change to continue.</span>}
        </div>
      </form>
      <div aria-live="polite" className="mt-2 min-h-5 text-sm">
        {submit.kind === "failed" && <p className="text-[var(--status-bad)]">{submit.message}</p>}
        {submit.kind === "queued" && <p className="text-[var(--status-info)]">
          {submit.receipt.duplicate ? "Existing request found" : "Request queued"} · {submit.receipt.request_id}. No execution is implied.
        </p>}
      </div>
    </section>}
  </section>;
}

export default DailyDecisionCards;
