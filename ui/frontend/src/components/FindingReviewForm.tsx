// FindingReviewForm — one-shot finding disposition (B4, D-046-blessed).
// POSTs /api/attest/finding_review, which argv-execs
// `orchestrator.finding_session --set-status <id> <status> --by human:ui`.
// SUCCESS SHAPE DIFFERS from the other forms: the CLI prints an ENVELOPE
// {finding_id, session_id, outcome, loop_feedback_row, status_audit_row} —
// this form renders `status_audit_row` (its `changed_by` carries the
// human:ui stamp); `loop_feedback_row` is null for in_review. Do not assume
// the ledger-row shape here.
//
// Queue semantics per status (ui/backend/human_todo.py lists findings whose
// effective status is surfaced|in_review):
//   validated / rejected — the item LEAVES the queue; the re-poll confirming
//     its absence is the durable confirmation (contract principle 5).
//   in_review — the item STAYS listed by design (it is still awaiting human
//     interrogation); the envelope's status_audit_row is the recorded write
//     and the form says so honestly instead of claiming a departure.
//
// Self-gates on the page-load-cached GET /api/attest/available; required
// note (the audit value); 502 renders the CLI stderr VERBATIM.
import { useState } from "react";
import {
  postFindingReview,
  queueHasItem,
  statusAuditRowOf,
  useAttestCapability,
  useAttestSubmission,
  type FindingStatus,
} from "../api/attest";

const BUTTON_BASE =
  "rounded border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide " +
  "disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-600";

// Frozen enum (finding_session.QUICK_STATUSES): validated emerald,
// in_review amber (still open), rejected red.
const STATUS_TONES: Record<FindingStatus, string> = {
  validated: "border-emerald-800 bg-emerald-950 text-emerald-300 hover:bg-emerald-900",
  in_review: "border-amber-800 bg-amber-950 text-amber-300 hover:bg-amber-900",
  rejected: "border-red-800 bg-red-950 text-red-300 hover:bg-red-900",
};

const STATUS_ORDER: FindingStatus[] = ["validated", "in_review", "rejected"];

interface Props {
  findingId: string;
  onResolved?: () => void;
}

export default function FindingReviewForm({ findingId, onResolved }: Props) {
  const capability = useAttestCapability();
  const { phase, submit } = useAttestSubmission();
  const [note, setNote] = useState("");
  // The status the human clicked — drives the honest confirmation copy
  // (in_review keeps the item in the queue by design).
  const [chosen, setChosen] = useState<FindingStatus | null>(null);

  if (capability === null) {
    return (
      <div data-testid="attest-checking" className="text-[10px] text-zinc-600">
        checking write-back availability…
      </div>
    );
  }
  if (capability.actions.finding_review !== true) {
    return (
      <div data-testid="attest-unavailable" className="text-[10px] text-zinc-600">
        in-UI finding review isn’t in this backend build — use the CLI
        fallback.
      </div>
    );
  }

  const submitting = phase.state === "submitting";
  const done = phase.state === "done";
  const disabled = submitting || note.trim().length === 0;

  const submitStatus = (status: FindingStatus) => {
    setChosen(status);
    return submit({
      exec: () =>
        postFindingReview({ finding_id: findingId, status, note: note.trim() }),
      confirmed: (items) =>
        status === "in_review"
          ? // in_review keeps the finding listed — the recorded audit row is
            // the write; the queue intentionally still carries the item.
            queueHasItem(items, "finding_review", findingId)
          : !queueHasItem(items, "finding_review", findingId),
      onResolved,
    });
  };

  const auditRow = done ? statusAuditRowOf(phase.result) : null;

  return (
    <div data-testid="finding-review-form" className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-zinc-600">
        finding review · POST /api/attest/finding_review →
        orchestrator.finding_session --set-status · stamps human:ui
      </div>
      {!done && (
        <>
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            aria-label="finding review note (required)"
            placeholder="note (required — the audit value)"
            className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
          />
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {STATUS_ORDER.map((status) => (
              <button
                key={status}
                type="button"
                disabled={disabled}
                onClick={() => submitStatus(status)}
                className={`${BUTTON_BASE} ${STATUS_TONES[status]}`}
              >
                {status}
              </button>
            ))}
            {submitting && (
              <span data-testid="attest-submitting" className="text-[11px] text-zinc-500">
                submitting…
              </span>
            )}
          </div>
        </>
      )}

      {done && (
        <div data-testid="attest-success" className="mt-1 text-[11px] text-emerald-400">
          status recorded
          {phase.stamp !== null && (
            <>
              {" — "}
              <span className="font-mono">{phase.stamp}</span>
            </>
          )}
          <span className="text-zinc-500">
            {" · "}
            {chosen === "in_review"
              ? phase.confirmed
                ? "finding stays in the review queue (in_review, by design)"
                : phase.repollError !== null
                  ? `re-poll failed — queue state unknown: ${phase.repollError}`
                  : "queue no longer lists the finding (re-poll)"
              : phase.confirmed
                ? "confirmed — item left the queue (re-poll)"
                : phase.repollError !== null
                  ? `re-poll failed — confirmation unknown: ${phase.repollError}`
                  : "row appended — item still listed in the queue (re-poll)"}
          </span>
          {auditRow !== null && (
            <code
              data-testid="attest-audit-row"
              className="mt-1 block overflow-x-auto whitespace-pre rounded bg-zinc-900 px-2 py-1 font-mono text-[10px] text-zinc-400"
            >
              {JSON.stringify(auditRow)}
            </code>
          )}
        </div>
      )}

      {phase.state === "error" &&
        (phase.stderr !== null ? (
          <div className="mt-1">
            <div className="text-[10px] uppercase tracking-wide text-red-500">
              cli failed (rc {phase.rc ?? "?"}) — stderr verbatim
            </div>
            <pre
              data-testid="attest-stderr"
              className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded border border-red-900 bg-red-950/40 p-2 font-mono text-[11px] text-red-400"
            >
              {phase.stderr}
            </pre>
          </div>
        ) : (
          <div data-testid="attest-error" className="mt-1 text-[11px] text-red-400">
            {phase.detail}
          </div>
        ))}
    </div>
  );
}
