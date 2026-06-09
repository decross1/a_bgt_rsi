// CoordinatorCycleCard — one cycle = one narrative. Renders a single row of
// run_state/coordinator_cycles.jsonl so a human auditor can read the whole
// decision in one scroll: the auto-chosen topic (+ its source) → the plan as
// per-action status chips → the linked dispatched iteration → how many findings
// were promoted and bubbles raised. See ui_plan.md §AUTONOMY OBSERVABILITY
// ("one cycle = one narrative") and ui_autonomy_observability_plan.md.
//
// The headline design principle here is "make absence legible": a dispatched
// action that ERRORED is a visible red chip carrying its error string inline,
// never a silent gap. Executed = emerald, skipped = zinc, errored = red.
// Provenance is on the header via <AgentBadge> + a topic_source badge.
import { useId } from "react";
import AgentBadge from "./AgentBadge";
import SourceBadge from "./SourceBadge";
import type {
  CoordinatorCycle,
  CoordinatorOutcome,
  CoordinatorPlanStep,
} from "../types/schemas";

// Status → chip tone. Open default (quiet zinc) so an unrecognized EMIT-side
// status renders generically rather than crashing. `pending` is the synthesized
// status for a planned-but-not-yet-executed action (a `status:"planned"` cycle
// carries a plan with no outcomes) — amber, distinct from a ran-and-passed
// (emerald) or skipped (zinc) action: the plan is legible before it runs.
const STATUS_TONE: Record<string, string> = {
  passed: "bg-emerald-950 text-emerald-400",
  skipped: "bg-zinc-800 text-zinc-400",
  errored: "bg-red-950 text-red-400",
  pending: "bg-amber-950 text-amber-400",
};

function statusTone(status: string): string {
  // `status` is producer-owned JSONL (an outcome's `status`), so a novel /
  // forward-compat enum value can collide with an inherited Object.prototype
  // member name ("toString", "constructor", "valueOf", "hasOwnProperty",
  // "__proto__", ...). A bare `STATUS_TONE[status]` then resolves to a FUNCTION
  // via the prototype chain instead of undefined, so `?? QUIET` does NOT fall
  // through and that function interpolates into className as
  // "function toString() { [native code] }" — the chip loses its quiet fallback
  // and lands garbage CSS. Look up own keys only; any unrecognized status
  // (incl. a prototype collision) degrades to the quiet zinc fallback.
  // (Mirrors SourceBadge.sourceTone / AgentBadge's guard.)
  return Object.prototype.hasOwnProperty.call(STATUS_TONE, status)
    ? STATUS_TONE[status]
    : "bg-zinc-800 text-zinc-400";
}

// The cycle rows are producer-owned JSONL (run_state/coordinator_cycles.jsonl)
// and may be partial/legacy/malformed — a pre-2026-06-09 row, a half-written
// append, or a future EMIT shape can hand us `plan`/`outcomes` that are
// undefined, null, or not even an array. Reading `.length`/`.map` on those
// throws and unwinds the whole Coordinator page (one bad row blanks every
// cycle). Coerce to a safe array so a malformed field degrades to "empty"
// rather than crashing the list (make-absence-legible applies to the row's
// own shape too).
function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

// A producer-owned scalar (topic / dispatched_iteration_id) rendered as a React
// child must be a string — a malformed row carrying an object/array there throws
// "Objects are not valid as a React child" and crashes the whole card. Returns
// the string (incl. empty) or null when it's not a string, so the block omits
// instead of crashing. Numbers are stringified (a numeric id is still legible).
function asText(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

// `timestamp` is a producer-owned scalar. A well-shaped row carries an ISO
// string (a garbage string like "not-a-date" is harmless — `.replace` is a
// no-op), but a malformed/legacy row could write a NUMBER (e.g. a Unix epoch
// int) where the string is expected; calling `.replace` on that throws
// "iso.replace is not a function" and unwinds the whole card — and the route
// maps every cycle, so one bad row blanks the entire Coordinator page. Only
// `.replace` an actual string; anything non-string degrades to the em-dash
// placeholder rather than crashing.
function shortTimestamp(iso: unknown): string {
  if (typeof iso !== "string" || iso === "") return "—";
  return iso.replace("T", " ").replace("Z", "");
}

// `promoted_finding_ids` / `bubble_run_ids` are producer-owned and meant to be
// arrays; the count is just their length. But `value?.length ?? 0` reads
// `.length` off WHATEVER the field is — and a malformed row carrying a STRING
// there (a scalar id like "sf-001" instead of `["sf-001"]`) yields the string's
// CHARACTER count, fabricating a wrong number ("6 findings promoted") with no
// crash to flag it. Count the elements only when it's truly an array; any other
// type (string/number/object/null) is "not a list" → 0.
function countArray(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

// One action's chip. For an errored action the error string is shown inline
// (red) — a failed dispatch must be a visible row, never hidden. `action`/
// `status` are coalesced so an outcome row missing either (a malformed/legacy
// producer row) still renders a legible chip rather than an empty/`undefined`
// label or a broken testid.
function ActionChip({ outcome }: { outcome: CoordinatorOutcome }) {
  // `action`/`status` are producer-owned JSONL. `?? "?"` only catches
  // null/undefined — a malformed/legacy row carrying an OBJECT or ARRAY there
  // (the row-27 shape) sails past `??` and, interpolated as a React child,
  // throws "Objects are not valid as a React child" and unwinds the whole
  // Coordinator page (the route maps every cycle). Route both through asText
  // (string-or-null, numbers stringified) and fall back to the legible
  // "?"/"unknown" placeholder so a bad element degrades to a visible-but-quiet
  // chip rather than crashing — make-absence-legible applies to the chip's own
  // shape too. (Same defense already used for topic/dispatched_iteration_id.)
  const action = asText(outcome.action) ?? "?";
  const status = asText(outcome.status) ?? "unknown";
  const errored = status === "errored";
  // `error` is the producer's string; a malformed row could carry a non-string
  // (object/array), which as a React child throws "Objects are not valid as a
  // React child" and crashes the page. Only render it when it's a real string.
  const errorText = typeof outcome.error === "string" ? outcome.error : null;
  return (
    <li
      data-testid={`coordinator-action-${action}`}
      className="flex flex-wrap items-baseline gap-2"
    >
      <span className="font-mono text-xs text-zinc-300">{action}</span>
      <span
        className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${statusTone(
          status,
        )}`}
      >
        {status}
      </span>
      {errored && errorText && (
        <span
          data-testid={`coordinator-action-error-${action}`}
          className="w-full rounded border border-red-900/60 bg-red-950/30 px-2 py-1 font-mono text-[11px] text-red-300"
        >
          {errorText}
        </span>
      )}
    </li>
  );
}

export default function CoordinatorCycleCard({
  cycle,
}: {
  cycle: CoordinatorCycle;
}) {
  const promotedCount = countArray(cycle.promoted_finding_ids);
  const bubbleCount = countArray(cycle.bubble_run_ids);

  // a11y: this card IS the "one cycle = one narrative" unit, so it is an
  // <article> landmark a screen-reader user can navigate to. Name it by the
  // topic heading via aria-labelledby when there's a topic; a malformed/absent
  // topic (asText → null) leaves nothing to label, so fall back to a generic
  // aria-label so the region is never anonymous. `useId` (not run_id) backs the
  // id: run_id is producer-owned and NOT unique across rows (the route keys
  // cards by run_id+index for exactly that reason), so a static id-from-run_id
  // would duplicate across cards; useId is unique per instance.
  const topic = asText(cycle.topic);
  const topicId = useId();

  // Make the plan legible BEFORE it executes. A `status:"planned"` cycle (live
  // 2026-06-09 data) carries a non-empty `plan` with EMPTY `outcomes` — mapping
  // only `outcomes` would render the proposed actions as a blank section, i.e.
  // "nothing happened" when the truth is "planned, not yet run" (the dark-loop
  // failure this view exists to fix). When there are no outcomes, synthesize a
  // `pending` chip per plan step so each proposed action is a visible row. When
  // outcomes exist, render them verbatim (errored chips unchanged).
  //
  // `plan`/`outcomes` come through `asArray` so a missing/null/non-array field
  // on a malformed row degrades to empty (→ the no-plan note) instead of
  // throwing. A null/non-object outcome element is dropped (it carries no
  // legible action), and a plan step's `action` falls back to "?" so a step
  // missing it still renders a row rather than an empty chip.
  const rawOutcomes = asArray<unknown>(cycle.outcomes).filter(
    (o): o is CoordinatorOutcome => typeof o === "object" && o !== null,
  );
  const actions: CoordinatorOutcome[] =
    rawOutcomes.length > 0
      ? rawOutcomes
      : asArray<CoordinatorPlanStep>(cycle.plan).map((step) => ({
          action: step?.action ?? "?",
          status: "pending",
        }));

  return (
    <article
      data-testid="coordinator-cycle-card"
      role="article"
      {...(topic
        ? { "aria-labelledby": topicId }
        : { "aria-label": "coordinator cycle" })}
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
    >
      {/* Header — topic, its source, the actor, and when. The topic_source
          provenance now goes through <SourceBadge> so the in-sandbox
          "nemoclaw_agent" origin reads violet, distinct from a host-coordinator
          cycle. The stable `coordinator-topic-source` testid is kept on the
          wrapper for the cycle/route tests. */}
      <div className="flex flex-wrap items-baseline gap-2">
        <AgentBadge agent={cycle.agent} />
        <span data-testid="coordinator-topic-source">
          <SourceBadge source={cycle.topic_source} />
        </span>
        <span className="ml-auto font-mono text-[10px] text-zinc-500">
          {shortTimestamp(cycle.timestamp)}
        </span>
      </div>
      {/* Topic as an <h3>: the card's accessible name + a heading a
          screen-reader user can jump to (it was a bare <div>). Same classes →
          identical visual; getByText(topic) still matches the text node. Only
          rendered when there's a real topic string (a malformed row falls back
          to the region's generic aria-label above). */}
      {topic !== null && (
        <h3
          id={topicId}
          className="mt-1 text-sm font-normal text-zinc-200"
        >
          {topic}
        </h3>
      )}

      {/* Plan — per-action status chips. Errored chips carry the error inline;
          a planned-but-not-run cycle shows its proposed actions as `pending`
          chips; a cycle with no valid plan shows an explicit note (never a
          blank gap). */}
      <div className="mt-3">
        {/* a11y: the visible "plan" label names the action list via
            aria-labelledby (an unlabeled <ul> reads as a bare "list" to a
            screen reader). `${topicId}-plan` derives off the per-instance
            useId so it's unique across the many cards the route renders. */}
        <div
          id={`${topicId}-plan`}
          className="text-[10px] uppercase tracking-wide text-zinc-500"
        >
          plan
        </div>
        {actions.length > 0 ? (
          <ul
            aria-labelledby={`${topicId}-plan`}
            className="mt-1 space-y-1.5"
          >
            {actions.map((outcome, i) => (
              <ActionChip key={`${outcome.action}-${i}`} outcome={outcome} />
            ))}
          </ul>
        ) : (
          <div
            data-testid="coordinator-no-plan"
            className="mt-1 text-[11px] text-zinc-500"
          >
            no valid plan{cycle.status ? ` (${cycle.status})` : ""}
          </div>
        )}
      </div>

      {/* Footer — the join keys: dispatched iteration, promoted findings,
          bubbles. */}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-zinc-500">
        {asText(cycle.dispatched_iteration_id) && (
          <span data-testid="coordinator-dispatched-iteration">
            dispatched{" "}
            <span className="font-mono text-zinc-300">
              {asText(cycle.dispatched_iteration_id)}
            </span>
          </span>
        )}
        <span data-testid="coordinator-promoted-count">
          {promotedCount} finding{promotedCount === 1 ? "" : "s"} promoted
        </span>
        <span data-testid="coordinator-bubble-count">
          {bubbleCount} bubble{bubbleCount === 1 ? "" : "s"}
        </span>
      </div>
    </article>
  );
}
