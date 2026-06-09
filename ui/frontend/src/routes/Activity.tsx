// PAGE A (/activity) — "which agents are active right now and what are they
// doing?" Top->bottom: (1) a refined live-vs-history status strip; (2) the
// HERO "Active now" full-width — the ActiveIterationPanel + ActiveWorkersPanel,
// with a clear idle empty-state shown only when BOTH the orchestrator
// iteration is idle AND zero workers are in flight; (3) the subordinate
// SyntheticInferencePanel disclosure; (4) the recent-history react-flow graph,
// demoted into a collapsible <details> so an idle apparatus's history never
// masquerades as live activity.
//
// The active-iteration poll is lifted to this page (so the idle gate can read
// it) and fed to ActiveIterationPanel as `initial`. Poll discipline: monitor
// 1 Hz, iteration 1 Hz, graph 5 s with change-detection so react-flow only
// relayouts when the graph actually changed.
import { useEffect, useRef, useState } from "react";
import ActiveIterationPanel from "../components/ActiveIterationPanel";
import ActiveRunCard from "../components/ActiveRunCard";
import ActiveWorkersPanel from "../components/ActiveWorkersPanel";
import ActivityGraph from "../components/ActivityGraph";
import AgentBadge from "../components/AgentBadge";
import CoordinatorPhases from "../components/CoordinatorPhases";
import LiveCallsBanner from "../components/LiveCallsBanner";
import SyntheticInferencePanel from "../components/SyntheticInferencePanel";
import {
  getActiveRun,
  getActivityGraph,
  getActivityMonitor,
} from "../api/activity";
import {
  getActiveIteration,
  getCoordinatorActive,
  getCoordinatorCycles,
} from "../api/http";
import { elapsed, useNow } from "../time";
import type {
  ActiveRun,
  ActivityGraphResponse,
  MonitorResponse,
} from "../types/activity";
import type {
  ActiveIteration,
  CoordinatorActiveRun,
  CoordinatorCycle,
} from "../types/schemas";

// A failed dispatch must never be a silent gap: each errored action from a
// coordinator cycle becomes an explicit red row carrying its error string. We
// derive these from getCoordinatorCycles() outcomes (the cycle row is the
// source of truth for dispatch outcome — ui_autonomy_observability_plan.md).
interface FailedDispatch {
  run_id: string;
  agent: string;
  topic: string;
  action: string;
  error: string;
  timestamp: string;
}

function deriveFailedDispatches(cycles: CoordinatorCycle[]): FailedDispatch[] {
  const out: FailedDispatch[] = [];
  for (const cycle of cycles) {
    for (const outcome of cycle.outcomes) {
      if (outcome.status === "errored") {
        out.push({
          run_id: cycle.run_id,
          agent: cycle.agent,
          topic: cycle.topic,
          action: outcome.action,
          error: outcome.error ?? "(no error message recorded)",
          timestamp: cycle.timestamp,
        });
      }
    }
  }
  return out;
}

function shortTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  return iso.replace("T", " ").replace("Z", "");
}

// The explicit failed-dispatch surface. Renders nothing when there are no
// errored actions (a clean loop leaves no rows here) — but when a dispatch
// failed, it is a visible red row, not a "nothing happened" gap.
function FailedDispatches({ cycles }: { cycles: CoordinatorCycle[] }) {
  const failures = deriveFailedDispatches(cycles);
  if (failures.length === 0) return null;
  return (
    <div
      className="rounded border border-red-900/60 bg-red-950/20 p-4"
      data-testid="failed-dispatches"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-red-300">
          Failed dispatches
        </h2>
        <span className="text-[10px] text-zinc-500">
          coordinator actions that errored
        </span>
        <span className="ml-auto text-[11px] text-zinc-500">
          {failures.length}
        </span>
      </div>
      <ul className="mt-2 space-y-1.5">
        {failures.map((f) => (
          <li
            key={`${f.run_id}-${f.action}`}
            data-testid={`failed-dispatch-${f.run_id}`}
            className="rounded border border-red-900/60 bg-red-950/30 px-2 py-1.5"
          >
            <div className="flex flex-wrap items-baseline gap-2 text-xs">
              <AgentBadge agent={f.agent} />
              <span className="font-mono text-red-300">{f.action}</span>
              <span className="text-zinc-400">{f.topic}</span>
              <span className="ml-auto font-mono text-[10px] text-zinc-500">
                {shortTimestamp(f.timestamp)}
              </span>
            </div>
            <div className="mt-1 font-mono text-[11px] text-red-300">
              {f.error}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface ActivityProps {
  initialGraph?: ActivityGraphResponse;
  initialMonitor?: MonitorResponse;
  // Tests inject the active-iteration so the page can gate the idle
  // empty-state on BOTH iteration-idle AND zero-workers (see below). When
  // provided (even as null) the page does not self-poll the iteration.
  initialIteration?: ActiveIteration | null;
  // The active RUN (run_state/active_run.json). Injected (even as null) so the
  // page does not self-poll it in tests; a present run means NOT idle.
  initialActiveRun?: ActiveRun | null;
  // The coordinator's live cycle (CoordinatorPhases) + recent cycles (the
  // failed-dispatch surface). Injected for tests; otherwise polled only when
  // the page is live (same static-render gate the graph/monitor use).
  initialCoordinatorActive?: CoordinatorActiveRun | null;
  initialCoordinatorCycles?: CoordinatorCycle[];
}

type Detail = "overview" | "full";

const GRAPH_POLL_MS = 5000;
const MONITOR_POLL_MS = 1000;

export default function Activity({
  initialGraph,
  initialMonitor,
  initialIteration,
  initialActiveRun,
  initialCoordinatorActive,
  initialCoordinatorCycles,
}: ActivityProps) {
  const [graph, setGraph] = useState<ActivityGraphResponse | null>(
    initialGraph ?? null,
  );
  const [monitor, setMonitor] = useState<MonitorResponse | null>(
    initialMonitor ?? null,
  );
  // The active iteration is lifted to the page so the idle empty-state can be
  // gated on BOTH the iteration being idle AND zero workers in flight (the
  // prompt's explicit requirement). ActiveIterationPanel still owns its own
  // rendering; we pass this down as its `initial` so it does not double-poll.
  const [iteration, setIteration] = useState<ActiveIteration | null>(
    initialIteration ?? null,
  );
  // The active RUN is lifted to the page too, so a present run folds into the
  // idle gate (a run in flight is NOT idle) and the status strip.
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(
    initialActiveRun ?? null,
  );
  // The coordinator's live cycle (phases stepper) + recent cycles (the
  // failed-dispatch surface). Default to null/[] so an un-injected test renders
  // the quiet idle/empty states without a network call.
  const [coordinatorActive, setCoordinatorActive] =
    useState<CoordinatorActiveRun | null>(initialCoordinatorActive ?? null);
  const [coordinatorCycles, setCoordinatorCycles] = useState<CoordinatorCycle[]>(
    initialCoordinatorCycles ?? [],
  );
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail>("overview");
  const now = useNow();
  // Last graph content signature — skip setGraph (and the react-flow
  // relayout it triggers) when nothing structural changed between polls.
  const graphSig = useRef<string>("");

  // When fixtures are injected, do not poll — the page is static for tests.
  const live = initialGraph === undefined && initialMonitor === undefined;
  // The active iteration self-polls here only when not injected by a test.
  const liveIteration = initialIteration === undefined;
  // The active run self-polls only when not injected by a test.
  const liveActiveRun = initialActiveRun === undefined;

  useEffect(() => {
    if (!live) return;
    let cancelled = false;
    graphSig.current = ""; // detail changed — force the next graph to apply

    const pollGraph = () => {
      getActivityGraph(detail)
        .then((g) => {
          if (cancelled) return;
          const sig = JSON.stringify({ d: g.detail, n: g.nodes, e: g.edges });
          if (sig !== graphSig.current) {
            graphSig.current = sig;
            setGraph(g);
          }
        })
        .catch((e) => !cancelled && setError(String(e)));
    };
    const pollMonitor = () => {
      getActivityMonitor()
        .then((m) => !cancelled && setMonitor(m))
        .catch((e) => !cancelled && setError(String(e)));
    };

    pollGraph();
    pollMonitor();
    const gid = setInterval(pollGraph, GRAPH_POLL_MS);
    const mid = setInterval(pollMonitor, MONITOR_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(gid);
      clearInterval(mid);
    };
  }, [live, detail]);

  useEffect(() => {
    if (!liveIteration) return;
    let cancelled = false;
    const poll = () =>
      getActiveIteration()
        .then((it) => !cancelled && setIteration(it))
        .catch((e) => !cancelled && setError(String(e)));
    poll();
    const id = setInterval(poll, MONITOR_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [liveIteration]);

  useEffect(() => {
    if (!liveActiveRun) return;
    let cancelled = false;
    const poll = () =>
      getActiveRun()
        .then((r) => !cancelled && setActiveRun(r))
        .catch((e) => !cancelled && setError(String(e)));
    poll();
    const id = setInterval(poll, MONITOR_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [liveActiveRun]);

  // Coordinator phases + recent cycles. Gated on `live` (graph+monitor not
  // injected) so the existing static-render tests stay network-free; a test
  // that wants coordinator data injects the props above instead. Polled at the
  // graph cadence (these change per cycle, not per second).
  useEffect(() => {
    if (!live) return;
    let cancelled = false;
    const pollActive = () =>
      getCoordinatorActive()
        .then((r) => !cancelled && setCoordinatorActive(r))
        .catch((e) => !cancelled && setError(String(e)));
    const pollCycles = () =>
      getCoordinatorCycles()
        .then((r) => !cancelled && setCoordinatorCycles(r.cycles))
        .catch((e) => !cancelled && setError(String(e)));
    pollActive();
    pollCycles();
    const id = setInterval(() => {
      pollActive();
      pollCycles();
    }, GRAPH_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [live]);

  const activeCount = monitor?.active.length ?? 0;
  // The monitor is "available" only when its source file is present. On the
  // {available:false} degrade path active[] is empty for want of data, not
  // because the apparatus is quiescent — so neither the status strip nor the
  // idle empty-state may speak as if it were idle. ActiveWorkersPanel owns the
  // sole "unavailable" notice on that path.
  const monitorAvailable = monitor != null && monitor.available !== false;
  // Recent wrapper-call activity — true even when this run bypasses both the
  // orchestrator and the loop (e.g. a raw experiment driver still calling the
  // wrapper). Counts as live for the idle gate and the status strip.
  const liveCallsActive = monitor?.live_calls?.active ?? false;
  // A run registered in run_state/active_run.json is live, regardless of run
  // kind — fold it into the idle gate and the status strip.
  const runActive = activeRun != null;
  // Idle requires ALL sides quiescent: no workers in flight AND no active
  // orchestrator iteration AND no recent wrapper calls AND no registered run.
  // A running iteration with zero workers, a bare experiment driver still
  // making calls, or any active_run is live, not idle.
  const iterationIdle = iteration == null;
  const pageIdle =
    monitorAvailable &&
    activeCount === 0 &&
    iterationIdle &&
    !liveCallsActive &&
    !runActive;

  return (
    <div className="mx-auto w-full max-w-[1800px] px-6 py-5">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="font-mono text-sm text-zinc-200">activity</h1>
        <span className="text-xs text-zinc-600">monitor 1 Hz · graph 5 s</span>
      </div>

      {/* (1) Live-vs-history status strip. Suppressed on the unavailable
          degrade path — a missing data source is not a quiescent apparatus;
          ActiveWorkersPanel renders the sole "unavailable" notice there. */}
      {monitorAvailable && (
        <div
          data-testid="activity-status"
          className={`mt-3 rounded border px-3 py-2 text-xs ${
            activeCount > 0 || liveCallsActive || runActive
              ? "border-emerald-800/50 bg-emerald-950/20 text-emerald-300"
              : "border-zinc-800 bg-zinc-900/40 text-zinc-400"
          }`}
        >
          {activeCount > 0 ? (
            <>
              <span className="font-medium text-emerald-300">
                {activeCount} task{activeCount === 1 ? "" : "s"} active now.
              </span>{" "}
              Live worker + iteration state below.
            </>
          ) : runActive ? (
            <>
              <span className="font-medium text-emerald-300">Live</span> — a{" "}
              {activeRun!.kind} run is in flight. See the active-run card below.
            </>
          ) : liveCallsActive ? (
            <>
              <span className="font-medium text-emerald-300">Live</span> — the
              apparatus is making wrapper calls (no orchestrator task or loop
              iteration registered). See the live-calls banner below.
            </>
          ) : (
            <>
              <span className="font-medium text-zinc-300">Idle</span> — no
              workers in flight. Recent task history is in the collapsed graph
              at the bottom.
            </>
          )}
        </div>
      )}

      {error && (
        <div className="mt-2 text-xs text-red-400" data-testid="activity-error">
          {error}
        </div>
      )}

      {/* (2) HERO — "Active now", full width. */}
      <section className="mt-4 space-y-4" data-testid="active-now">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Active now
        </h2>
        {/* The active-run HERO card — renders nothing when no run is in
            flight (activeRun null). At the TOP of the hero. */}
        <ActiveRunCard data={activeRun} />
        <ActiveIterationPanel initial={iteration} />
        {monitor?.live_calls?.active && (
          <LiveCallsBanner data={monitor.live_calls} />
        )}
        {monitor ? (
          <ActiveWorkersPanel data={monitor} />
        ) : (
          <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-500">
            Loading agent monitor…
          </div>
        )}
        {/* Idle empty-state: shown only when the page is genuinely idle —
            BOTH no workers in flight AND no active orchestrator iteration,
            and the monitor source is available. A running iteration with zero
            in-flight workers is live, not idle, so this stays hidden then. */}
        {pageIdle && monitor && (
          <div
            data-testid="activity-idle-empty"
            className="rounded border border-zinc-800 bg-zinc-950/40 px-4 py-3 text-sm text-zinc-500"
          >
            No agents active — last activity{" "}
            <span className="font-mono text-zinc-400">
              {elapsed(monitor.last_activity_at, now)}
            </span>{" "}
            ago.
          </div>
        )}
      </section>

      {/* (2.5) Coordinator cycle — the loop's live phase stepper + an explicit
          failed-dispatch surface. Makes the autonomous loop legible on the
          activity page: WHAT stage it's in and why, and any dispatch that
          errored (a red row, never a silent gap). */}
      <section className="mt-4 space-y-4" data-testid="coordinator-activity">
        <CoordinatorPhases activeRun={coordinatorActive} />
        <FailedDispatches cycles={coordinatorCycles} />
      </section>

      {/* (3) Synthetic inference — subordinate disclosure. */}
      {monitor && (
        <div className="mt-4">
          <SyntheticInferencePanel data={monitor} />
        </div>
      )}

      {/* (4) Recent history — the react-flow graph, demoted into a
          collapsible details so it is reference, not the focal element. */}
      <details className="group mt-6" data-testid="recent-history-disclosure">
        <summary className="flex cursor-pointer list-none items-center justify-between text-xs font-medium uppercase tracking-wide text-zinc-500 hover:text-zinc-300">
          <span>
            <span className="group-open:hidden">▸ recent history (graph)</span>
            <span className="hidden group-open:inline">▾ recent history (graph)</span>
          </span>
          <DetailToggle value={detail} onChange={setDetail} />
        </summary>
        <div className="mt-3">
          {graph ? (
            <ActivityGraph data={graph} />
          ) : (
            <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-500">
              Loading activity graph…
            </div>
          )}
        </div>
      </details>
    </div>
  );
}

function DetailToggle({
  value,
  onChange,
}: {
  value: Detail;
  onChange: (d: Detail) => void;
}) {
  const opts: { key: Detail; label: string; title: string }[] = [
    { key: "overview", label: "overview", title: "one node per task" },
    { key: "full", label: "full chain", title: "expand each task's calls" },
  ];
  return (
    <div
      className="flex overflow-hidden rounded border border-zinc-800"
      data-testid="detail-toggle"
      // The toggle lives inside the disclosure summary; stop clicks from
      // toggling the <details> open/closed when switching detail level.
      onClick={(e) => e.preventDefault()}
    >
      {opts.map((o) => (
        <button
          key={o.key}
          type="button"
          title={o.title}
          onClick={() => onChange(o.key)}
          className={`px-2 py-0.5 font-mono text-xs ${
            value === o.key
              ? "bg-zinc-800 text-zinc-100"
              : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
