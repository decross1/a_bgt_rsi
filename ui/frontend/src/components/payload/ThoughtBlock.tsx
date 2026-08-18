// ThoughtBlock — channel-markup content split into a dimmed/italic "thought"
// block and the visible answer text (owner feedback 2026-08-18). The split
// itself lives in parse.splitThought (cleanup.py's grammar); this renders it.
// Either half may be empty — a thought-only completion shows just the
// thought, an unlabeled-channel completion shows just the answer.
import type { ThoughtSplit } from "./parse";

export default function ThoughtBlock({ split }: { split: ThoughtSplit }) {
  return (
    <div className="flex flex-col gap-1.5">
      {split.thought !== "" && (
        <div
          data-testid="thought-block"
          className="rounded border-l-2 border-zinc-700 bg-zinc-900/40 px-2 py-1.5"
        >
          <div className="text-[9px] uppercase tracking-wide text-zinc-500">
            thought
          </div>
          <div className="mt-0.5 whitespace-pre-wrap text-[13px] italic leading-relaxed text-zinc-500">
            {split.thought}
          </div>
        </div>
      )}
      {split.answer !== "" && (
        <div
          data-testid="answer-block"
          className="whitespace-pre-wrap font-mono text-[13px] text-zinc-200"
        >
          {split.answer}
        </div>
      )}
    </div>
  );
}
