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

// Loop v1 Step 8 human-gate state.
const GATE_TONE: Record<string, string> = {
  pending: "bg-sky-950 text-sky-300",
  valid: "bg-emerald-950 text-emerald-400",
  invalid: "bg-red-950 text-red-400",
  needs_revision: "bg-amber-950 text-amber-400",
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

// Loop v1 Step 2.5 red-team chip. Highlighted (red) when the critic ruled
// fatal_flaw OR any revision retries were spent — those are the rows a
// human most needs to eyeball. A clean "proceed / 0 retries" pass renders
// quiet zinc. Returns null when no redteam block is present (pre-v1 rows).
function RedteamChip({
  redteam,
}: {
  redteam: IterationRecord["redteam"];
}) {
  if (!redteam || (redteam.verdict == null && redteam.retries_used == null)) {
    return null;
  }
  const retries = redteam.retries_used ?? 0;
  const fatal = redteam.verdict === "fatal_flaw";
  const highlight = fatal || retries > 0;
  const tone = highlight
    ? "bg-red-950 text-red-400"
    : "bg-zinc-800 text-zinc-400";
  const label = `redteam ${redteam.verdict ?? "?"}${
    retries > 0 ? ` · ${retries} retr${retries === 1 ? "y" : "ies"}` : ""
  }`;
  return (
    <span
      data-testid="redteam-chip"
      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${tone}`}
    >
      {label}
    </span>
  );
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
                    <RedteamChip redteam={row.redteam} />
                    <Badge
                      text={row.gate_status}
                      tone={GATE_TONE[row.gate_status ?? ""] ?? ""}
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
                  {(row.meta_review?.conditioning_bullets?.length ?? 0) > 0 && (
                    // Loop v1 Step 1.5: the prior-memory bullets that
                    // conditioned this iteration. Shown so the human can see
                    // what the loop carried forward into the run.
                    <div
                      data-testid={`conditioning-${row.iteration_id}`}
                      className="mt-1.5 rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1"
                    >
                      <div className="text-[10px] uppercase tracking-wide text-zinc-500">
                        conditioned by
                      </div>
                      <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-[11px] text-zinc-400">
                        {row.meta_review!.conditioning_bullets!.map(
                          (bullet, i) => (
                            <li key={i}>{bullet}</li>
                          ),
                        )}
                      </ul>
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
