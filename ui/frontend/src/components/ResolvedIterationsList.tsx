// LOOP_V0 resolved-iterations list. Polls /api/loop_v0/iterations at ~0.2 Hz
// and renders past iterations newest-first: id, topic, novelty class,
// critique verdict, timestamp, and a button that loads the corresponding
// journal entry (via the `onSelect` callback). See agent/prompts/ui_session.md
// §"Resolved panel".
import { useEffect, useState } from "react";
import { getIterations } from "../api/http";
import type { IterationRecord } from "../types/schemas";

const NOVELTY_TONE: Record<string, string> = {
  novel: "bg-emerald-950 text-emerald-400",
  rediscovery: "bg-amber-950 text-amber-400",
  unclear: "bg-zinc-800 text-zinc-400",
  nonsense: "bg-red-950 text-red-400",
};

const VERDICT_TONE: Record<string, string> = {
  survives: "bg-emerald-950 text-emerald-400",
  restated: "bg-amber-950 text-amber-400",
  falsified: "bg-red-950 text-red-400",
  malformed: "bg-red-950 text-red-400",
};

// Process-status badge. `status` mirrors /api/loop_v0/processes:
// running / exited_clean / exited_error_<rc> / killed_signal_<sig>.
function processTone(status: string | undefined): string {
  if (!status) return "bg-zinc-800 text-zinc-400";
  if (status === "running") return "bg-sky-950 text-sky-300";
  if (status === "exited_clean") return "bg-emerald-950 text-emerald-400";
  if (status.startsWith("exited_error_")) return "bg-red-950 text-red-400";
  if (status.startsWith("killed_signal_")) return "bg-red-950 text-red-400";
  return "bg-zinc-800 text-zinc-400";
}

function processLabel(status: string | undefined): string | null {
  if (!status) return null;
  if (status === "exited_clean") return "pid clean";
  if (status === "running") return "pid running";
  if (status.startsWith("exited_error_")) return `pid err ${status.slice("exited_error_".length)}`;
  if (status.startsWith("killed_signal_")) return `pid killed ${status.slice("killed_signal_".length)}`;
  return status;
}

function Badge({
  text,
  tone,
}: {
  text: string | null | undefined;
  tone: string;
}) {
  if (!text) return null;
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${tone}`}
    >
      {text}
    </span>
  );
}

function shortTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  return iso.replace("T", " ").replace("Z", "");
}

interface Props {
  initial?: IterationRecord[];
  onSelect?: (iterationId: string) => void;
  selectedId?: string | null;
  pollMs?: number;
}

export default function ResolvedIterationsList({
  initial,
  onSelect,
  selectedId,
  pollMs = 5000,
}: Props) {
  const [rows, setRows] = useState<IterationRecord[]>(initial ?? []);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(initial !== undefined);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getIterations()
        .then((r) => {
          if (!active) return;
          // Backend returns newest-first per the contract; if a producer
          // ever appends out-of-order, sort by ended_at descending here
          // to keep the panel stable.
          const sorted = [...r.iterations].sort((a, b) =>
            (b.ended_at ?? "").localeCompare(a.ended_at ?? ""),
          );
          setRows(sorted);
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

  return (
    <div
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="resolved-iterations-list"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Resolved iterations
        </h2>
        <span className="text-[10px] text-zinc-600">
          /api/loop_v0/iterations · newest first
        </span>
        <span className="ml-auto text-[11px] text-zinc-500">
          {rows.length}
        </span>
      </div>

      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}

      {loaded && rows.length === 0 && !error && (
        <div className="mt-2 text-sm text-zinc-500">
          No iterations yet. Submit a topic above to start the first one.
        </div>
      )}

      {rows.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {rows.map((row) => {
            const selected = row.iteration_id === selectedId;
            return (
              <li key={row.iteration_id}>
                <button
                  type="button"
                  onClick={() => onSelect?.(row.iteration_id)}
                  className={
                    selected
                      ? "block w-full rounded border border-emerald-700 bg-emerald-950/30 px-2 py-1.5 text-left hover:bg-emerald-950/50"
                      : "block w-full rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5 text-left hover:border-zinc-700"
                  }
                  aria-label={`load journal ${row.iteration_id}`}
                >
                  <div className="flex flex-wrap items-baseline gap-2 text-xs">
                    <span className="font-mono text-zinc-200">
                      {row.iteration_id}
                    </span>
                    <Badge
                      text={row.novelty?.class}
                      tone={
                        NOVELTY_TONE[row.novelty?.class ?? ""] ??
                        "bg-zinc-800 text-zinc-400"
                      }
                    />
                    <Badge
                      text={row.critique?.verdict}
                      tone={
                        VERDICT_TONE[row.critique?.verdict ?? ""] ??
                        "bg-zinc-800 text-zinc-400"
                      }
                    />
                    <Badge
                      text={processLabel(row.process_status)}
                      tone={processTone(row.process_status)}
                    />
                    <span className="ml-auto font-mono text-[10px] text-zinc-500">
                      {shortTimestamp(row.ended_at)}
                    </span>
                  </div>
                  {row.seed?.topic && (
                    <div className="mt-1 text-xs text-zinc-300">
                      {row.seed.topic}
                    </div>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
