// DirectiveSignOffField — the optional --directive add-on to a sign-off
// (outcome 1 variant). A sign-off MAY carry a directive ("proceed to <next
// step>") instead of a bare "this is fine". This is the SUPERSET of the existing
// gate_verdict valid path: EMPTY directive == a bare sign-off == today's
// behaviour (the integrator routes that through GateVerdictForm / attest.ts). A
// non-empty directive routes through the NEW sign-off CLI, which records the
// directive on the verdict/audit row.
//
// POSTs /api/todo/directive_signoff, which — once the seam lands — shells the
// NEW directive sign-off argv. Until then the endpoint is an honest STUB:
// {status:"stub", would_run:[...argv]}, writing NOTHING (rule 4). No execute
// button — the would-run argv is read-only (D-046 / rule 8).
//
// It is a small CONTROLLED field: the integrator owns the iterationId and the
// note (the sign-off's audit note) and lifts the directive value via
// onDirectiveChange if it wants to drive its own submit; the field also offers
// its own submit for the directive variant. Empty directive disables that
// submit and shows the bare-sign-off note.
import { useState } from "react";
import { postDirectiveSignoff, TodoError, type TodoResult } from "../../api/todo";

interface Props {
  iterationId: string;
  /** the sign-off audit note (required by the sign-off CLI for the directive
   *  variant — the integrator passes the same note its verdict form collects). */
  note: string;
  /** actions.directive_signoff from GET /api/todo/available — false keeps the
   *  field in its honest stub state (directive submit disabled). */
  available: boolean;
  /** lift the directive value so the integrator can drive a combined submit. */
  onDirectiveChange?: (directive: string) => void;
  onSubmitted?: () => void;
}

// `iterationId` and `note` are typed `string`, but they are CONTROLLED by the
// integrator, which lifts them off producer-owned bodies (active_run.json / the
// /api/* envelopes). A legacy/partial row can hand us a non-string (null, a
// number, an object) where a string is expected; a bare `.trim()` then throws
// "x.trim is not a function" and blanks the cockpit on one bad field. Coerce to
// a safe string and DROP a non-stringy value to "" (SystemActivityHero.asText
// idiom) so an empty-vs-malformed prop degrades to the same bare-placeholder
// path as a genuinely empty one.
const asStr = (v: unknown): string => (typeof v === "string" ? v : "");

const argvPreview = (iterationId: unknown, directive: unknown, note: unknown): string => {
  const iter = asStr(iterationId).trim();
  const dir = asStr(directive).trim();
  const n = asStr(note).trim();
  return (
    ".venv-chroma/bin/python -m orchestrator.gate_cli --iteration-id" +
    ` ${iter || "<iter-ID>"} --verdict valid` +
    ` --directive ${dir ? JSON.stringify(dir) : "<proceed to ...>"}` +
    ` --note ${n ? JSON.stringify(n) : "<why>"}` +
    " --gated-by human:ui"
  );
};

export default function DirectiveSignOffField({
  iterationId,
  note,
  available,
  onDirectiveChange,
  onSubmitted,
}: Props) {
  const [directive, setDirective] = useState("");
  const [result, setResult] = useState<TodoResult | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // `note` is a controlled prop lifted off producer-owned JSON; a non-string
  // value would make `note.trim()` throw and blank the field. Coerce defensively
  // — a non-string note reads as empty, which (correctly) leaves the directive
  // submit disabled, the same as a genuinely empty note.
  const noteStr = asStr(note);
  const hasDirective = directive.trim().length > 0;
  // The directive variant additionally needs the sign-off note (its audit value)
  // and the live capability. Coerce `available` strictly (=== true) — a truthy
  // non-boolean must NOT light up the live submit (rule 4 / attest.ts idiom).
  const disabled = submitting || available !== true || !hasDirective || noteStr.trim().length === 0;

  const update = (value: string) => {
    setDirective(value);
    onDirectiveChange?.(value);
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await postDirectiveSignoff({
        iteration_id: asStr(iterationId),
        directive: directive.trim(),
        note: noteStr.trim(),
      });
      setResult(res);
      onSubmitted?.();
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div data-testid="directive-signoff-field" className="rounded border border-emerald-900/60 bg-zinc-950/40 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-emerald-400">
        sign-off directive (optional) · POST /api/todo/directive_signoff →
        orchestrator.gate_cli --directive
      </div>
      {available !== true && (
        <div data-testid="directive-signoff-stub" className="mt-0.5 text-[10px] text-zinc-500">
          stub — lights up when the directive sign-off seam lands
          (docs/todo_cockpit_seam_plan.md). Posts now return a read-only
          would-run preview and write nothing.
        </div>
      )}

      <input
        type="text"
        value={directive}
        onChange={(e) => update(e.target.value)}
        aria-label="sign-off directive (optional)"
        placeholder="directive (optional — e.g. 'proceed to step 9')"
        className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
      />
      {!hasDirective && (
        <div data-testid="directive-signoff-bare" className="mt-0.5 text-[10px] text-zinc-500">
          empty = a bare sign-off (today's behaviour) — record it through the
          normal verdict form; no directive is attached.
        </div>
      )}

      {hasDirective && (
        <>
          <div className="mt-1 text-[10px] uppercase tracking-wide text-zinc-600">
            would run (read-only — no execute)
          </div>
          <pre
            data-testid="directive-signoff-argv"
            aria-label="would run (read-only — no execute)"
            className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-[11px] text-zinc-400"
          >
            {argvPreview(iterationId, directive, note)}
          </pre>
        </>
      )}

      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          disabled={disabled}
          onClick={submit}
          className={
            "rounded border border-emerald-800 bg-emerald-950 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-emerald-300 hover:bg-emerald-900 " +
            "disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-600"
          }
        >
          sign off with directive
        </button>
        {submitting && (
          <span data-testid="directive-signoff-submitting" className="text-[11px] text-zinc-500">
            submitting…
          </span>
        )}
      </div>

      {result !== null && typeof result === "object" && (
        <div data-testid="directive-signoff-result" className="mt-1 text-[11px] text-emerald-300">
          {/* Rule 4 / honest-stub: a `would_run` preview is the DEFINING
              signature of a stub body that wrote NOTHING. We must NOT claim a
              write just because `stub`/`status` arrived mistyped (e.g. the
              producer sent `stub:"true"` or a stray `status:"ok"` alongside a
              `would_run` array). Treat ANY body carrying a would-run preview as
              a stub (nothing written); only a body with NO preview AND no stub
              marker is reported as a real recorded sign-off — the safe,
              under-claiming default. */}
          {result.stub === true ||
          result.status === "stub" ||
          Array.isArray(result.would_run)
            ? "stub response — nothing written (the seam is not live)"
            : "sign-off recorded with directive"}
          {Array.isArray(result.would_run) && (
            <pre
              data-testid="directive-signoff-wouldrun"
              className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-[11px] text-zinc-400"
            >
              {/* would_run is producer-owned: a non-string element (object /
                  null / number) must NOT leak "[object Object]" into the
                  human-facing argv preview — keep only legible string/number
                  tokens (asText idiom), drop the rest. */}
              {(result.would_run as unknown[])
                .map((t) =>
                  typeof t === "string"
                    ? t
                    : typeof t === "number" && Number.isFinite(t)
                      ? String(t)
                      : null,
                )
                .filter((t): t is string => t !== null)
                .join(" ")}
            </pre>
          )}
        </div>
      )}

      {error !== null &&
        (error instanceof TodoError && error.stderr !== null ? (
          <div className="mt-1">
            <div className="text-[10px] uppercase tracking-wide text-red-500">
              cli failed (rc {error.rc ?? "?"}) — stderr verbatim
            </div>
            <pre
              data-testid="directive-signoff-stderr"
              className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded border border-red-900 bg-red-950/40 p-2 font-mono text-[11px] text-red-400"
            >
              {error.stderr}
            </pre>
          </div>
        ) : (
          <div data-testid="directive-signoff-error" className="mt-1 text-[11px] text-red-400">
            {error.message}
          </div>
        ))}
    </div>
  );
}
