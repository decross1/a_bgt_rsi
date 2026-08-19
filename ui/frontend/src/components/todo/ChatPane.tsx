// ChatPane — the ONE mode-parameterized chat pane of the dossier reader (UI
// simplification S2; merges the retired TutorChatPane + TwoVoiceChatPane).
// `mode` selects everything that differed between the two panes:
//
//   - mode="tutor": the LIVE single-voice tutor chat (U2). A probing/explaining
//     conversation about the finding — the human asks, the tutor (single voice,
//     no stance) replies. Indigo accent; NO addressee selector; the fence note
//     cites the REAL tutor-fence source: the 2026-06-14 session note PART 2 +
//     inviolate rule 4 + D-053/D-054 (NOT D-044 — that is the two-voice
//     independence decision and has no place on a single-voice surface).
//   - mode="two_voice": the human-DRIVEN two-voice interrogation (U3). Per
//     D-044 independence, Gemma DEFENDS the finding (the authoring model) and
//     Qwen ATTACKS it (the independent adversary). NOT a spectator debate: the
//     human directs each turn at the defender, the attacker, or both via the
//     addressee selector. Zinc accent; stance-labeled replies; the fence note
//     cites D-044.
//
// THE FENCE (D-053 / D-054, enforced BY CONSTRUCTION — STRUCTURALLY
// fence-preserving): this pane accepts NO verdict / confidence / onResolved /
// calibration / setter prop. It is STRUCTURALLY unable to influence the
// verdict — it is never handed the means to. The chat seam itself is
// verdict-fenced (only start/turn; no disposition verb), so a chat turn can
// never close a disposition. useChatSession is untouched by this merge.
//
// CLOSE-OUT (GAP 2, 2026-08-19): the two_voice pane carries a persistent
// CloseOutStrip naming what ending the session DOES (validate / reject /
// spawn follow-up topic / refine — sourced from GET /api/todo/close_out, the
// backend's own truth) because the owner test-driving the cockpit could not
// find the answer to "how do we get the outcome of this to yield a follow up
// for nara?". The strip is fence-preserving too: it records no verdict (the
// disposition footer does) and its one interactive path — spawn_topic — is a
// SESSION-EXIT that writes nothing. It is handed the attacker's last turn as
// the read-only prefill source, never a setter.
//
// AVAILABILITY: `available` (the cockpit chat-capability flag) gates the live
// path. available!==true means the chat exec is not enabled in this
// environment — the pane sits disabled (send disabled, a capability-off
// banner) and never calls a model. The live transcript + errors come from
// useChatSession(mode, findingId), whose replies are producer-owned and
// defensively coerced before render.
import { useState } from "react";
import { useChatSession } from "./useChatSession";
import CloseOutStrip from "./CloseOutStrip";
import type { ChatMode } from "../../types/todo";

type Addressee = "defender" | "attacker" | "both";

const ADDRESSEES: readonly Addressee[] = ["defender", "attacker", "both"];

const STANCE_LABEL: Record<string, string> = {
  defender: "Gemma · DEFENDS",
  attacker: "Qwen · ATTACKS",
};

const STANCE_TONE: Record<string, string> = {
  defender: "border-emerald-900/60 bg-emerald-950/20 text-emerald-300",
  attacker: "border-red-900/60 bg-red-950/20 text-red-300",
};

// Quiet fallback tone for an unknown / malformed stance — same neutral idiom as
// the other badges' fallback. A producer-owned reply (the live transcript is
// the finding_session seam) may carry a never-seen or garbage stance; it must
// render generically, never leak a function/object into the className.
const STANCE_FALLBACK_TONE = "border-zinc-800/60 bg-zinc-950/40 text-zinc-400";

// Own-key lookups on the tone/label maps. A bare `MAP[stance]` resolves a
// prototype-member collision ("toString", "valueOf", "constructor", …) to an
// inherited FUNCTION, which would interpolate `function toString() { [native
// code] }` into the className. Object.hasOwn guards that, mirroring
// SourceBadge / chips.toneFor's prototype-collision guard.
function stanceTone(stance: unknown): string {
  return typeof stance === "string" &&
    Object.hasOwn(STANCE_TONE, stance) &&
    typeof STANCE_TONE[stance] === "string"
    ? STANCE_TONE[stance]
    : STANCE_FALLBACK_TONE;
}

function stanceLabel(stance: unknown): string {
  if (
    typeof stance === "string" &&
    Object.hasOwn(STANCE_LABEL, stance) &&
    typeof STANCE_LABEL[stance] === "string"
  ) {
    return STANCE_LABEL[stance];
  }
  // An unknown stance still shows generically (the raw value if it's a string),
  // never vanishes and never crashes.
  return typeof stance === "string" && stance.length > 0 ? stance : "voice";
}

// Render-safe text: React can render strings/numbers but throws on a raw
// object/array child. A producer may emit a non-string; coerce to a legible
// scalar.
function asText(v: unknown, fallback: string): string {
  if (typeof v === "string") return v;
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return fallback;
}

// A read-only cap intent is a display-only number. NaN/Infinity/non-number must
// degrade to "—" rather than print "NaN turns".
function asCap(v: unknown): string {
  return typeof v === "number" && Number.isFinite(v) ? String(v) : "—";
}

interface Props {
  findingId: string;
  /** Which pane this is: "tutor" (single voice) or "two_voice" (Gemma defends /
   *  Qwen attacks). Selects the useChatSession mode, the fence-note citation,
   *  the accent, and the addressee selector. */
  mode: ChatMode;
  /** Gate from GET /api/todo/available — false means the chat exec is not
   *  enabled in this environment (no model calls). */
  available?: boolean;
  /** Read-only cap intent surfaced to the human (two_voice only; the seam
   *  enforces the real caps; this only displays the intent). */
  turnCap?: number;
  tokenCap?: number;
}

export default function ChatPane({
  findingId,
  mode,
  available = false,
  turnCap = 24,
  tokenCap = 1024,
}: Props) {
  const isLive = available === true;
  const twoVoice = mode === "two_voice";
  // findingId is producer-owned (it threads up from /api/human_todo rows); the
  // `string` type is a compile-time fiction. A non-string must not leak
  // "[object Object]" into the surface.
  const safeFindingId = asText(findingId, "");
  const { turns, sending, error, send } = useChatSession(mode, safeFindingId);
  const [draft, setDraft] = useState("");
  const [addressee, setAddressee] = useState<Addressee>("both");

  // Empty draft (or mid-send, or capability off) gates the send — never post an
  // empty turn. `available` is coerced strictly so a truthy non-true value
  // never silently enables a model call.
  const sendDisabled = !isLive || sending || draft.trim().length === 0;

  // The attacker's (Qwen's) LAST reply — the close-out strip's read-only
  // prefill source. Derived, never stored: the transcript is not mutated. A
  // producer-owned non-string reply degrades to "" (asText), which the strip
  // reads as "no suggestion" rather than seeding a garbage topic.
  const lastAttackerReply =
    [...turns].reverse().find((turn) => turn.stance === "attacker")?.reply ??
    null;

  const onSend = () => {
    if (sendDisabled) return;
    const message = draft.trim();
    setDraft("");
    // useChatSession.send swallows its own errors (sets the error state); the
    // void is intentional — nothing throws out of here. The addressee threads
    // ONLY in two_voice mode (tutor mode rejects one — single voice).
    void send(message, twoVoice ? addressee : undefined);
  };

  // Per-mode chrome: testids keep the pre-merge names so the ported pins (the
  // kind-gating suite, the reader tests) read 1:1.
  const t = twoVoice
    ? {
        pane: "two-voice-chat-pane",
        fence: "two-voice-fence-note",
        stub: "two-voice-stub-banner",
        empty: "two-voice-empty",
        send: "two-voice-send",
        sending: "two-voice-sending",
        error: "two-voice-error",
        frame: "rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5",
        header: "text-[10px] uppercase tracking-wide text-zinc-600",
        title: "two-voice interrogation · human-driven (not a spectator debate)",
      }
    : {
        pane: "tutor-chat-pane",
        fence: "tutor-chat-fence-note",
        stub: "tutor-chat-stub-banner",
        empty: "tutor-chat-empty",
        send: "tutor-chat-send",
        sending: "tutor-chat-sending",
        error: "tutor-chat-error",
        frame: "rounded border border-indigo-900/60 bg-indigo-950/20 px-2 py-1.5",
        header: "text-[10px] uppercase tracking-wide text-indigo-400",
        title: "tutor chat · single voice (probes / explains)",
      };

  return (
    <div data-testid={t.pane} className={t.frame}>
      <div className="flex flex-wrap items-center justify-between gap-1">
        <div className={t.header}>{t.title}</div>
        {twoVoice && (
          <div
            data-testid="two-voice-cap-intent"
            className="text-[10px] text-zinc-600"
          >
            caps: {asCap(turnCap)} turns · {asCap(tokenCap)} tok/turn (intent)
          </div>
        )}
      </div>

      {/* THE VISIBLE FENCE — each mode cites its REAL source. The tutor cites
          the tutor fence (rule 4 · D-053/D-054, NOT D-044); the two-voice pane
          cites D-044 (interrogator independence). Neither affects the verdict. */}
      {twoVoice ? (
        <div
          data-testid="two-voice-fence-note"
          className="mt-0.5 text-[10px] text-zinc-500"
        >
          two-voice interrogation — does not affect your verdict; Gemma defends,
          Qwen attacks independently (D-044 independence). Decision support
          only; the forms below are the only dispositions.
        </div>
      ) : (
        <div
          data-testid="tutor-chat-fence-note"
          className="mt-0.5 text-[10px] text-zinc-500"
        >
          tutor chat — does not affect your verdict; it probes/explains, it never
          recommends (2026-06-14 note PART 2 · inviolate rule 4 · D-053/D-054).
        </div>
      )}

      {/* The two-stance layout header — D-044: Gemma defends, Qwen attacks. */}
      {twoVoice && (
        <div className="mt-1 flex gap-1.5 text-[10px] font-medium uppercase tracking-wide">
          <span
            data-testid="stance-defender"
            className="rounded border border-emerald-900/60 bg-emerald-950/20 px-1.5 py-0.5 text-emerald-300"
          >
            Gemma DEFENDS
          </span>
          <span
            data-testid="stance-attacker"
            className="rounded border border-red-900/60 bg-red-950/20 px-1.5 py-0.5 text-red-300"
          >
            Qwen ATTACKS
          </span>
        </div>
      )}

      {!isLive && (
        <div data-testid={t.stub} className="mt-1 text-[10px] text-zinc-500">
          capability disabled — the {twoVoice ? "two-voice" : "tutor"} chat exec
          is not enabled in this environment. No model calls happen here; your
          message is not sent.
        </div>
      )}

      {/* Transcript: the LIVE session-local turns. Tutor replies are single
          voice (no stance); two-voice replies are stance-tagged (defender =
          Gemma, attacker = Qwen — D-044 interrogator independence). */}
      <div className="mt-1.5 space-y-1">
        {turns.length === 0 ? (
          <div data-testid={t.empty} className="text-[11px] text-zinc-600">
            {twoVoice
              ? "no turns yet — direct the first turn below."
              : "no turns yet — ask the tutor about this finding below."}
          </div>
        ) : twoVoice ? (
          turns.map((turn, i) => {
            const stance = turn.stance;
            const stanceKey =
              typeof stance === "string" && Object.hasOwn(STANCE_TONE, stance)
                ? stance
                : "unknown";
            return (
              <div
                key={turn.request_id ?? i}
                data-testid={`chat-turn-${stanceKey}`}
                className={`rounded border px-2 py-1 text-[11px] ${stanceTone(stance)}`}
              >
                <span className="text-[10px] uppercase tracking-wide opacity-80">
                  {stanceLabel(stance)}
                </span>
                <div className="mt-0.5 text-zinc-300">
                  {asText(turn.reply, "")}
                </div>
              </div>
            );
          })
        ) : (
          turns.map((turn, i) => (
            <div
              key={turn.request_id ?? i}
              data-testid="tutor-chat-reply"
              className="rounded border border-indigo-900/60 bg-indigo-950/20 px-2 py-1 text-[11px] text-indigo-200"
            >
              <span className="text-[10px] uppercase tracking-wide opacity-80">
                tutor
              </span>
              <div className="mt-0.5 text-zinc-300">{asText(turn.reply, "")}</div>
            </div>
          ))
        )}
      </div>

      {/* Human turn-input. two_voice carries the addressee selector (a turn is
          DIRECTED — not a spectator debate); tutor is a single plain message. */}
      <div className="mt-1.5 border-t border-zinc-800/60 pt-1.5">
        {twoVoice && (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[10px] uppercase tracking-wide text-zinc-600">
              direct turn at
            </span>
            {ADDRESSEES.map((a) => (
              <button
                key={a}
                type="button"
                aria-pressed={addressee === a}
                onClick={() => setAddressee(a)}
                className={`rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
                  addressee === a
                    ? "border-sky-700 bg-sky-950 text-sky-300"
                    : "border-zinc-800 bg-zinc-950 text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {a}
              </button>
            ))}
          </div>
        )}
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          aria-label={twoVoice ? "two-voice turn input" : "tutor chat input"}
          placeholder={
            twoVoice
              ? isLive
                ? `direct a turn at the ${addressee}`
                : `direct a turn at the ${addressee} (disabled — not sent)`
              : isLive
                ? "ask the tutor about this finding"
                : "ask the tutor (disabled — not sent)"
          }
          rows={2}
          className={`${twoVoice ? "mt-1 " : ""}w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none`}
        />
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            disabled={sendDisabled}
            onClick={onSend}
            data-testid={t.send}
            title={
              isLive
                ? twoVoice
                  ? "send a turn directed at the selected voice(s)"
                  : "send a message to the tutor"
                : "disabled — the chat exec is not enabled in this environment"
            }
            className={
              "rounded border border-zinc-600 bg-zinc-900 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-zinc-300 hover:bg-zinc-800 " +
              "disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-600"
            }
          >
            {twoVoice ? "send turn" : "send"}
          </button>
          {sending && (
            <span data-testid={t.sending} className="text-[11px] text-zinc-500">
              {twoVoice ? "interrogating…" : "asking the tutor…"}
            </span>
          )}
          {twoVoice && isLive && (
            <span className="text-[10px] text-zinc-600">
              directed at {addressee} · {safeFindingId}
            </span>
          )}
          {!isLive && (
            <span className="text-[10px] text-zinc-600">
              disabled — capability not enabled in this environment
            </span>
          )}
        </div>

        {/* A failed start/turn degrades in place — the CLI's stderr verbatim
            (D-046), never a blank pane and never a fabricated reply. */}
        {error !== null && (
          <div
            data-testid={t.error}
            className="mt-1 overflow-x-auto whitespace-pre-wrap rounded border border-red-900 bg-red-950/40 p-2 font-mono text-[11px] text-red-400"
          >
            {error}
          </div>
        )}
      </div>

      {/* The PERSISTENT close-out strip (GAP 2) — visible from the first
          render, not only after a turn: the point is that the human can see
          what ending the session does BEFORE they decide. Fence-preserving:
          the strip gets the attacker's last reply as a read-only prefill
          source and no verdict/setter of any kind. */}
      {twoVoice && (
        <CloseOutStrip
          findingId={safeFindingId}
          attackerSuggestion={lastAttackerReply}
        />
      )}
    </div>
  );
}
