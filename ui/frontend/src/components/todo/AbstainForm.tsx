// AbstainForm — outcome 6: abstain. The HONEST no-verdict exit — the human
// records NO verdict, the finding is left to re-look later (it is NOT validated,
// NOT rejected, NOT deferred). Abstain is a SESSION-EXIT, not an in-UI one-shot:
// `available` is false BY DESIGN. POSTs /api/todo/abstain return a read-only
// would-run preview ({status:"stub", would_run:[...argv]}, writing NOTHING —
// inviolate rule 4); the actual abstention stays a primary-session step (no
// execute button — D-046 / rule 8). The cockpit shows the exit and its argv; it
// does not run it.
//
// The copy must make the no-verdict semantics explicit so abstain is never
// mistaken for a soft sign-off (rule 4 — a near-miss is not coerced to a pass).
import { useState } from "react";
import { postAbstain, TodoError, type TodoResult } from "../../api/todo";

interface Props {
  findingId: string;
  /** actions.abstain from GET /api/todo/available — false BY DESIGN (abstain is
   *  a session-exit, not an in-UI one-shot); the form stays preview-only. */
  available: boolean;
  onSubmitted?: () => void;
}

// findingId is producer-owned (it threads up from /api/todo + loop_memory rows);
// the `string` type is a compile-time fiction. A non-string (number/object/null/
// array) must degrade to the legible `<finding_id>` placeholder, never crash or
// leak `[object Object]`. asFindingId returns "" for anything that isn't a
// non-empty string so the `|| "<finding_id>"` fallback fires uniformly.
const asFindingId = (v: unknown): string =>
  typeof v === "string" && v.trim().length > 0 ? v : "";

const argvPreview = (findingId: string, note: string): string =>
  ".venv-chroma/bin/python -m orchestrator.finding_session abstain" +
  ` --ref-id ${asFindingId(findingId) || "<finding_id>"}` +
  ` --note ${note.trim() ? JSON.stringify(note.trim()) : "<why>"}` +
  " --by human:ui";

export default function AbstainForm({ findingId, available, onSubmitted }: Props) {
  const [note, setNote] = useState("");
  const [result, setResult] = useState<TodoResult | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // `available` is producer-owned (actions.abstain from GET /api/todo/available);
  // coerce strictly (=== true), mirroring asAvailability in api/todo.ts — a
  // truthy non-true legacy value must NOT silently enable the stub's submit.
  const isAvailable = available === true;
  const safeFindingId = asFindingId(findingId);
  const disabled = submitting || !isAvailable || note.trim().length === 0;

  // `result` is forwarded raw from the stub/CLI body (TodoResult = an UNVALIDATED
  // Record). Probe it through a safe map so a non-object 200 body (null is already
  // filtered by the `result !== null` render guard; this covers number/string/
  // array) never trips a property access on a primitive nor reads as a real verdict.
  const isResultObject =
    result !== null && typeof result === "object" && !Array.isArray(result);
  const resultObj: Record<string, unknown> = isResultObject
    ? (result as Record<string, unknown>)
    : {};

  // would_run members are producer-owned: the documented shape is a string[] argv,
  // but a legacy/version-skewed body can carry structured members (a number, or an
  // arg emitted as a {flag,value} object/group). A bare String(member) leaks the
  // forbidden `[object Object]` (and a comma-mashed array) into the read-only argv
  // preview, hiding what the CLI would run. Render a non-string member via
  // JSON.stringify (the same legible idiom argvPreview uses for the note) so an
  // object reads as `{"x":1}`, never `[object Object]`; strings pass verbatim.
  const wouldRunMember = (m: unknown): string => {
    if (typeof m === "string") return m;
    try {
      return JSON.stringify(m) ?? String(m);
    } catch {
      // JSON.stringify can throw (BigInt / circular) on exotic non-JSON values
      // that should never reach here from resp.json(); degrade rather than crash.
      return "<unprintable>";
    }
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await postAbstain({ ref_id: safeFindingId, note: note.trim() });
      setResult(res);
      onSubmitted?.();
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div data-testid="abstain-form" className="rounded border border-zinc-700/60 bg-zinc-950/40 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-zinc-400">
        outcome 6 · abstain · POST /api/todo/abstain → orchestrator.finding_session
        abstain
      </div>
      {!isAvailable && (
        <div data-testid="abstain-stub" className="mt-0.5 text-[10px] text-zinc-500">
          abstain is a session-exit, not an in-UI one-shot — preview only. The
          would-run argv below shows the exit; recording the abstention stays a
          primary-session step (nothing is written from here).
        </div>
      )}
      <div data-testid="abstain-semantics" className="mt-1 text-[10px] text-zinc-500">
        No verdict is recorded. The finding is NOT validated, NOT rejected — it
        is left to re-look later. Abstain is not a soft sign-off.
      </div>

      <input
        type="text"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        aria-label="abstain note (required)"
        placeholder="note (required — why you're abstaining / what to revisit)"
        className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
      />

      <div className="mt-1 text-[10px] uppercase tracking-wide text-zinc-600">
        would run (read-only — no execute)
      </div>
      <pre
        data-testid="abstain-argv"
        aria-label="would run (read-only — no execute)"
        className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-[11px] text-zinc-400"
      >
        {argvPreview(findingId, note)}
      </pre>

      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          disabled={disabled}
          onClick={submit}
          className={
            "rounded border border-zinc-600 bg-zinc-900 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-zinc-300 hover:bg-zinc-800 " +
            "disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-600"
          }
        >
          abstain
        </button>
        {submitting && (
          <span data-testid="abstain-submitting" className="text-[11px] text-zinc-500">
            submitting…
          </span>
        )}
      </div>

      {result !== null && (
        <div data-testid="abstain-result" className="mt-1 text-[11px] text-zinc-300">
          {/* result is producer-owned JSON (postTodo forwards `await resp.json()`
              raw); a malformed 200 body can be a bare null/number/string/array.
              A non-object body has NO honest "recorded" semantics — treat it as a
              stub-shaped degrade rather than fabricate an "abstention recorded"
              verdict (rule 4). resultObj is {} for any non-object body, so the
              stub-vs-recorded probe below reads from a safe map. */}
          {resultObj.stub === true || resultObj.status === "stub" || !isResultObject
            ? "stub response — nothing written (preview only; abstain is a session-exit)"
            : "abstention recorded — no verdict; the finding stays open for re-look"}
          {Array.isArray(resultObj.would_run) && (
            <pre
              data-testid="abstain-wouldrun"
              className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-[11px] text-zinc-400"
            >
              {(resultObj.would_run as unknown[]).map(wouldRunMember).join(" ")}
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
              data-testid="abstain-stderr"
              className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded border border-red-900 bg-red-950/40 p-2 font-mono text-[11px] text-red-400"
            >
              {error.stderr}
            </pre>
          </div>
        ) : (
          <div data-testid="abstain-error" className="mt-1 text-[11px] text-red-400">
            {error.message}
          </div>
        ))}
    </div>
  );
}
