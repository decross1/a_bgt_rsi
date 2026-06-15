// SpawnTopicForm — outcome 5: spawn a follow-up TOPIC from a finding into the
// finding_followups queue. POSTs /api/todo/spawn_topic, which — once the seam
// lands — shells the cockpit-driven followups argv. Until then the endpoint is
// an honest STUB: it returns {status:"stub", would_run:[...argv]} and writes
// NOTHING (inviolate rule 4). No execute button — the would-run argv is
// read-only (D-046 / rule 8).
//
// Two required fields: the kind ("finding" | "step" — the followup taxonomy) and
// the new topic (what to chase next). The submit stays disabled until the topic
// is non-empty AND the capability is live (kind always has a valid default).
import { useState } from "react";
import { postSpawnTopic, TodoError, type TodoResult } from "../../api/todo";

type SpawnKind = "finding" | "step";

interface Props {
  findingId: string;
  /** actions.spawn_topic from GET /api/todo/available — false keeps the form in
   *  its honest stub state (submit disabled). */
  available: boolean;
  onSubmitted?: () => void;
}

// `findingId` rides in from producer-owned todo JSON (selected.id); a legacy/
// partial row could carry a non-string, null, or absent id. Coerce to a clean
// string (only a real string survives — number/object/array/null/NaN-source all
// degrade to ""), so the argv's `|| "<finding_id>"` placeholder and the POST
// `ref_id` never leak "[object Object]" / "undefined" into the page or the body.
const asId = (v: unknown): string => (typeof v === "string" ? v : "");

// `would_run` is producer-owned (the stub envelope's argv array). Render only
// string/finite-number tokens; drop objects/arrays/null/undefined/non-finite so
// a malformed element degrades to its absence rather than leaking
// "[object Object]" / "null" / "NaN" into the read-only preview.
const wouldRunText = (argv: unknown[]): string =>
  argv
    .filter(
      (t): t is string | number =>
        typeof t === "string" ||
        (typeof t === "number" && Number.isFinite(t)),
    )
    .map(String)
    .join(" ");

const argvPreview = (findingId: string, kind: SpawnKind, topic: string): string =>
  ".venv-chroma/bin/python -m orchestrator.finding_session spawn-topic" +
  ` --ref-id ${findingId || "<finding_id>"}` +
  ` --kind ${kind}` +
  ` --topic ${topic.trim() ? JSON.stringify(topic.trim()) : "<new_topic>"}` +
  " --by human:ui";

export default function SpawnTopicForm({ findingId, available, onSubmitted }: Props) {
  // Defense-in-depth at the prop boundary (house idiom — coerce strictly, never
  // trust a producer-owned value's type): a clean id string, and `available`
  // coerced `=== true` so a non-boolean truthy value (e.g. a stringy "false", a
  // number) can never silently lift the stub state or enable submit.
  const safeId = asId(findingId);
  const isAvailable = available === true;
  const [kind, setKind] = useState<SpawnKind>("finding");
  const [topic, setTopic] = useState("");
  const [result, setResult] = useState<TodoResult | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const disabled = submitting || !isAvailable || topic.trim().length === 0;

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await postSpawnTopic({
        ref_id: safeId,
        kind,
        topic: topic.trim(),
      });
      setResult(res);
      // Guard a non-function `onSubmitted` (the prop is producer-/caller-owned;
      // `?.()` would still throw "not a function" on a truthy non-callable).
      if (typeof onSubmitted === "function") onSubmitted();
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div data-testid="spawn-topic-form" className="rounded border border-cyan-900/60 bg-zinc-950/40 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-cyan-400">
        outcome 5 · spawn topic · POST /api/todo/spawn_topic →
        orchestrator.finding_session spawn-topic
      </div>
      {!isAvailable && (
        <div data-testid="spawn-topic-stub" className="mt-0.5 text-[10px] text-zinc-500">
          stub — lights up when the finding_followups cockpit seam lands
          (docs/todo_cockpit_seam_plan.md). Posts now return a read-only
          would-run preview and write nothing.
        </div>
      )}

      <label className="mt-1 flex items-center gap-2 text-[11px] text-zinc-400">
        <span className="uppercase tracking-wide text-zinc-600">kind</span>
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as SpawnKind)}
          aria-label="spawn-topic kind (finding or step)"
          className="rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 focus:border-zinc-600 focus:outline-none"
        >
          <option value="finding">finding</option>
          <option value="step">step</option>
        </select>
      </label>
      <input
        type="text"
        value={topic}
        onChange={(e) => setTopic(e.target.value)}
        aria-label="new topic (required)"
        placeholder="new topic (required — what to chase next)"
        className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
      />

      <div className="mt-1 text-[10px] uppercase tracking-wide text-zinc-600">
        would run (read-only — no execute)
      </div>
      <pre
        data-testid="spawn-topic-argv"
        aria-label="would run (read-only — no execute)"
        className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-[11px] text-zinc-400"
      >
        {argvPreview(safeId, kind, topic)}
      </pre>

      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          disabled={disabled}
          onClick={submit}
          className={
            "rounded border border-cyan-800 bg-cyan-950 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-cyan-300 hover:bg-cyan-900 " +
            "disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-600"
          }
        >
          spawn topic
        </button>
        {submitting && (
          <span data-testid="spawn-topic-submitting" className="text-[11px] text-zinc-500">
            submitting…
          </span>
        )}
      </div>

      {result !== null && (
        <div data-testid="spawn-topic-result" className="mt-1 text-[11px] text-cyan-300">
          {result.stub === true || result.status === "stub"
            ? "stub response — nothing written (the seam is not live)"
            : "follow-up topic enqueued to finding_followups"}
          {Array.isArray(result.would_run) && (
            <pre
              data-testid="spawn-topic-wouldrun"
              className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-[11px] text-zinc-400"
            >
              {wouldRunText(result.would_run as unknown[])}
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
              data-testid="spawn-topic-stderr"
              className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded border border-red-900 bg-red-950/40 p-2 font-mono text-[11px] text-red-400"
            >
              {error.stderr}
            </pre>
          </div>
        ) : (
          <div data-testid="spawn-topic-error" className="mt-1 text-[11px] text-red-400">
            {error.message}
          </div>
        ))}
    </div>
  );
}
