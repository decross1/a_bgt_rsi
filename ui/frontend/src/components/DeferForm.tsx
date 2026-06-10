// DeferForm — defer ANY queue item to the next dev session (B4, D-046).
// POSTs /api/attest/defer, which argv-execs `orchestrator.todo_cli defer
// --kind <kind> --ref-id <id> --by human:ui`; success stdout is the appended
// memory/dev_session_queue.jsonl row itself (`attested_by` = human:ui,
// `status` = "open").
//
// Works for EVERY blessed kind — including stale_active_run and state_gate,
// whose DIRECT resolution is not blessed (contract table row 5: process
// autopsy / state-file edits stay primary-session actions); for those two
// kinds defer is the ONLY in-UI action and the form says so. Item kinds
// normalize through the alias map (bubble_unacked→bubble_ack,
// state_file_gate→state_gate); an unknown kind renders NOTHING — the defer
// enum is frozen and the POST would 422.
//
// A deferral ASSIGNS the work; it does not resolve the item: the durable
// confirmation (contract principle 5) is the re-polled queue item carrying
// its additive `deferred: true` tag, not the item leaving. Required note;
// 502 renders the CLI stderr VERBATIM; renders as a quiet <details>
// disclosure so the primary action on the row stays primary.
import { useState } from "react";
import {
  deferKindOf,
  deferOnly,
  postDefer,
  queueHasDeferredItem,
  useAttestCapability,
  useAttestSubmission,
} from "../api/attest";

const DEFER_BUTTON =
  "rounded border border-sky-800 bg-sky-950 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-sky-300 hover:bg-sky-900 " +
  "disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-600";

interface Props {
  /** The queue item's kind — normalized to the frozen defer enum here. */
  kind: string;
  refId: string;
  onResolved?: () => void;
}

export default function DeferForm({ kind, refId, onResolved }: Props) {
  const capability = useAttestCapability();
  const { phase, submit } = useAttestSubmission();
  const [note, setNote] = useState("");

  const deferKind = deferKindOf(kind);
  // Unknown kind (frozen enum) or no defer capability: render nothing — the
  // item's CLI fallback disclosure is the remaining action surface.
  if (deferKind === null) return null;
  if (capability === null || capability.actions.defer !== true) return null;

  const submitting = phase.state === "submitting";
  const done = phase.state === "done";
  const disabled = submitting || note.trim().length === 0;

  const defer = () =>
    submit({
      exec: () => postDefer({ kind: deferKind, ref_id: refId, note: note.trim() }),
      // A deferral does NOT resolve the item — confirmation is the re-polled
      // item carrying its open-deferral tag (deferred: true).
      confirmed: (items) => queueHasDeferredItem(items, refId),
      onResolved,
    });

  return (
    <details data-testid="defer-form" className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1">
      <summary className="cursor-pointer list-none text-[10px] uppercase tracking-wide text-sky-500 hover:text-sky-400">
        defer to dev session
      </summary>
      <div className="pb-0.5">
        <div className="mt-1 text-[10px] uppercase tracking-wide text-zinc-600">
          POST /api/attest/defer → orchestrator.todo_cli defer · kind {deferKind} ·
          stamps human:ui
        </div>
        {deferOnly(kind) && (
          <div data-testid="defer-only-note" className="mt-0.5 text-[10px] text-zinc-500">
            direct resolution stays a primary-session action (not blessed) —
            defer is the only in-UI action for this kind.
          </div>
        )}
        {!done && (
          <>
            <input
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              aria-label="defer note (required)"
              placeholder="note (required — what the dev session should do)"
              className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
            />
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <button type="button" disabled={disabled} onClick={defer} className={DEFER_BUTTON}>
                defer
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
          <div data-testid="attest-success" className="mt-1 text-[11px] text-sky-400">
            deferred to dev session
            {phase.stamp !== null && (
              <>
                {" — "}
                <span className="font-mono">{phase.stamp}</span>
              </>
            )}
            <span className="text-zinc-500">
              {" · "}
              {phase.confirmed
                ? "tagged in the queue (re-poll) — a deferral assigns the work, it does not resolve the item"
                : phase.repollError !== null
                  ? `re-poll failed — confirmation unknown: ${phase.repollError}`
                  : "row appended — deferral tag not yet visible in the queue (re-poll)"}
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
    </details>
  );
}
