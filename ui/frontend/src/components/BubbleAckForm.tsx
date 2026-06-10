// BubbleAckForm — acknowledge a coordinator bubble (B4, D-046-blessed).
// POSTs /api/attest/bubble_ack, which argv-execs
// `orchestrator.todo_cli ack --bubble-run-id <id> --by human:ui`; success
// stdout is the appended memory/coordinator_acks.jsonl row itself
// (`ack_by` = human:ui — `bubble_run_id` is the join key
// ui/backend/human_todo.py reads). Durable confirmation = the bubble item
// leaving the re-polled queue (contract principle 5). Required note; 502
// renders the CLI stderr VERBATIM; self-gates on the cached capability
// handshake like the sibling forms.
import { useState } from "react";
import {
  postBubbleAck,
  queueHasItem,
  useAttestCapability,
  useAttestSubmission,
} from "../api/attest";

const ACK_BUTTON =
  "rounded border border-emerald-800 bg-emerald-950 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-emerald-300 hover:bg-emerald-900 " +
  "disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-600";

interface Props {
  bubbleRunId: string;
  onResolved?: () => void;
}

export default function BubbleAckForm({ bubbleRunId, onResolved }: Props) {
  const capability = useAttestCapability();
  const { phase, submit } = useAttestSubmission();
  const [note, setNote] = useState("");

  if (capability === null) {
    return (
      <div data-testid="attest-checking" className="text-[10px] text-zinc-600">
        checking write-back availability…
      </div>
    );
  }
  if (capability.actions.bubble_ack !== true) {
    return (
      <div data-testid="attest-unavailable" className="text-[10px] text-zinc-600">
        in-UI bubble acknowledgement isn’t in this backend build — use the
        CLI fallback.
      </div>
    );
  }

  const submitting = phase.state === "submitting";
  const done = phase.state === "done";
  const disabled = submitting || note.trim().length === 0;

  const ack = () =>
    submit({
      exec: () => postBubbleAck({ bubble_run_id: bubbleRunId, note: note.trim() }),
      // bubble_ack / bubble_unacked are the same kind family (alias-folded).
      confirmed: (items) => !queueHasItem(items, "bubble_ack", bubbleRunId),
      onResolved,
    });

  return (
    <div data-testid="bubble-ack-form" className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-zinc-600">
        bubble ack · POST /api/attest/bubble_ack → orchestrator.todo_cli ack ·
        stamps human:ui
      </div>
      {!done && (
        <>
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            aria-label="bubble ack note (required)"
            placeholder="note (required — the audit value)"
            className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
          />
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <button type="button" disabled={disabled} onClick={ack} className={ACK_BUTTON}>
              ack
            </button>
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
          acknowledged
          {phase.stamp !== null && (
            <>
              {" — "}
              <span className="font-mono">{phase.stamp}</span>
            </>
          )}
          <span className="text-zinc-500">
            {" · "}
            {phase.confirmed
              ? "confirmed — item left the queue (re-poll)"
              : phase.repollError !== null
                ? `re-poll failed — confirmation unknown: ${phase.repollError}`
                : "row appended — item still listed in the queue (re-poll)"}
          </span>
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
