// DebateExchange — the bounded challenger⇄defender debate (D-071) inside the
// dossier's critic section. Renders ONLY when critique.debate exists (the
// caller guards with asRecord and mounts nothing otherwise, so pre-debate
// iterations keep their single-shot skeptic line untouched — zero regression).
//
//   - HEADER: verdict badge (survives_debate emerald / refuted-family red /
//     anything else quiet zinc — a LOCAL tone map, additive-only per roles.ts:
//     never retints VERDICT_TONE), round count, and the raw stop_reason.
//   - CONCESSION: stop_reason === "challenger_conceded" is a machine-validated
//     terminal EVENT, not a prose turn — rendered as an explicit terminal row
//     after the transcript ("challenger CONCEDED (machine-validated stance)"),
//     visible even while the transcript is collapsed (it is the outcome).
//   - TRANSCRIPT: the turns in producer order (alternating challenger/defender
//     by data, never forced), each with a role accent (challenger rose /
//     defender emerald — the roles.ts skeptic/nara accent families), a backend
//     badge in the qwen/gemma tones the health panels + model-io page use
//     (roles.backendTone), the model in quiet mono, and the turn text in a
//     monospace-friendly pre-wrap block. Collapsed beyond the first 2 turns;
//     "show all N turns" expands (and collapses back).
//
// ROBUSTNESS: every field is producer-owned JSON parsed unchecked. All scalars
// ride asText (drop-by-typeof — an object/NaN/array never reaches React as a
// child); a non-array transcript renders no turns (header + any concession
// still show); non-record turns are dropped, not faked. Turn text reads `text`
// (the producer key) and falls back to `content` defensively.
import { useState } from "react";
import { backendTone, TONE_QUIET } from "../../roles";
import { Badge } from "../chips";
import { asRecord, asText } from "./journeyStations";

// Debate-verdict tones — a LOCAL additive map (roles.ts contract: new ink
// only). survives_debate mirrors VERDICT_TONE.survives' emerald; the
// refuted/falsified family mirrors its red; unknown values stay quiet.
const DEBATE_VERDICT_TONE: Record<string, string> = {
  survives_debate: "bg-emerald-950 text-emerald-400",
  refuted: "bg-red-950 text-red-400",
  refuted_in_debate: "bg-red-950 text-red-400",
  falsified: "bg-red-950 text-red-400",
};

function debateVerdictTone(verdict: string): string {
  return Object.prototype.hasOwnProperty.call(DEBATE_VERDICT_TONE, verdict)
    ? DEBATE_VERDICT_TONE[verdict]
    : TONE_QUIET;
}

// Role accents: the roles.ts caller-tag families — adversarial (skeptic_*)
// rose, the generator/defender emerald, anything unknown quiet zinc.
const ROLE_ACCENT: Record<string, string> = {
  challenger: "text-rose-300",
  defender: "text-emerald-300",
};

function roleAccent(role: string): string {
  return Object.prototype.hasOwnProperty.call(ROLE_ACCENT, role)
    ? ROLE_ACCENT[role]
    : "text-zinc-300";
}

const VISIBLE_COLLAPSED = 2;

export default function DebateExchange({
  debate,
}: {
  /** The critique.debate block, already asRecord-coerced by the caller. */
  debate: Record<string, unknown>;
}) {
  const [showAll, setShowAll] = useState(false);

  const verdict = asText(debate.verdict);
  const rounds = asText(debate.rounds);
  const stopReason = asText(debate.stop_reason);
  const conceded = stopReason === "challenger_conceded";

  // Usable turns only: record-shaped entries. Non-records drop (never faked);
  // a record turn with no usable text still shows its role/badge line.
  const turns = (Array.isArray(debate.transcript) ? debate.transcript : [])
    .map((t) => asRecord(t))
    .filter((t): t is Record<string, unknown> => t !== null);

  const visibleTurns = showAll ? turns : turns.slice(0, VISIBLE_COLLAPSED);
  const hidden = turns.length - visibleTurns.length;

  return (
    <div
      data-testid="journey-debate"
      className="mt-2 rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5"
    >
      {/* header: verdict badge · rounds · stop_reason */}
      <div
        data-testid="debate-header"
        className="flex flex-wrap items-baseline gap-2 text-[11px]"
      >
        <span className="text-[10px] uppercase tracking-wide text-zinc-500">
          debate
        </span>
        <span data-testid="debate-verdict">
          <Badge text={verdict} tone={debateVerdictTone(verdict)} />
        </span>
        {rounds.length > 0 ? (
          <span data-testid="debate-rounds" className="text-zinc-400">
            {rounds} rounds
          </span>
        ) : null}
        {stopReason.length > 0 ? (
          <span data-testid="debate-stop" className="font-mono text-[10px] text-zinc-500">
            stop: {stopReason}
          </span>
        ) : null}
      </div>

      {/* transcript: producer-ordered turns, collapsed beyond the first 2 */}
      {turns.length > 0 ? (
        <ol data-testid="debate-transcript" className="mt-1.5 space-y-1.5">
          {visibleTurns.map((turn, i) => {
            const role = asText(turn.role);
            const backend = asText(turn.backend);
            const model = asText(turn.model);
            const round = asText(turn.round);
            const text = asText(turn.text) || asText(turn.content);
            return (
              <li
                key={i}
                data-testid={`debate-turn-${i}`}
                data-role={role || undefined}
                className="rounded border border-zinc-800/60 bg-zinc-950/60 px-2 py-1"
              >
                <div className="flex flex-wrap items-baseline gap-2">
                  <span
                    className={`text-[10px] font-medium uppercase tracking-wide ${roleAccent(role)}`}
                  >
                    {role || "(unattributed)"}
                  </span>
                  {round.length > 0 ? (
                    <span className="text-[9px] text-zinc-600">r{round}</span>
                  ) : null}
                  {backend.length > 0 ? (
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] ${backendTone(backend)}`}
                    >
                      {backend}
                    </span>
                  ) : null}
                  {model.length > 0 ? (
                    <span className="font-mono text-[10px] text-zinc-500">
                      {model}
                    </span>
                  ) : null}
                </div>
                {text.length > 0 ? (
                  <p className="mt-1 whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-zinc-300">
                    {text}
                  </p>
                ) : (
                  <p className="mt-1 text-[10px] text-zinc-600">
                    (no turn text on this row)
                  </p>
                )}
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="mt-1 text-[10px] text-zinc-600">
          no debate transcript on this row
        </p>
      )}

      {hidden > 0 || (showAll && turns.length > VISIBLE_COLLAPSED) ? (
        <button
          type="button"
          data-testid="debate-expand"
          aria-expanded={showAll}
          onClick={() => setShowAll((v) => !v)}
          className="mt-1.5 rounded border border-zinc-800 px-1.5 py-0.5 text-[10px] text-sky-300 hover:border-zinc-600 hover:text-sky-200"
        >
          {showAll
            ? "collapse transcript"
            : `show all ${turns.length} turns (${hidden} more)`}
        </button>
      ) : null}

      {/* the CONCESSION — a machine-validated terminal event, not a prose
          turn; always visible, even while the transcript is collapsed. */}
      {conceded ? (
        <div
          data-testid="debate-concession"
          className="mt-1.5 rounded border border-emerald-900/50 bg-emerald-950/20 px-2 py-1 text-[11px] text-emerald-300"
        >
          <span className="text-[10px] uppercase tracking-wide">
            terminal event
          </span>{" "}
          challenger CONCEDED (machine-validated stance)
        </div>
      ) : null}
    </div>
  );
}
