// Page B index — browse experiments. One card per experiment dir. The
// experiments are heterogeneous: JSON-shaped ones show opponents/rounds/
// coop-rate; markdown-shaped ones get a "markdown summary" badge; ones
// with no results/ dir are marked "no results yet". Nothing is fabricated.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getExperiments } from "../api/experiments";
import { fmt } from "../format";
import type {
  ExperimentListItem,
  ExperimentsListResponse,
} from "../types/experiments";

interface Props {
  initial?: ExperimentsListResponse | null;
}

function Badge({
  text,
  tone,
}: {
  text: string;
  tone: "ok" | "warn" | "muted" | "sky";
}) {
  const cls = {
    ok: "border-emerald-700/50 bg-emerald-900/20 text-emerald-300",
    warn: "border-amber-700/50 bg-amber-900/20 text-amber-300",
    muted: "border-zinc-700 bg-zinc-800/40 text-zinc-400",
    sky: "border-sky-700/50 bg-sky-900/20 text-sky-300",
  }[tone];
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[10px] ${cls}`}>
      {text}
    </span>
  );
}

function ExperimentCard({ exp }: { exp: ExperimentListItem }) {
  const empty = !exp.has_results_dir;
  return (
    <Link
      to={`/experiments/${encodeURIComponent(exp.id)}`}
      data-testid={`exp-card-${exp.id}`}
      className="block rounded border border-zinc-800 bg-zinc-900/40 p-4 hover:border-zinc-700"
    >
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-sm text-zinc-200">{exp.id}</span>
        <span className="text-xs text-zinc-500">{exp.title}</span>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {empty && <Badge text="no results yet" tone="warn" />}
        {exp.has_summary_json && <Badge text="json summary" tone="ok" />}
        {exp.has_summary_md && <Badge text="markdown summary" tone="sky" />}
        {exp.has_per_round && <Badge text="per-round" tone="muted" />}
        {exp.has_trials && <Badge text="trials" tone="muted" />}
        {!empty && (
          <Badge text={`${exp.n_results_files} files`} tone="muted" />
        )}
      </div>

      {empty && (
        <div className="mt-2 text-xs text-zinc-500">
          No <span className="font-mono">results/</span> directory — this
          experiment has not produced results yet.
        </div>
      )}
    </Link>
  );
}

export default function Experiments({ initial }: Props) {
  const [data, setData] = useState<ExperimentsListResponse | null>(
    initial ?? null,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    getExperiments()
      .then((d) => active && setData(d))
      .catch((e) => active && setError(String(e)));
    return () => {
      active = false;
    };
  }, [initial]);

  return (
    <div className="mx-auto max-w-7xl p-5" data-testid="experiments-page">
      <div className="flex items-baseline gap-3">
        <h1 className="text-base font-semibold text-zinc-100">Experiments</h1>
        <span className="text-[10px] text-zinc-600">/api/experiments</span>
      </div>

      {error && <div className="mt-3 text-sm text-red-400">{error}</div>}

      {data && !data.available && (
        <div
          className="mt-4 rounded border border-amber-800/50 bg-amber-900/10 p-4 text-sm text-amber-300"
          data-testid="experiments-unavailable"
        >
          Experiments directory is not available
          {data.reason ? ` (${data.reason})` : ""}.
        </div>
      )}

      {data && data.available && data.experiments.length === 0 && (
        <div className="mt-4 text-sm text-zinc-500">
          No experiments found.
        </div>
      )}

      {data && data.available && data.experiments.length > 0 && (
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {data.experiments.map((exp) => (
            <ExperimentCard key={exp.id} exp={exp} />
          ))}
        </div>
      )}

      {!data && !error && (
        <div className="mt-4 text-sm text-zinc-500">Loading…</div>
      )}

      <div className="mt-4 text-[11px] text-zinc-600">
        {fmt(data?.experiments.length ?? 0)} experiment(s) scanned.
      </div>
    </div>
  );
}
