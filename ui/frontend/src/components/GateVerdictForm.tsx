// GateVerdictForm — in-UI Step-8 gate attestation (B4, D-046-blessed).
// POSTs /api/attest/gate_verdict, which argv-execs orchestrator.gate_cli
// with `--gated-by human:ui`; the CLI is the writer of record. The POST
// response is the appended loop_feedback ledger row, but the DURABLE
// confirmation is the queue: after success this form re-polls
// GET /api/human_todo and reports whether the item left it (contract
// principle 5 — encoded in useAttestSubmission).
//
// Props are FROZEN at {iterationId, onResolved} — the iteration detail
// modal's gate panel mounts this form too (a different integrator), so it
// self-gates on the page-load-cached GET /api/attest/available: when the
// capability is absent (available:false, or a 404 from an older backend),
// it renders a quiet zinc fallback note, never a broken submit surface.
//
// Three verdict buttons (frozen enum, schema/loop_feedback.schema.json):
// valid = emerald, needs_revision = amber, invalid = red. The note is
// REQUIRED — every button stays disabled while it is empty (the CLI permits
// an empty gate note, but the note is the audit value; the UI requires it).
// A 502 renders the CLI's stderr VERBATIM in a red mono block.
import { useState } from "react";
import {
  postGateVerdict,
  queueHasItem,
  useAttestCapability,
  useAttestSubmission,
  type GateVerdict,
} from "../api/attest";

const BUTTON_BASE =
  "rounded border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide " +
  "disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-600";

// Frozen-enum tones: valid emerald, needs_revision amber, invalid red.
const VERDICT_TONES: Record<GateVerdict, string> = {
  valid: "border-emerald-800 bg-emerald-950 text-emerald-300 hover:bg-emerald-900",
  needs_revision: "border-amber-800 bg-amber-950 text-amber-300 hover:bg-amber-900",
  invalid: "border-red-800 bg-red-950 text-red-300 hover:bg-red-900",
};

// Render order: the safe affirmation first, the destructive verdict last.
const VERDICT_ORDER: GateVerdict[] = ["valid", "needs_revision", "invalid"];

interface Props {
  iterationId: string;
  onResolved?: () => void;
}

export default function GateVerdictForm({ iterationId, onResolved }: Props) {
  const capability = useAttestCapability();
  const { phase, submit } = useAttestSubmission();
  const [note, setNote] = useState("");

  // Capability unresolved: quiet placeholder (one microtask in practice —
  // the handshake is cached per page-load).
  if (capability === null) {
    return (
      <div data-testid="attest-checking" className="text-[10px] text-zinc-600">
        checking write-back availability…
      </div>
    );
  }
  if (capability.actions.gate_verdict !== true) {
    // Degraded path: older backend (404) or missing CLI/interpreter — the
    // copy-paste CLI fallback on the queue item is the action surface.
    return (
      <div data-testid="attest-unavailable" className="text-[10px] text-zinc-600">
        in-UI gate attestation isn’t in this backend build — use the CLI
        fallback.
      </div>
    );
  }

  const submitting = phase.state === "submitting";
  const done = phase.state === "done";
  const disabled = submitting || note.trim().length === 0;

  const submitVerdict = (verdict: GateVerdict) =>
    submit({
      exec: () =>
        postGateVerdict({
          iteration_id: iterationId,
          verdict,
          note: note.trim(),
        }),
      // Durable confirmation: the gate item for this iteration left the queue.
      confirmed: (items) => !queueHasItem(items, "gate_verdict", iterationId),
      onResolved,
    });

  return (
    <div data-testid="gate-verdict-form" className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-zinc-600">
        gate verdict · POST /api/attest/gate_verdict → orchestrator.gate_cli ·
        stamps human:ui
      </div>
      {!done && (
        <>
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            aria-label="gate verdict note (required)"
            placeholder="note (required — the audit value)"
            className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
          />
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {VERDICT_ORDER.map((verdict) => (
              <button
                key={verdict}
                type="button"
                disabled={disabled}
                onClick={() => submitVerdict(verdict)}
                className={`${BUTTON_BASE} ${VERDICT_TONES[verdict]}`}
              >
                {verdict}
              </button>
            ))}
            {submitting && (
              <span data-testid="attest-submitting" className="text-[11px] text-zinc-500">
                submitting…
              </span>
            )}
          </div>
          <div data-testid="gate-verdict-guidance" className="mt-1 text-[10px] leading-snug text-zinc-500">
            <span className="text-emerald-400">valid</span> = approved, loop
            advances ·{" "}
            <span className="text-amber-400">needs_revision</span> = paused for
            refinement ·{" "}
            <span className="text-red-400">invalid</span> = rejected.
          </div>
        </>
      )}

      {done && (
        <div data-testid="attest-success" className="mt-1 text-[11px] text-emerald-400">
          verdict recorded
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
