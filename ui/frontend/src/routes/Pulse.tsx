// Pulse (/) — the designed dashboard (revamp R3, on the R0 token system).
//
// The page is THREE ZONES, read top-down in the F-pattern, with deliberately
// UNEQUAL emphasis (the R3 brief's anti-pattern list: no KPI-tile carpet, no
// uniform emphasis, no fake activity):
//
//   0. Identity bar — hostname · backend sha · the HealthVerdict, now a
//      compact status LINE rather than a panel. System health is a
//      precondition, not the headline.
//   1. HERO — OweStrip: what the human actually owes (gate verdicts + L4/L5
//      findings). Biggest type, highest contrast, first thing read. Everything
//      below the ladder bar renders inside it as ONE muted line, never a row.
//   1b. LabTodo — the LAB's queue (what Nara and the PI advance on their own),
//      directly under the hero and deliberately quieter. The two queues are
//      adjacent so the ownership line is obvious, and the panel points back up
//      at the hero rather than restating the human's work.
//   2. The loop's state — "Running now" (the D-047 registry as Vercel-style
//      deployment cards), then the lab-activity sparkgrid + the L0->L5 ladder
//      mini-funnel side by side.
//   3. Secondary, dense — last cycle, host/GPU strip, the two model servers,
//      and the launch disclosure. Marked data-density="dense" so shared rows
//      tighten to 28px without per-component props.
//
// This page owns the WS telemetry stream; LoopAlertBanner is global (App).
// It also owns the ONE /api/coordinator/cycles poll, handing the rows to both
// LastCycleLine and the sparkgrid instead of letting them each poll.
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import Card from "../design/Card";
import { registerPaletteActions } from "../design/CommandPalette";
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
import OweStrip from "../components/OweStrip";
import { getActivityMonitor } from "../api/activity";
import { getCoordinatorCycles, getHealth, getIterations, getServedModels } from "../api/http";
import { useTelemetryStream } from "../hooks/useTelemetryStream";
import { useNow } from "../time";
import type { LiveCalls } from "../types/activity";
import type {
  CoordinatorCycle,
  Health,
  IterationRecord,
  TelemetrySample,
} from "../types/schemas";

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

export default function Pulse() {
  const { samples, latest, connected } = useTelemetryStream();
  const [health, setHealth] = useState<Health | null>(null);
  // Live served-model names — the card titles must not be strings (an A/B
  // window on 2026-08-16 had the dashboard announcing 3.6 while 3.8 served).
  const [servedModels, setServedModels] = useState<
    Record<string, { model: string | null; error: string | null }> | null
  >(null);
  // The live wrapper-call aggregate — feeds the NowBoard headline strip and
  // both ModelServerCards' "driving" sub-lines. limit=1 keeps the monitor
  // payload cheap (only its live_calls block is read). Fails quiet.
  const [liveCalls, setLiveCalls] = useState<LiveCalls | null>(null);
  // The two event histories behind the sparkgrid. Both fail quiet: an
  // unreachable endpoint leaves the grid empty (an honest "no evidence of
  // activity"), never a fabricated one.
  const [cycles, setCycles] = useState<CoordinatorCycle[] | null>(null);
  const [cyclesLoaded, setCyclesLoaded] = useState(false);
  // Pulse took over LastCycleLine's poll, so it also inherits its duty to be
  // honest about a FAILED read: an unreachable cycles endpoint must say so,
  // not render an empty slot that reads as "the loop has done nothing".
  const [cyclesFailed, setCyclesFailed] = useState(false);
  const [iterations, setIterations] = useState<IterationRecord[]>([]);
  const [launchOpen, setLaunchOpen] = useState(false);
  const now = useNow();
  const { hash } = useLocation();

  const heroRef = useRef<HTMLDivElement>(null);
  const labQueueRef = useRef<HTMLDivElement>(null);
  const activityRef = useRef<HTMLDivElement>(null);
  const launchRef = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    const loadHealth = () => getHealth().then(setHealth).catch(() => {});
    loadHealth();
    const id = setInterval(loadHealth, 10000);
    return () => clearInterval(id);
  }, []);

  // Polled, not read once: a model server can be swapped under a running
  // dashboard (that is exactly how the 2026-08-16 mislabel happened). A failed
  // read leaves the previous value rather than blanking the card; a reachable
  // endpoint reporting no model renders "unknown".
  useEffect(() => {
    const load = () => getServedModels().then(setServedModels).catch(() => {});
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const load = () =>
      getActivityMonitor(1)
        .then((r) => setLiveCalls(r?.live_calls ?? null))
        .catch(() => {});
    load();
    const id = setInterval(load, 7000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const load = () => {
      getCoordinatorCycles()
        .then((r) => {
          setCycles(Array.isArray(r?.cycles) ? r.cycles : []);
          setCyclesLoaded(true);
          setCyclesFailed(false);
        })
        .catch(() => setCyclesFailed(true));
      getIterations()
        .then((r) => setIterations(Array.isArray(r?.iterations) ? r.iterations : []))
        .catch(() => {});
    };
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  // Arriving from /ladder's "lab queue →" link (`/#lab-queue`): React Router
  // does not scroll for a hash, so bring the zone into view once.
  useEffect(() => {
    if (hash !== "#lab-queue") return;
    labQueueRef.current?.scrollIntoView?.({ block: "start" });
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
        perform: () => scrollTo(heroRef.current),
      },
      {
        id: "pulse-lab-queue",
        label: "lab queue",
        group: "Pulse",
        keywords: ["nara", "pi", "todo", "owed", "agenda", "refine", "cluster"],
        perform: () => scrollTo(labQueueRef.current),
      },
      {
        id: "pulse-activity",
        label: "show lab activity",
        group: "Pulse",
        keywords: ["sparkgrid", "heatmap", "alive", "ladder"],
        perform: () => scrollTo(activityRef.current),
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
  // scrape instead of a crashed page.
  const cleanSamples = samples.filter(
    (s): s is TelemetrySample => s != null && typeof s === "object",
  );

  const lastSeen = latest?.timestamp ?? health?.telemetry_last_seen ?? null;
  // Guard against a malformed/absent timestamp: Date.parse -> NaN, which
  // would otherwise slip past the `ageMs > threshold` staleness check
  // (NaN comparisons are always false) and paint a false-healthy hero.
  // Coerce non-finite ages to null so the verdict treats freshness as
  // unknown rather than fresh.
  const parsedAge = lastSeen ? now - Date.parse(lastSeen) : null;
  const ageMs =
    parsedAge != null && Number.isFinite(parsedAge) ? parsedAge : null;
  // Qwen is excluded from the verdict (staged/unwired today): a failing-but-
  // enabled Qwen reader emits a "vllm-qwen-metrics" read error, which must
  // not drag the whole system to degraded. Drop Qwen-owned keys here.
  // read_errors is sampler-owned and forwarded raw off the WS, so a legacy/
  // garbage frame can hand back a non-object truthy value — a string, a
  // number, or an array. A bare `? Object.keys(...)` would then mine that
  // value for index keys ("0","1",…) and paint a FALSE degraded with numeric
  // "read errors". Only treat a plain object as a real error map; any other
  // shape is "no legible read errors", not a fault.
  const rawReadErrors = latest?.read_errors;
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
  // it down. With fewer samples than the window, fall back to the latest.
  const GEMMA_DOWN_WINDOW = 2;
  const recent = cleanSamples.slice(-GEMMA_DOWN_WINDOW);
  const gemmaUp =
    recent.length === 0
      ? false
      : recent.length < GEMMA_DOWN_WINDOW
        ? recent[recent.length - 1]?.vllm != null
        : recent.some((s) => s.vllm != null);

  // Sparkgrid inputs: both endpoints sort newest-first, so [0] is the most
  // recent of each and their newer end is "last finished".
  const cycleTimes = (cycles ?? []).map((c) => c?.timestamp);
  const iterationTimes = iterations.map((r) => r?.ended_at);
  const lastFinishedIso = newestIso([...cycleTimes, ...iterationTimes]);

  return (
    <div className="page-full" data-testid="pulse-page">
      {/* ── 0 · identity bar ────────────────────────────────────────────── */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: "var(--space-4)",
          marginBottom: "var(--space-4)",
          fontSize: "var(--text-meta)",
          color: "var(--fg-muted)",
        }}
      >
        <span style={{ fontFamily: "var(--font-mono)", color: "var(--fg)" }}>
          {health?.hostname ?? "spark"}
        </span>
        <span>backend {health?.version ?? "?"}</span>
        <span style={{ marginLeft: "auto" }}>
          <HealthVerdict
            connected={connected}
            hasTelemetry={cleanSamples.length > 0}
            ageMs={ageMs}
            readErrors={readErrors}
            gemmaUp={gemmaUp}
          />
        </span>
      </div>

      {/* ── 1 · HERO — what you owe ─────────────────────────────────────── */}
      {/* id: LabTodo's blocked-on-you line points back UP at this hero rather
          than restating the same work as a second list. */}
      <div id="what-you-owe" ref={heroRef}>
        <OweStrip />
      </div>

      {/* ── 1b · the LAB's queue — secondary to the hero, by design ─────── */}
      {/* The human's queue is the hero; what Nara and the PI advance on their
          own sits directly under it, quieter. */}
      <div ref={labQueueRef} style={{ marginTop: "var(--space-4)" }}>
        <LabTodo />
      </div>

      {/* ── 2 · the loop's state ────────────────────────────────────────── */}
      <div style={{ marginTop: "var(--space-5)" }}>
        <Card testId="pulse-running-now">
          <NowBoard
            live
            liveCalls={liveCalls}
            telemetry={cleanSamples[cleanSamples.length - 1] ?? null}
            lastFinishedIso={lastFinishedIso}
          />
        </Card>
      </div>

      <div
        ref={activityRef}
        style={{
          marginTop: "var(--space-4)",
          display: "grid",
          gap: "var(--space-4)",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
        }}
      >
        <Card title="Lab activity" testId="pulse-lab-activity">
          <LabSparkgrid
            iterationTimes={iterationTimes}
            cycleTimes={cycleTimes}
            nowMs={now}
          />
        </Card>
        {/* Hides itself entirely when the ledger has never been written (204)
            or the running binary predates /api/ladder (404) — no error noise. */}
        <LadderMiniFunnel />
      </div>

      {/* ── 3 · secondary, dense ────────────────────────────────────────── */}
      <div
        data-density="dense"
        data-testid="pulse-secondary"
        style={{
          marginTop: "var(--space-6)",
          paddingTop: "var(--space-4)",
          borderTop: "1px solid var(--border-1)",
          display: "flex",
          flexDirection: "column",
          gap: "var(--space-4)",
        }}
      >
        {cyclesLoaded ? (
          <LastCycleLine initial={cycles} />
        ) : cyclesFailed ? (
          <div
            data-testid="pulse-cycles-unavailable"
            style={{ fontSize: "var(--text-meta)", color: "var(--status-warn)" }}
          >
            /api/coordinator/cycles unreachable — the loop's last cycle is
            UNKNOWN, not absent.
          </div>
        ) : null}

        <HealthStrip samples={cleanSamples} />

        <div
          style={{
            display: "grid",
            gap: "var(--space-4)",
            gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          }}
        >
          <ModelServerCard
            title={servedModels?.gemma?.model ?? "unknown"}
            servedModel={servedModels?.gemma?.model ?? VLLM_SERVED_MODEL}
            pick={(s) => s.vllm}
            samples={cleanSamples}
            liveCalls={liveCalls}
            accent="zinc"
            workloadHint
          />
          <ModelServerCard
            title={servedModels?.qwen?.model ?? "unknown"}
            servedModel={servedModels?.qwen?.model ?? QWEN_SERVED_MODEL}
            pick={(s) => s.vllm_qwen}
            samples={cleanSamples}
            liveCalls={liveCalls}
            accent="sky"
            transientDropBanner
          />
        </div>

        {/* Launching an iteration is deliberate, not ambient — disclosed.
            Controlled so the ⌘K "launch an iteration" verb can open it. */}
        <details
          ref={launchRef}
          open={launchOpen}
          onToggle={(e) => setLaunchOpen((e.target as HTMLDetailsElement).open)}
          data-testid="pulse-launch-disclosure"
        >
          <summary
            style={{
              cursor: "pointer",
              listStyle: "none",
              fontSize: "var(--text-meta)",
              color: "var(--fg-muted)",
            }}
          >
            {launchOpen ? "▾" : "▸"} launch an iteration
          </summary>
          <div style={{ marginTop: "var(--space-2)" }}>
            <NaraPromptForm />
          </div>
        </details>
      </div>
    </div>
  );
}
