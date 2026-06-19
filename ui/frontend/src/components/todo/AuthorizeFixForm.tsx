// AuthorizeFixForm — outcome 4 (NET-NEW, gated): authorize an AUTONOMOUS fix.
// POSTs /api/todo/authorize_fix — a LIVE exec — which enqueues a spawn-contract
// a later dev session dispatches; the coding agent produces a BRANCH + tests +
// report that lands ONLY via the merge gate. When the capability is enabled the
// endpoint records the enqueue; if a backend returns {status:"stub", would_run:
// [...argv]} (a body that wrote NOTHING) we report that honestly (inviolate rule
// 4 — never claim a write a body did not make).
//
// HARD LINE (the form copy must say this): UI approval authorizes the WORK, not
// a merge. The human approves enqueuing the spawn-contract; a human/gated-primary
// still merges the branch (D-014 runtime firewall; rule 4). No execute button —
// the would-run argv is read-only (D-046 / rule 8).
//
// Self-gates on the cockpit capability: when `available` (actions.authorize_fix)
// is false the exec is not enabled in this environment, so the submit is disabled
// and a read-only would-run preview shows what it WOULD run.
import { useState } from "react";
import { postAuthorizeFix, TodoError, type TodoResult } from "../../api/todo";

interface Props {
  findingId: string;
  /** actions.authorize_fix from GET /api/todo/available — false means the exec
   *  is not enabled in this environment (submit disabled, preview only). */
  available: boolean;
  onSubmitted?: () => void;
}

// findingId arrives from a producer-owned finding row (unvalidated). A non-string
// — a number, an object, an array, null — must degrade to the legible
// `<finding_id>` placeholder, NOT leak `[object Object]` / a comma-joined array
// into the read-only argv or the POST ref_id. (House doctrine: a malformed value
// degrades to an honest stub, never garbles the surface.)
const safeFindingId = (findingId: unknown): string =>
  typeof findingId === "string" ? findingId : "";

const argvPreview = (findingId: string, task: string, note: string): string =>
  ".venv-chroma/bin/python -m orchestrator.todo_cli authorize-fix" +
  ` --ref-id ${findingId || "<finding_id>"}` +
  ` --task ${task.trim() ? JSON.stringify(task.trim()) : "<spawn-contract statement>"}` +
  ` --note ${note.trim() ? JSON.stringify(note.trim()) : "<why>"}` +
  " --by human:ui";

export default function AuthorizeFixForm({ findingId, available, onSubmitted }: Props) {
  const [task, setTask] = useState("");
  const [note, setNote] = useState("");
  const [result, setResult] = useState<TodoResult | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Coerce both props strictly. `available` is the cockpit capability flag
  // (producer-owned) — a non-boolean must NOT enable the live exec via truthy
  // coercion (mirrors api/todo.ts asAvailability's `=== true`). `findingId` is
  // coerced to a safe string so a malformed id degrades to the placeholder.
  const isAvailable = available === true;
  const refId = safeFindingId(findingId);

  const disabled =
    submitting || !isAvailable || task.trim().length === 0 || note.trim().length === 0;

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await postAuthorizeFix({
        ref_id: refId,
        task: task.trim(),
        note: note.trim(),
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
    <div data-testid="authorize-fix-form" className="rounded border border-violet-900/60 bg-zinc-950/40 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-violet-400">
        outcome 4 · authorize autonomous fix · POST /api/todo/authorize_fix →
        orchestrator.todo_cli authorize-fix
      </div>
      {!isAvailable && (
        <div data-testid="authorize-fix-stub" className="mt-0.5 text-[10px] text-zinc-500">
          capability disabled — the authorize_fix exec is not enabled in this
          environment (actions.authorize_fix is off). The would-run argv below is
          a read-only preview; nothing is enqueued from here.
        </div>
      )}
      <div data-testid="authorize-fix-discipline" className="mt-1 rounded border border-amber-900/60 bg-amber-950/30 px-2 py-1 text-[10px] text-amber-300">
        You approve the WORK, not a merge. This enqueues a spawn-contract; a
        coding agent later produces a branch + tests + report that lands ONLY via
        the human/gated-primary merge gate.
      </div>

      <textarea
        value={task}
        onChange={(e) => setTask(e.target.value)}
        aria-label="authorize-fix task (required — the spawn-contract statement)"
        placeholder="task (required — the spawn-contract statement: what the coding agent must do)"
        rows={2}
        className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
      />
      <input
        type="text"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        aria-label="authorize-fix note (required)"
        placeholder="note (required — why you're authorizing this fix)"
        className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
      />

      <div className="mt-1 text-[10px] uppercase tracking-wide text-zinc-600">
        would run (read-only — no execute)
      </div>
      <pre
        data-testid="authorize-fix-argv"
        aria-label="would run (read-only — no execute)"
        className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-[11px] text-zinc-400"
      >
        {argvPreview(refId, task, note)}
      </pre>

      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          disabled={disabled}
          onClick={submit}
          className={
            "rounded border border-violet-800 bg-violet-950 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-violet-300 hover:bg-violet-900 " +
            "disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-600"
          }
        >
          authorize fix
        </button>
        {submitting && (
          <span data-testid="authorize-fix-submitting" className="text-[11px] text-zinc-500">
            submitting…
          </span>
        )}
      </div>

      {result !== null && (
        <div data-testid="authorize-fix-result" className="mt-1 text-[11px] text-violet-300">
          {result.stub === true || result.status === "stub"
            ? "stub response — nothing written (the exec is not enabled here)"
            : "spawn-contract enqueued — a dev session will dispatch it"}
          {Array.isArray(result.would_run) && (
            <pre
              data-testid="authorize-fix-wouldrun"
              className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-[11px] text-zinc-400"
            >
              {(result.would_run as unknown[]).map(String).join(" ")}
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
              data-testid="authorize-fix-stderr"
              className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded border border-red-900 bg-red-950/40 p-2 font-mono text-[11px] text-red-400"
            >
              {error.stderr}
            </pre>
          </div>
        ) : (
          <div data-testid="authorize-fix-error" className="mt-1 text-[11px] text-red-400">
            {error.message}
          </div>
        ))}
    </div>
  );
}
