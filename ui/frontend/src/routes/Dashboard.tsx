// Live dashboard. The page is health-first: a composed HealthVerdict hero
// at the top synthesizes connection / telemetry-staleness / read_errors /
// Gemma reachability, then the health row (HealthStrip + both model-server
// panels). The LOOP_V0 workflow sits below as a high-level glance — a
// compact active-iteration line, a launcher, and a collapsible resolved
// list whose journal opens on selection. Deep data lives on /experiments
// and the /chain inspector, not here. BaselineCard + ProcessGrid are
// low-priority sanity checks behind a "reference" disclosure.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import ActiveIterationPanel from "../components/ActiveIterationPanel";
import BaselineCard from "../components/BaselineCard";
import BubblesPanel from "../components/BubblesPanel";
import HealthSignalsPanel from "../components/HealthSignalsPanel";
import HealthStrip from "../components/HealthStrip";
import HealthVerdict, {
  excludeQwenReadErrors,
} from "../components/HealthVerdict";
import JournalScroll from "../components/JournalScroll";
import NaraPromptForm from "../components/NaraPromptForm";
import ProcessGrid from "../components/ProcessGrid";
import QwenPanel from "../components/QwenPanel";
import RedFlagsTrendStrip from "../components/RedFlagsTrendStrip";
import ResolvedIterationsList from "../components/ResolvedIterationsList";
import SurfacedFindingsPanel from "../components/SurfacedFindingsPanel";
import SystemActivityHero from "../components/SystemActivityHero";
import VllmPanel from "../components/VllmPanel";
import { getActivityMonitor } from "../api/activity";
import {
  getActiveIteration,
  getCoordinatorActive,
  getHealth,
  getHumanTodo,
  getIterations,
} from "../api/http";
import { useTelemetryStream } from "../hooks/useTelemetryStream";
import { useNow } from "../time";
import type { LiveCalls } from "../types/activity";
import type {
  ActiveIteration,
  CoordinatorActiveRun,
  Health,
  IterationRecord,
  TelemetrySample,
} from "../types/schemas";

export default function Dashboard() {
  const { samples, latest, connected } = useTelemetryStream();
  const [health, setHealth] = useState<Health | null>(null);
  const [selectedIteration, setSelectedIteration] = useState<string | null>(
    null,
  );
  // Iterations are lifted here only to feed the standing red-flags strip (the
  // novel-rate / suspected-false-novel / off-domain self-checks). The resolved
  // list below still owns its own poll/pagination.
  const [iterations, setIterations] = useState<IterationRecord[]>([]);
  // SystemActivityHero feeds — "what is the machine doing RIGHT NOW"
  // (reconciliation plan B1). live_calls rides the same activity-monitor
  // endpoint the /activity page polls; the two registered-run mirrors
  // (active iteration + coordinator active_run) resolve null on 204. Their
  // absence while calls flow IS the signal: the hero renders the amber
  // busy-but-unregistered state instead of a false "idle".
  const [liveCalls, setLiveCalls] = useState<LiveCalls | null>(null);
  const [activeIteration, setActiveIteration] =
    useState<ActiveIteration | null>(null);
  const [coordinatorActive, setCoordinatorActive] =
    useState<CoordinatorActiveRun | null>(null);
  // PART 1 coupling (2026-06-14 work order): the dashboard's at-a-glance
  // escalation signal that replaces the removed HumanTodoPanel mount. N is the
  // REAL-decision count = taxonomy A (gate_verdict) + B (state_gate) ONLY —
  // bubble_ack/stale_active_run (taxonomy C, read-receipt/ops-autopsy) and
  // finding_review are deliberately EXCLUDED (they are not blocking decisions).
  // Keyed on the backend's emitted kind strings via the counts map, so the
  // stale `state_file_gate`/`bubble_unacked` names in the TS union don't matter.
  const [needsYouCount, setNeedsYouCount] = useState<number | null>(null);
  const now = useNow();

  useEffect(() => {
    const loadHealth = () => getHealth().then(setHealth).catch(() => {});
    loadHealth();
    const id = setInterval(loadHealth, 10000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const loadIterations = () =>
      getIterations()
        // The iterations payload is producer-owned (loop_memory.jsonl surfaced
        // live): a legacy/empty/mid-rotation backend can hand back a body with
        // no `iterations` key, `iterations: null`, or even a null body. Coerce
        // to [] so a malformed response never flows a non-array into
        // RedFlagsTrendStrip's `.length`/`.filter` and blanks the page.
        // Array.isArray guards null, undefined, and any non-array shape at once.
        .then((r) =>
          setIterations(Array.isArray(r?.iterations) ? r.iterations : []),
        )
        .catch(() => {});
    loadIterations();
    const id = setInterval(loadIterations, 10000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    // One modest poll for the hero's three feeds. Each fetch fails quietly
    // and independently (the getHealth idiom): a dead activity endpoint must
    // not blank the registered-run mirrors, and vice versa. limit=1 keeps the
    // monitor payload cheap — the hero only reads its `live_calls` block.
    const load = () => {
      getActivityMonitor(1)
        .then((r) => setLiveCalls(r?.live_calls ?? null))
        .catch(() => {});
      getActiveIteration()
        .then(setActiveIteration)
        .catch(() => {});
      getCoordinatorActive()
        .then(setCoordinatorActive)
        .catch(() => {});
    };
    load();
    const id = setInterval(load, 7000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    // The "N need you →" coupling source. counts is producer-owned
    // (Record<string, number>); a malformed/legacy body could omit it or hand
    // back a non-number — coerce each kind independently to 0 so one bad field
    // can't NaN the badge. A failed fetch leaves the last good count (the
    // getHealth idiom): the escalation signal must not blink to "none" on a
    // transient miss.
    //
    // A "pending human decision" count is a small non-negative integer. The
    // producer could still hand back a negative (sign-flip/underflow bug), a
    // fractional value, or an absurdly-huge number; clamp each kind into
    // [0, CAP] as an integer so the badge degrades to a sane "N" instead of
    // "-5 need you →", "2.7", or a "1e+308" scientific-notation string (the
    // JSX coerces the count with a template literal, which prints huge numbers
    // in exponent form). CAP is far above any real escalation backlog, so
    // valid counts pass through unchanged; an absurd value simply pegs at CAP.
    const CAP = 9999;
    const num = (v: unknown): number =>
      typeof v === "number" && Number.isFinite(v)
        ? Math.min(CAP, Math.max(0, Math.floor(v)))
        : 0;
    const load = () =>
      getHumanTodo()
        .then((r) => {
          // counts may itself be absent/null or a non-object (string/number/
          // array) on a malformed body. Property access on a non-object
          // primitive yields undefined (not a throw), and num() coerces that
          // to 0, so guarding null/undefined to {} is sufficient.
          const counts = (r?.counts ?? {}) as Record<string, unknown>;
          setNeedsYouCount(num(counts.gate_verdict) + num(counts.state_gate));
        })
        .catch(() => {});
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  // The telemetry buffer is forwarded raw off the WS (`msg.line as
  // TelemetrySample`, no runtime validation in useTelemetryStream), so a
  // malformed/legacy frame can drop a `null` (or any non-object) into the
  // array. That bad element white-screens the page the moment any consumer
  // dereferences it — Dashboard's own gemmaUp `.some((s) => s.vllm)` throws
  // "Cannot read properties of null", and so would every child panel
  // (HealthStrip/Vllm/Qwen/ProcessGrid all index `s.gpu`/`s.vllm`). Skip the
  // bad rows once here (the backend's own "drop malformed rows" philosophy)
  // and feed the cleaned array to the verdict math AND every panel below, so
  // one garbage frame degrades to a missing scrape instead of a crashed page.
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
  // read_errors is sampler-owned and forwarded raw off the WS (the hook does
  // not validate `msg.line`), so a legacy/garbage frame can hand back a
  // non-object truthy value — a string ("thermal failed"), a number, or an
  // array. A bare `? Object.keys(...)` would then mine that value for index
  // keys ("0","1",…) and paint a FALSE degraded with numeric "read errors".
  // Only treat a plain object as a real error map; any other shape is "no
  // legible read errors", not a fault.
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

  return (
    <div className="mx-auto max-w-7xl p-5">
      {/* Thin identity header. The health signals it used to carry inline
          are now composed into the HealthVerdict hero below. */}
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
        <span className="font-mono text-zinc-200">
          {health?.hostname ?? "spark"}
        </span>
        <span className="text-zinc-500">backend {health?.version ?? "?"}</span>
      </div>

      {/* HumanTodoPanel was REMOVED from the dashboard here (2026-06-14 work
          order PART 1). It now lives ONLY on the /todo cockpit route. This is
          safe BECAUSE of the SystemActivityHero "N need you →" coupling below:
          the pending A+B escalation count is the dashboard's at-a-glance signal,
          so nothing blocked on the human sits silently off-screen. Do NOT
          re-add the panel without that coupling in place. */}

      {/* HERO: composed health verdict. */}
      <div className="mt-3">
        <HealthVerdict
          connected={connected}
          hasTelemetry={cleanSamples.length > 0}
          ageMs={ageMs}
          readErrors={readErrors}
          gemmaUp={gemmaUp}
        />
      </div>

      {/* ACTIVITY HERO: what the machine is doing RIGHT NOW. Health says
          "is anything broken"; this says "is anything RUNNING" — composed
          from live wrapper calls, GPU/vllm load, and the registered-run
          mirrors, so GPU-at-96% can never coexist with "idle". */}
      <div className="mt-3">
        <SystemActivityHero
          liveCalls={liveCalls}
          telemetry={cleanSamples[cleanSamples.length - 1] ?? null}
          activeIteration={activeIteration}
          coordinatorActive={coordinatorActive}
          needsYou={
            needsYouCount != null ? (
              <Link
                to="/todo"
                data-testid="dashboard-needs-you"
                className={`rounded px-2 py-0.5 text-xs font-medium ${
                  needsYouCount > 0
                    ? "bg-amber-950 text-amber-300 hover:bg-amber-900"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {needsYouCount > 0
                  ? `${needsYouCount} need you →`
                  : "none need you →"}
              </Link>
            ) : undefined
          }
        />
        <div className="mt-1 text-right">
          <Link
            to="/activity"
            className="text-[11px] text-zinc-600 hover:text-zinc-300"
          >
            drill into activity →
          </Link>
        </div>
      </div>

      {/* Health row: host/GPU strip + both model-server panels side-by-side.
          Gemma (primary orchestrator) first, Qwen (staged sub-agent) second.
          Stacked on narrow screens. */}
      <div className="mt-4">
        <HealthStrip samples={cleanSamples} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <VllmPanel samples={cleanSamples} liveCalls={liveCalls} />
        <QwenPanel samples={cleanSamples} liveCalls={liveCalls} />
      </div>

      {/* LOOP_V0 high-level glance: compact active line + launcher. */}
      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1fr]">
        <ActiveIterationPanel compact />
        <NaraPromptForm />
      </div>

      {/* AUTONOMY block — the coordinator loop's standing self-checks +
          its two "raise to the human" channels. Kept below the health-first
          hero/panels: the red-flags strip answers "is the loop surfacing
          things genuinely new?" at a glance; Surfaced Findings + Bubbles are
          the loop's promoted output and its escalations. */}
      <section className="mt-6 space-y-4" data-testid="autonomy-block">
        <div className="flex items-baseline gap-3">
          <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
            Autonomy
          </h2>
          <Link
            to="/coordinator"
            className="text-[11px] text-zinc-600 hover:text-zinc-300"
          >
            drill into coordinator →
          </Link>
        </div>
        <RedFlagsTrendStrip iterations={iterations} />
        <HealthSignalsPanel />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <SurfacedFindingsPanel />
          <BubblesPanel />
        </div>
      </section>

      {/* Recent iterations — secondary, collapsible. Kept fully functional
          (pagination + filters + Loop-v1 chips); the journal for a selected
          row opens inline only on selection. */}
      <details className="mt-4 group" data-testid="recent-iterations-disclosure" open>
        <summary className="cursor-pointer list-none text-xs font-medium uppercase tracking-wide text-zinc-500 hover:text-zinc-300">
          <span className="group-open:hidden">▸ recent iterations</span>
          <span className="hidden group-open:inline">▾ recent iterations</span>
          {/* T1.6: a Link inside a <summary> both navigates AND toggles the
              disclosure — stop the click from reaching the summary so the
              link only navigates. */}
          <Link
            to="/activity"
            onClick={(e) => e.stopPropagation()}
            className="ml-3 text-[11px] font-normal normal-case tracking-normal text-zinc-600 hover:text-zinc-300"
          >
            drill into activity →
          </Link>
        </summary>
        <div className="mt-2 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ResolvedIterationsList
            onSelect={setSelectedIteration}
            selectedId={selectedIteration}
          />
          {selectedIteration && (
            <JournalScroll iterationId={selectedIteration} />
          )}
        </div>
      </details>

      {/* Reference: Spark perf baseline + tracked processes (low-priority
          sanity checks). Collapsed by default to keep the page health-first. */}
      <details className="mt-6 group" data-testid="reference-disclosure">
        <summary className="cursor-pointer list-none text-xs font-medium uppercase tracking-wide text-zinc-500 hover:text-zinc-300">
          <span className="group-open:hidden">▸ reference — baseline & processes</span>
          <span className="hidden group-open:inline">▾ reference — baseline & processes</span>
        </summary>
        <div className="mt-2">
          <BaselineCard />
        </div>
        <div className="mt-4">
          <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
            Tracked processes
          </h2>
          <ProcessGrid samples={cleanSamples} />
        </div>
      </details>
    </div>
  );
}
