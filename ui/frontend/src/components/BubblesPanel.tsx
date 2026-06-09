// BubblesPanel — the coordinator loop's "raise to the human" channel
// (memory/coordinator_bubbles.jsonl, via GET /api/coordinator/bubbles). This is
// the noisiest-by-importance surface in the autonomy views, so it follows
// ui_plan.md §AUTONOMY OBSERVABILITY design principle #8 ("don't over-alarm"):
// prominent but not noisy — tone is driven by severity, not blanket-red. A
// `raise` is what actually needs a human's eyes (red emphasis); `warn` is amber;
// `info` is quiet zinc. Every bubble badges its actor (AgentBadge) so the human
// can see WHO raised it (coordinator / nara / a workflow sub-agent).
//
// Polls getBubbles() at ~0.2 Hz unless an `initial` list is passed (tests render
// synchronously from BUBBLES_FIXTURE, no fetch mock — mirrors
// ResolvedIterationsList's `initial` prop). Renders a clean empty state when the
// channel is quiet (the gitignored file is absent / no bubbles raised yet).
import { useEffect, useState } from "react";
import { getBubbles } from "../api/http";
import AgentBadge from "./AgentBadge";
import type { Bubble } from "../types/schemas";

// Severity tone. `raise` is the only tier that demands a human now, so it gets
// red emphasis; `warn` is amber (degraded, eyeball-when-convenient); `info` is
// quiet zinc (a log line, not an alarm). Unknown/absent severity reads as info.
const SEVERITY_TONE: Record<string, string> = {
  raise: "border-red-900/60 bg-red-950/30",
  warn: "border-amber-900/60 bg-amber-950/20",
  info: "border-zinc-800/60 bg-zinc-950/40",
};

const SEVERITY_CHIP: Record<string, string> = {
  raise: "bg-red-950 text-red-400",
  warn: "bg-amber-950 text-amber-400",
  info: "bg-zinc-800 text-zinc-400",
};

function severityKey(severity: Bubble["severity"]): "raise" | "warn" | "info" {
  if (severity === "raise" || severity === "warn") return severity;
  return "info";
}

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
        <div
          className="mt-2 text-sm text-zinc-500"
          data-testid="bubbles-empty"
        >
          No bubbles. The loop has nothing to raise.
        </div>
      )}

      {bubbles.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {bubbles.map((bubble) => {
            const key = severityKey(bubble.severity);
            return (
              <li
                key={bubble.bubble_id}
                data-testid={`bubble-${bubble.bubble_id}`}
                data-severity={key}
                className={`rounded border px-2 py-1.5 ${SEVERITY_TONE[key]}`}
              >
                <div className="flex flex-wrap items-baseline gap-2 text-xs">
                  <AgentBadge agent={bubble.agent} />
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${SEVERITY_CHIP[key]}`}
                  >
                    {key}
                  </span>
                  <span className="ml-auto font-mono text-[10px] text-zinc-500">
                    {shortTimestamp(bubble.timestamp)}
                  </span>
                </div>
                <div className="mt-1 text-xs text-zinc-300">{bubble.text}</div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
