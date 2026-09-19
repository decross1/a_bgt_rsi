// ModelServerCard — the parameterized local-model endpoint panel. It began as
// the shared Gemma/Qwen telemetry card and now also accepts the backend's
// dynamic endpoint inventory, allowing a Flash research candidate (and future
// registered endpoints) to use the same status/stat hierarchy. Configuration,
// /v1/models identity, /metrics activity, and benchmark authority stay
// visibly separate.
//
// Body states (LAST-GOOD RETENTION, adversarial-review residual fix 5,
// 2026-08-18 — the badge + body used to key off the LATEST sample alone, so
// ONE missed /metrics scrape swapped a healthy card to "/metrics
// unavailable" under a hard-red badge):
//   - the latest sample carries the block → data, "● up".
//   - the latest sample lost the block but a sample within the last
//     STALE_MISS_LIMIT scrapes carried it → the body KEEPS the last-good
//     data with an explicit staleness note ("stale telemetry — last sample
//     Xs ago"), and the badge reads amber "● stale": stale telemetry is not
//     a down server, and the badge now says which is which.
//   - STALE_MISS_LIMIT consecutive misses → the body degrades:
//     transientDropBanner=false (Gemma) shows "/metrics unavailable";
//     transientDropBanner=true (Qwen) shows the amber "/metrics dropped"
//     banner. Badge "● down".
//   - NO sample ever carried the block → "unavailable" (binary mode) or
//     "endpoint unreachable" (tri-state; expected while a server is
//     unwired). Badge "● down".
// There is no per-card hard down signal on today's wire (read_errors are
// sampler-reader-keyed and filtered upstream of this card), so consecutive
// misses are the sole degrade trigger.
//
// The "driving" derivation (roles.drivingTags) is EXACT-match on the served
// model name — no substring/heuristic matching, absent when none.
import { memo, type ReactNode } from "react";
import { useNow } from "../time";
import { getWorkloadHint } from "../api/http";
import type { ModelRuntime, ServedModel } from "../api/http";
import { usePolled } from "../api/pollhub";
import { fmt, fmtRatioPct } from "../format";
import { callerTagTone, drivingTags } from "../roles";
import type { LiveCalls } from "../types/activity";
import type { TelemetrySample, VllmSample, WorkloadHint } from "../types/schemas";
import Sparkline from "./Sparkline";

// LAST-RESORT fallbacks only. These are what the servers served on
// 2026-06-10; they are NOT the truth about what is running now. The live name
// comes from GET /api/served_models — on 2026-08-16 these constants had the
// dashboard announcing "Qwen3.6" for an hour while :8001 served 3.8, which is
// why a card title must never be sourced from here.
export const VLLM_SERVED_MODEL = "gemma-4-26b-a4b";
export const QWEN_SERVED_MODEL = "qwen3.6-27b-nvfp4-mtp";

export interface InventoryMetricPoint {
  timestamp: string;
  metrics: VllmSample | null;
}

// How many CONSECUTIVE trailing samples may miss this card's block before
// the body stops showing retained last-good data and degrades to its
// no-data message (residual fix 5; the reviewer's pick of 3). Below the
// limit the miss renders as "stale telemetry", never as an outage.
const STALE_MISS_LIMIT = 3;

// "last sample Xs ago" — self-ticking (30 s) so the note cannot freeze
// under the card's memo between telemetry flushes; the tick re-renders this
// leaf alone, never the rows/sparklines around it.
function SampleAge({ iso }: { iso: string | null }) {
  const now = useNow(30_000);
  if (typeof iso !== "string") return <>an unknown time</>;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return <>an unknown time</>;
  const s = Math.max(0, Math.round((now - t) / 1000));
  const text =
    s < 120
      ? `${s}s`
      : s < 7200
        ? `${Math.floor(s / 60)}m`
        : s < 172800
          ? `${Math.floor(s / 3600)}h`
          : `${Math.floor(s / 86400)}d`;
  return <>{text}</>;
}

// "driving: <tag> ×N" — who is generating this panel's load right now,
// derived from the live-call groups (2026-06-10 EMIT). Absent (renders null)
// when no group's model exactly equals the served model.
export function DrivingLine({
  liveCalls,
  servedModel,
  testId,
}: {
  liveCalls: LiveCalls | null | undefined;
  servedModel: string;
  testId: string;
}) {
  const tags = drivingTags(liveCalls, servedModel);
  if (tags.length === 0) return null;
  return (
    <div className="mt-1 text-[11px] leading-snug" data-testid={testId}>
      <span className="text-zinc-500">driving: </span>
      {tags.slice(0, 3).map((t, i) => (
        <span key={t.tag} className="font-mono">
          {i > 0 && <span className="text-zinc-600"> · </span>}
          <span className={callerTagTone(t.tag)}>{t.tag}</span>
          <span className="text-zinc-400"> ×{t.count}</span>
        </span>
      ))}
    </div>
  );
}

function Row({
  label,
  value,
  valueClass = "text-zinc-100",
  spark,
}: {
  label: string;
  value: string;
  valueClass?: string;
  spark?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-zinc-800/60 py-2 last:border-0">
      <span className="text-sm text-zinc-400">{label}</span>
      <div className="flex items-center gap-3">
        {spark}
        <span className={`w-24 text-right text-sm tabular-nums ${valueClass}`}>
          {value}
        </span>
      </div>
    </div>
  );
}

// Day-7 UX audit (ui_plan.md r10): the day-1 decode band [80,130] was
// measured with 256-tok completions. A PD workload with ~2 tok/call makes the
// tile read ~11 tok/s by construction. The workload-hint pill surfaces that
// context so the user doesn't read low decode as a bug.
function decodeRegimeColor(regime: WorkloadHint["regime"]): string {
  switch (regime) {
    case "short_completion":
      return "text-zinc-400"; // not a regression — workload-bound
    case "decode_bound":
      return "text-emerald-400"; // day-1 band applies
    case "mixed":
      return "text-amber-400";
    default:
      return "text-zinc-600";
  }
}

function regimeShortLabel(regime: WorkloadHint["regime"]): string {
  switch (regime) {
    case "short_completion":
      return "short-completion";
    case "decode_bound":
      return "decode-bound";
    case "mixed":
      return "mixed";
    default:
      return "idle";
  }
}

// Header/border accent per server. Gemma keeps the quiet zinc header; Qwen
// keeps its sky identity (the roles.ts backend-tone family).
const ACCENT: Record<string, { header: string; border: string }> = {
  zinc: { header: "text-zinc-500", border: "border-zinc-800" },
  sky: { header: "text-sky-400", border: "border-sky-900/60" },
  violet: { header: "text-violet-400", border: "border-violet-900/60" },
};

export interface ModelServerCardProps {
  // Header text (e.g. "gemma-4-26b-a4b" / "Qwen3.6-27B · NVFP4-MTP").
  title: string;
  // The exact served-model name for the DrivingLine attribution and this
  // card's testids (`<servedModel>-status` / `-driving` / `-details`).
  servedModel: string;
  // Which per-sample block this card reads (s.vllm vs s.vllm_qwen).
  pick: (s: TelemetrySample) => VllmSample | null | undefined;
  samples: TelemetrySample[];
  // Optional (additive): the live-call aggregate, for the "driving" sub-line.
  liveCalls?: LiveCalls | null;
  // Header/border accent family; unknown keys degrade to zinc.
  accent?: "zinc" | "sky" | string;
  // Gemma-only: poll /api/workload_hint and render the decode-regime pill +
  // the decode sparkline's expected-band reference line.
  workloadHint?: boolean;
  // Qwen-mode tri-state body (see file header). Default false = binary.
  transientDropBanner?: boolean;
  // Dynamic endpoint inventory. When present, its independent /models and
  // /metrics observations own the card's current status; websocket samples
  // remain useful only for the resident sparklines. Optional for backward
  // compatibility with an older backend and the focused card fixtures.
  inventory?: ServedModel | null;
  endpointName?: string;
  // Context for an observed offline endpoint. Pulse supplies these only from
  // either the immutable deployment role (candidate standby) or a fresh,
  // controller-bound runtime receipt. The card never derives planned state
  // from reachability itself.
  serviceExpectation?: "expected_offline" | "starting" | "standby" | null;
  // An exact, controller-bound v4 plan/state selects Mia for this run. This
  // never follows /v1/models reachability alone and does not qualify a model.
  selectedVariant?: NonNullable<ModelRuntime["candidate_variant"]> | null;
  // Browser-observed /api/served_models probes for this exact endpoint
  // identity/runtime generation. Dynamic endpoints do not exist in the
  // legacy websocket schema, so this is their genuine (session-local) trend.
  inventorySamples?: InventoryMetricPoint[];
  inventoryRefreshFailed?: boolean;
}

function ModelServerCard({
  title,
  servedModel,
  pick,
  samples,
  liveCalls,
  accent = "zinc",
  workloadHint = false,
  transientDropBanner = false,
  inventory = null,
  endpointName,
  serviceExpectation = null,
  selectedVariant = null,
  inventorySamples = [],
  inventoryRefreshFailed = false,
}: ModelServerCardProps) {
  const inventoryAware =
    inventory?.service_status === "online" ||
    inventory?.service_status === "offline" ||
    inventory?.service_status === "unknown";
  const inventoryMetrics =
    inventoryAware &&
    inventory?.metrics_endpoint_status === "available" &&
    inventory?.metrics != null &&
    typeof inventory.metrics === "object" &&
    !Array.isArray(inventory.metrics)
      ? inventory.metrics
      : null;
  const latest = samples[samples.length - 1] ?? null;
  const latestBlock = inventoryAware
    ? inventoryMetrics
    : latest
      ? (pick(latest) ?? null)
      : null;
  // LAST-GOOD RETENTION (residual fix 5): the newest sample that carried
  // this card's block, scanned from the tail. `missedScrapes` counts the
  // consecutive trailing samples WITHOUT it — the staleness the body and
  // badge now key off, instead of the latest sample alone.
  let lastGoodIdx = -1;
  for (let i = samples.length - 1; i >= 0; i--) {
    if (pick(samples[i]) != null) {
      lastGoodIdx = i;
      break;
    }
  }
  const lastGood = lastGoodIdx >= 0 ? (pick(samples[lastGoodIdx]) ?? null) : null;
  const lastGoodAt =
    lastGoodIdx >= 0 ? (samples[lastGoodIdx]?.timestamp ?? null) : null;
  const missedScrapes =
    lastGoodIdx >= 0 ? samples.length - 1 - lastGoodIdx : samples.length;
  const anyBlock = lastGood != null;
  const retaining =
    !inventoryAware &&
    latestBlock == null &&
    lastGood != null &&
    missedScrapes < STALE_MISS_LIMIT;
  // What the body renders: the live block, or the retained last-good one
  // while the miss run is still below the limit.
  const block = latestBlock ?? (retaining ? lastGood : null);
  const series = (metric: (b: VllmSample) => number | null | undefined) =>
    inventoryAware
      ? inventorySamples.map((sample) =>
          sample.metrics == null ? null : metric(sample.metrics),
        )
      : samples.map((s) => {
          const b = pick(s);
          return b == null ? null : metric(b);
        });
  const inventoryGaps = inventorySamples.filter((sample) => sample.metrics == null).length;

  // pollhub (perf 2026-08-18): the hint endpoint measured 3.2s under load —
  // 30s cadence (was a bare 10s setInterval), in-flight-guarded, SWR (a
  // failed refetch keeps the previous hint rather than flapping the pill).
  const hint: WorkloadHint | null =
    usePolled<WorkloadHint>("workload_hint", getWorkloadHint, {
      intervalMs: 30000,
      initialDelayMs: 400,
      enabled: workloadHint,
    }).data ?? null;

  const tone = Object.prototype.hasOwnProperty.call(ACCENT, accent)
    ? ACCENT[accent]
    : ACCENT.zinc;

  // Body state: `block` already folds in the retention rule, so a null here
  // means EITHER no sample ever carried the block or the miss run reached
  // STALE_MISS_LIMIT. Tri-state mode still distinguishes "never any block"
  // (unreachable — expected while a server is unwired) from "had it, lost
  // it" (dropped).
  const body = block != null
    ? "data"
    : inventoryAware
      ? inventory?.service_status === "offline"
        ? "offline"
        : inventory?.service_status === "online"
          ? "metrics-unavailable"
          : "identity-unavailable"
      : transientDropBanner
        ? anyBlock
          ? "dropped"
          : "unreachable"
        : "unavailable";
  // Badge (residual fix 5): three states, so stale telemetry no longer
  // reads as a down server — "● up" (latest sample has data), amber
  // "● stale" (retaining last-good data through a short miss run), red
  // "● down" (miss run at the limit, or no data ever).
  const selectedIdentityMatch = inventoryAware &&
    inventory?.service_status === "online" &&
    inventory?.model === selectedVariant?.served_model;
  const selectedVariantConflict = selectedVariant != null &&
    inventory?.service_status === "online" &&
    inventory?.model !== selectedVariant.served_model;
  const badge = inventoryAware
    ? selectedVariantConflict
      ? "variant-mismatch"
      : inventory?.identity_status === "mismatch" && !selectedIdentityMatch
      ? "mismatch"
      : inventory?.service_status === "offline" && serviceExpectation === "expected_offline"
        ? "expected-offline"
        : inventory?.service_status === "offline" && serviceExpectation === "starting"
          ? "starting"
          : inventory?.service_status === "offline" && serviceExpectation === "standby"
            ? "standby"
      : inventory?.service_status === "online"
        ? "online"
        : inventory?.service_status === "offline"
          ? "offline"
          : "unknown"
    : latestBlock != null
      ? "up"
      : retaining
        ? "stale"
        : "down";
  const endpoint = (() => {
    if (!inventory?.url) return "endpoint unknown";
    try {
      const parsed = new URL(inventory.url);
      return parsed.port ? `:${parsed.port}` : parsed.host;
    } catch {
      return "endpoint unknown";
    }
  })();
  const deploymentLabel =
    inventory?.deployment_role === "production_resident"
      ? "Production resident"
      : inventory?.deployment_role === "research_candidate"
        ? "Research candidate"
        : inventory?.deployment_role === "rollback_available"
          ? "Rollback available"
        : "Role not recorded";
  const activityLabel =
    inventory?.activity_status === "busy"
      ? "busy"
      : inventory?.activity_status === "idle"
        ? "idle"
        : "activity unknown";
  const requestSeries = series(
    (sample) => sample.running_requests + sample.waiting_requests,
  );
  const mtpValue = (() => {
    if (selectedVariant?.configured_mtp_speculative_tokens === 0) {
      return "disabled · configured depth 0";
    }
    if (block?.mtp_acceptance_rate != null) {
      return `${fmtRatioPct(block.mtp_acceptance_rate, 1)} %`;
    }
    if (block?.mtp_draft_tokens === 0) {
      return typeof selectedVariant?.configured_mtp_speculative_tokens === "number"
        ? `no draft tokens observed · configured depth ${selectedVariant.configured_mtp_speculative_tokens}`
        : "no draft tokens observed";
    }
    if (typeof selectedVariant?.configured_mtp_speculative_tokens === "number") {
      return `configured depth ${selectedVariant.configured_mtp_speculative_tokens} · metric absent`;
    }
    return "metric not reported";
  })();

  return (
    <div className={`rounded border ${tone.border} bg-zinc-900/40 p-4`}>
      <div className="flex items-baseline gap-2">
        <h2
          className={`text-xs font-medium uppercase tracking-wide ${tone.header}`}
        >
          {title}
        </h2>
        {inventoryAware && inventory?.model == null && inventory?.configured_model && (
          <span className="text-[10px] uppercase tracking-wide text-zinc-500">
            configured
          </span>
        )}
        {/* Badge distinguishes 'down' from 'stale telemetry' (residual
            fix 5): a short scrape-miss run reads amber "● stale" while the
            body keeps the last-good data; hard-red "● down" is reserved for
            a miss run at the limit or a server that never reported. */}
        <span
          className={`ml-auto font-mono text-[11px] ${
            badge === "up" || badge === "online"
              ? "text-emerald-400"
              : badge === "stale" || badge === "unknown" || badge === "starting"
                ? "text-amber-400"
                : badge === "expected-offline" || badge === "standby"
                  ? "text-zinc-500"
                : "text-red-400"
          }`}
          data-testid={`${servedModel}-status`}
        >
          {badge === "up"
            ? "● up"
            : badge === "online"
              ? "● online"
              : badge === "stale"
                ? "● stale"
                : badge === "expected-offline"
                  ? "● offline · expected during research"
                  : badge === "starting"
                    ? "● starting"
                    : badge === "standby"
                      ? "● not serving"
                : badge === "mismatch"
                  ? "● identity mismatch"
                  : badge === "variant-mismatch"
                    ? "● selected variant mismatch"
                  : badge === "unknown"
                    ? "● unknown"
                    : badge === "offline"
                      ? "● offline"
                      : "● down"}
        </span>
      </div>
      {inventoryAware && (
        <div
          className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-zinc-500"
          data-testid={`${endpointName ?? servedModel}-inventory`}
        >
          <span className="font-medium text-zinc-400">{deploymentLabel}</span>
          <span aria-hidden="true">·</span>
          <span className="font-mono">
            {endpointName ? `${endpointName} · ${endpoint}` : endpoint}
          </span>
          <span aria-hidden="true">·</span>
          <span>{activityLabel}</span>
          {inventory?.deployment_role === "research_candidate" &&
            inventory.promotion_authorized === false && (
              <span className="rounded border border-violet-800/60 px-1.5 py-0.5 text-violet-400">
                Evaluation only
              </span>
            )}
          {inventory?.probed_at && (
            <span className="ml-auto">
              probed <SampleAge iso={inventory.probed_at} /> ago
            </span>
          )}
        </div>
      )}
      {inventoryAware && inventoryRefreshFailed && (
        <p className="mt-1 text-[11px] text-amber-400" data-testid={`${endpointName ?? servedModel}-inventory-stale`}>
          Endpoint refresh failed; retained gauges were probed <SampleAge iso={inventory?.probed_at ?? null} /> ago.
        </p>
      )}
      {selectedVariant && (
        <div className="mt-2 text-xs text-violet-300" data-testid={`${endpointName ?? servedModel}-selected-variant`}>
          <p>
            Controller-selected candidate: <strong>{selectedVariant.repository}</strong> at
            <span className="font-mono"> {selectedVariant.revision.slice(0, 8)}</span>.
            {selectedIdentityMatch
              ? " The served name matches this recorded variant; qualification remains separate."
              : " The selected variant has not been observed serving at this probe."}
            {selectedVariant.image_evidence === "bound_live_container"
              ? " Its image matches the controller's live cgroup-bind receipt."
              : " Its image is registered in the plan; this phase does not include a current live image proof."}
            {inventory?.configured_model && <span> Static inventory default: <span className="font-mono">{inventory.configured_model}</span>.</span>}
          </p>
          {(selectedVariant.configured_max_context_tokens !== undefined ||
            selectedVariant.configured_mtp_speculative_tokens !== undefined ||
            selectedVariant.configured_kv_cache_memory_bytes !== undefined) && (
            <p className="mt-1 text-zinc-400" data-testid={`${endpointName ?? servedModel}-profile-config`}>
              Controller profile:
              {selectedVariant.configured_max_context_tokens !== undefined &&
                <span> context {selectedVariant.configured_max_context_tokens.toLocaleString()} tokens;</span>}
              {selectedVariant.configured_mtp_speculative_tokens !== undefined &&
                <span> MTP configured depth {selectedVariant.configured_mtp_speculative_tokens};</span>}
              {selectedVariant.configured_kv_cache_memory_bytes !== undefined &&
                <span> KV reserve {(selectedVariant.configured_kv_cache_memory_bytes / 1024 ** 3).toFixed(1)} GiB.</span>}
              <span> These settings do not measure context quality or decode speed.</span>
            </p>
          )}
        </div>
      )}
      {selectedVariantConflict && (
        <p className="mt-2 text-xs text-red-400" data-testid={`${endpointName ?? servedModel}-variant-mismatch`}>
          The last endpoint probe's served name does not match the controller-selected variant.
          Expected <span className="font-mono">{selectedVariant.served_model}</span>;
          observed <span className="font-mono">{inventory?.model ?? "unknown"}</span>.
        </p>
      )}
      {inventoryAware && inventory?.identity_status === "mismatch" && !selectedIdentityMatch && (
        <p className="mt-2 text-xs text-red-400">
          Served identity does not match the configured model. Configured:{" "}
          <span className="font-mono">{inventory.configured_model ?? "unknown"}</span>.
        </p>
      )}
      {/* Who is generating this backend's load right now — exact-match
          live-call groups only; absent when none. Rendered in EVERY body
          state: the derivation comes from the call log, not the sampler, so
          a panel whose /metrics reader is down can still be the busy backend. */}
      <DrivingLine
        liveCalls={liveCalls}
        servedModel={servedModel}
        testId={`${servedModel}-driving`}
      />
      {body === "unavailable" && (
        <div className="mt-3 text-sm text-zinc-500">
          /metrics unavailable — the server may be down or still loading.
        </div>
      )}
      {body === "unreachable" && (
        <div className="mt-3 text-sm text-zinc-500">
          endpoint unreachable — server may be down or not enabled.
        </div>
      )}
      {body === "dropped" && (
        // Sampler had readings earlier but the miss run reached the limit
        // (residual fix 5: a SINGLE missed scrape no longer lands here — it
        // renders as retained data + the stale note). Softer banner so the
        // panel keeps its space and the user knows data existed before.
        <div className="mt-3 text-sm text-amber-400/80">
          /metrics dropped — {missedScrapes} consecutive scrape
          {missedScrapes === 1 ? "" : "s"} without a reading.
        </div>
      )}
      {body === "offline" && (
        <div className="mt-3 text-sm text-zinc-500">
          {serviceExpectation === "expected_offline"
            ? "This production resident is intentionally stopped for the controller-bound research window. Live metrics were not observed."
            : serviceExpectation === "starting"
              ? "The research candidate is starting; its model endpoint was not ready at the last probe. Live metrics were not observed."
              : serviceExpectation === "standby"
                ? "This optional research candidate is configured and is not currently serving. Live metrics were not observed."
                : "Model endpoint was unreachable at the last probe. Live metrics were not observed."}
        </div>
      )}
      {body === "metrics-unavailable" && (
        <div className="mt-3 text-sm text-amber-400/80">
          Model identity responded, but the metrics endpoint was not available at the last probe.
        </div>
      )}
      {body === "identity-unavailable" && (
        <div className="mt-3 text-sm text-amber-400/80">
          Model endpoint state could not be established from the last probe.
        </div>
      )}
      {inventoryAware && body !== "data" && (
        <details className="mt-3 group" data-testid={`${servedModel}-details`}>
          <summary className="cursor-pointer list-none text-[11px] uppercase tracking-wide text-zinc-500 hover:text-zinc-300">
            <span className="group-open:hidden">show configuration ▸</span>
            <span className="hidden group-open:inline">hide configuration ▾</span>
          </summary>
          <div className="mt-1">
            <Row
              label={selectedVariant ? "Inventory default context" : "Configured context"}
              value={
                typeof inventory?.configured_max_context_tokens === "number"
                  ? `${Math.round(inventory.configured_max_context_tokens / 1024)}K`
                  : "n/a"
              }
            />
            <Row
              label="Server-advertised context"
              value={
                typeof inventory?.observed_max_context_tokens === "number"
                  ? `${Math.round(inventory.observed_max_context_tokens / 1024)}K`
                  : "n/a"
              }
            />
            <Row
              label="Model identity"
              value={selectedIdentityMatch ? "match · controller-selected variant" : inventory?.identity_status ?? "unknown"}
              valueClass={
                inventory?.identity_status === "mismatch" && !selectedIdentityMatch
                  ? "text-red-400"
                  : "text-zinc-500"
              }
            />
            <Row
              label="Metrics endpoint"
              value={inventory?.metrics_endpoint_status ?? "unknown"}
            />
          </div>
        </details>
      )}
      {body === "data" && block != null && (
        <div className="mt-2">
          {retaining && (
            // The explicit staleness note that makes retention honest: the
            // rows below are the LAST GOOD sample, aged out loud.
            <div
              className="mb-1 text-[11px] leading-snug text-amber-400/80"
              data-testid={`${servedModel}-stale-note`}
            >
              stale telemetry — last sample <SampleAge iso={lastGoodAt} /> ago
              ({missedScrapes} missed scrape{missedScrapes === 1 ? "" : "s"})
            </div>
          )}
          {inventoryAware && (
            <div
              className="mb-1 flex items-center gap-2 border-b border-zinc-800/60 py-2 text-[11px]"
              data-testid={`${endpointName ?? servedModel}-activity-ticker`}
            >
              <span className="text-zinc-500">Activity</span>
              <Sparkline values={requestSeries} width={88} height={20} color="#a78bfa" />
              <span className={`font-mono ${inventory?.activity_status === "busy" ? "text-emerald-400" : "text-zinc-400"}`}>
                {inventory?.activity_status === "busy"
                  ? `${fmt(block.running_requests)} running · ${fmt(block.waiting_requests)} queued`
                  : inventory?.activity_status === "idle"
                    ? "idle · 0 requests"
                    : "request state unknown"}
              </span>
              <span className="ml-auto text-zinc-600">
                {inventorySamples.length < 2
                  ? "trend starts with this page"
                  : `${inventorySamples.length} probes${inventoryGaps ? ` · ${inventoryGaps} gap${inventoryGaps === 1 ? "" : "s"}` : ""}`}
              </span>
            </div>
          )}
          {/* Core health — always visible: decode tok/s and KV-cache
              headroom (red over 85%). Everything else is operator-grade
              detail behind the disclosure below. */}
          <Row
            label="Decode tok/s"
            value={fmt(block.tokens_per_sec_decode, 1)}
            spark={
              <Sparkline
                values={series((b) => b.tokens_per_sec_decode)}
                color="#34d399"
                reference={
                  workloadHint && hint?.regime === "decode_bound"
                    ? 40
                    : undefined
                }
              />
            }
          />
          <Row
            label="KV-cache usage"
            value={`${fmt(block.gpu_cache_usage_pct, 1)} %`}
            valueClass={
              block.gpu_cache_usage_pct > 85 ? "text-red-400" : "text-zinc-100"
            }
            spark={
              <Sparkline
                values={series((b) => b.gpu_cache_usage_pct)}
                color="#38bdf8"
              />
            }
          />
          {workloadHint && hint?.available && (
            <div className="mt-1 flex flex-wrap items-baseline gap-x-2 text-[11px] leading-snug">
              <span
                className={`rounded bg-zinc-800/60 px-1.5 py-0.5 font-mono ${decodeRegimeColor(
                  hint.regime,
                )}`}
              >
                workload: {regimeShortLabel(hint.regime)}
              </span>
              {hint.median_output_tokens != null && hint.calls_per_s != null && (
                <span className="text-zinc-500">
                  ~{hint.median_output_tokens} tok/call · {hint.calls_per_s}{" "}
                  call/s
                </span>
              )}
              {hint.expected_decode_tok_s_lower != null &&
                hint.expected_decode_tok_s_upper != null && (
                  <span className="text-zinc-500">
                    expected ~{hint.expected_decode_tok_s_lower}–
                    {hint.expected_decode_tok_s_upper} tok/s
                  </span>
                )}
              <span className="text-zinc-600">{hint.note}</span>
            </div>
          )}

          {/* Operator-grade internals: queue depth, prefix-cache, MTP
              acceptance. Kept but collapsed so the glance stays clean. */}
          <details className="mt-2 group" data-testid={`${servedModel}-details`}>
            <summary className="cursor-pointer list-none text-[11px] uppercase tracking-wide text-zinc-500 hover:text-zinc-300">
              <span className="group-open:hidden">show internals ▸</span>
              <span className="hidden group-open:inline">hide internals ▾</span>
            </summary>
            <div className="mt-1">
              {inventoryAware && (
                <>
                  <Row
                    label="Configured context"
                    value={
                      typeof inventory?.configured_max_context_tokens === "number"
                        ? `${Math.round(inventory.configured_max_context_tokens / 1024)}K`
                        : "n/a"
                    }
                  />
                  <Row
                    label="Server-advertised context"
                    value={
                      typeof inventory?.observed_max_context_tokens === "number"
                        ? `${Math.round(inventory.observed_max_context_tokens / 1024)}K`
                        : "n/a"
                    }
                  />
                  <Row
                    label="Model identity"
                    value={selectedIdentityMatch ? "match · controller-selected variant" : inventory?.identity_status ?? "unknown"}
                    valueClass={
                      inventory?.identity_status === "mismatch" && !selectedIdentityMatch
                        ? "text-red-400"
                        : inventory?.identity_status === "match"
                          ? "text-emerald-400"
                          : "text-zinc-500"
                    }
                  />
                  <Row
                    label="Metrics endpoint"
                    value={inventory?.metrics_endpoint_status ?? "unknown"}
                  />
                </>
              )}
              <Row
                label="Running requests"
                value={fmt(block.running_requests)}
                spark={<Sparkline values={series((b) => b.running_requests)} />}
              />
              <Row
                label="Waiting requests"
                value={fmt(block.waiting_requests)}
                spark={<Sparkline values={series((b) => b.waiting_requests)} />}
              />
              <Row
                label="Prefix-cache hit rate"
                value={
                  block.gpu_prefix_cache_hit_rate == null
                    ? "n/a"
                    : `${fmtRatioPct(block.gpu_prefix_cache_hit_rate, 1)} %`
                }
              />
              <Row
                label="MTP acceptance"
                value={mtpValue}
                // Chosen heuristic (carried from VllmPanel): ≥50% draft-token
                // acceptance reads as healthy MTP, below it as poor (decode
                // tok/s then suffers). This threshold is ours, not a plan's —
                // open question in ui/notes/ui-build.md.
                valueClass={
                  block.mtp_acceptance_rate == null
                    ? "text-zinc-600"
                    : block.mtp_acceptance_rate >= 0.5
                      ? "text-emerald-400"
                      : "text-amber-400"
                }
                spark={
                  block.mtp_acceptance_rate != null ? (
                    <Sparkline values={series((b) => b.mtp_acceptance_rate)} />
                  ) : undefined
                }
              />
            </div>
          </details>
        </div>
      )}
    </div>
  );
}

// Memoized: `samples` identity changes only on a telemetry flush (~0.5 Hz)
// and `pick` is a module-level constant in Pulse — page clock ticks and
// unrelated polls no longer re-render the card (and its sparklines).
export default memo(ModelServerCard);
