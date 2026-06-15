// ConcurrencyWarning — the cockpit's in-place warn/queue guard. The loop and
// the cockpit reuse the SAME models (Gemma gen+defend; Qwen skeptic+attack),
// so when an iteration is mid-flight on the shared models the cockpit shows an
// explicit warning (the model-health panels already surface contention; this is
// the in-cockpit reminder). This is a WARN/QUEUE tone, NOT a hard block —
// continuous-loop scheduling is a Phase-2 concern, not this build (2026-06-14
// session note PART 2 "Concurrency warning").
//
// Source: GET /api/todo/concurrency (api/todo.ts getConcurrency). `active: false`
// means no contention → this renders NOTHING. When mid-flight (active:true) the
// run is named (kind / label / narration, sourced from run_state/active_run.json).
// A missing endpoint (version skew) resolves active:false quietly in
// getConcurrency — so a skewed backend never fabricates a warning.
//
// The `status` prop (when provided) wins and suppresses the fetch — the cockpit
// shell / tests inject a known ConcurrencyStatus; a standalone mount passes
// nothing and self-polls once. No new deps; mirrors the override idiom of
// useAttestCapability.
import { useEffect, useState } from "react";
import { getConcurrency } from "../../api/todo";
import type { ConcurrencyStatus } from "../../types/todo";

interface Props {
  /** Injected status — when provided, wins and suppresses the self-fetch. */
  status?: ConcurrencyStatus;
}

// Mirror api/todo.ts's asConcurrency: strictly re-type a producer-owned (here,
// injected) status so a garbled value degrades to a legible fallback. A
// non-object / array / null → null (renders nothing — never throws on a
// primitive's `.active`). `active` is strict === true; the optional run-describing
// fields survive ONLY when a non-empty string (an object/number/array/empty
// string is dropped, so React never renders "[object Object]" or a stray number).
function asSafeStatus(raw: unknown): ConcurrencyStatus | null {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return null;
  const b = raw as Record<string, unknown>;
  const out: ConcurrencyStatus = { active: b.active === true };
  if (typeof b.kind === "string" && b.kind.length > 0) out.kind = b.kind;
  if (typeof b.label === "string" && b.label.length > 0) out.label = b.label;
  if (typeof b.narration === "string" && b.narration.length > 0) {
    out.narration = b.narration;
  }
  return out;
}

export default function ConcurrencyWarning({ status }: Props) {
  const [fetched, setFetched] = useState<ConcurrencyStatus | null>(null);
  useEffect(() => {
    if (status !== undefined) return;
    let active = true;
    getConcurrency()
      .then((s) => {
        if (active) setFetched(s);
      })
      // A failed self-fetch (network error, a non-404 !ok throw from
      // getConcurrency) must NOT fabricate a warning — leave `fetched` null so
      // the guard stays silent, and swallow the rejection so it never surfaces
      // as an unhandled-rejection console error.
      .catch(() => {
        /* cannot detect contention → stay idle, never warn */
      });
    return () => {
      active = false;
    };
  }, [status]);

  // The fetched path is already sanitized by api/todo.ts (asConcurrency strictly
  // coerces every field). The INJECTED `status` prop, however, is producer-owned
  // and bypasses that client — the cockpit shell / a future caller may hand us a
  // garbled value (a non-object, an array, `active` as a stringy/numeric truthy,
  // `kind`/`label`/`narration` as an object/number). Coerce the resolved status
  // the same way the client does so an injected prop degrades, never crashes or
  // leaks "[object Object]". A well-formed ConcurrencyStatus passes through
  // unchanged (behavior-preserving for valid input).
  const safe = asSafeStatus(status !== undefined ? status : fetched);

  // Idle (or unresolved, or a skew-default idle) → render nothing. The guard is
  // only present when there is real contention to warn about. `active` is
  // coerced strictly (=== true), so a truthy non-boolean never fabricates a
  // warning.
  if (safe === null || safe.active !== true) return null;

  return (
    <div
      data-testid="concurrency-warning"
      role="status"
      className="rounded border border-amber-800/70 bg-amber-950/40 px-2 py-1 text-[11px] text-amber-300"
    >
      <span className="font-medium uppercase tracking-wide">⚠ models busy</span>
      {" — "}
      {safe.narration ??
        "an iteration is mid-flight on the shared models (Gemma/Qwen); your turn may queue."}
      {(safe.kind != null || safe.label != null) && (
        <span className="text-zinc-500">
          {" · "}
          {safe.kind != null && (
            <span className="font-mono">{safe.kind}</span>
          )}
          {safe.label != null && (
            <>
              {" "}
              <span className="font-mono">{safe.label}</span>
            </>
          )}
        </span>
      )}
      <span className="text-zinc-500">
        {" · "}warn/queue, not a block
      </span>
    </div>
  );
}
