// TutorChatPane — the LIVE single-voice tutor chat (U2, 2026-06-18 work order).
// A probing/explaining conversation about the finding the human is resolving:
// the human asks, the tutor (single voice, no stance) replies. It is backed by
// the `finding_session chat --mode tutor` seam (one model voice; the envelope
// carries stance:null and NO addressee).
//
// THE FENCE (D-053 / D-054, enforced BY CONSTRUCTION):
//   - This pane accepts NO verdict / confidence / onResolved / calibration /
//     setter prop. It is STRUCTURALLY unable to influence the verdict — it is
//     never handed the means to. The chat seam itself is verdict-fenced (only
//     start/turn; no disposition verb), so a tutor turn can never close a
//     disposition.
//   - The visible fence note cites the REAL source: the 2026-06-14 session note
//     PART 2 + inviolate rule 4 + D-053/D-054 (NOT D-044 — D-044 is the
//     vllm-qwen novelty-skeptic independence decision, the two-voice fence; it
//     has no place on this single-voice teaching surface).
//
// AVAILABILITY: `available` (actions.two_voice_chat-style flag the cockpit
// threads) gates the live path. available!==true keeps the pane in an honest
// disabled stub (send disabled, a stub banner) — it never calls a model. The
// live transcript + errors come from useChatSession("tutor", findingId), whose
// replies are producer-owned and defensively coerced before render.
import { useState } from "react";
import { useChatSession } from "./useChatSession";

interface Props {
  findingId: string;
  /** Gate from GET /api/todo/available — false keeps the pane in its honest
   *  disabled stub (no model calls). Mirrors TwoVoiceChatPane's `available`. */
  available?: boolean;
}

// findingId is producer-owned (it threads up from /api/todo + loop_memory rows);
// the `string` type is a compile-time fiction. A non-string must not leak
// "[object Object]" into the surface.
function asText(v: unknown, fallback: string): string {
  if (typeof v === "string") return v;
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return fallback;
}

export default function TutorChatPane({ findingId, available = false }: Props) {
  const isLive = available === true;
  const safeFindingId = asText(findingId, "");
  const { turns, sending, error, send } = useChatSession("tutor", safeFindingId);
  const [draft, setDraft] = useState("");

  // Empty draft (or mid-send, or stub) gates the send — never post an empty
  // turn. `available` is coerced strictly so a truthy non-true value never
  // silently enables a model call.
  const sendDisabled = !isLive || sending || draft.trim().length === 0;

  const onSend = () => {
    if (sendDisabled) return;
    const message = draft.trim();
    setDraft("");
    // useChatSession.send swallows its own errors (sets the error state); the
    // void is intentional — nothing throws out of here.
    void send(message);
  };

  return (
    <div
      data-testid="tutor-chat-pane"
      className="rounded border border-indigo-900/60 bg-indigo-950/20 px-2 py-1.5"
    >
      <div className="text-[10px] uppercase tracking-wide text-indigo-400">
        tutor chat · single voice (probes / explains)
      </div>

      {/* THE VISIBLE FENCE — cites the REAL source (NOT D-044). It probes and
          explains; it never recommends and never affects the verdict. */}
      <div
        data-testid="tutor-chat-fence-note"
        className="mt-0.5 text-[10px] text-zinc-500"
      >
        tutor chat — does not affect your verdict; it probes/explains, it never
        recommends (2026-06-14 note PART 2 · inviolate rule 4 · D-053/D-054).
      </div>

      {!isLive && (
        <div
          data-testid="tutor-chat-stub-banner"
          className="mt-1 text-[10px] text-zinc-500"
        >
          stub — lights up when the finding_session tutor chat seam is available.
          No model calls happen here yet; your message is not sent.
        </div>
      )}

      {/* Transcript: alternating human turn + tutor reply (single voice, no
          stance, no addressee). */}
      <div className="mt-1.5 space-y-1">
        {turns.length === 0 ? (
          <div
            data-testid="tutor-chat-empty"
            className="text-[11px] text-zinc-600"
          >
            no turns yet — ask the tutor about this finding below.
          </div>
        ) : (
          turns.map((t, i) => (
            <div
              key={t.request_id ?? i}
              data-testid="tutor-chat-reply"
              className="rounded border border-indigo-900/60 bg-indigo-950/20 px-2 py-1 text-[11px] text-indigo-200"
            >
              <span className="text-[10px] uppercase tracking-wide opacity-80">
                tutor
              </span>
              <div className="mt-0.5 text-zinc-300">{t.reply}</div>
            </div>
          ))
        )}
      </div>

      {/* Human turn-input — a single message to the tutor (no addressee). */}
      <div className="mt-1.5 border-t border-zinc-800/60 pt-1.5">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          aria-label="tutor chat input"
          placeholder={
            isLive
              ? "ask the tutor about this finding"
              : "ask the tutor (stub — not sent)"
          }
          rows={2}
          className="w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
        />
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            disabled={sendDisabled}
            onClick={onSend}
            data-testid="tutor-chat-send"
            title={
              isLive
                ? "send a message to the tutor"
                : "stub — lights up when the tutor chat seam is available"
            }
            className={
              "rounded border border-zinc-600 bg-zinc-900 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-zinc-300 hover:bg-zinc-800 " +
              "disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-600"
            }
          >
            send
          </button>
          {sending && (
            <span
              data-testid="tutor-chat-sending"
              className="text-[11px] text-zinc-500"
            >
              asking the tutor…
            </span>
          )}
          {!isLive && (
            <span className="text-[10px] text-zinc-600">
              disabled — seam not yet available
            </span>
          )}
        </div>

        {/* A failed start/turn degrades in place — the CLI's stderr verbatim
            (D-046), never a blank pane and never a fabricated reply. */}
        {error !== null && (
          <div
            data-testid="tutor-chat-error"
            className="mt-1 overflow-x-auto whitespace-pre-wrap rounded border border-red-900 bg-red-950/40 p-2 font-mono text-[11px] text-red-400"
          >
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
