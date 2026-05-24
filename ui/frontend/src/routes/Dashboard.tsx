// Live dashboard: is the Spark healthy and what is the apparatus doing?
// See ui_plan.md section 5.3. Telemetry arrives over the /api/live
// WebSocket (ui/hooks/useTelemetryStream); the orchestrator queue polls.
import { useEffect, useState } from "react";
import BaselineCard from "../components/BaselineCard";
import Day4ChainList from "../components/Day4ChainList";
import HealthStrip from "../components/HealthStrip";
import OrchestratorQueue from "../components/OrchestratorQueue";
import ProcessGrid from "../components/ProcessGrid";
import RobustnessPanel from "../components/RobustnessPanel";
import UnlockPanel from "../components/UnlockPanel";
import VllmPanel from "../components/VllmPanel";
import { getHealth, getState } from "../api/http";
import { useTelemetryStream } from "../hooks/useTelemetryStream";
import type { AppState, Health } from "../types/schemas";

function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

export default function Dashboard() {
  const { samples, latest, connected } = useTelemetryStream();
  const [health, setHealth] = useState<Health | null>(null);
  const [state, setState] = useState<AppState | null>(null);
  const now = useNow();

  useEffect(() => {
    const loadHealth = () => getHealth().then(setHealth).catch(() => {});
    loadHealth();
    getState().then(setState).catch(() => {});
    const id = setInterval(loadHealth, 10000);
    return () => clearInterval(id);
  }, []);

  const lastSeen = latest?.timestamp ?? health?.telemetry_last_seen ?? null;
  const ageMs = lastSeen ? now - Date.parse(lastSeen) : null;
  const stale = ageMs != null && ageMs > 5000;
  const readErrors = latest?.read_errors
    ? Object.keys(latest.read_errors)
    : [];

  return (
    <div className="mx-auto max-w-7xl p-5">
      {/* header */}
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
        <span className="font-mono text-zinc-200">
          {health?.hostname ?? "spark"}
        </span>
        {state?.current_day && (
          <span className="text-zinc-500">apparatus: {state.current_day}</span>
        )}
        <span className="text-zinc-500">backend {health?.version ?? "?"}</span>
        <span className={connected ? "text-emerald-400" : "text-red-400"}>
          {connected ? "● live" : "● disconnected"}
        </span>
        <span className={stale ? "text-red-400" : "text-zinc-500"}>
          telemetry{" "}
          {ageMs != null ? `${(ageMs / 1000).toFixed(0)} s ago` : "—"}
        </span>
      </div>

      {readErrors.length > 0 && (
        <div className="mt-2 text-xs text-amber-500/80">
          telemetry read issues: {readErrors.join(", ")}
        </div>
      )}

      {samples.length === 0 && (
        <div className="mt-4 rounded border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-500">
          Waiting for telemetry — is the sampler running?
        </div>
      )}

      <div className="mt-4">
        <HealthStrip samples={samples} />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4">
        <OrchestratorQueue />
        <VllmPanel samples={samples} />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4">
        <Day4ChainList />
        <RobustnessPanel />
      </div>

      {/* Week-2 unlock prerequisites — alignment-evidence the human needs
          to attest the Week-2 tier-shift unlock (ui_plan.md §11.3). */}
      <div className="mt-4">
        <UnlockPanel />
      </div>

      <div className="mt-4">
        <BaselineCard />
      </div>

      <div className="mt-4">
        <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
          Tracked processes
        </h2>
        <ProcessGrid samples={samples} />
      </div>
    </div>
  );
}
