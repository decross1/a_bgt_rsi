// CalibrationCapture — the pre-verdict calibration capture (ARCH §6.5.4 /
// research_program_v2 red-flag). The cockpit captures the human's PREDICTION +
// CONFIDENCE *before* a verdict is recorded, then opens the verdict form. That
// ordering is the contract: this component captures FIRST, and only on a
// successful capture fires `onCaptured` — the shell uses that callback to then
// reveal the verdict form (the verdict form is never shown by this component).
//
// Persistence: POST /api/todo/calibration (api/todo.ts postCalibration), which
// — once the seam lands — shells the calibration CLI that writes the
// `calibration_entry` run-log event. Until then the endpoint is an honest STUB:
// it surfaces the would-run argv read-only and writes NOTHING (inviolate rule
// 4). This component never writes a ledger itself.
//
// STUB note: the capability flag `calibration` is false until the primary seam
// lands; the banner says so. Capture still works locally (the draft is held in
// component state and handed to onCaptured) — what is STUBBED is the durable
// write, not the human's input.
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
  /** Fired AFTER a successful capture — the shell then reveals the verdict
   *  form. Carries the captured draft so the shell can echo it. This is the
   *  ordering contract: calibration FIRST, verdict SECOND. */
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

  const capture = async () => {
    const draft: CalibrationDraft = {
      prediction: prediction.trim(),
      confidence: safeConfidence,
    };
    setPhase("submitting");
    setErrorDetail(null);
    try {
      // Stub today: returns the would-run argv read-only, writes nothing.
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
        pre-verdict calibration (ARCH §6.5.4) · captured FIRST, then the verdict
        opens
      </div>
      {!available && (
        <div
          data-testid="calibration-stub-banner"
          className="mt-0.5 text-[10px] text-zinc-500"
        >
          calibration_cli not reachable in this environment — your input is
          captured locally but not durably written (the calibration_entry writer
          itself landed in P4 / D-055).
        </div>
      )}

      {phase !== "captured" && (
        <>
          <input
            type="text"
            value={prediction}
            onChange={(e) => setPrediction(e.target.value)}
            aria-label="calibration prediction (required)"
            placeholder="your prediction (required — before you see the verdict)"
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
              capture calibration → open verdict
            </button>
            {phase === "submitting" && (
              <span data-testid="calibration-submitting" className="text-[11px] text-zinc-500">
                capturing…
              </span>
            )}
          </div>
        </>
      )}

      {phase === "captured" && (
        <div data-testid="calibration-captured" className="mt-1 text-[11px] text-emerald-400">
          calibration captured — the verdict form is now open.
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
