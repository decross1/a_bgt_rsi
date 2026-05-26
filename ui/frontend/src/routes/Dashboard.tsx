// Live dashboard: is the Spark healthy and what is the apparatus doing?
// See ui_plan.md §LOOP_V0. Top of the page is the LOOP_V0 iteration view
// (prompt → active iteration → resolved list → journal). Below that, the
// substrate panels (health, orchestrator queue, vLLM, etc.) stay mounted
// so the human can see the Spark itself while Nara runs.
import { useEffect, useState } from "react";
import ActiveIterationPanel from "../components/ActiveIterationPanel";
import BaselineCard from "../components/BaselineCard";
import Day4ChainList from "../components/Day4ChainList";
import HealthStrip from "../components/HealthStrip";
import JournalScroll from "../components/JournalScroll";
import NaraPromptForm from "../components/NaraPromptForm";
import OrchestratorQueue from "../components/OrchestratorQueue";
import ProcessGrid from "../components/ProcessGrid";
import ResolvedIterationsList from "../components/ResolvedIterationsList";
import RobustnessPanel from "../components/RobustnessPanel";
// UnlockPanel was keyed to the retired Track-A/B/C/D + autonomy-tier
// framework (see DECISIONS.md D-030, 2026-05-26). Commented out — kept in
// the file so a future session can decide whether to repurpose it for the
// LOOP_V0 exit criterion (LOOP_V0.md §Exit criterion) or remove it.
// CriticPanel + MetaReviewPanel referenced in the LOOP_V0 UI prompt do
// not exist on this branch — nothing to comment out there.
// import UnlockPanel from "../components/UnlockPanel";
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
  const [selectedIteration, setSelectedIteration] = useState<string | null>(
    null,
  );
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

      {/* LOOP_V0 iteration view — the apparatus's cognitive loop made
          visible. Prompt → active → resolved → journal. */}
      <div className="mt-4">
        <NaraPromptForm />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ActiveIterationPanel />
        <ResolvedIterationsList
          onSelect={setSelectedIteration}
          selectedId={selectedIteration}
        />
      </div>

      <div className="mt-4">
        <JournalScroll iterationId={selectedIteration} />
      </div>

      {/* Substrate panels below — Spark health + apparatus telemetry. */}
      <div className="mt-6">
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

      {/* UnlockPanel — Week-2 unlock prerequisites keyed to the retired
          autonomy-tier framework (D-030). Commented out 2026-05-26; kept
          for future repurpose into a LOOP_V0 exit-criterion progress strip. */}
      {/* <UnlockPanel /> */}

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
