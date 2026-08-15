// Pulse (/) — "is the apparatus healthy, and do I owe anything?" (UI
// simplification S1, docs/ui_simplification_plan_2026-08-15.md §Pulse). The
// home page after the 2026-08 inversion: selection-before-the-human means
// the front door answers exactly two questions, in order —
//
//   1. HealthVerdict hero (lifted VERBATIM from the old Dashboard, incl. the
//      excludeQwenReadErrors / cleanSamples / gemmaUp-debounce guards) +
//      NowBoard as the ONE merged now-card (D-047 registry runs + the
//      RUNNING/BUSY/IDLE headline strip; the retired activeIteration/
//      coordinatorActive mirror endpoints are NOT polled here).
//   2. OweStrip (gate verdicts + L4+-bar findings ONLY, rows into the
//      dossier reader) + LastCycleLine (the loop's latest cycle one-liner).
//
// Below the fold: HealthStrip + the two ModelServerCards, and NaraPromptForm
// behind a disclosure (launching an iteration is deliberate, not ambient).
// This page owns the WS telemetry stream; LoopAlertBanner is global (App).
import { useEffect, useState } from "react";
import HealthStrip from "../components/HealthStrip";
import HealthVerdict, {
  excludeQwenReadErrors,
} from "../components/HealthVerdict";
import LastCycleLine from "../components/LastCycleLine";
import ModelServerCard, {
  QWEN_SERVED_MODEL,
  VLLM_SERVED_MODEL,
} from "../components/ModelServerCard";
import NaraPromptForm from "../components/NaraPromptForm";
import NowBoard from "../components/NowBoard";
import OweStrip from "../components/OweStrip";
import { getActivityMonitor } from "../api/activity";
import { getHealth } from "../api/http";
import { useTelemetryStream } from "../hooks/useTelemetryStream";
import { useNow } from "../time";
import type { LiveCalls } from "../types/activity";
import type { Health, TelemetrySample } from "../types/schemas";

export default function Pulse() {
  const { samples, latest, connected } = useTelemetryStream();
  const [health, setHealth] = useState<Health | null>(null);
  // The live wrapper-call aggregate — feeds the NowBoard headline strip and
  // both ModelServerCards' "driving" sub-lines. limit=1 keeps the monitor
  // payload cheap (only its live_calls block is read). Fails quiet.
  const [liveCalls, setLiveCalls] = useState<LiveCalls | null>(null);
  const now = useNow();

  useEffect(() => {
    const loadHealth = () => getHealth().then(setHealth).catch(() => {});
    loadHealth();
    const id = setInterval(loadHealth, 10000);
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

  return (
    <div className="mx-auto max-w-7xl p-5" data-testid="pulse-page">
      {/* Thin identity line. */}
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
        <span className="font-mono text-zinc-200">
          {health?.hostname ?? "spark"}
        </span>
        <span className="text-zinc-500">backend {health?.version ?? "?"}</span>
      </div>

      {/* 1 — healthy? */}
      <div className="mt-3">
        <HealthVerdict
          connected={connected}
          hasTelemetry={cleanSamples.length > 0}
          ageMs={ageMs}
          readErrors={readErrors}
          gemmaUp={gemmaUp}
        />
      </div>

      {/* The ONE now-card: registry runs + RUNNING/BUSY/IDLE strip. */}
      <div className="mt-3">
        <NowBoard
          live
          liveCalls={liveCalls}
          telemetry={cleanSamples[cleanSamples.length - 1] ?? null}
        />
      </div>

      {/* 2 — do I owe anything? */}
      <div className="mt-4">
        <OweStrip />
      </div>
      <div className="mt-3">
        <LastCycleLine />
      </div>

      {/* Below the fold: host/GPU strip + the two model servers. */}
      <div className="mt-4">
        <HealthStrip samples={cleanSamples} />
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ModelServerCard
          title="gemma-4-26b-a4b"
          servedModel={VLLM_SERVED_MODEL}
          pick={(s) => s.vllm}
          samples={cleanSamples}
          liveCalls={liveCalls}
          accent="zinc"
          workloadHint
        />
        <ModelServerCard
          title="Qwen3.6-27B · NVFP4-MTP"
          servedModel={QWEN_SERVED_MODEL}
          pick={(s) => s.vllm_qwen}
          samples={cleanSamples}
          liveCalls={liveCalls}
          accent="sky"
          transientDropBanner
        />
      </div>

      {/* Launching an iteration is deliberate, not ambient — disclosed. */}
      <details className="mt-4 group" data-testid="pulse-launch-disclosure">
        <summary className="cursor-pointer list-none text-xs font-medium uppercase tracking-wide text-zinc-500 hover:text-zinc-300">
          <span className="group-open:hidden">▸ launch an iteration</span>
          <span className="hidden group-open:inline">▾ launch an iteration</span>
        </summary>
        <div className="mt-2">
          <NaraPromptForm />
        </div>
      </details>
    </div>
  );
}
