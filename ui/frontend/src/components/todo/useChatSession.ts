// useChatSession — the shared LIVE chat hook behind the cockpit's two probing
// panes (U2 tutor / U3 two-voice, 2026-06-18 work order). It threads the
// `finding_session chat start|turn` seam: the first send opens a session
// (postChatStart → session_id + stances), then every send posts ONE
// human-directed turn (postChatTurn) and appends the returned model replies to
// a local, session-only transcript.
//
// THE VERDICT FENCE (inviolate): the seam exposes ONLY start/turn — there is no
// disposition/verdict verb. This hook mirrors that: it neither accepts nor
// exposes any verdict/disposition/confidence value. `send` carries a message
// (+ an optional two-voice addressee) and nothing more.
//
// PRODUCER-OWNED ENVELOPES: every field on ChatStartResult / ChatTurnResult is
// CLI stdout, unvalidated. A malformed body (replies non-array, reply/stance a
// non-string, a bare-null turn) must DEGRADE to a legible safe value, never
// crash the pane. A swallowed catch sets a legible `error` string; `send` never
// throws. The session resets (clears session_id + transcript) when findingId
// changes, so a stale session never leaks across findings.
import { useCallback, useEffect, useRef, useState } from "react";
import { postChatStart, postChatTurn, TodoError } from "../../api/todo";
import type { ChatMode, ChatReply, ChatTurnResult } from "../../types/todo";

type Addressee = "defender" | "attacker" | "both";

// One rendered transcript entry. `stance` is null in tutor mode; "defender"
// (Gemma) / "attacker" (Qwen) in two_voice — but it is producer-owned, so the
// renderer still guards it. `reply` is always a string here (coerced below).
export interface ChatTranscriptReply {
  stance: string | null;
  reply: string;
  request_id: string | null;
}

export interface UseChatSession {
  turns: ChatTranscriptReply[];
  sessionId: string | null;
  sending: boolean;
  error: string | null;
  started: boolean;
  send: (message: string, addressee?: Addressee) => Promise<void>;
}

// Render-safe string: a producer may emit `reply` as a number / object / null.
// Coerce to a legible scalar (a finite number stringifies; everything else →
// fallback) so React never receives a raw object child and the DOM never shows
// "[object Object]".
function asReplyText(v: unknown): string {
  if (typeof v === "string") return v;
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return "";
}

// `stance` is "defender" | "attacker" | null (tutor) — but unvalidated. Keep a
// string verbatim (the pane's toneFor/labelFor guard unknowns); coerce anything
// else to null so the renderer's null-stance path (tutor) is taken, never an
// object leaked into a className.
function asStance(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

function asRequestId(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

// Coerce a turn envelope's `replies` (producer-owned) into safe transcript rows.
// A non-array body → [] (the empty append, never a `.map` crash); each member
// is normalized field-by-field. A bare-null / non-object member is dropped.
function coerceReplies(result: ChatTurnResult | null | undefined): ChatTranscriptReply[] {
  const raw: unknown = result?.replies;
  if (!Array.isArray(raw)) return [];
  const out: ChatTranscriptReply[] = [];
  for (const m of raw as unknown[]) {
    if (m === null || typeof m !== "object" || Array.isArray(m)) continue;
    const r = m as ChatReply;
    out.push({
      stance: asStance(r.stance),
      reply: asReplyText(r.reply),
      request_id: asRequestId(r.request_id),
    });
  }
  return out;
}

// A legible error string from a thrown value. A TodoError carries the CLI's
// stderr verbatim (the seam's own validation message is the truth — D-046);
// fall back to the error message, then a generic line. Never throws.
function asErrorText(e: unknown): string {
  if (e instanceof TodoError && typeof e.stderr === "string" && e.stderr.length > 0) {
    return e.stderr;
  }
  if (e instanceof Error && e.message.length > 0) return e.message;
  return "chat seam unavailable";
}

export function useChatSession(mode: ChatMode, findingId: string): UseChatSession {
  const [turns, setTurns] = useState<ChatTranscriptReply[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The session id read by an in-flight send must not be a stale closure value
  // (two quick sends, or a send racing a state batch). Mirror it into a ref so
  // `send` always reads the latest opened session.
  const sessionRef = useRef<string | null>(null);

  // Generation guard (the verdict-fence's "no stale session leaks across
  // findings" promise, made real). A send that is in-flight when `findingId`
  // changes still holds the prior finding's closure + the stable state setters;
  // without this its late-resolving start/turn would write the OLD session id,
  // error, or replies into the NEW finding's transcript. Each reset bumps the
  // generation; `send` captures it at call time and applies NOTHING once it is
  // stale. A ref (not state) so the in-flight closure reads the live value.
  const genRef = useRef(0);

  // Reset everything when the finding changes (cleanup): a session opened for
  // one finding must never thread into another. Also clears a stale error and
  // retires every in-flight send (genRef bump) so its result is dropped.
  useEffect(() => {
    genRef.current += 1;
    setTurns([]);
    setSessionId(null);
    sessionRef.current = null;
    setSending(false);
    setError(null);
    return () => {
      // Retire any send still in-flight at unmount/finding-change.
      genRef.current += 1;
      sessionRef.current = null;
    };
  }, [findingId]);

  const send = useCallback(
    async (message: string, addressee?: Addressee): Promise<void> => {
      // The generation this send belongs to. Any await below may resolve AFTER
      // the finding changed (genRef bumped); a stale send applies nothing.
      const gen = genRef.current;
      const fresh = () => gen === genRef.current;

      setSending(true);
      setError(null);
      try {
        // Open a session on first send (no id yet) — its session_id threads
        // into the turn. A start failure degrades to the error state below.
        let sid = sessionRef.current;
        if (sid === null || sid.length === 0) {
          const start = await postChatStart({ mode, finding_id: findingId });
          // The finding changed while start was in flight — drop this session
          // so its id never threads into (or contaminates) the new finding.
          if (!fresh()) return;
          sid = typeof start?.session_id === "string" ? start.session_id : null;
          if (sid === null || sid.length === 0) {
            // The seam returned no usable session id — surface a legible error
            // rather than post a turn against a fabricated/empty session.
            setError("chat session did not open (no session_id returned)");
            return;
          }
          sessionRef.current = sid;
          setSessionId(sid);
        }

        const turn = await postChatTurn({
          mode,
          finding_id: findingId,
          session_id: sid,
          message,
          // two_voice only; tutor mode rejects an addressee (single-voice).
          ...(mode === "two_voice" && addressee !== undefined ? { addressee } : {}),
        });
        // The finding changed while the turn was in flight — its replies belong
        // to the prior finding's transcript, never the current one.
        if (!fresh()) return;
        const replies = coerceReplies(turn);
        if (replies.length > 0) {
          setTurns((prev) => [...prev, ...replies]);
        }
      } catch (e) {
        // A swallowed catch — never throw out of send. The CLI's stderr (via
        // TodoError) is the legible truth (D-046). A stale send's error belongs
        // to the prior finding and is dropped.
        if (fresh()) setError(asErrorText(e));
      } finally {
        // Only the current generation owns the sending flag; a stale send must
        // not clear a fresh send's spinner.
        if (fresh()) setSending(false);
      }
    },
    [mode, findingId],
  );

  return {
    turns,
    sessionId,
    sending,
    error,
    started: sessionId !== null,
    send,
  };
}
