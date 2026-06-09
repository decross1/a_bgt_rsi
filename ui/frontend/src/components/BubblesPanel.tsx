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
  if (!iso) return "—";
  return iso.replace("T", " ").replace("Z", "");
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
          {bubbles.length}
        </span>
      </div>

      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}

      {loaded && bubbles.length === 0 && !error && (
        <div className="mt-2 text-sm text-zinc-500" data-testid="bubbles-empty">
          No bubbles. The loop has nothing to raise.
        </div>
      )}

      {bubbles.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {bubbles.map((bubble, i) => (
            <li
              key={`${bubble.run_id ?? "bubble"}-${i}`}
              data-testid={`bubble-${i}`}
              className="rounded border border-amber-900/60 bg-amber-950/20 px-2 py-1.5"
            >
              <div className="flex flex-wrap items-baseline gap-2 text-[10px]">
                {bubble.run_id && (
                  <span className="font-mono text-zinc-500">{bubble.run_id}</span>
                )}
                {(bubble.finding_ids ?? []).map((fid) => (
                  <span
                    key={fid}
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
                {bubble.note ?? "(no note)"}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
