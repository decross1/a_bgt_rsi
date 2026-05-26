// LOOP_V0 prompt entry: human types a topic, clicks submit, Nara runs.
// POSTs to /api/loop_v0/start which subprocess-spawns the CLI on the primary
// session's worktree. The form does not poll the resulting iteration — the
// ActiveIterationPanel does. See ui_plan.md §LOOP_V0.
import { useState } from "react";
import { startIteration } from "../api/http";

type SubmitState =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "ok"; pid: number }
  | { kind: "error"; message: string };

export default function NaraPromptForm() {
  const [topic, setTopic] = useState("");
  const [state, setState] = useState<SubmitState>({ kind: "idle" });

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = topic.trim();
    if (!trimmed) return;
    setState({ kind: "submitting" });
    try {
      const result = await startIteration(trimmed);
      setState({ kind: "ok", pid: result.pid });
      setTopic("");
    } catch (err) {
      setState({ kind: "error", message: String(err) });
    }
  }

  const disabled = state.kind === "submitting" || topic.trim().length === 0;

  return (
    <form
      onSubmit={onSubmit}
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
      aria-label="nara-prompt-form"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Nara prompt
        </h2>
        <span className="text-[10px] text-zinc-600">
          POST /api/loop_v0/start — subprocess to orchestrator.loop_v0_cli
        </span>
      </div>
      <label
        htmlFor="nara-topic"
        className="mt-2 block text-[11px] uppercase tracking-wide text-zinc-500"
      >
        topic
      </label>
      <textarea
        id="nara-topic"
        value={topic}
        onChange={(e) => setTopic(e.target.value)}
        rows={3}
        placeholder="e.g. Tit-for-Tat dominance in repeated PD"
        className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
      />
      <div className="mt-2 flex items-center gap-3">
        <button
          type="submit"
          disabled={disabled}
          className="rounded border border-emerald-800 bg-emerald-950 px-3 py-1 text-xs font-medium uppercase tracking-wide text-emerald-300 hover:bg-emerald-900 disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-600"
        >
          {state.kind === "submitting" ? "starting…" : "start iteration"}
        </button>
        {state.kind === "ok" && (
          <span className="text-xs text-emerald-400">
            spawned pid {state.pid}
          </span>
        )}
        {state.kind === "error" && (
          <span className="text-xs text-red-400">{state.message}</span>
        )}
      </div>
    </form>
  );
}
