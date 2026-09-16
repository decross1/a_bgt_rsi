// Pulse (/) — the designed dashboard (revamp R3, on the R0 token system).
//
// The page is THREE ZONES, read top-down in the F-pattern, with deliberately
// UNEQUAL emphasis (the R3 brief's anti-pattern list: no KPI-tile carpet, no
// uniform emphasis, no fake activity):
//
//   0. Identity bar — hostname · backend sha · the HealthVerdict, now a
//      compact status LINE rather than a panel. System health is a
//      precondition, not the headline.
//   1. HERO — OweCard: what the human actually owes (gate verdicts + L4/L5
//      findings). Biggest type, highest contrast, first thing read. Everything
//      below the ladder bar renders inside it as ONE muted line, never a row.
//   1b. LabTodo — the LAB's queue (what Nara and the PI advance on their own),
//      directly under the hero and deliberately quieter. The two queues are
//      adjacent so the ownership line is obvious, and the panel points back up
//      at the hero rather than restating the human's work.
//   2. The loop's state — "Running now" (the D-047 registry as Vercel-style
//      deployment cards), then the lab-activity sparkgrid + the L0->L5 ladder
//      mini-funnel side by side.
//   3. Secondary, dense — last cycle, host/GPU strip, the dynamic model
//      endpoint catalog, and the launch disclosure. Marked data-density=
//      "dense" so shared rows tighten to 28px without per-component props.
//
// This page owns the WS telemetry stream; LoopAlertBanner is global (App).
// It also owns the ONE /api/coordinator/cycles poll, handing the rows to both
// LastCycleLine and the sparkgrid instead of letting them each poll.
//
// PERF (2026-08-18, owner: "it keeps refreshing"): every poll on this page
// now runs through the pollhub scheduler (src/api/pollhub.ts) — one heartbeat
// timer, per-source cadences, in-flight guards, change detection (an
// unchanged payload re-renders nothing), and stale-while-revalidate (a failed
// refetch never blanks rendered data). The page clock dropped from 1 Hz to
// 0.2 Hz (it only feeds staleness math and day-bucket boundaries), heavy
// children are memoized, and the iterations poll asks the backend for
// timestamps only (the full payload measured 3.4 MB per poll).
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
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
import OweCard from "../components/OweCard";
import { ResearchOpsCard } from "../components/ResearchOpsCard";
import ResearchScopeBar from "../components/ResearchScopeBar";
import { getActivityMonitor } from "../api/activity";
import {
  getCoordinatorCycles,
  getHealth,
  getIterations,
  getModelRuntime,
  getResearchOpsStatus,
  getServedModels,
} from "../api/http";
import type { ModelRuntime, ServedModel } from "../api/http";
import { usePolled } from "../api/pollhub";
import { useTelemetryStream } from "../hooks/useTelemetryStream";
import { useNow } from "../time";
import { researchScopedHref, useResearchScope, type ResearchScope } from "../researchScope";
import type { LiveCalls, MonitorResponse } from "../types/activity";
import type {
  CoordinatorCycle,
  Health,
  IterationRecord,
  TelemetrySample,
  VllmSample,
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

// Stable `pick` identities for the model catalog cards — inline arrows would
// re-create per render and defeat the cards' React.memo.
const pickGemma = (s: TelemetrySample) => s.vllm;
const pickQwen = (s: TelemetrySample) => s.vllm_qwen;
const pickNoTelemetry = (_s: TelemetrySample) => null;

const MODEL_ORDER = ["gemma", "qwen", "flash"] as const;
const MIA_VARIANT = {
  spec_id: "mia-925d7be6-c0-s1",
  spec_sha256: "dde4fe1f72cf91de92089a95748cee1f6a8204e351d517aa0ae46d8d27122857",
  repository: "Mia-AiLab/Qwen3.8-Flash-Next-NVFP4",
  revision: "925d7be6c14c6c9442ef83e8f05b5a3c39304f69",
  served_model: "qwen3.8-flash-next-mia",
  image_id: "sha256:da68dd27a8ef1dadd0f380178a51f0a0671dc4235933ea1ae89fdaf66295ec72",
  model_artifact_sha256: "a40ce50173dd3aff54da88503894967e5248bbb927f9e4a91eff5a6a7270c168",
  profile: "C0-MIA-S1",
} as const;
const MIA_PROFILE_CONFIG: Record<string, {
  profile: string; context: number; mtp: number; kvBytes: number;
  imageId?: string;
}> = {
  "mia-925d7be6-mtp1-fullvocab-v1": {
    profile: "MIA-MTP1-FULLVOCAB-32K", context: 32768, mtp: 1,
    kvBytes: 2 * 1024 ** 3,
  },
  "mia-925d7be6-mtp2-fullvocab-v1": {
    profile: "MIA-MTP2-FULLVOCAB-32K", context: 32768, mtp: 2,
    kvBytes: 2 * 1024 ** 3,
  },
  "mia-925d7be6-mtp3-fullvocab-v1": {
    profile: "MIA-MTP3-FULLVOCAB-32K", context: 32768, mtp: 3,
    kvBytes: 2 * 1024 ** 3,
  },
  "mia-925d7be6-ctx69632-bf16kv3g-v1": {
    profile: "MIA-NATIVE69632-BF16KV3G-MTP0", context: 69632,
    mtp: 0, kvBytes: 3 * 1024 ** 3,
  },
  "mia-925d7be6-mtp3-reduced47k-v2opt-v1": {
    profile: "MIA-MTP3-REDUCED47K-V2-FULL4-MODE0-32K",
    context: 32768, mtp: 3, kvBytes: 2 * 1024 ** 3,
    imageId: "sha256:29eab5a29b765eef8b6405bbe0f2d385fc1e7b5e3c7ae18ae70382a68a0a2201",
  },
};

const isExtendedFlashRunId = (value: unknown): value is string =>
  typeof value === "string" && /^qfn-ab-[a-z0-9][a-z0-9._-]{0,63}\.flash$/.test(value);
const isFollowonFlashRunId = (value: unknown): value is string =>
  typeof value === "string" && /^qfn-followon-[a-z0-9][a-z0-9._-]{0,63}\.flash$/.test(value);
const isFollowonResidentRunId = (value: unknown): value is string =>
  typeof value === "string" && /^qfn-followon-[a-z0-9][a-z0-9._-]{0,63}\.resident$/.test(value);
const isLabRunId = (value: unknown): value is string =>
  typeof value === "string" && /^qfn-ab-[a-z0-9][a-z0-9._-]{0,63}\.(resident|flash)$/.test(value);
const isLabFlashRunId = (value: unknown): value is string =>
  typeof value === "string" && /^qfn-ab-[a-z0-9][a-z0-9._-]{0,63}\.flash$/.test(value);
const isStableBenchmarkRunId = (value: unknown): value is string =>
  typeof value === "string" && /^stable-benchmark-[a-z0-9][a-z0-9._-]{0,47}\.resident$/.test(value);
const isBoundedUntrustedRuntimeField = (value: unknown, maximum: number): value is string | null =>
  value === null || typeof value === "string" && value.length <= maximum;
const STABLE_BENCHMARK_PHASES = new Set([
  "preflight",
  "sentinel_created",
  "nara_quiescing",
  "evaluation",
  "restoration",
  "complete",
  "failed",
  "recovery_unknown",
  "supervisor_recovered",
]);
const isMiaProfileRunId = (value: unknown): value is string =>
  typeof value === "string" && /^qfn-mia-(?:mtp[123]|ctx69632|mtp3-red47k)-[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(value);
const positiveInteger = (value: unknown) =>
  typeof value === "number" && Number.isInteger(value) && value > 0;

function isRegisteredMiaVariant(value: ModelRuntime["candidate_variant"],
                                modeSource: ModelRuntime["mode_source"] | undefined): boolean {
  if (!value) return false;
  if (Object.entries(MIA_VARIANT).every(([key, expected]) =>
    value[key as keyof typeof MIA_VARIANT] === expected,
  )) return true;
  // Profile variants are selected only by the newer exact-state backend
  // reader. These shared checkpoint/image fields do not establish a passed
  // qualification; they keep the viewport from labeling Mia as NVIDIA.
  const profileConfig = MIA_PROFILE_CONFIG[value.spec_id];
  return modeSource != null && ["qualification_state", "followon_evaluation_state", "lab_evaluation_state"].includes(modeSource) &&
    profileConfig !== undefined &&
    value.repository === MIA_VARIANT.repository &&
    value.revision === MIA_VARIANT.revision &&
    value.served_model === MIA_VARIANT.served_model &&
    value.image_id === (profileConfig.imageId ?? MIA_VARIANT.image_id) &&
    value.model_artifact_sha256 === MIA_VARIANT.model_artifact_sha256 &&
    value.profile === profileConfig.profile &&
    value.configured_max_context_tokens === profileConfig.context &&
    value.configured_mtp_speculative_tokens === profileConfig.mtp &&
    value.configured_kv_cache_memory_bytes === profileConfig.kvBytes;
}
const MODEL_PRESENTATION: Record<
  string,
  {
    pick: (sample: TelemetrySample) => VllmSample | null | undefined;
    accent: "zinc" | "sky" | "violet";
    workloadHint: boolean;
    transientDropBanner: boolean;
  }
> = {
  gemma: { pick: pickGemma, accent: "zinc", workloadHint: true, transientDropBanner: false },
  qwen: { pick: pickQwen, accent: "sky", workloadHint: false, transientDropBanner: true },
  flash: { pick: pickNoTelemetry, accent: "violet", workloadHint: false, transientDropBanner: true },
};

function isModelRuntime(value: unknown): value is ModelRuntime {
  if (value == null || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  const variant = row.candidate_variant;
  const variantValid = variant === undefined || variant === null || (
    typeof variant === "object" && !Array.isArray(variant) &&
    (() => {
      const source = variant as Record<string, unknown>;
      return ["spec_id", "repository", "revision", "served_model", "profile"].every(
        key => typeof source[key] === "string" && (source[key] as string).length > 0,
      ) && ["spec_sha256", "model_artifact_sha256"].every(
        key => typeof source[key] === "string" && /^[0-9a-f]{64}$/.test(source[key] as string),
      ) && typeof source.image_id === "string" && /^sha256:[0-9a-f]{64}$/.test(source.image_id) &&
        (source.configured_max_context_tokens === undefined || positiveInteger(source.configured_max_context_tokens)) &&
        (source.configured_mtp_speculative_tokens === undefined ||
          typeof source.configured_mtp_speculative_tokens === "number" &&
          Number.isInteger(source.configured_mtp_speculative_tokens) &&
          source.configured_mtp_speculative_tokens >= 0 &&
          source.configured_mtp_speculative_tokens <= 3) &&
        (source.configured_kv_cache_memory_bytes === undefined || positiveInteger(source.configured_kv_cache_memory_bytes)) &&
        source.source === "registered_plan_and_controller_state" &&
        ["registered_source_only", "bound_live_container"].includes(String(source.image_evidence)) &&
        source.promotion_authorized === false;
    })()
  );
  return (
    row.schema_version === "model-runtime/v1" &&
    typeof row.observed_at === "string" &&
    ["resident", "candidate_research", "transitioning", "unknown"].includes(
      String(row.mode),
    ) &&
    ["qualification_state", "extended_evaluation_state", "followon_evaluation_state", "followon_resident_state", "lab_evaluation_state", "stable_benchmark_state", "none"].includes(String(row.mode_source)) &&
    (row.mode_source !== "extended_evaluation_state" || isExtendedFlashRunId(row.run_id)) &&
    (row.mode_source !== "followon_evaluation_state" || isFollowonFlashRunId(row.run_id)) &&
    (row.mode_source !== "followon_resident_state" || isFollowonResidentRunId(row.run_id)) &&
    (row.mode_source !== "lab_evaluation_state" || isLabRunId(row.run_id)) &&
    (row.mode_source !== "stable_benchmark_state" || row.candidate_variant === null && (
      isStableBenchmarkRunId(row.run_id) &&
        STABLE_BENCHMARK_PHASES.has(String(row.phase)) &&
        row.mode === "resident" &&
        row.resident_services_expected === "online" ||
      row.mode === "unknown" &&
        row.resident_services_expected === "unknown" &&
        row.nara_service_expected === "unknown" &&
        row.mode_source_sha256 === null &&
        typeof row.source_error === "string" && row.source_error.length > 0 &&
        isBoundedUntrustedRuntimeField(row.run_id, 96) &&
        isBoundedUntrustedRuntimeField(row.phase, 64)
    )) &&
    ["online", "stopped", "unknown"].includes(
      String(row.resident_services_expected),
    ) &&
    ["running", "paused", "unknown"].includes(String(row.nara_service_expected)) &&
    (row.mode_source_sha256 === null || typeof row.mode_source_sha256 === "string") &&
    (row.run_id === null || typeof row.run_id === "string") &&
    (row.phase === null || typeof row.phase === "string") &&
    (row.source_error === null || typeof row.source_error === "string") &&
    variantValid
  );
}

function orderedModelCatalog(value: unknown): Array<[string, ServedModel]> {
  if (value == null || typeof value !== "object" || Array.isArray(value)) return [];
  const source = value as Record<string, unknown>;
  const keys = [
    ...MODEL_ORDER.filter((key) => key in source),
    ...Object.keys(source)
      .filter((key) => !MODEL_ORDER.includes(key as (typeof MODEL_ORDER)[number]))
      .sort(),
  ];
  return keys.flatMap((key) => {
    const row = source[key];
    if (row == null || typeof row !== "object" || Array.isArray(row)) return [];
    return [[key, row as ServedModel]];
  });
}

function isInventoryModel(row: ServedModel): boolean {
  return (
    typeof row.url === "string" &&
    (row.model === null || typeof row.model === "string") &&
    typeof row.probed_at === "string" &&
    Number.isFinite(Date.parse(row.probed_at)) &&
    typeof row.configured_model === "string" &&
    row.configured_model.length > 0 &&
    positiveInteger(row.configured_max_context_tokens) &&
    (row.observed_max_context_tokens == null || positiveInteger(row.observed_max_context_tokens)) &&
    ["production_resident", "research_candidate"].includes(String(row.deployment_role)) &&
    ["resident", "flash"].includes(String(row.benchmark_cohort)) &&
    row.promotion_authorized === false &&
    ["available", "unreachable", "invalid_response"].includes(String(row.models_endpoint_status)) &&
    ["online", "offline", "unknown"].includes(String(row.service_status)) &&
    ["match", "mismatch", "unknown"].includes(String(row.identity_status)) &&
    ["available", "unreachable", "invalid_response"].includes(String(row.metrics_endpoint_status)) &&
    ["busy", "idle", "unknown"].includes(String(row.activity_status))
  );
}

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
      className={`rounded border ${
        accent === "sky" ? "border-sky-900/60" : "border-zinc-800"
      } bg-zinc-900/40 p-4`}
    >
      <div className="flex items-baseline gap-2">
        <h2
          className={`text-xs font-medium uppercase tracking-wide ${
            accent === "sky" ? "text-sky-400" : "text-[var(--fg-muted)]"
          }`}
        >
          {title}
        </h2>
        <span
          className="ml-auto font-mono text-[11px] text-[var(--fg-muted)]"
          data-testid={`${servedModel}-status`}
        >
          {historical ? "● historical" : "● unknown"}
        </span>
      </div>
      <p className="mt-3 text-sm text-[var(--fg-muted)]">{explanation}</p>
    </div>
  );
}

// The iterations poll feeds ONLY the sparkgrid + the idle "last finished"
// clause, so ask the backend for the timestamp column, not the full record
// (the full payload measured 3.4 MB / 2.9 s per poll on 2026-08-18; an older
// backend binary ignores the params and still answers with the full rows).
const fetchIterationTimes = (scope: ResearchScope) =>
  getIterations({ fields: "iteration_id,ended_at", limit: 1000 }, scope);

// CHURN-STRIP (adversarial-review residual fix 2, 2026-08-18):
// /api/activity/monitor stamps a fresh top-level `generated_at` on EVERY
// response, so an otherwise-idle monitor payload always read as "changed"
// to the hub's JSON change detection — NowBoard and the model catalog cards
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

import DevelopmentNotice from "../components/DevelopmentNotice";

export default function Pulse() {
  const researchScope = useResearchScope();
  const { samples, connected } = useTelemetryStream();
  const [launchOpen, setLaunchOpen] = useState(false);
  const [requestsOpen, setRequestsOpen] = useState(false);
  const [queueRequested, setQueueRequested] = useState(false);
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
  const servedModelsPoll = usePolled("served_models", getServedModels, {
    intervalMs: 30000,
  });
  const servedModels = servedModelsPoll.data ?? null;
  const runtimePoll = usePolled("model_runtime", getModelRuntime, {
    intervalMs: 5000,
    initialDelayMs: 50,
  });
  const modelRuntime = isModelRuntime(runtimePoll.data) ? runtimePoll.data : null;
  const researchOpsPoll = usePolled("research_ops_status", getResearchOpsStatus, {
    intervalMs: 60000,
    initialDelayMs: 350,
  });
  const modelCatalog = useMemo(
    () => orderedModelCatalog(servedModels),
    [servedModels],
  );
  // The live wrapper-call aggregate — feeds the NowBoard headline strip and
  // each ModelServerCard's "driving" sub-line. limit=1 keeps the monitor
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
  const cyclesPoll = usePolled(`cycles:${researchScope}`, getCoordinatorCycles, {
    intervalMs: 60000,
    initialDelayMs: 200,
    enabled: researchScope === "all",
  });
  const iterationsPoll = usePolled(
    `iterations:${researchScope}`,
    () => fetchIterationTimes(researchScope),
    {
    intervalMs: 60000,
    initialDelayMs: 300,
    },
  );
  const cycles: CoordinatorCycle[] | null = useMemo(
    () =>
      researchScope !== "all"
        ? []
        : cyclesPoll.data === undefined
        ? null
        : Array.isArray(cyclesPoll.data?.cycles)
          ? cyclesPoll.data.cycles
          : [],
    [cyclesPoll.data, researchScope],
  );
  const cyclesLoaded = cycles !== null;
  // Pulse took over LastCycleLine's poll, so it also inherits its duty to be
  // honest about a FAILED read: an unreachable cycles endpoint must say so,
  // not render an empty slot that reads as "the loop has done nothing".
  // (With SWR, "failed" only blanks the line when NO payload ever landed;
  // once data exists a failing refetch keeps showing it.)
  const cyclesFailed = researchScope === "all" && cyclesPoll.failing && !cyclesLoaded;
  const iterations: IterationRecord[] = useMemo(
    () =>
      Array.isArray(iterationsPoll.data?.iterations)
        ? iterationsPoll.data.iterations
        : [],
    [iterationsPoll.data],
  );

  const heroRef = useRef<HTMLDivElement>(null);
  const labQueueRef = useRef<HTMLDivElement>(null);
  const activityRef = useRef<HTMLDivElement>(null);
  const launchRef = useRef<HTMLDetailsElement>(null);

  // Arriving from /ladder's "lab queue →" link (`/#lab-queue`): React Router
  // does not scroll for a hash, so bring the zone into view once.
  useEffect(() => {
    if (hash === "#what-you-owe") {
      setRequestsOpen(true);
      heroRef.current?.scrollIntoView?.({ block: "start" });
    }
    if (hash === "#lab-queue") labQueueRef.current?.scrollIntoView?.({ block: "start" });
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
  const runtimeObservedMs = modelRuntime ? Date.parse(modelRuntime.observed_at) : Number.NaN;
  // A runtime response can arrive after the last 5 s UI clock tick. Read the
  // current time at this render so a fresh bound receipt is not misclassified
  // as future-dated until the next tick; the tick still refreshes stale UI.
  const runtimeAgeMs = Number.isFinite(runtimeObservedMs) ? Date.now() - runtimeObservedMs : Number.NaN;
  const boundRuntimeMode =
    (modelRuntime?.mode_source === "qualification_state" ||
      (modelRuntime?.mode_source === "extended_evaluation_state" && isExtendedFlashRunId(modelRuntime.run_id)) ||
      (modelRuntime?.mode_source === "followon_evaluation_state" && isFollowonFlashRunId(modelRuntime.run_id)) ||
      (modelRuntime?.mode_source === "followon_resident_state" && isFollowonResidentRunId(modelRuntime.run_id)) ||
      (modelRuntime?.mode_source === "lab_evaluation_state" && isLabRunId(modelRuntime.run_id)) ||
      (modelRuntime?.mode_source === "stable_benchmark_state" && isStableBenchmarkRunId(modelRuntime.run_id) && STABLE_BENCHMARK_PHASES.has(modelRuntime.phase ?? ""))) &&
    typeof modelRuntime.mode_source_sha256 === "string" &&
    /^[0-9a-f]{64}$/.test(modelRuntime.mode_source_sha256) &&
    typeof modelRuntime.run_id === "string" &&
    modelRuntime.run_id.length > 0 &&
    typeof modelRuntime.phase === "string" &&
    modelRuntime.phase.length > 0 &&
    modelRuntime.source_error === null &&
    Number.isFinite(runtimeAgeMs) &&
    runtimeAgeMs >= 0 &&
    runtimeAgeMs <= 20_000 &&
    !runtimePoll.failing;
  const candidateResearchWindow =
    modelRuntime?.mode === "candidate_research" &&
    boundRuntimeMode &&
    modelRuntime.resident_services_expected === "stopped";
  const residentResearchWindow =
    (modelRuntime?.mode_source === "followon_resident_state" ||
      (modelRuntime?.mode_source === "lab_evaluation_state" && modelRuntime.run_id?.endsWith(".resident"))) &&
    modelRuntime.mode === "resident" && boundRuntimeMode &&
    modelRuntime.phase === "evaluation" &&
    modelRuntime.resident_services_expected === "online" &&
    modelRuntime.nara_service_expected === "paused";
  const stableBenchmarkRuntime =
    modelRuntime?.mode_source === "stable_benchmark_state" &&
    modelRuntime.mode === "resident" &&
    boundRuntimeMode &&
    modelRuntime.resident_services_expected === "online" &&
    modelRuntime.candidate_variant === null;
  const stableBenchmarkUnverified =
    modelRuntime?.mode_source === "stable_benchmark_state" &&
    modelRuntime.mode === "unknown" &&
    modelRuntime.mode_source_sha256 === null &&
    modelRuntime.resident_services_expected === "unknown" &&
    modelRuntime.nara_service_expected === "unknown" &&
    modelRuntime.candidate_variant === null &&
    typeof modelRuntime.source_error === "string" &&
    modelRuntime.source_error.length > 0 &&
    Number.isFinite(runtimeAgeMs) &&
    runtimeAgeMs >= 0 &&
    runtimeAgeMs <= 20_000 &&
    !runtimePoll.failing;
  const stableBenchmarkVisible = stableBenchmarkRuntime || stableBenchmarkUnverified;
  const stableBenchmarkPhase = stableBenchmarkVisible
    ? STABLE_BENCHMARK_PHASES.has(modelRuntime?.phase ?? "") ? modelRuntime?.phase ?? "unverified" : "unverified"
    : null;
  const stableBenchmarkPreparing = stableBenchmarkPhase === "preflight" || stableBenchmarkPhase === "sentinel_created";
  const stableBenchmarkRecovering = stableBenchmarkPhase === "restoration" || stableBenchmarkPhase === "supervisor_recovered";
  const stableBenchmarkProblem = stableBenchmarkUnverified || stableBenchmarkPhase === "failed" || stableBenchmarkPhase === "recovery_unknown";
  const selectedMiaVariant = boundRuntimeMode &&
    isRegisteredMiaVariant(modelRuntime?.candidate_variant, modelRuntime?.mode_source) &&
    (modelRuntime?.run_id?.startsWith("qfn-mia-c0-") ||
      isMiaProfileRunId(modelRuntime?.run_id) ||
      (modelRuntime?.mode_source === "extended_evaluation_state" && isExtendedFlashRunId(modelRuntime.run_id)) ||
      (modelRuntime?.mode_source === "followon_evaluation_state" && isFollowonFlashRunId(modelRuntime.run_id)) ||
      (modelRuntime?.mode_source === "lab_evaluation_state" && isLabFlashRunId(modelRuntime.run_id))) &&
    modelRuntime?.mode !== "resident"
      ? modelRuntime?.candidate_variant ?? null
      : null;
  const candidateEndpointStarting =
    candidateResearchWindow &&
    ["candidate_start", "readiness"].includes(modelRuntime.phase ?? "");
  const runtimeTransition =
    modelRuntime?.mode === "transitioning" &&
    boundRuntimeMode;
  const runtimePreparing =
    runtimeTransition &&
    ["preflight", "model_verification", "setup_quiescence", "sentinel_create"].includes(
      modelRuntime.phase ?? "",
    );
  const residentRuntime =
    modelRuntime?.mode === "resident" &&
    boundRuntimeMode &&
    modelRuntime.resident_services_expected === "online";
  const inventoryCatalog = modelCatalog.filter(([, row]) => isInventoryModel(row));
  const inventoryContractReady =
    MODEL_ORDER.every((key) =>
      inventoryCatalog.some(([endpointName]) => endpointName === key),
    ) && inventoryCatalog.length === modelCatalog.length;
  const runtimeObservabilityIssues = [
    !connected ? "telemetry disconnected" : null,
    cleanSamples.length === 0 ? "no telemetry received" : null,
    cleanSamples.length > 0 && telemetryTimeUnknown ? "telemetry time unknown" : null,
    cleanSamples.length > 0 && telemetryStale ? "telemetry stale" : null,
    readErrors.length > 0 ? `read errors: ${readErrors.join(", ")}` : null,
  ].filter((value): value is string => value != null);
  const runtimeModeLabel =
    stableBenchmarkVisible
      ? stableBenchmarkProblem
        ? "Stable benchmark lifecycle needs review"
        : stableBenchmarkPreparing
          ? "Stable benchmark preparing"
          : stableBenchmarkRecovering
            ? "Stable benchmark restoration"
            : stableBenchmarkPhase === "complete"
              ? "Stable benchmark lifecycle complete"
              : "Stable benchmark resident arm active"
      : residentResearchWindow
      ? modelRuntime?.mode_source === "lab_evaluation_state" ? "Resident model evaluation active" : "Resident research window"
      : residentRuntime
      ? "Resident serving"
      : candidateResearchWindow
        ? modelRuntime?.mode_source === "lab_evaluation_state" ? "Mia model evaluation active" :
          selectedMiaVariant ? "Mia candidate research window" : "Candidate research window"
        : runtimeTransition
          ? runtimePreparing
            ? "Preparing research window"
            : "Runtime transition"
          : "Operating mode unverified";
  const runtimeModeNote =
    stableBenchmarkUnverified
      ? `The stable benchmark projector could not verify the current ${(stableBenchmarkPhase ?? "unknown").replaceAll("_", " ")} lifecycle state. Endpoint observations remain independent.`
      : stableBenchmarkRuntime
      ? `Source-bound stable benchmark phase: ${(stableBenchmarkPhase ?? "unknown").replaceAll("_", " ")}. Resident services are expected online and Nara is expected ${modelRuntime.nara_service_expected}; this lifecycle state does not establish a benchmark score.`
      : residentResearchWindow
      ? "Controller state expects Gemma and Qwen online while Nara is paused for this supervised research arm. Live endpoint and service observations remain separate."
      : residentRuntime
      ? "Controller state expects the production resident services online."
      : candidateResearchWindow
        ? candidateEndpointStarting
          ? `Controller state expects residents stopped while ${selectedMiaVariant ? "the registered Mia variant" : "the research candidate"} endpoint starts. Promotion remains unauthorized.`
          : `Controller state expects residents stopped while ${selectedMiaVariant ? "the registered Mia variant" : "the research candidate"} is evaluated. Promotion remains unauthorized.`
        : runtimeTransition
          ? runtimePreparing
            ? "The controller is verifying prerequisites before model services are changed."
            : "The controller is changing model services; endpoint observations may be temporarily mixed."
          : "No current controller-bound operating-mode receipt is available. Endpoint observations remain independent.";

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

  return (
    <div className="page-full" data-testid="pulse-page">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-widest text-[var(--fg-muted)]">Lab workspace</p>
          <h1 className="text-3xl font-semibold tracking-tight">Now</h1>
          <p className="mt-2 text-sm text-[var(--fg-muted)]">Find the next useful decision. Keep research evidence and runtime activity separate.</p>
        </div>
        <div className="flex flex-wrap gap-3 text-sm">
          <Link to={researchScopedHref("/ladder", researchScope)} className="rounded-md border border-[var(--border-2)] bg-[var(--surface-1)] px-4 py-2 text-[var(--accent)]">Explore research</Link>
          <Link to="/benchmarks" className="rounded-md border border-[var(--border-2)] bg-[var(--surface-1)] px-4 py-2 text-[var(--accent)]">View model evidence</Link>
          <Link to="/development" className="rounded-md border border-[var(--border-2)] bg-[var(--surface-1)] px-4 py-2 text-[var(--accent)]">Review delivery and readiness</Link>
        </div>
      </header>
      <ResearchScopeBar />
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
        <span>backend-reported revision {health?.version ?? "unknown"}</span>
        <span style={{ marginLeft: "auto" }}>
          {stableBenchmarkVisible ? (
            <div
              data-testid="health-verdict"
              data-level={stableBenchmarkProblem ? "unknown" : stableBenchmarkPreparing || stableBenchmarkRecovering ? "transitioning" : "research"}
              className="flex flex-wrap items-center gap-2 text-[var(--fg-muted)]"
            >
              <span className={`font-semibold ${stableBenchmarkProblem ? "text-[var(--status-warn)]" : "text-[var(--accent)]"}`}>
                {stableBenchmarkProblem ? "BENCHMARK NEEDS REVIEW" : stableBenchmarkPreparing ? "BENCHMARK PREPARING" : stableBenchmarkRecovering ? "BENCHMARK RESTORATION" : stableBenchmarkPhase === "complete" ? "BENCHMARK COMPLETE" : "BENCHMARK RUN"}
              </span>
              <span>Phase: {(stableBenchmarkPhase ?? "unknown").replaceAll("_", " ")}.</span>
              {stableBenchmarkUnverified
                ? <span>Runtime expectations are unknown until the lifecycle source verifies again.</span>
                : <span>Resident models are expected online; Nara is expected {modelRuntime?.nara_service_expected}.</span>}
              <Link to="/benchmarks" className="text-[var(--accent)]">View benchmark progress →</Link>
              {runtimeObservabilityIssues.length > 0 && (
                <span className="text-[var(--status-warn)]" data-testid="runtime-observability-warning">
                  Observability: {runtimeObservabilityIssues.join("; ")}.
                </span>
              )}
            </div>
          ) : residentResearchWindow ? (
            <div
              data-testid="health-verdict"
              data-level="research"
              className="flex flex-wrap items-center gap-2 text-[var(--fg-muted)]"
            >
              <span className="font-semibold text-[var(--accent)]">RESEARCH WINDOW</span>
              <span>Resident models are expected online while Nara is paused for this research arm.</span>
              <span>Live model and Nara status remain separately observed.</span>
              {runtimeObservabilityIssues.length > 0 && (
                <span className="text-[var(--status-warn)]" data-testid="runtime-observability-warning">
                  Observability: {runtimeObservabilityIssues.join("; ")}.
                </span>
              )}
            </div>
          ) : candidateResearchWindow ? (
            <div
              data-testid="health-verdict"
              data-level="research"
              className="flex flex-wrap items-center gap-2 text-[var(--fg-muted)]"
            >
              <span className="font-semibold text-[var(--accent)]">RESEARCH WINDOW</span>
              <span>Resident model services are expected to be stopped.</span>
              <span>
                During this phase Nara is expected {modelRuntime.nara_service_expected === "paused" ? "paused" : modelRuntime.nara_service_expected === "running" ? "running" : "in an unknown state"}; live Nara status is not inferred.
              </span>
              {runtimeObservabilityIssues.length > 0 && (
                <span className="text-[var(--status-warn)]" data-testid="runtime-observability-warning">
                  Observability: {runtimeObservabilityIssues.join("; ")}.
                </span>
              )}
            </div>
          ) : runtimeTransition ? (
            <div
              data-testid="health-verdict"
              data-level="transitioning"
              className="flex flex-wrap items-center gap-2 text-[var(--fg-muted)]"
            >
              <span className="font-semibold text-[var(--status-warn)]">
                {runtimePreparing ? "PREPARING" : "TRANSITIONING"}
              </span>
              <span>
                {runtimePreparing
                  ? "Research-window prerequisites are being verified; model services have not been changed in this phase."
                  : "Model runtime transition is recorded; endpoint expectations are not yet settled."}
              </span>
              {runtimeObservabilityIssues.length > 0 && (
                <span className="text-[var(--status-warn)]" data-testid="runtime-observability-warning">
                  Observability: {runtimeObservabilityIssues.join("; ")}.
                </span>
              )}
            </div>
          ) : gemmaUp === null || !connected || telemetryTimeUnknown || telemetryStale ? (
            <div data-testid="health-verdict" data-level="unknown"
              className="flex flex-wrap items-center gap-2 text-[var(--fg-muted)]">
              <span className="font-semibold">UNKNOWN</span>
              <span>{!connected
                ? "Telemetry disconnected"
                : telemetryStale
                  ? "Telemetry stale"
                  : telemetryTimeUnknown
                    ? "Telemetry time unknown"
                    : "Awaiting telemetry"}</span>
              <span>{gemmaUp === null ? "Model health not observed" : gemmaUp
                ? "Last samples: Gemma metrics present"
                : "Last samples: Gemma metrics unavailable"}</span>
              {readErrors.length > 0 && <span>
                {modelEvidenceMode === "current" ? "Read errors" : "Last read errors"}: {readErrors.join(", ")}
              </span>}
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
        </span>
      </div>

      {/* ── 1 · HERO — what you owe ─────────────────────────────────────── */}
      {/* id: LabTodo's blocked-on-you line points back UP at this hero rather
          than restating the same work as a second list. OweCard (2026-08-18)
          keeps OweStrip's pins and adds per-row expand + triage/age chips. */}
      {researchScope === "all" && <DevelopmentNotice />}
      <div id="what-you-owe" ref={heroRef} className="mt-4">
        <details data-testid="pulse-human-requests" open={requestsOpen}
          onToggle={(event) => setRequestsOpen(event.currentTarget.open)}
          className="rounded-lg border border-[var(--border-1)] bg-[var(--surface-1)] p-4">
          <summary className="cursor-pointer text-base font-medium">Recorded human requests</summary>
          <p className="my-3 text-sm text-[var(--fg-muted)]">Review each request and its date before acting. Older requests remain in the record; this view does not clear them.</p>
          <OweCard />
        </details>
      </div>

      <div className="mt-4"><ResearchOpsCard data={researchOpsPoll.data}
        failing={researchOpsPoll.error != null} /></div>

      {/* ── 1b · the LAB's queue — secondary to the hero, by design ─────── */}
      {/* The human's queue is the hero; what Nara and the PI advance on their
          own sits directly under it, quieter. */}
      <div id="lab-queue" ref={labQueueRef} style={{ marginTop: "var(--space-4)" }}>
        {queueRequested ? <LabTodo researchScope={researchScope} /> : <Card testId="pulse-queue-not-read">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="text-base font-medium">Lab queue</h2>
              <p className="mt-1 text-sm text-[var(--fg-muted)]">The queue has not been loaded in this view. Its contents and freshness are unknown.</p>
              <p className="mt-1 text-xs text-[var(--fg-muted)]">Loading may run a topic and embedding assessment. Existing cache behavior is retained.</p>
            </div>
            <button type="button" onClick={() => setQueueRequested(true)}
              className="rounded-md border border-[var(--border-2)] px-4 py-2 text-sm text-[var(--accent)]">Load lab queue</button>
          </div>
        </Card>}
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
        <Card
          title={researchScope === "active" ? "Campaign activity" : "Lab activity · history"}
          testId="pulse-lab-activity"
        >
          <LabSparkgrid
            iterationTimes={iterationTimes}
            cycleTimes={cycleTimes}
            nowMs={now}
            activityScope={researchScope === "active" ? "active_campaign" : "lab_history"}
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
        {researchScope === "all" && cyclesLoaded ? (
          <LastCycleLine initial={cycles} />
        ) : researchScope === "all" && cyclesFailed ? (
          <div
            data-testid="pulse-cycles-unavailable"
            style={{ fontSize: "var(--text-meta)", color: "var(--status-warn)" }}
          >
            /api/coordinator/cycles unreachable — the loop's last cycle is
            UNKNOWN, not absent.
          </div>
        ) : researchScope === "active" ? (
          <p className="text-xs text-[var(--fg-muted)]" data-testid="pulse-cycle-history-boundary">
            Coordinator cycle history is retained in All research history; this view does not mix it into the current campaign.
          </p>
        ) : null}

        <HealthStrip samples={cleanSamples} />

        <section aria-labelledby="model-runtime-heading" data-testid="pulse-model-runtime">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-[11px] font-medium uppercase tracking-widest text-[var(--fg-muted)]">
                Model runtime
              </p>
              <h2 id="model-runtime-heading" className="mt-1 text-lg font-medium">
                {runtimeModeLabel}
              </h2>
              <p className="mt-1 max-w-3xl text-xs text-[var(--fg-muted)]">
                {runtimeModeNote}
              </p>
            </div>
            <div className="flex flex-wrap gap-3 text-xs">
              <Link
                to="/benchmarks"
                className="text-[var(--accent)] transition-colors hover:text-[var(--fg)]"
              >
                Benchmark evidence →
              </Link>
              <Link
                to="/model-io"
                data-testid="pulse-model-io-link"
                className="text-[var(--accent)] transition-colors hover:text-[var(--fg)]"
              >
                Inspect model I/O →
              </Link>
            </div>
          </div>
          {inventoryContractReady && (
            <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-[var(--fg-muted)]">
              <span className="rounded border border-[var(--border-1)] px-2 py-1">
                {inventoryCatalog.length} configured endpoints
              </span>
              <span className="rounded border border-[var(--border-1)] px-2 py-1">
                {inventoryCatalog.filter(([, row]) => row.service_status === "online").length} online
              </span>
              {inventoryCatalog.some(([, row]) => row.service_status === "offline") && (
                <span className="rounded border border-[var(--border-1)] px-2 py-1">
                  {inventoryCatalog.filter(([, row]) => row.service_status === "offline").length} offline
                </span>
              )}
              {inventoryCatalog.some(([, row]) => row.service_status === "unknown") && (
                <span className="rounded border border-[var(--border-1)] px-2 py-1">
                  {inventoryCatalog.filter(([, row]) => row.service_status === "unknown").length} service unknown
                </span>
              )}
              <span className="rounded border border-[var(--border-1)] px-2 py-1">
                {inventoryCatalog.filter(([, row]) => row.activity_status === "busy").length} busy
              </span>
              {inventoryCatalog.some(([, row]) => row.activity_status === "unknown") && (
                <span className="rounded border border-[var(--border-1)] px-2 py-1">
                  {inventoryCatalog.filter(([, row]) => row.activity_status === "unknown").length} activity unknown
                </span>
              )}
            </div>
          )}
          {inventoryContractReady && (
            <p className="mt-2 text-[11px] text-[var(--fg-muted)]">
              Live rates come from each server&apos;s metrics endpoint. Advertised context is capacity, not tested long-context quality; benchmark evidence stays separate.
            </p>
          )}
          {!inventoryContractReady && servedModels != null && (
            <p className="mt-2 text-[11px] text-[var(--status-warn)]" data-testid="model-inventory-legacy">
              Detailed endpoint inventory is unavailable from this backend response. Only legacy resident telemetry is shown.
            </p>
          )}
          {!inventoryContractReady && servedModels == null && servedModelsPoll.failing && (
            <p className="mt-2 text-[11px] text-[var(--status-warn)]" data-testid="model-inventory-unavailable">
              Endpoint inventory is unavailable. Configured and live endpoint states are not inferred.
            </p>
          )}
          <div
            className="mt-3"
            style={{
              display: "grid",
              gap: "var(--space-4)",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))",
            }}
          >
          {inventoryContractReady ? inventoryCatalog.map(([key, row]) => {
            const presentation = MODEL_PRESENTATION[key] ?? MODEL_PRESENTATION.flash;
            const observedName = typeof row.model === "string" && row.model.trim() ? row.model : null;
            const configuredName = typeof row.configured_model === "string" && row.configured_model.trim()
              ? row.configured_model
              : null;
            const identity = observedName ?? configuredName ?? "unknown model";
            const serviceExpectation =
              row.service_status !== "offline"
                ? null
                : row.deployment_role === "production_resident" && candidateResearchWindow
                  ? "expected_offline"
                  : row.deployment_role === "research_candidate" && candidateEndpointStarting
                    ? "starting"
                    : row.deployment_role === "research_candidate" && !candidateResearchWindow
                      ? "standby"
                      : null;
            return <ModelServerCard
              key={key}
              title={identity}
              servedModel={observedName ?? `unobserved-${key}`}
              endpointName={key}
              inventory={row}
              serviceExpectation={serviceExpectation}
              selectedVariant={key === "flash" ? selectedMiaVariant : null}
              pick={presentation.pick}
              samples={cleanSamples}
              liveCalls={liveCalls}
              accent={presentation.accent}
              workloadHint={presentation.workloadHint}
              transientDropBanner={presentation.transientDropBanner}
            />;
          }) : modelEvidenceMode === "current" ? <>
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
          </> : <>
            <ModelEvidenceCard
              title={servedModels?.gemma?.model ?? "unknown"}
              servedModel={servedModels?.gemma?.model ?? VLLM_SERVED_MODEL}
              metricsObserved={cleanSamples.some((sample) => pickGemma(sample) != null)}
              mode={modelEvidenceMode}
            />
            <ModelEvidenceCard
              title={servedModels?.qwen?.model ?? "unknown"}
              servedModel={servedModels?.qwen?.model ?? QWEN_SERVED_MODEL}
              metricsObserved={cleanSamples.some((sample) => pickQwen(sample) != null)}
              mode={modelEvidenceMode}
              accent="sky"
            />
          </>}
          </div>
        </section>

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
