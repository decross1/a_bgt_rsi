// SessionThreadCard — ONE chat session as ONE card (owner feedback
// 2026-08-19: "I posed 3 questions for iter-2026-06-05-006 but it shows up
// as 6 cards instead of maybe 1 or 2 (since it goes to 2 models)").
//
// The finding-session engine is a STATELESS REPLAY: every turn re-sends the
// whole message stack, so 3 questions × 2 voices = 6 wrapper calls, each
// carrying the entire growing prompt. Rendered per call that reads as six
// near-identical walls of text. Here the same rows read as the conversation
// they were:
//
//   header  — session id, one chip per voice (stance + the model that
//             actually answered), turn count, question count, total wall;
//   body    — the questions in order; each question is printed ONCE as a
//             shared header with BOTH voices' answers underneath (the two
//             stances are asked the same thing in a "both" turn, so the
//             backend's consecutive-identical user_delta rule collapses
//             them — see questionGroups below);
//   answers — the existing payload renderers (MessageBody → ThoughtBlock /
//             raw fallback), so qwen's <|channel> think markup is folded
//             exactly as it is in the expanded call reader;
//   footer  — per turn: tokens, latency, clock, and the "context: N prior
//             messages" chip that opens the FULL replayed stack through the
//             page's existing expanded-call affordance.
//
// HONESTY: every field is backend passthrough (ui/backend/model_io.py) — a
// missing value renders "—", never a guess. The header chips are derived
// from the turns THIS CARD HOLDS rather than from the thread's summary
// arrays, because a paged merge can prepend older turns to a card; the
// summary arrays remain the backend's own statement over its scan window.
// A thread whose replay stacks do not prove the first turn is present says
// so ("older turns may be outside the scan window") instead of implying the
// card is the whole session — and a card folded from several page slices
// RE-DERIVES that claim over its merged turns (threadComplete), because a
// slice that held the attacker's opener says nothing about a defender it
// never carried.
import { ReactNode } from "react";
import MessageBody from "./payload/MessageBody";
import EmptyCompletionNote from "./payload/EmptyCompletionNote";
import { backendTone, TONE_QUIET } from "../roles";
import { fmt } from "../format";

// ─── wire types (backend/model_io.py `threads`) ─────────────────────────
// Owned here rather than in api/modelIO.ts, following the /model-io page's
// existing precedent of keeping its own endpoint shapes local.

export interface SessionTurn {
  ts: string | null;
  request_id: string | null;
  caller_tag: string | null;
  /** "attacker" / "defender" / "tutor"; null for the single-voice seam. */
  stance: string | null;
  model: string | null;
  backend: string | null;
  /** The NEW question this call asked — the last user message. */
  user_delta: string | null;
  user_delta_truncated: boolean;
  /** Messages replayed AHEAD of the question (the context disclosure).
   * NULL when the row carried no legible prompt_messages: 0 would be a
   * CLAIM (it means "the stack IS the opening question", the evidence
   * threadComplete reads), and a malformed row must not forge it. */
  prefix_message_count: number | null;
  completion: string;
  completion_truncated: boolean;
  empty: boolean;
  tokens_in: number | null;
  tokens_out: number | null;
  latency_ms: number | null;
}

export interface SessionThread {
  kind: "session_thread";
  session_id: string;
  run_id: string | null;
  started: string | null;
  ended: string | null;
  wall_ms: number | null;
  models: string[];
  stances: string[];
  caller_tags: string[];
  turn_count: number;
  /** True when the PAGE stopped at its per-thread turn cap: older turns of
   * this session exist and the next page continues it. */
  turns_truncated: boolean;
  turns_complete: boolean;
  turns: SessionTurn[];
}
// NOTE: no `question_count` on the wire (dropped 2026-08-19). A card can be
// folded from several page slices, so the only correct count is the one
// derived from the turns the card HOLDS — questionGroups() below. A
// per-slice scalar would contradict the rendered number after a merge.

// ─── derivations ────────────────────────────────────────────────────────

/** Consecutive turns sharing a user_delta are the same question answered by
 * different voices — one question header, N answers. Only CONSECUTIVE
 * equality collapses (the rule the backend hands the ask sequence in): the same
 * question asked again later is honestly a second question. */
export function questionGroups(turns: SessionTurn[]): SessionTurn[][] {
  const groups: SessionTurn[][] = [];
  for (const turn of turns) {
    const last = groups[groups.length - 1];
    if (last != null && last[0].user_delta === turn.user_delta) last.push(turn);
    else groups.push([turn]);
  }
  return groups;
}

/** Mirror of the backend's `_thread_complete` (ui/backend/model_io.py): the
 * thread is whole only when EVERY voice on it has a turn whose replayed
 * prefix is <= 1 message — that call IS the voice's opener, so nothing
 * older can belong to it. A null prefix (no legible prompt_messages on the
 * row) is NOT evidence and proves nothing.
 *
 * Recomputed over the MERGED turns rather than trusting any one slice's
 * wire flag: a card can be folded from several pages, and a slice that held
 * the attacker's opener says nothing about a defender it never carried. */
export function threadComplete(turns: SessionTurn[]): boolean {
  const earliest = new Map<string, number | null>();
  for (const turn of turns) {
    const key = turn.stance ?? "";
    const prefix = turn.prefix_message_count ?? null;
    if (!earliest.has(key)) {
      earliest.set(key, prefix);
      continue;
    }
    const held = earliest.get(key) ?? null;
    if (prefix != null && (held == null || prefix < held)) {
      earliest.set(key, prefix);
    }
  }
  if (earliest.size === 0) return false;
  return [...earliest.values()].every((p) => p != null && p <= 1);
}

/** Compact wall time: "47s", "13m 42s", "1h 04m". Null → "—". */
export function formatWall(ms: number | null): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "—";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

// Stance accents — the DebateExchange / roles.ts families: the adversarial
// voice rose, the generator/defender emerald, the tutor sky, anything
// unknown quiet zinc. Own-key lookup (the SourceBadge prototype guard).
const STANCE_ACCENT: Record<string, string> = {
  attacker: "text-rose-300",
  challenger: "text-rose-300",
  defender: "text-emerald-300",
  tutor: "text-sky-300",
};

export function stanceAccent(stance: string | null): string {
  if (!stance) return "text-zinc-300";
  return Object.prototype.hasOwnProperty.call(STANCE_ACCENT, stance)
    ? STANCE_ACCENT[stance]
    : "text-zinc-300";
}

/** hh:mm:ss (UTC) out of an ISO timestamp; "—" when absent/short. */
function clock(ts: string | null): string {
  return ts && ts.length >= 19 ? ts.slice(11, 19) : "—";
}

/** One chip per VOICE, in first-appearance order: the stance, and EVERY
 * model and backend that actually answered for it.
 *
 * Models and backends accumulate the same way on purpose (fix 2026-08-19):
 * taking the backend from the voice's FIRST turn while listing all its
 * models made the chip self-contradicting the moment a voice was re-served
 * — "gemma, qwen3.8 · vllm-gemma" claims one backend served both. A voice
 * whose serving moved mid-session shows both, which is the truth. */
export function voices(
  turns: SessionTurn[],
): { stance: string | null; models: string[]; backends: string[] }[] {
  const out: {
    stance: string | null;
    models: string[];
    backends: string[];
  }[] = [];
  for (const turn of turns) {
    let hit = out.find((v) => v.stance === turn.stance);
    if (hit == null) {
      hit = { stance: turn.stance, models: [], backends: [] };
      out.push(hit);
    }
    if (turn.model && !hit.models.includes(turn.model)) {
      hit.models.push(turn.model);
    }
    if (turn.backend && !hit.backends.includes(turn.backend)) {
      hit.backends.push(turn.backend);
    }
  }
  return out;
}

const CHIP = "rounded px-1.5 py-0.5 font-mono text-[10px]";
const META = "font-mono text-[11px] text-zinc-500";

// ─── the card ───────────────────────────────────────────────────────────

export default function SessionThreadCard({
  thread,
  expandedRequestId = null,
  expansion = null,
  onToggleContext,
}: {
  thread: SessionThread;
  /** request_id of the turn whose full replayed stack is open (page-wide:
   * one expansion at a time, the same rule the call table follows). */
  expandedRequestId?: string | null;
  /** The page's <CallExpansion> for that turn — rendered by THIS card only
   * when the expanded id belongs to one of its turns (keeps the reader in
   * one place without this component owning the detail fetch). */
  expansion?: ReactNode;
  onToggleContext: (requestId: string | null) => void;
}) {
  const turns = Array.isArray(thread.turns) ? thread.turns : [];
  const groups = questionGroups(turns);
  const voiceChips = voices(turns);

  return (
    <div
      data-testid="session-thread"
      data-session-id={thread.session_id}
      className="border-b border-zinc-800/60 py-2 last:border-0"
    >
      {/* header: the session, its voices, and its shape at a glance */}
      <div
        data-testid="thread-header"
        className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs"
      >
        <span className="text-[10px] uppercase tracking-wide text-zinc-500">
          session
        </span>
        <span
          data-testid="thread-session-id"
          className="font-mono text-zinc-300"
          title={thread.run_id ?? undefined}
        >
          {thread.session_id}
        </span>
        {voiceChips.map((v, i) => (
          <span
            key={`${v.stance ?? "voice"}-${i}`}
            data-testid="thread-voice"
            className="flex items-baseline gap-1.5"
          >
            <span
              className={`text-[10px] font-medium uppercase tracking-wide ${stanceAccent(v.stance)}`}
            >
              {v.stance ?? "single voice"}
            </span>
            {v.models.map((m) => (
              <span key={m} className={`${CHIP} ${TONE_QUIET}`}>
                {m}
              </span>
            ))}
            {v.backends.map((b) => (
              <span key={b} className={`${CHIP} ${backendTone(b)}`}>
                {b}
              </span>
            ))}
          </span>
        ))}
        <span className="ml-auto flex flex-wrap items-baseline gap-x-3">
          <span data-testid="thread-questions" className={META}>
            {groups.length} question{groups.length === 1 ? "" : "s"}
          </span>
          <span data-testid="thread-turns" className={META}>
            {turns.length} turn{turns.length === 1 ? "" : "s"}
          </span>
          <span
            data-testid="thread-wall"
            className={META}
            title={`${thread.started ?? "?"} → ${thread.ended ?? "?"}`}
          >
            {formatWall(thread.wall_ms)}
          </span>
        </span>
      </div>

      {/* Bounded-window honesty: the card claims to be the whole session
          only when every voice's opening call (a [system, user] prompt) is
          actually in hand. */}
      {!thread.turns_complete && (
        <div
          data-testid="thread-incomplete"
          className="mt-1 text-[11px] text-amber-400/80"
        >
          older turns of this session may sit outside the scanned window —
          this card shows the turns that were read.
        </div>
      )}
      {/* The page's per-thread turn cap stopped the read (a session cannot
          be allowed to blow a polled response). Announced, never silent —
          "load older" continues the SAME session into this card. */}
      {thread.turns_truncated && (
        <div
          data-testid="thread-turns-truncated"
          className="mt-1 text-[11px] text-amber-400/80"
        >
          this page carried the newest {turns.length} turns of the session and
          stopped there — "load older" continues it into this card.
        </div>
      )}

      {/* body: one block per QUESTION, both answers under the one header */}
      <div className="mt-1.5 flex flex-col gap-2">
        {groups.map((group, gi) => (
          <div
            key={`${gi}-${group[0].request_id ?? group[0].ts ?? gi}`}
            data-testid="thread-question"
            className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5"
          >
            <div className="flex items-baseline gap-2">
              <span className="shrink-0 font-mono text-[10px] text-zinc-600">
                Q{gi + 1}
              </span>
              <span
                data-testid="thread-question-text"
                className="whitespace-pre-wrap text-[13px] text-sky-200"
              >
                {group[0].user_delta ?? "—"}
                {group[0].user_delta_truncated && (
                  <span className="text-[10px] text-zinc-600"> …(clipped)</span>
                )}
              </span>
            </div>

            <div className="mt-1.5 flex flex-col gap-1.5">
              {group.map((turn, ti) => {
                const open =
                  turn.request_id != null &&
                  turn.request_id === expandedRequestId;
                return (
                  <div
                    key={turn.request_id ?? `${gi}-${ti}`}
                    data-testid="thread-turn"
                    data-stance={turn.stance ?? undefined}
                    className="rounded border border-zinc-800/60 bg-zinc-950/60 px-2 py-1"
                  >
                    <div className="mb-1 flex flex-wrap items-baseline gap-2">
                      <span
                        data-testid="thread-stance-chip"
                        className={`text-[10px] font-medium uppercase tracking-wide ${stanceAccent(turn.stance)}`}
                      >
                        {turn.stance ?? "reply"}
                      </span>
                      <span className="font-mono text-[10px] text-zinc-500">
                        {turn.model ?? "—"}
                      </span>
                    </div>

                    {turn.empty ? (
                      // A finding-session turn makes no tool calls, so an
                      // empty completion is a genuine "the model returned
                      // nothing" — the loud branch, via the shared note.
                      <EmptyCompletionNote messages={null} />
                    ) : (
                      <MessageBody
                        role="assistant"
                        content={turn.completion}
                        testId={`thread-answer-${turn.request_id ?? ti}`}
                      />
                    )}
                    {turn.completion_truncated && (
                      <div
                        data-testid="thread-answer-clipped"
                        className="text-[10px] text-zinc-600"
                      >
                        answer clipped for the list payload — the context
                        chip opens the untouched record.
                      </div>
                    )}

                    {/* per-turn footer: cost + the context disclosure */}
                    <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                      <button
                        type="button"
                        data-testid="thread-context-chip"
                        aria-expanded={open}
                        className={`${CHIP} ${TONE_QUIET} hover:text-zinc-200`}
                        onClick={() => onToggleContext(turn.request_id)}
                      >
                        {/* null = the row carried no legible prompt stack,
                            so there is no count to disclose — the reader
                            still opens the untouched record. */}
                        {(turn.prefix_message_count ?? 0) > 0
                          ? `context: ${turn.prefix_message_count} prior message${
                              turn.prefix_message_count === 1 ? "" : "s"
                            }`
                          : "full record"}
                      </button>
                      <span className={META}>
                        {turn.tokens_in ?? "—"}→{turn.tokens_out ?? "—"} tok
                      </span>
                      <span className={META}>
                        {turn.latency_ms != null
                          ? `${fmt(turn.latency_ms, 0)}ms`
                          : "—"}
                      </span>
                      <span className={META} title={turn.ts ?? ""}>
                        {clock(turn.ts)}
                      </span>
                    </div>

                    {open && expansion}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
