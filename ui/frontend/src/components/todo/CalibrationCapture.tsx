// CalibrationCapture — the OPTIONAL pre-verdict calibration capture (ARCH §6.5.4
// / research_program_v2 red-flag). The owner MAY record a PREDICTION + CONFIDENCE
// BEFORE they see the decision support — a "blind" prediction whose accuracy is
// itself research data. It is OPT-IN: it no longer GATES the resolution forms
// (the owner can decide without it). Recorded ONCE per item id — the shell tracks
// a per-id Set and passes `captured`, so a switch-away-and-back never re-prompts
// (flag-2: no double calibration_entry).
//
// Persistence: POST /api/todo/calibration (api/todo.ts postCalibration) shells
// the blessed calibration CLI that writes the `calibration_entry` run-log event
// when actions.calibration is enabled (the writer landed P4 / D-055). When the
// capability is OFF the input is captured locally but not durably written; the
// banner says so. This component never writes a ledger itself.
import { useState } from "react";
import { postCalibration } from "../../api/todo";
import type { CalibrationDraft } from "../../types/todo";

interface Props {
  /** the selected item's ref_id — a finding_id, or an iteration_id for a
   *  gate_verdict item (the calibration ordering gate precedes ANY verdict, so
   *  this is the generic item id, not finding-specific). */
  refId: string;
  /** actions.calibration from GET /api/todo/available — false disables the
   *  DURABLE write (calibration_cli absent in this env); local capture still
   *  works. The calibration_entry writer itself landed (P4 / D-055). */
  available?: boolean;
  /** true when this item's id is already in the shell's calibrated Set — show
   *  the "recorded" state, do NOT re-prompt (flag-2: no double calibration_entry
   *  on switch-away-and-back). */
  captured?: boolean;
  /** Fired AFTER a successful capture, carrying the captured draft. Calibration
   *  is OPTIONAL — this does not gate anything; the shell records the id. */
  onCaptured: (draft: CalibrationDraft) => void;
}

// Confidence is a 0–1 number (ARCH §6.5.4). The range input's onChange uses
// Number(), which yields NaN for non-numeric strings; a malformed default or a
// version-skew odd value could also arrive out of band. Coerce defensively:
// non-finite → the neutral 0.5 midpoint, otherwise clamp into [0,1]. This keeps
// `.toFixed(2)` from ever rendering "NaN"/"Infinity" and stops an out-of-bounds
// confidence from being handed to the calibration ledger via onCaptured.
function cleanConfidence(n: number): number {
  if (typeof n !== "number" || !Number.isFinite(n)) return 0.5;
  if (n < 0) return 0;
  if (n > 1) return 1;
  return n;
}

export default function CalibrationCapture({
  refId,
  available = false,
  captured = false,
  onCaptured,
}: Props) {
  const [prediction, setPrediction] = useState("");
  const [confidence, setConfidence] = useState(0.5);
  const [phase, setPhase] = useState<"idle" | "submitting" | "captured" | "error">(
    "idle",
  );
  const [errorDetail, setErrorDetail] = useState<string | null>(null);

  // refId is producer-owned (the selected item's id — a finding_id, or an
  // iteration_id for a gate_verdict item); a null/non-string/empty value must
  // degrade to a legible empty ref, never crash the trim/POST. (NOTE: the live
  // calibration_cli expects a surfaced-finding ref_id; whether it accepts an
  // iteration_id for a gate_verdict item is a primary-side question — flagged in
  // ui_plan.md. A reject surfaces as a legible error here, never a bad write.)
  const safeRefId = typeof refId === "string" ? refId : "";
  // Render the clamped value so a malformed confidence in state can never leak a
  // "NaN"/"Infinity" label or push the slider out of its [0,1] track.
  const safeConfidence = cleanConfidence(confidence);
  const disabled = phase === "submitting" || prediction.trim().length === 0;
  // Already recorded for this id (the shell's per-id Set) OR just captured here.
  // Either way show the "recorded" state and never re-present the form (flag-2).
  const recorded = captured || phase === "captured";

  const capture = async () => {
    const draft: CalibrationDraft = {
      prediction: prediction.trim(),
      confidence: safeConfidence,
    };
    setPhase("submitting");
    setErrorDetail(null);
    try {
      // POST shells the blessed calibration CLI when actions.calibration is on
      // (writes the calibration_entry); when off it returns a read-only preview.
      // FLAT body — the backend takes prediction + confidence as top-level fields.
      await postCalibration({
        ref_id: safeRefId,
        prediction: draft.prediction,
        confidence: draft.confidence,
      });
    } catch (err) {
      // ONLY a POST failure lands here — the capture did NOT happen (no durable
      // write once the seam lands), so the verdict must NOT open and a retry is
      // safe. onCaptured is deliberately NOT in this try: a downstream throw from
      // the shell's verdict-reveal callback must not be mislabeled as a failed
      // capture (which would re-present the form and, once the seam lands, double-
      // write the calibration_entry on retry).
      setPhase("error");
      setErrorDetail(String(err));
      return;
    }
    // The POST succeeded — the capture is durable (once the seam lands). Commit
    // the captured state BEFORE notifying the shell, then fire the ordering-
    // contract callback. If onCaptured itself throws (a producer-owned id or a
    // malformed verdict-reveal), the capture STILL stands: surface the callback
    // fault without rolling back to the error/retry state.
    setPhase("captured");
    try {
      // Ordering contract: only NOW does the shell get to reveal the verdict.
      onCaptured(draft);
    } catch {
      // The capture is already durable; swallow the post-capture callback fault
      // rather than masquerading a successful capture as a failed one.
    }
  };

  return (
    <div
      data-testid="calibration-capture"
      className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5"
    >
      <div className="text-[10px] uppercase tracking-wide text-zinc-600">
        optional blind calibration (ARCH §6.5.4) · record a prediction before the
        decision support, if you want one
      </div>
      {!available && (
        <div
          data-testid="calibration-stub-banner"
          className="mt-0.5 text-[10px] text-zinc-500"
        >
          calibration capture is not available in this environment (the CLI is
          not reachable). Your input below is a preview only and will not be
          recorded.
        </div>
      )}

      {!recorded && (
        <>
          <input
            type="text"
            value={prediction}
            onChange={(e) => setPrediction(e.target.value)}
            aria-label="calibration prediction (required)"
            placeholder="optional — predict the outcome before you interrogate"
            className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
          />
          <label className="mt-1.5 flex items-center gap-2 text-[11px] text-zinc-400">
            <span className="uppercase tracking-wide text-zinc-600">confidence</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={safeConfidence}
              onChange={(e) => setConfidence(cleanConfidence(Number(e.target.value)))}
              aria-label="calibration confidence"
              className="flex-1"
            />
            <span className="font-mono tabular-nums">{safeConfidence.toFixed(2)}</span>
          </label>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              disabled={disabled}
              onClick={capture}
              className="rounded border border-sky-800 bg-sky-950 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-sky-300 hover:bg-sky-900 disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-600"
            >
              record blind calibration
            </button>
            {phase === "submitting" && (
              <span data-testid="calibration-submitting" className="text-[11px] text-zinc-500">
                capturing…
              </span>
            )}
          </div>
        </>
      )}

      {recorded && (
        <div data-testid="calibration-captured" className="mt-1 text-[11px] text-emerald-400">
          blind calibration recorded for this item.
        </div>
      )}

      {phase === "error" && errorDetail !== null && (
        <div data-testid="calibration-error" className="mt-1 text-[11px] text-red-400">
          {errorDetail}
        </div>
      )}
    </div>
  );
}
