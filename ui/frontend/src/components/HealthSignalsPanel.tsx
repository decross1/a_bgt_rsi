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

// health_signals.jsonl is producer-owned and may emit a partial/legacy/malformed
// row: a field the type calls a string can arrive as a number, object, or null.
// Coerce any non-primitive to a safe label so React never sees an object as a
// child (which throws "Objects are not valid as a React child" and blanks the
// whole Dashboard). null/undefined → ""; a finite number/primitive → its string;
// an object → "" (drop it rather than crash the page on one bad row).
// A NON-FINITE number (NaN / Infinity / -Infinity) — which a producer can emit
// when a numeric field is a degenerate division (e.g. empty_calls/total_calls
// with total_calls=0) or a malformed legacy value — also drops to "": String(NaN)
// is the literal text "NaN", and a sentinel leaking into the chip is worse than
// an empty field (it reads as a real signal value).
function asLabel(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return "";
  if (typeof v === "number" && !Number.isFinite(v)) return "";
  return String(v);
}

function signalLabel(signal: string): string {
  const key = asLabel(signal);
  // The signal chip is the row's anchor — it is rendered unconditionally (unlike
  // the iteration_id/detail/timestamp, which are gated on being non-empty). A
  // producer-owned row can emit an empty, whitespace-only, or absent `signal`
  // (which asLabel coerces to ""), and a bare `SIGNAL_LABEL[""] ?? ""` then
  // renders an EMPTY amber pill: a content-less chip reads as a phantom degraded
  // signal with no identity — the opposite of "make absence legible" (design
  // principle #2). Fall back to a legible token (the BubblesPanel `note ||
  // "(no note)"` idiom) so the chip always names something rather than rendering
  // blank. Match on own keys after trimming so a known signal still humanizes.
  if (key.trim() === "") return "(unknown signal)";
  return SIGNAL_LABEL[key] ?? key;
}

function shortTimestamp(iso: string | null | undefined): string {
  // Guard against a non-string timestamp (a malformed row): .replace() on a
  // number/object would throw. Coerce first, then fall back to "—" if empty.
  const s = asLabel(iso);
  if (!s) return "—";
  return s.replace("T", " ").replace("Z", "");
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

  // A producer-owned JSONL line can survive parsing as a non-object (null, a
  // bare scalar) or arrive as a non-array payload. Skip anything that isn't a
  // real object so one bad row can't crash the whole list (`sig.signal` on a
  // null throws). The count + empty state then reflect what's renderable.
  const visible = (Array.isArray(signals) ? signals : []).filter(
    (sig): sig is HealthSignal => sig !== null && typeof sig === "object",
  );

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
          {visible.length}
        </span>
      </div>

      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}

      {loaded && visible.length === 0 && !error && (
        <div
          className="mt-2 text-sm text-zinc-500"
          data-testid="health-signals-empty"
        >
          No degraded signals — workers nominal.
        </div>
      )}

      {visible.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {visible.map((sig, i) => {
            const iterationId = asLabel(sig.iteration_id);
            const detail = asLabel(sig.detail);
            // The React key must route run_id through asLabel AND append the
            // row index (the BubblesPanel/SurfacedFindingsPanel idiom). run_id is
            // producer-owned (`[key: string]: unknown`) and can arrive as an
            // object/array; a raw `sig.run_id ?? i` stringifies every object
            // run_id to "[object Object]", so multiple such rows collide on one
            // key → React's "two children with the same key" console.error. The
            // trailing index keeps the key unique even when two rows legitimately
            // share a signal + run_id.
            const keyRunId = asLabel(sig.run_id) || "signal";
            return (
              <li
                key={`${keyRunId}-${i}`}
                data-testid={`health-signal-${i}`}
                className="rounded border border-amber-900/60 bg-amber-950/20 px-2 py-1.5"
              >
                <div className="flex flex-wrap items-baseline gap-2 text-[10px]">
                  <span className="rounded bg-amber-950 px-1.5 py-0.5 uppercase tracking-wide text-amber-400">
                    {signalLabel(sig.signal)}
                  </span>
                  {iterationId && (
                    <span className="font-mono text-zinc-500">{iterationId}</span>
                  )}
                  <span className="ml-auto font-mono text-zinc-500">
                    {shortTimestamp(sig.timestamp)}
                  </span>
                </div>
                {detail && (
                  <div className="mt-1 text-xs text-amber-200">{detail}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
