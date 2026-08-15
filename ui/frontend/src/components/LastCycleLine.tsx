// LastCycleLine — Pulse's one-line "what did the loop just do" (UI
// simplification S1). One /api/coordinator/cycles poll; renders cycles[0]
// (the backend sorts newest-first): topic · status · errored count ·
// promoted findings · age. Tones: status "no_valid_plan" amber (the loop
// planned nothing actionable), errored outcomes red, promoted findings
// emerald. Links into the cycle narrative at /cycles (the S3 rename of the
// old /coordinator route — the S1 deviation is now resolved).
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getCoordinatorCycles } from "../api/http";
import { ageLabel } from "../ladderBar";
import type { CoordinatorCycle } from "../types/schemas";

function asText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  if (typeof v === "boolean") return String(v);
  return null;
}

interface Props {
  // Fixture injection (tests render synchronously, never fetch). null =
  // loaded-but-empty history.
  initial?: CoordinatorCycle[] | null;
  pollMs?: number;
}

export default function LastCycleLine({ initial, pollMs = 30000 }: Props) {
  const [cycles, setCycles] = useState<CoordinatorCycle[]>(
    Array.isArray(initial) ? initial : [],
  );
  const [loaded, setLoaded] = useState(initial !== undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getCoordinatorCycles()
        .then((r) => {
          if (!active) return;
          setCycles(Array.isArray(r?.cycles) ? r.cycles : []);
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

  if (error) {
    return (
      <div className="text-xs text-red-400" data-testid="last-cycle-error">
        {error}
      </div>
    );
  }
  if (!loaded) return null;

  // Producer-owned row guard (one malformed line never blanks Pulse).
  const last =
    cycles.length > 0 && cycles[0] != null && typeof cycles[0] === "object"
      ? cycles[0]
      : null;

  if (last == null) {
    return (
      <div className="text-xs text-zinc-500" data-testid="last-cycle-empty">
        no coordinator cycles yet
      </div>
    );
  }

  const topic = asText(last.topic) ?? "(no topic)";
  const status = asText(last.status);
  const errored = Array.isArray(last.outcomes)
    ? last.outcomes.filter(
        (o) => o != null && typeof o === "object" && o.status === "errored",
      ).length
    : 0;
  const findings = Array.isArray(last.promoted_finding_ids)
    ? last.promoted_finding_ids.length
    : 0;

  return (
    <div
      className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded border border-zinc-800 bg-zinc-900/40 px-3 py-2 text-xs"
      data-testid="last-cycle-line"
    >
      <span className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
        last cycle
      </span>
      <span className="text-zinc-200">{topic}</span>
      {status && (
        <span
          data-testid="last-cycle-status"
          className={
            status === "no_valid_plan" ? "text-amber-400" : "text-zinc-400"
          }
        >
          {status}
        </span>
      )}
      {errored > 0 && (
        <span className="text-red-400" data-testid="last-cycle-errored">
          {errored} errored
        </span>
      )}
      {findings > 0 && (
        <span className="text-emerald-400" data-testid="last-cycle-findings">
          +{findings} finding{findings === 1 ? "" : "s"}
        </span>
      )}
      <span className="font-mono text-[10px] text-zinc-500">
        {ageLabel(last.timestamp, Date.now())}
      </span>
      <Link
        to="/cycles"
        className="ml-auto text-[11px] text-zinc-600 hover:text-zinc-300"
      >
        cycles →
      </Link>
    </div>
  );
}
