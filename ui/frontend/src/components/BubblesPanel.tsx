// BubblesPanel — the coordinator loop's "raise to the human" channel
// (memory/coordinator_bubbles.jsonl, via GET /api/coordinator/bubbles). A bubble
// IS an escalation: the loop is asking for a human's eyes. Per ui_plan.md
// §AUTONOMY OBSERVABILITY design principle #8 ("don't over-alarm") the channel
// is prominent (amber) but quiet when empty — it carries only what needs a human.
//
// Row shape is the EMIT contract (orchestrator/coordinator.py:_persist_bubble_up):
// the whole row is {timestamp, run_id, finding_ids, note}. `note` is the message;
// `finding_ids` are the findings being raised (rendered as chips). There is no
// per-bubble severity, bubble_id, or agent — every bubble is a coordinator
// escalation, so the panel tones them uniformly rather than inventing a tier.
//
// Polls getBubbles() unless an `initial` list is passed (tests render
// synchronously from BUBBLES_FIXTURE, no fetch mock — mirrors
// ResolvedIterationsList's `initial` prop). Clean empty state when the channel
// is quiet (the gitignored file is absent / no bubbles raised yet).
import { useEffect, useState } from "react";
import { getBubbles } from "../api/http";
import type { Bubble } from "../types/schemas";

function shortTimestamp(iso: string | null | undefined): string {
  // The row is producer-owned JSONL: `timestamp` is declared string|null but a
  // producer could write a number (epoch) or other non-string. Guard so a bad
  // value renders "—" rather than throwing `iso.replace is not a function` and
  // blanking the whole panel.
  if (typeof iso !== "string" || !iso) return "—";
  return iso.replace("T", " ").replace("Z", "");
}

// Coerce a producer-owned `finding_ids` into a clean list of non-empty string
// chips. The EMIT contract is string[], but the row is partial/legacy/malformed
// data: the field may be null/undefined (skip), a non-array scalar (skip — never
// `.map` a string), or an array carrying null/blank/non-string elements (drop
// them, so no blank chip and no duplicate-empty React `key` warning).
function findingChips(finding_ids: unknown): string[] {
  if (!Array.isArray(finding_ids)) return [];
  return finding_ids
    .filter((fid): fid is string => typeof fid === "string" && fid.length > 0);
}

// Coerce a producer-owned display scalar (`note`, `run_id`) to a safe string.
// `note`/`run_id` are declared string|null, but the row is producer-owned JSONL
// that could carry the wrong TYPE: an object or array there makes React throw
// "Objects are not valid as a React child" and blanks the WHOLE panel (an object
// `note` and an object `run_id` both did, pre-guard). A string passes through; a
// finite number/bool stringifies (so a numeric run_id still reads); an object /
// array / null/undefined / non-finite number (NaN/±Infinity) returns "" — the
// caller treats "" as absent (no stray node, no NaN text). Mirrors AgentBadge's
// "treat any non-string the same as absent" type-guard.
function displayText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  if (typeof value === "boolean") return String(value);
  return "";
}

interface Props {
  initial?: Bubble[];
  pollMs?: number;
}

export default function BubblesPanel({ initial, pollMs = 5000 }: Props) {
  const [bubbles, setBubbles] = useState<Bubble[]>(initial ?? []);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(initial !== undefined);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getBubbles()
        .then((r) => {
          if (!active) return;
          setBubbles(r.bubbles);
          setLoaded(true);
          setError(null);
        })
        .catch((e) => {
          if (active) setError(String(e));
        });
    load();
    const id = setInterval(load, pollMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [initial, pollMs]);

  // Drop rows the producer-owned JSONL could emit that aren't bubble objects
  // (a malformed line parsed to null/undefined, or a non-object scalar). Skip a
  // bad row rather than let `bad.run_id` crash the whole list — the count and
  // empty state then reflect renderable bubbles. `Array.isArray` first: the
  // backend payload `bubbles` is producer-owned too, so a non-array there (a
  // single object, null, a scalar) would make `.filter` throw and blank the
  // panel — coerce it to [] (clean empty state) instead.
  const rows = (Array.isArray(bubbles) ? bubbles : []).filter(
    (b): b is Bubble => typeof b === "object" && b !== null,
  );

  return (
    <div
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="bubbles-panel"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Bubbles
        </h2>
        <span className="text-[10px] text-zinc-600">
          /api/coordinator/bubbles · raised to you
        </span>
        <span className="ml-auto text-[11px] text-zinc-500">
          {rows.length}
        </span>
      </div>

      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}

      {loaded && rows.length === 0 && !error && (
        <div className="mt-2 text-sm text-zinc-500" data-testid="bubbles-empty">
          No bubbles. The loop has nothing to raise.
        </div>
      )}

      {rows.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {rows.map((bubble, i) => {
            // Coerce the producer-owned display scalars once. `runId`/`note` may
            // arrive as the wrong TYPE (object/array → React-child crash); pass
            // them through displayText so a bad value renders as absent/empty
            // rather than throwing and blanking the panel.
            const runId = displayText(bubble.run_id);
            const note = displayText(bubble.note);
            return (
            <li
              key={`${runId || "bubble"}-${i}`}
              data-testid={`bubble-${i}`}
              className="rounded border border-amber-900/60 bg-amber-950/20 px-2 py-1.5"
            >
              <div className="flex flex-wrap items-baseline gap-2 text-[10px]">
                {runId && (
                  <span className="font-mono text-zinc-500">{runId}</span>
                )}
                {findingChips(bubble.finding_ids).map((fid, j) => (
                  <span
                    key={`${fid}-${j}`}
                    className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono uppercase tracking-wide text-zinc-400"
                  >
                    {fid}
                  </span>
                ))}
                <span className="ml-auto font-mono text-zinc-500">
                  {shortTimestamp(bubble.timestamp)}
                </span>
              </div>
              <div className="mt-1 text-xs text-amber-200">
                {note || "(no note)"}
              </div>
            </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
