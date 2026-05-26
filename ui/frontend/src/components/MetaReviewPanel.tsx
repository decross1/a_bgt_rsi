// Meta-review (Day-40 W2-02) — empty-state stub shipped on Day 9.
// Polls /api/meta_review_summary; until logs/meta_review.jsonl exists
// the panel renders "awaiting Day-40 meta-review outputs" rather than
// an error. Per-row rendering lands when Track A finalizes the record
// shape.
import { useEffect, useState } from "react";
import { getMetaReviewSummary } from "../api/http";
import type { MetaReviewSummary } from "../types/schemas";

export default function MetaReviewPanel() {
  const [data, setData] = useState<MetaReviewSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = () =>
      getMetaReviewSummary()
        .then((d) => {
          if (!active) return;
          setData(d);
          setError(null);
        })
        .catch((e) => {
          if (active) setError(String(e));
        });
    load();
    const id = setInterval(load, 30000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const tone = data?.available ? "bg-zinc-800 text-zinc-400" : "bg-amber-950 text-amber-400";
  const badge = data?.available ? `${data.total_runs} runs` : "awaiting day-40";

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Meta-review
        </h2>
        <span className="text-[10px] text-zinc-600">
          §11.3 phase-2 prereq — /api/meta_review_summary
        </span>
        <span
          className={`ml-auto rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${tone}`}
        >
          {badge}
        </span>
      </div>
      {error && <div className="mt-2 text-sm text-red-400">{error}</div>}
      {!data && !error && (
        <div className="mt-2 text-sm text-zinc-500">Loading…</div>
      )}
      {data && (
        <div className="mt-2 text-xs text-zinc-400">{data.note}</div>
      )}
    </div>
  );
}
