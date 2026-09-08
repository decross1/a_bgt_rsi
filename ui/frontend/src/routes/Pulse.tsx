// Pulse (/) — a compact source-aware orientation surface. The first view keeps
// three meanings separate: recorded human-request metadata, the current run
// registry, and recorded research history. Full activity, runtime telemetry,
// dated delivery notes, and launch controls remain available in disclosures.
// The lab queue stays opt-in because loading it may trigger topic/embedding
// assessment; hash and command-palette navigation reveal it without loading.
//
// This page owns the WS telemetry stream and the single coordinator-cycle
// poll. All polls use pollhub's in-flight guard, change detection, and
// stale-while-revalidate behavior. The page clock is coarse because it feeds
// only source-age and history-bucket labels; run timers tick inside NowBoard.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import Card from "../design/Card";
import { registerPaletteActions } from "../design/CommandPalette";
import DevelopmentNotice from "../components/DevelopmentNotice";
import HealthStrip from "../components/HealthStrip";
import HealthVerdict, {
  excludeQwenReadErrors,
} from "../components/HealthVerdict";
import LabSparkgrid from "../components/LabSparkgrid";
import LabTodo from "../components/LabTodo";
import LadderMiniFunnel from "../components/LadderMiniFunnel";
import LastCycleLine from "../components/LastCycleLine";
import ModelServerCard, {
  QWEN_SERVED_MODEL,
  VLLM_SERVED_MODEL,
} from "../components/ModelServerCard";
import NaraPromptForm from "../components/NaraPromptForm";
import NowBoard from "../components/NowBoard";
import OweCard from "../components/OweCard";
import { getActivityMonitor } from "../api/activity";
import { getCoordinatorCycles, getHealth, getIterations, getServedModels } from "../api/http";
import { usePolled } from "../api/pollhub";
import { useTelemetryStream } from "../hooks/useTelemetryStream";
import { ageLabel } from "../ladderBar";
import { useNow } from "../time";
import type { LiveCalls, MonitorResponse } from "../types/activity";
import type {
  CoordinatorCycle,
  Health,
  IterationRecord,
  TelemetrySample,
} from "../types/schemas";
import "./now.css";

// Newest parseable ISO instant among candidates, or null. Used for the honest
// idle line ("last finished Xh ago") — an unparseable timestamp contributes
// nothing rather than standing in as "now". Scans EVERY candidate rather than
// trusting the endpoints' newest-first sort, so a producer whose ordering
// degrades understates nothing.
function newestIso(candidates: unknown[]): string | null {
  let best: { iso: string; t: number } | null = null;
  for (const c of candidates) {
    if (typeof c !== "string" || !c) continue;
    const t = Date.parse(c);
    if (Number.isNaN(t)) continue;
    if (best == null || t > best.t) best = { iso: c, t };
  }
  return best?.iso ?? null;
}

// Stable `pick` identities for the two ModelServerCards — inline arrows would
// re-create per render and defeat the cards' React.memo.
const pickGemma = (s: TelemetrySample) => s.vllm;
const pickQwen = (s: TelemetrySample) => s.vllm_qwen;

// A telemetry row is evidence for model health only when it carries the
// producer's minimum model fields. The websocket boundary is unvalidated, so
// arrays and object-shaped garbage must not become an observed failed scrape.
function isTelemetrySample(value: unknown): value is TelemetrySample {
  if (value == null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const row = value as Record<string, unknown>;
  if (typeof row.timestamp !== "string" || !("vllm" in row)) return false;
  const validBlock = (block: unknown) =>
    block == null || (typeof block === "object" && !Array.isArray(block));
  return validBlock(row.vllm) && validBlock(row.vllm_qwen);
}

const CURRENT_TELEMETRY_MAX_AGE_MS = 5000;

type ModelEvidenceMode =
  | "awaiting"
  | "disconnected-unobserved"
  | "historical-disconnected"
  | "historical-stale"
  | "time-unknown";

// ModelServerCard intentionally owns only supplied current-sample semantics.
// Pulse owns connection and time context, so it substitutes this neutral card
// whenever the retained rows cannot establish current model health.
function ModelEvidenceCard({
  title,
  servedModel,
  metricsObserved,
  mode,
  accent = "zinc",
}: {
  title: string;
  servedModel: string;
  metricsObserved: boolean;
  mode: ModelEvidenceMode;
  accent?: "zinc" | "sky";
}) {
  const historical =
    mode === "historical-disconnected" || mode === "historical-stale";
  const explanation =
    mode === "awaiting"
      ? "Awaiting first telemetry sample — current model health not observed."
      : mode === "disconnected-unobserved"
        ? "Telemetry disconnected — model health not observed."
        : mode === "time-unknown"
          ? "Telemetry sample time is invalid or ahead of this clock — current model health is unknown."
          : `Historical telemetry — retained samples ${
              metricsObserved ? "contained" : "did not contain"
            } metrics. Current model health is unknown because telemetry is ${
              mode === "historical-stale" ? "stale" : "disconnected"
            }.`;

  return (
    <div
      className="now-model-evidence"
      data-accent={accent}
    >
      <div className="now-model-evidence__header">
        <h2>
          {title}
        </h2>
        <span
          className="now-model-evidence__status"
          data-testid={`${servedModel}-status`}
        >
          {historical ? "● historical" : "● unknown"}
        </span>
      </div>
      <p>{explanation}</p>
    </div>
  );
}

// The iterations poll feeds ONLY the sparkgrid + the idle "last finished"
// clause, so ask the backend for the timestamp column, not the full record
// (the full payload measured 3.4 MB / 2.9 s per poll on 2026-08-18; an older
// backend binary ignores the params and still answers with the full rows).
const fetchIterationTimes = () =>
  getIterations({ fields: "iteration_id,ended_at", limit: 1000 });

// CHURN-STRIP (adversarial-review residual fix 2, 2026-08-18):
// /api/activity/monitor stamps a fresh top-level `generated_at` on EVERY
// response, so an otherwise-idle monitor payload always read as "changed"
// to the hub's JSON change detection — NowBoard and both ModelServerCards
// re-rendered on every 15 s poll of a perfectly quiet lab. Strip it BEFORE
// the payload reaches the hub. It is the only churn-only field on this
// payload (live_calls / synthetic_inference / active / recent move only
// when calls or worker rows actually move, and their windows shift only
// when rows enter/leave them), and nothing on this page displays it
// (NowBoard and the cards read only live_calls), so no stripped value
// needs keeping aside. Exported for the test pin in test_pulse.tsx.
export function stripMonitorChurn(
  m: MonitorResponse,
): Omit<MonitorResponse, "generated_at"> {
  const { ...rest } = m;
  delete (rest as { generated_at?: unknown }).generated_at;
  return rest;
}
const fetchMonitor = () => getActivityMonitor(1).then(stripMonitorChurn);

export default function Pulse() {
  const { samples, connected } = useTelemetryStream();
  const [launchOpen, setLaunchOpen] = useState(false);
  const [requestsOpen, setRequestsOpen] = useState(false);
  const [queueRequested, setQueueRequested] = useState(false);
  const [queueOpen, setQueueOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  // 0.2 Hz page clock: `now` feeds only telemetry-staleness math and the
  // sparkgrid's UTC day buckets — nothing on this page renders live seconds.
  // (NowBoard runs its own 1 Hz clock for elapsed counters, in its own
  // subtree.) The old 1 Hz clock re-rendered the entire page every second.
  const now = useNow(5000);
  const { hash } = useLocation();

  // --- every poll goes through the pollhub: one heartbeat, per-source
  // cadences, in-flight guards, change detection, stale-while-revalidate.
  // Initial fetches are lightly staggered so first paint is the cheap
  // sources, not a 10-request thundering herd on one backend threadpool.
  const health: Health | null =
    usePolled("health", getHealth, { intervalMs: 15000 }).data ?? null;
  // Live served-model names — the card titles must not be strings (an A/B
  // window on 2026-08-16 had the dashboard announcing 3.6 while 3.8 served).
  // Polled, not read once: a model server can be swapped under a running
  // dashboard. SWR keeps the previous value on a failed read rather than
  // blanking the card; a reachable endpoint reporting no model renders
  // "unknown".
  const servedModels = usePolled("served_models", getServedModels, {
    intervalMs: 30000,
  }).data ?? null;
  // The live wrapper-call aggregate — feeds the NowBoard headline strip and
  // both ModelServerCards' "driving" sub-lines. limit=1 keeps the monitor
  // payload cheap (only its live_calls block is read). Fails quiet (SWR).
  const monitor = usePolled("monitor", fetchMonitor, {
    intervalMs: 15000,
    initialDelayMs: 100,
  }).data;
  const liveCalls: LiveCalls | null = useMemo(
    () => monitor?.live_calls ?? null,
    [monitor],
  );
  // The two event histories behind the sparkgrid. Both fail quiet: an
  // unreachable endpoint leaves the grid empty (an honest "no evidence of
  // activity"), never a fabricated one.
  const cyclesPoll = usePolled("cycles", getCoordinatorCycles, {
    intervalMs: 60000,
    initialDelayMs: 200,
  });
  const iterationsPoll = usePolled("iterations", fetchIterationTimes, {
    intervalMs: 60000,
    initialDelayMs: 300,
  });
  const rawCycles: unknown = cyclesPoll.data?.cycles;
  const cyclesShapeValid =
    cyclesPoll.data !== undefined && Array.isArray(rawCycles);
  const cycles: CoordinatorCycle[] | null = useMemo(
    () =>
      Array.isArray(cyclesPoll.data?.cycles)
        ? cyclesPoll.data.cycles.filter(
            (cycle): cycle is CoordinatorCycle =>
              cycle != null &&
              typeof cycle === "object" &&
              !Array.isArray(cycle),
          )
        : null,
    [cyclesPoll.data],
  );
  const cyclesMalformedRows =
    Array.isArray(rawCycles) ? rawCycles.length - (cycles?.length ?? 0) : 0;
  const cyclesMalformed =
    cyclesPoll.data !== undefined &&
    (!cyclesShapeValid || cyclesMalformedRows > 0);
  const cyclesLoaded = cyclesShapeValid;
  // Pulse took over LastCycleLine's poll, so it also inherits its duty to be
  // honest about a FAILED read: an unreachable cycles endpoint must say so,
  // not render an empty slot that reads as "the loop has done nothing".
  // (With SWR, "failed" only blanks the line when NO payload ever landed;
  // once data exists a failing refetch keeps showing it.)
  const cyclesFailed = cyclesPoll.failing && !cyclesLoaded;
  const cyclesStale = cyclesPoll.failing && cyclesLoaded;
  const rawIterations: unknown = iterationsPoll.data?.iterations;
  const iterationsShapeValid =
    iterationsPoll.data !== undefined && Array.isArray(rawIterations);
  const iterations: IterationRecord[] = useMemo(
    () =>
      Array.isArray(iterationsPoll.data?.iterations)
        ? iterationsPoll.data.iterations.filter(
            (iteration): iteration is IterationRecord =>
              iteration != null &&
              typeof iteration === "object" &&
              !Array.isArray(iteration),
          )
        : [],
    [iterationsPoll.data],
  );
  const iterationsMalformedRows = Array.isArray(rawIterations)
    ? rawIterations.length - iterations.length
    : 0;
  const iterationsMalformed =
    iterationsPoll.data !== undefined &&
    (!iterationsShapeValid || iterationsMalformedRows > 0);
  const iterationsFailed =
    iterationsPoll.failing && !iterationsShapeValid;
  const iterationsStale =
    iterationsPoll.failing && iterationsShapeValid;

  const heroRef = useRef<HTMLDivElement>(null);
  const labQueueRef = useRef<HTMLDetailsElement>(null);
  const activityRef = useRef<HTMLDetailsElement>(null);
  const launchRef = useRef<HTMLDetailsElement>(null);

  // Arriving from /ladder's "lab queue →" link (`/#lab-queue`): React Router
  // does not scroll for a hash, so bring the zone into view once.
  useEffect(() => {
    if (hash === "#what-you-owe") {
      setRequestsOpen(true);
      heroRef.current?.scrollIntoView?.({ block: "start" });
    }
    if (hash === "#lab-queue") {
      setQueueOpen(true);
      labQueueRef.current?.scrollIntoView?.({ block: "start" });
    }
  }, [hash]);

  // Pulse's verbs in the ⌘K palette (the R0 registerPaletteActions seam).
  // Registered once — the closures read refs and setState, both stable.
  useEffect(() => {
    const scrollTo = (el: HTMLElement | null) => el?.scrollIntoView?.({ block: "start" });
    return registerPaletteActions([
      {
        id: "pulse-owed",
        label: "review what you owe",
        group: "Pulse",
        keywords: ["todo", "queue", "gate", "verdict", "finding"],
        perform: () => {
          setRequestsOpen(true);
          scrollTo(heroRef.current);
        },
      },
      {
        id: "pulse-lab-queue",
        label: "lab queue",
        group: "Pulse",
        keywords: ["nara", "pi", "todo", "owed", "agenda", "refine", "cluster"],
        perform: () => {
          setQueueOpen(true);
          scrollTo(labQueueRef.current);
        },
      },
      {
        id: "pulse-activity",
        label: "show lab activity",
        group: "Pulse",
        keywords: ["sparkgrid", "heatmap", "alive", "ladder"],
        perform: () => {
          setActivityOpen(true);
          scrollTo(activityRef.current);
        },
      },
      {
        id: "pulse-launch",
        label: "launch an iteration",
        group: "Pulse",
        keywords: ["nara", "run", "start", "prompt"],
        perform: () => {
          setLaunchOpen(true);
          scrollTo(launchRef.current);
        },
      },
    ]);
  }, []);

  // --- HealthVerdict inputs, lifted verbatim from Dashboard.tsx ----------
  // The telemetry buffer is forwarded raw off the WS (`msg.line as
  // TelemetrySample`, no runtime validation in useTelemetryStream), so a
  // malformed/legacy frame can drop a `null` (or any non-object) into the
  // array. That bad element white-screens the page the moment any consumer
  // dereferences it. Skip the bad rows once here (the backend's own "drop
  // malformed rows" philosophy) and feed the cleaned array to the verdict
  // math AND every panel below, so one garbage frame degrades to a missing
  // scrape instead of a crashed page. Memoized so the array identity is
  // stable across renders that did not change `samples` — the children's
  // React.memo depends on it.
  const cleanSamples = useMemo(
    () => samples.filter(isTelemetrySample),
    [samples],
  );

  const latestSample = cleanSamples[cleanSamples.length - 1] ?? null;
  // Only the sample whose model blocks we render can establish their age.
  // A backend health timestamp cannot make an absent, malformed or retained
  // websocket row current. Invalid and future times remain unknown.
  // The coarse heartbeat triggers age rechecks, but can precede a new frame.
  // Compare with the render-time clock so a just-arrived frame is not future.
  const parsedAge = latestSample ? Date.now() - Date.parse(latestSample.timestamp) : null;
  const ageMs =
    parsedAge != null && Number.isFinite(parsedAge) && parsedAge >= 0
      ? parsedAge
      : null;
  const telemetryTimeUnknown = latestSample != null && ageMs == null;
  const telemetryStale =
    ageMs != null && ageMs > CURRENT_TELEMETRY_MAX_AGE_MS;
  // Qwen is excluded from the verdict (staged/unwired today): a failing-but-
  // enabled Qwen reader emits a "vllm-qwen-metrics" read error, which must
  // not drag the whole system to degraded. Drop Qwen-owned keys here.
  // read_errors is sampler-owned and forwarded raw off the WS, so a legacy/
  // garbage frame can hand back a non-object truthy value — a string, a
  // number, or an array. A bare `? Object.keys(...)` would then mine that
  // value for index keys ("0","1",…) and paint a FALSE degraded with numeric
  // "read errors". Only treat a plain object as a real error map; any other
  // shape is "no legible read errors", not a fault.
  const rawReadErrors = latestSample?.read_errors;
  const readErrorKeys =
    rawReadErrors != null &&
    typeof rawReadErrors === "object" &&
    !Array.isArray(rawReadErrors)
      ? Object.keys(rawReadErrors)
      : [];
  const readErrors = excludeQwenReadErrors(readErrorKeys);
  // Gemma is up when the latest sample carries a `vllm` block. Debounced:
  // a single transient scrape miss (server fine, one failed /metrics poll)
  // should not flip the hero to DOWN. We require the vllm block to be
  // absent across the most recent GEMMA_DOWN_WINDOW samples before calling
  // it down. With fewer observed samples than the window, use the latest.
  // No samples means unobserved, not an observed failed scrape. A disconnected
  // stream also cannot establish current model health; retain its last evidence
  // with a historical label instead of composing a current outage verdict.
  const GEMMA_DOWN_WINDOW = 2;
  const recent = cleanSamples.slice(-GEMMA_DOWN_WINDOW);
  const gemmaUp =
    recent.length === 0
      ? null
      : recent.length < GEMMA_DOWN_WINDOW
        ? recent[recent.length - 1]?.vllm != null
        : recent.some((s) => s.vllm != null);
  const modelEvidenceMode: ModelEvidenceMode | "current" =
    cleanSamples.length === 0
      ? connected
        ? "awaiting"
        : "disconnected-unobserved"
      : !connected
        ? "historical-disconnected"
        : telemetryTimeUnknown
          ? "time-unknown"
          : telemetryStale
            ? "historical-stale"
            : "current";

  // Sparkgrid inputs: both endpoints sort newest-first, so [0] is the most
  // recent of each and their newer end is "last finished". Memoized for the
  // same reason as cleanSamples: LabSparkgrid is React.memo'd on these.
  const cycleTimes = useMemo(
    () => (cycles ?? []).map((c) => c?.timestamp),
    [cycles],
  );
  const iterationTimes = useMemo(
    () => iterations.map((r) => r?.ended_at),
    [iterations],
  );
  const lastFinishedIso = useMemo(
    () => newestIso([...cycleTimes, ...iterationTimes]),
    [cycleTimes, iterationTimes],
  );
  const historyPending =
    !cyclesShapeValid &&
    !iterationsShapeValid &&
    !cyclesFailed &&
    !iterationsFailed &&
    !cyclesMalformed &&
    !iterationsMalformed;
  const historyIncomplete =
    cyclesFailed ||
    iterationsFailed ||
    cyclesStale ||
    iterationsStale ||
    cyclesMalformed ||
    iterationsMalformed;
  const historyHeadline =
    cyclesMalformed || iterationsMalformed
      ? "Recorded history is incomplete because a source response was malformed."
      : cyclesFailed || iterationsFailed
        ? "A recorded-history source is unavailable; the latest change is unknown."
        : cyclesStale || iterationsStale
          ? lastFinishedIso
            ? `Latest timestamp in the retained history read ended ${ageLabel(lastFinishedIso, now)} ago; a refresh is failing.`
            : "History refresh is failing; the latest recorded change is unknown."
          : lastFinishedIso
            ? `Latest timestamped cycle or iteration ended ${ageLabel(lastFinishedIso, now)} ago.`
            : historyPending
              ? "Reading recorded cycle and iteration sources…"
              : "No timestamped cycle or iteration appears in the loaded history window.";

  return (
    <div className="page-full now-page" data-testid="pulse-page">
      <header className="now-page__header">
        <div>
          <p className="now-page__eyebrow">Lab workspace</p>
          <h1 className="now-page__title">Now</h1>
          <p className="now-page__dek">
            Find the next justified inspection. Recorded requests, running work,
            and research history keep their own source and meaning.
          </p>
        </div>
        <div className="now-page__routes" aria-label="Related workspaces">
          <Link to="/ladder">Explore research</Link>
          <Link to="/development">Review delivery and readiness</Link>
        </div>
      </header>

      <div className="now-page__source" data-testid="pulse-source-line">
        <code>
          {health?.hostname ?? "host unknown"}
        </code>
        <span>backend-reported revision {health?.version ?? "unknown"}</span>
      </div>

      <section
        className="now-orientation"
        aria-labelledby="now-orientation-heading"
        data-testid="now-orientation"
      >
        <header className="now-orientation__header">
          <p className="now-orientation__eyebrow">Attention and source state</p>
          <h2 id="now-orientation-heading">What deserves inspection</h2>
          <p>
            Each row answers a different question. A recorded request is not a
            verified current obligation, an idle registry is not research
            progress, and history does not establish eligibility.
          </p>
        </header>

        <div id="what-you-owe" ref={heroRef} className="now-anchor">
          <OweCard
            expanded={requestsOpen}
            onExpandedChange={setRequestsOpen}
          />
        </div>

        <section className="now-lane" data-testid="pulse-running-now">
          <header className="now-lane__label">
            <p className="now-lane__eyebrow">Runtime now</p>
            <h3>Running work</h3>
            <span className="now-lane__source">/api/activity/active_runs</span>
          </header>
          <div className="now-lane__body">
            <div className="now-runtime-board">
              <NowBoard
                live
                orientation
                liveCalls={liveCalls}
                telemetry={cleanSamples[cleanSamples.length - 1] ?? null}
                lastFinishedIso={lastFinishedIso}
              />
            </div>
            <div className="now-runtime-context">
              {gemmaUp === null ||
              !connected ||
              telemetryTimeUnknown ||
              telemetryStale ? (
                <div
                  data-testid="health-verdict"
                  data-level="unknown"
                  className="flex flex-wrap items-center text-[var(--fg-muted)]"
                >
                  <span className="font-semibold">UNKNOWN</span>
                  <span>
                    {!connected
                      ? "Telemetry disconnected"
                      : telemetryStale
                        ? "Telemetry stale"
                        : telemetryTimeUnknown
                          ? "Telemetry time unknown"
                          : "Awaiting telemetry"}
                  </span>
                  <span>
                    {gemmaUp === null
                      ? "Model health not observed"
                      : gemmaUp
                        ? "Last samples: Gemma metrics present"
                        : "Last samples: Gemma metrics unavailable"}
                  </span>
                  {readErrors.length > 0 && (
                    <span>
                      {modelEvidenceMode === "current"
                        ? "Read errors"
                        : "Last read errors"}
                      : {readErrors.join(", ")}
                    </span>
                  )}
                </div>
              ) : (
                <HealthVerdict
                  connected={connected}
                  hasTelemetry={cleanSamples.length > 0}
                  ageMs={ageMs}
                  readErrors={readErrors}
                  gemmaUp={gemmaUp}
                />
              )}
            </div>
          </div>
        </section>

        <section className="now-lane" data-testid="pulse-recorded-research">
          <header className="now-lane__label">
            <p className="now-lane__eyebrow">Recorded research</p>
            <h3>Latest history</h3>
            <span className="now-lane__source">cycles + iterations</span>
          </header>
          <div className="now-lane__body">
            <p
              className={`now-lane__headline${historyIncomplete ? " now-read-warning" : ""}`}
              data-testid="pulse-history-summary"
            >
              {historyHeadline}
            </p>
            <p className="now-lane__qualifier">
              This is recorded execution history. It is not a scientific
              result, current eligibility, or a progress score.
            </p>
            <div className="now-lane__meta">
              <Link className="now-inline-link" to="/cycles">
                Inspect trace history
              </Link>
              <Link className="now-inline-link" to="/ladder">
                Inspect research claims
              </Link>
            </div>
          </div>
        </section>
      </section>

      <section
        className="now-support"
        data-density="dense"
        data-testid="pulse-secondary"
      >
        <h2 className="now-support__heading">Evidence and controls</h2>

        <details
          id="lab-queue"
          ref={labQueueRef}
          className="now-disclosure"
          open={queueOpen}
          onToggle={(event) => setQueueOpen(event.currentTarget.open)}
          data-testid="pulse-lab-queue"
        >
          <summary>
            <span className="now-disclosure__title">Lab queue</span>
            <span className="now-disclosure__state">
              {queueRequested
                ? "Loaded on request · source details shown below"
                : "Not loaded · freshness unknown · expensive source remains opt-in"}
            </span>
          </summary>
          <div className="now-disclosure__body">
            {queueRequested ? (
              <LabTodo />
            ) : (
              <div className="now-queue-intro" data-testid="pulse-queue-not-read">
                <div>
                  <p>
                    The lab queue has not been loaded in this view, so its
                    contents and freshness are unknown.
                  </p>
                  <p>
                    Loading may run topic and embedding assessment. Existing
                    cache behavior and request shape are retained.
                  </p>
                </div>
                <button type="button" onClick={() => setQueueRequested(true)}>
                  Load lab queue
                </button>
              </div>
            )}
          </div>
        </details>

        <details
          ref={activityRef}
          className="now-disclosure"
          open={activityOpen}
          onToggle={(event) => setActivityOpen(event.currentTarget.open)}
          data-testid="pulse-recorded-evidence"
        >
          <summary>
            <span className="now-disclosure__title">
              Recorded activity and research distribution
            </span>
            <span className="now-disclosure__state">
              History, last cycle, and ladder counts · recorded evidence
            </span>
          </summary>
          <div className="now-disclosure__body now-evidence-stack">
            {cyclesMalformed && (cycles?.length ?? 0) === 0 ? (
              <div data-testid="pulse-cycles-malformed" className="now-read-warning">
                /api/coordinator/cycles returned malformed history; the last
                recorded cycle is unknown.
              </div>
            ) : cyclesLoaded ? (
              <LastCycleLine initial={cycles} />
            ) : cyclesFailed ? (
              <div data-testid="pulse-cycles-unavailable" className="now-read-warning">
                /api/coordinator/cycles unreachable — the last recorded cycle
                is UNKNOWN, not absent.
              </div>
            ) : (
              <div className="now-muted-read">Reading recorded cycle history…</div>
            )}
            {cyclesMalformed && (cycles?.length ?? 0) > 0 && (
              <div data-testid="pulse-cycles-malformed" className="now-read-warning">
                {cyclesMalformedRows} unreadable cycle-history record
                {cyclesMalformedRows === 1 ? "" : "s"} omitted; the displayed
                history is incomplete.
              </div>
            )}
            {cyclesStale && (
              <div data-testid="pulse-cycles-stale" className="now-read-warning">
                Cycle-history refresh is failing; displayed rows are a retained
                read.
              </div>
            )}
            {iterationsFailed ? (
              <div data-testid="pulse-iterations-unavailable" className="now-read-warning">
                Iteration history is unavailable; activity distribution is
                incomplete.
              </div>
            ) : iterationsMalformed ? (
              <div data-testid="pulse-iterations-malformed" className="now-read-warning">
                Iteration history is malformed; activity distribution is
                incomplete.
              </div>
            ) : iterationsStale ? (
              <div data-testid="pulse-iterations-stale" className="now-read-warning">
                Iteration-history refresh is failing; displayed timestamps are
                a retained read.
              </div>
            ) : null}
            <div className="now-evidence-grid">
              <Card title="Lab activity" testId="pulse-lab-activity">
                <LabSparkgrid
                  iterationTimes={iterationTimes}
                  cycleTimes={cycleTimes}
                  nowMs={now}
                />
              </Card>
              <LadderMiniFunnel />
            </div>
          </div>
        </details>

        <details className="now-disclosure" data-testid="pulse-runtime-evidence">
          <summary>
            <span className="now-disclosure__title">Runtime evidence</span>
            <span className="now-disclosure__state">
              Host and model telemetry · full metrics and raw-source links
            </span>
          </summary>
          <div className="now-disclosure__body now-evidence-stack">
            <HealthStrip samples={cleanSamples} />
            <div className="now-source-link-row">
              <Link
                to="/model-io"
                data-testid="pulse-model-io-link"
                className="now-inline-link"
              >
                Inspect model input and output
              </Link>
            </div>
            <div className="now-evidence-grid now-model-grid">
              {modelEvidenceMode === "current" ? (
                <>
                  <ModelServerCard
                    title={servedModels?.gemma?.model ?? "unknown"}
                    servedModel={servedModels?.gemma?.model ?? VLLM_SERVED_MODEL}
                    pick={pickGemma}
                    samples={cleanSamples}
                    liveCalls={liveCalls}
                    accent="zinc"
                    workloadHint
                  />
                  <ModelServerCard
                    title={servedModels?.qwen?.model ?? "unknown"}
                    servedModel={servedModels?.qwen?.model ?? QWEN_SERVED_MODEL}
                    pick={pickQwen}
                    samples={cleanSamples}
                    liveCalls={liveCalls}
                    accent="sky"
                    transientDropBanner
                  />
                </>
              ) : (
                <>
                  <ModelEvidenceCard
                    title={servedModels?.gemma?.model ?? "unknown"}
                    servedModel={servedModels?.gemma?.model ?? VLLM_SERVED_MODEL}
                    metricsObserved={cleanSamples.some(
                      (sample) => pickGemma(sample) != null,
                    )}
                    mode={modelEvidenceMode}
                  />
                  <ModelEvidenceCard
                    title={servedModels?.qwen?.model ?? "unknown"}
                    servedModel={servedModels?.qwen?.model ?? QWEN_SERVED_MODEL}
                    metricsObserved={cleanSamples.some(
                      (sample) => pickQwen(sample) != null,
                    )}
                    mode={modelEvidenceMode}
                    accent="sky"
                  />
                </>
              )}
            </div>
          </div>
        </details>

        <details className="now-disclosure" data-testid="pulse-delivery-history">
          <summary>
            <span className="now-disclosure__title">Delivery history</span>
            <span className="now-disclosure__state">
              Dated engineering record · not current release or deployment state
            </span>
          </summary>
          <div className="now-disclosure__body">
            <DevelopmentNotice />
          </div>
        </details>

        <details
          ref={launchRef}
          className="now-disclosure"
          open={launchOpen}
          onToggle={(event) => setLaunchOpen(event.currentTarget.open)}
          data-testid="pulse-launch-disclosure"
        >
          <summary>
            <span className="now-disclosure__title">Launch an iteration</span>
            <span className="now-disclosure__state">
              Governed manual control · collapsed by default
            </span>
          </summary>
          <div className="now-disclosure__body">
            <NaraPromptForm />
          </div>
        </details>
      </section>
    </div>
  );
}
