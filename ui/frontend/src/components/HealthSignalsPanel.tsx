// HealthSignalsPanel — the coordinator loop's degraded-but-not-broken signals
// (run_state/health_signals.jsonl, via GET /api/coordinator/health_signals).
// Per ui_plan.md §AUTONOMY OBSERVABILITY design principle #4 ("degraded ≠
// broken"): ml-intern "ran but stored 0 papers" and qwen "generated but emitted
// empty content" are AMBER — the worker/route is up, its output was just thin.
// Surfacing them answers "can I trust this verdict's evidence?" — a verdict
// reached while external search was blind, or the skeptic was empty, is suspect.
//
// Polls getHealthSignals() unless an `initial` list is passed (tests render
// synchronously from HEALTH_SIGNALS_FIXTURE — the ResolvedIterationsList idiom).
// Clean empty state when workers are nominal (no signals → not a blank gap).
import { useEffect, useState } from "react";
import { getHealthSignals } from "../api/http";
import type { HealthSignal } from "../types/schemas";

// Humanize the EMIT signal id into a short chip label. Unknown signals fall
// back to the raw id so a new EMIT signal still renders rather than vanishing.
const SIGNAL_LABEL: Record<string, string> = {
  ml_intern_zero_papers: "ml-intern · 0 papers",
  qwen_degraded_empty_content: "qwen · empty content",
};

function signalLabel(signal: string): string {
  return SIGNAL_LABEL[signal] ?? signal;
}

function shortTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  return iso.replace("T", " ").replace("Z", "");
}

interface Props {
  initial?: HealthSignal[];
  pollMs?: number;
}

export default function HealthSignalsPanel({ initial, pollMs = 5000 }: Props) {
  const [signals, setSignals] = useState<HealthSignal[]>(initial ?? []);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(initial !== undefined);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getHealthSignals()
        .then((r) => {
          if (!active) return;
          setSignals(r.health_signals);
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
      data-testid="health-signals-panel"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Degraded signals
        </h2>
        <span className="text-[10px] text-zinc-600">
          /api/coordinator/health_signals · degraded ≠ down
        </span>
        <span className="ml-auto text-[11px] text-zinc-500">
          {signals.length}
        </span>
      </div>

      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}

      {loaded && signals.length === 0 && !error && (
        <div
          className="mt-2 text-sm text-zinc-500"
          data-testid="health-signals-empty"
        >
          No degraded signals — workers nominal.
        </div>
      )}

      {signals.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {signals.map((sig, i) => (
            <li
              key={`${sig.signal}-${sig.run_id ?? i}`}
              data-testid={`health-signal-${i}`}
              className="rounded border border-amber-900/60 bg-amber-950/20 px-2 py-1.5"
            >
              <div className="flex flex-wrap items-baseline gap-2 text-[10px]">
                <span className="rounded bg-amber-950 px-1.5 py-0.5 uppercase tracking-wide text-amber-400">
                  {signalLabel(sig.signal)}
                </span>
                {sig.iteration_id && (
                  <span className="font-mono text-zinc-500">
                    {sig.iteration_id}
                  </span>
                )}
                <span className="ml-auto font-mono text-zinc-500">
                  {shortTimestamp(sig.timestamp)}
                </span>
              </div>
              {sig.detail && (
                <div className="mt-1 text-xs text-amber-200">{sig.detail}</div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
