// TwoVoiceChatPane — the human-DRIVEN two-voice interrogation pane (2026-06-14
// session note PART 2 "Two-voice, HUMAN-DRIVEN interrogation"). The two stances,
// per D-044 independence (the interrogator must NOT be the authoring model):
//
//   - Gemma DEFENDS the finding (the authoring model defends its own claim).
//   - Qwen ATTACKS it (the independent adversary).
//
// This is NOT a spectator debate: the human DIRECTS the topic and flow, and may
// address a turn at the defender, the attacker, or both. The turn input below
// carries an explicit addressee selector to encode that.
//
// It is a STUB: backed by the two-stance extension of
// orchestrator/finding_session.py (multi-turn, honest-defender, append-only
// transcript, turn/token caps, concurrency guard) — a PART-2 seam that has not
// shipped. So no real model calls happen here; the transcript is whatever
// fixture turns are passed in, the human's queued turn is held locally and not
// sent, and the turn/token-cap intent is shown read-only. The banner says so.
import { useState } from "react";
import type { ChatTurn } from "../../types/todo";

type Addressee = "defender" | "attacker" | "both";

const ADDRESSEES: readonly Addressee[] = ["defender", "attacker", "both"];

interface Props {
  findingId: string;
  /** Prior transcript turns to render (fixture/stub today; the live transcript
   *  is the finding_session two-stance seam). */
  turns?: ChatTurn[];
  /** false until the two_voice_chat primary seam lands (cockpit availability). */
  available?: boolean;
  /** Read-only cap intent surfaced to the human (the seam enforces the real
   *  caps; this only displays the intent). */
  turnCap?: number;
  tokenCap?: number;
}

const STANCE_LABEL: Record<ChatTurn["stance"], string> = {
  defender: "Gemma · DEFENDS",
  attacker: "Qwen · ATTACKS",
};

const STANCE_TONE: Record<ChatTurn["stance"], string> = {
  defender: "border-emerald-900/60 bg-emerald-950/20 text-emerald-300",
  attacker: "border-red-900/60 bg-red-950/20 text-red-300",
};

// Quiet fallback tone for an unknown / malformed stance — same neutral idiom as
// the other badges' fallback. A producer-owned ChatTurn (the live transcript is
// the finding_session two-stance seam) may carry a never-seen or garbage stance;
// it must render generically, never leak a function/object into the className.
const STANCE_FALLBACK_TONE =
  "border-zinc-800/60 bg-zinc-950/40 text-zinc-400";

// Own-key lookups on the tone/label maps. A bare `MAP[stance]` resolves a
// prototype-member collision ("toString", "valueOf", "constructor", …) to an
// inherited FUNCTION, which would interpolate `function toString() { [native
// code] }` into the className. Object.hasOwn guards that, mirroring
// SourceBadge / ResolvedIterationsList's prototype-collision guard.
function toneFor(stance: unknown): string {
  return typeof stance === "string" &&
    Object.hasOwn(STANCE_TONE, stance) &&
    typeof STANCE_TONE[stance as ChatTurn["stance"]] === "string"
    ? STANCE_TONE[stance as ChatTurn["stance"]]
    : STANCE_FALLBACK_TONE;
}

function labelFor(stance: unknown): string {
  if (
    typeof stance === "string" &&
    Object.hasOwn(STANCE_LABEL, stance) &&
    typeof STANCE_LABEL[stance as ChatTurn["stance"]] === "string"
  ) {
    return STANCE_LABEL[stance as ChatTurn["stance"]];
  }
  // An unknown stance still shows generically (the raw value if it's a string),
  // never vanishes and never crashes.
  return typeof stance === "string" && stance.length > 0 ? stance : "voice";
}

// Render-safe text: React can render strings/numbers but throws on a raw
// object/array child ("Objects are not valid as a React child"). A producer may
// emit turn.text / turn.addressee as a non-string; coerce to a legible scalar.
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

export default function TwoVoiceChatPane({
  findingId,
  turns = [],
  available = false,
  turnCap = 24,
  tokenCap = 1024,
}: Props) {
  const [addressee, setAddressee] = useState<Addressee>("both");
  const [draft, setDraft] = useState("");

  // `turns` is producer-owned (the live transcript is the finding_session
  // two-stance seam). A non-array body (null / object / number / a bare 404
  // default) must degrade to the empty state, never crash `.length` / `.map`.
  // Mirrors ResolvedIterationsList's Array.isArray coercion.
  const safeTurns: ChatTurn[] = Array.isArray(turns) ? turns : [];
  // findingId is shown read-only in the available branch; a non-string must not
  // leak "[object Object]".
  const safeFindingId = asText(findingId, "");

  return (
    <div
      data-testid="two-voice-chat-pane"
      className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5"
    >
      <div className="flex flex-wrap items-center justify-between gap-1">
        <div className="text-[10px] uppercase tracking-wide text-zinc-600">
          two-voice interrogation · human-driven (not a spectator debate)
        </div>
        <div
          data-testid="two-voice-cap-intent"
          className="text-[10px] text-zinc-600"
        >
          caps: {asCap(turnCap)} turns · {asCap(tokenCap)} tok/turn (intent)
        </div>
      </div>

      {/* The two-stance layout header — D-044: Gemma defends, Qwen attacks. */}
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

      <div
        data-testid="two-voice-stub-banner"
        className="mt-1 text-[10px] text-zinc-500"
      >
        stub — lights up when the finding_session two-voice seam lands. No model
        calls happen here yet; your turn is held locally, not sent.
      </div>

      {/* Transcript (fixture/stub turns). */}
      <div className="mt-1.5 space-y-1">
        {safeTurns.length === 0 ? (
          <div data-testid="two-voice-empty" className="text-[11px] text-zinc-600">
            no turns yet — direct the first turn below.
          </div>
        ) : (
          safeTurns.map((turn, i) => {
            // A single turn may be a bare null / non-object (a partial / legacy
            // transcript row). Treat its fields defensively rather than crash.
            const t = (turn && typeof turn === "object" ? turn : {}) as Partial<ChatTurn>;
            const stance = t.stance;
            // The testid uses a known stance when valid, else a stable "unknown"
            // — never an [object Object]/undefined testid.
            const stanceKey =
              typeof stance === "string" && Object.hasOwn(STANCE_TONE, stance)
                ? stance
                : "unknown";
            return (
              <div
                key={i}
                data-testid={`chat-turn-${stanceKey}`}
                className={`rounded border px-2 py-1 text-[11px] ${toneFor(stance)}`}
              >
                <span className="text-[10px] uppercase tracking-wide opacity-80">
                  {labelFor(stance)} → {asText(t.addressee, "—")}
                </span>
                <div className="mt-0.5 text-zinc-300">{asText(t.text, "")}</div>
              </div>
            );
          })
        )}
      </div>

      {/* Human turn-input — directs a turn at defender / attacker / both. */}
      <div className="mt-1.5 border-t border-zinc-800/60 pt-1.5">
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
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          aria-label="two-voice turn input"
          placeholder={`direct a turn at the ${addressee} (stub — not sent)`}
          rows={2}
          className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
        />
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            disabled
            data-testid="two-voice-send"
            title="stub — lights up when the finding_session two-voice seam lands"
            className="rounded border border-zinc-800 bg-zinc-900 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-zinc-600 disabled:cursor-not-allowed"
          >
            send turn
          </button>
          <span className="text-[10px] text-zinc-600">
            {available
              ? `directed at ${addressee} · ${safeFindingId}`
              : "disabled — seam not yet live"}
          </span>
        </div>
      </div>
    </div>
  );
}
