import { useEffect, useMemo, useState } from "react";

import {
  BENCHMARK_PROGRAM_ENDPOINT,
  getBenchmarkProgram,
} from "../api/benchmarkProgram";
import { getServedModels, type ServedModel } from "../api/http";
import { usePolled } from "../api/pollhub";
import type {
  BenchmarkProgramLayer,
  BenchmarkProgramResponse,
} from "../types/benchmarkProgram";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const asText = (value: unknown, fallback = "Not reported"): string =>
  typeof value === "string" && value.trim() !== "" ? value : fallback;
const asNumber = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
const asFinite = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const asRows = (value: unknown): Record<string, unknown>[] =>
  Array.isArray(value) ? value.filter(isRecord) : [];
function label(value: unknown): string {
  return asText(value, "unknown").replaceAll("_", " ");
}

const constructPresentation: Record<string, { label: string; order: number }> = {
  science_evidence: { label: "Evidence and quantitative reasoning", order: 10 },
  functional_code_repair: { label: "Functional code repair", order: 20 },
  deterministic_tool_use: { label: "Deterministic tool use", order: 30 },
  public_goods: { label: "Public goods provision", order: 40 },
  vickrey_auction: { label: "Vickrey auction", order: 41 },
  cournot: { label: "Cournot quantity choice", order: 42 },
  proper_scoring_reporting: { label: "Brier score and truthful reporting", order: 43 },
  system_harness: { label: "Harness workflows", order: 50 },
};

function constructKey(row: Record<string, unknown>): string {
  return asText(row.mechanism ?? row.construct ?? row.domain, "unknown");
}

function constructLabel(key: string): string {
  const known = constructPresentation[key]?.label;
  if (known) return known;
  const fallback = label(key);
  return fallback.charAt(0).toUpperCase() + fallback.slice(1);
}

function constructRows(rows: Record<string, unknown>[]): Record<string, unknown>[] {
  return rows.map((row, index) => ({ row, index, key: constructKey(row) }))
    .sort((left, right) => {
      const leftOrder = constructPresentation[left.key]?.order ?? 1_000;
      const rightOrder = constructPresentation[right.key]?.order ?? 1_000;
      return leftOrder - rightOrder || left.key.localeCompare(right.key) || left.index - right.index;
    })
    .map(({ row }) => row);
}

function dateLabel(value: unknown): string {
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) return "Not reported";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" }).format(new Date(value));
}

function categoryRows(value: unknown): Array<{ id: string; label: string; count: number | null; detail: string | null }> {
  if (Array.isArray(value)) {
    return value.filter(isRecord).map((row, index) => ({
      id: asText(row.id ?? row.category ?? row.label, `category ${index + 1}`),
      label: asText(row.label ?? row.id ?? row.category, `Category ${index + 1}`),
      count: asNumber(row.units ?? row.count ?? row.tasks),
      detail: typeof row.summary === "string" ? row.summary : null,
    }));
  }
  if (!isRecord(value)) return [];
  return Object.entries(value).map(([id, item]) => ({
    id,
    label: asText(isRecord(item) ? item.label : null, id),
    count: asNumber(isRecord(item) ? item.units ?? item.count ?? item.tasks : item),
    detail: isRecord(item) && typeof item.summary === "string" ? item.summary : null,
  }));
}

function warningText(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === "string" && item.trim()) return [item];
    if (!isRecord(item)) return [];
    const detail = item.detail ?? item.message ?? item.warning;
    return typeof detail === "string" && detail.trim() ? [detail] : [];
  });
}

interface ReleaseOptionView {
  version: string;
  label: string;
  active: boolean;
  selected: boolean;
  href: string;
}

function releaseOptions(value: unknown): ReleaseOptionView[] {
  return asRows(value).flatMap((row) => {
    const version = asText(row.version, "");
    if (version === "" || version.length > 64) return [];
    const expectedHref = `/benchmarks?release=${encodeURIComponent(version)}`;
    return [{
      version,
      label: asText(row.label, `Release ${version}`),
      active: row.active === true,
      selected: row.selected === true,
      href: typeof row.href === "string" && row.href === expectedHref ? row.href : expectedHref,
    }];
  });
}

function comparisonRows(value: unknown): Record<string, unknown>[] {
  return asRows(value);
}

type VerifiedProductionResident = ServedModel & {
  configured_model: string;
  model: string;
  probed_at: string;
};

const CURRENT_SERVING_MAX_AGE_MS = 90_000;

function verifiedProductionResident(
  value: unknown,
  refreshFailing: boolean,
  nowMs = Date.now(),
): VerifiedProductionResident | null {
  if (refreshFailing) return null;
  if (!isRecord(value)) return null;
  const rows = Object.values(value).filter((row): row is VerifiedProductionResident =>
    isRecord(row)
    && row.deployment_role === "production_resident"
    && row.promotion_authorized === true
    && row.models_endpoint_status === "available"
    && row.service_status === "online"
    && row.identity_status === "match"
    && typeof row.configured_model === "string"
    && row.configured_model.trim() !== ""
    && row.model === row.configured_model
    && typeof row.probed_at === "string"
    && Number.isFinite(Date.parse(row.probed_at))
    && nowMs - Date.parse(row.probed_at) >= 0
    && nowMs - Date.parse(row.probed_at) <= CURRENT_SERVING_MAX_AGE_MS);
  return rows.length === 1 ? rows[0] : null;
}

function hasClaimedProductionResident(value: unknown): boolean {
  return isRecord(value) && Object.values(value).some((row) =>
    isRecord(row) && row.deployment_role === "production_resident");
}

function armUsesModelIdentifier(row: Record<string, unknown>, model: string): boolean {
  const policy = isRecord(row.policy) ? row.policy : null;
  const routes = policy !== null && isRecord(policy.routes) ? policy.routes : null;
  if (routes === null) return false;
  return Object.values(routes).some((route) => {
    if (!isRecord(route)) return false;
    const runtime = isRecord(route.runtime_identity) ? route.runtime_identity : null;
    return route.model === model || runtime?.served_model === model;
  });
}

function isPercentUnit(value: unknown): boolean {
  return value === "%" || value === "percent";
}

function metricValue(value: unknown, unit: unknown): string {
  const number = asFinite(value);
  if (number === null) return "—";
  return `${number.toFixed(1)}${isPercentUnit(unit) ? "%" : ""}`;
}

function deltaValue(value: unknown, unit: unknown): string {
  const number = asFinite(value);
  if (number === null) return "—";
  const suffix = isPercentUnit(unit) ? " pp" : "";
  return `${number > 0 ? "+" : ""}${number.toFixed(1)}${suffix}`;
}

function objectSummary(value: unknown): string {
  if (!isRecord(value)) return "Not reported";
  const parts = Object.entries(value).flatMap(([key, item]) => {
    const number = asFinite(item);
    return number === null ? [] : [`${label(key)} ${number}`];
  });
  return parts.length > 0 ? parts.join(" · ") : "Not reported";
}

function uncertaintySummary(value: unknown): string {
  if (!isRecord(value)) return "Not reported";
  const method = label(value.method);
  const lower = asFinite(value.lower);
  const upper = asFinite(value.upper);
  return lower === null || upper === null
    ? `${method} · interval not available`
    : `${method} · ${lower.toFixed(1)} to ${upper.toFixed(1)}`;
}

function runDetail(row: Record<string, unknown>): string {
  const window = isRecord(row.window) ? row.window : null;
  const parts = [
    typeof row.week === "string" ? row.week : null,
    typeof row.date === "string" ? dateLabel(row.date) : null,
    typeof row.profile === "string" ? row.profile : isRecord(row.profile) ? asText(row.profile.label ?? row.profile.id, "") : null,
    window === null ? null : `${dateLabel(window.started_at)} – ${dateLabel(window.ended_at)}`,
  ].filter((item): item is string => typeof item === "string" && item !== "" && item !== "Not reported");
  return parts.length > 0 ? parts.join(" · ") : "Not reported";
}

function MatchedResultsTable({ rows }: { rows: Record<string, unknown>[] }) {
  return <div className="benchmark-table-wrap" role="region" tabIndex={0} aria-label="Matched canary results, scroll horizontally">
    <table className="benchmark-table" data-testid="benchmark-matched-results">
      <caption className="sr-only">Matched fixed-canary result rows</caption>
      <thead><tr><th scope="col">Construct</th><th scope="col">Baseline</th><th scope="col">Candidate</th><th scope="col">Delta</th><th scope="col">Pairs</th><th scope="col">Discordance</th><th scope="col">Uncertainty</th><th scope="col">Run detail</th></tr></thead>
      <tbody>{constructRows(rows).map((row, index) => {
        const construct = constructKey(row);
        const mechanism = asText(row.mechanism, "");
        const unit = row.unit;
        return <tr key={asText(row.id, `${construct}-${index}`)}>
          <th scope="row"><strong title={`Construct key: ${construct}`}>{constructLabel(construct)}</strong>{mechanism && mechanism !== construct && <span title={`Mechanism key: ${mechanism}`}>{constructLabel(mechanism)}</span>}<small>{label(row.metric)}</small></th>
          <td>{metricValue(row.baseline_value, unit)}</td>
          <td>{metricValue(row.candidate_value, unit)}</td>
          <td>{deltaValue(row.delta, unit)}</td>
          <td>{asNumber(row.n_pairs) ?? "—"}</td>
          <td>{objectSummary(row.discordant_counts)}</td>
          <td>{uncertaintySummary(row.uncertainty)}</td>
          <td>{runDetail(row)}</td>
        </tr>;
      })}</tbody>
    </table>
  </div>;
}

function statusTone(value: unknown): "ok" | "warn" | "bad" | "idle" {
  const status = asText(value, "");
  if (status === "admitted") return "ok";
  if (status.startsWith("withheld") || status === "invalid_receipt_chain") return "bad";
  if (status.startsWith("awaiting") || status === "not_evaluated") return "warn";
  return "idle";
}

function gapLabel(status: unknown, terminal: unknown): string {
  const value = asText(status, "unknown");
  const terminalStatus = asText(terminal, "unknown");
  if (terminalStatus === "unissued") {
    return "This arm was explicitly unissued; no construct score exists.";
  }
  if (terminalStatus === "aborted") {
    return "This attempt aborted; no construct score was admitted.";
  }
  if (value.startsWith("withheld") || value === "invalid_receipt_chain") {
    return "Scores withheld; no construct result is shown.";
  }
  if (value.startsWith("awaiting") || value === "not_evaluated") {
    return "No construct score admitted yet; this attempt remains pending.";
  }
  return "No construct result is recorded for this arm.";
}

function executionPolicy(value: unknown): { summary: string; detail: string[] } {
  if (!isRecord(value)) return { summary: "Policy not reported", detail: [] };
  const routes = isRecord(value.routes) ? value.routes : {};
  const routeDetail = Object.entries(routes).map(([role, route]) => {
    if (!isRecord(route)) return `${label(role)} · route detail unavailable`;
    const expectedPolicy = isRecord(route.expected_policy) ? route.expected_policy : null;
    const temperature = asFinite(expectedPolicy?.temperature);
    const topP = asFinite(expectedPolicy?.top_p);
    const reasoningEffort = expectedPolicy?.reasoning_effort;
    const policyFields = [
      temperature !== null && temperature >= 0 && temperature <= 2
        ? `temperature ${temperature}`
        : null,
      topP !== null && topP > 0 && topP <= 1 ? `top-p ${topP}` : null,
      reasoningEffort === "low" || reasoningEffort === "medium" || reasoningEffort === "high" || reasoningEffort === "xhigh"
        ? `reasoning ${reasoningEffort}`
        : null,
    ].filter((item): item is string => item !== null);
    const fields = [route.model, route.profile]
      .filter((item): item is string => typeof item === "string" && item.trim() !== "")
      .concat(policyFields);
    return `${label(role)} · ${fields.length ? fields.join(" · ") : "route detail unavailable"}`;
  });
  const roleMap = isRecord(value.role_map)
    ? Object.entries(value.role_map).flatMap(([role, assigned]) =>
      typeof assigned === "string" ? [`${label(role)} → ${label(assigned)}`] : [])
    : [];
  const detail = [...routeDetail, ...roleMap];
  return {
    summary: routeDetail.length === 1 ? "1 registered route" : `${routeDetail.length} registered routes`,
    detail,
  };
}

function BenchmarkHistoryTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (rows.length === 0) {
    return <p>No registered run attempts are recorded for this release.</p>;
  }
  return <div className="benchmark-table-wrap" role="region" tabIndex={0} aria-label="Versioned benchmark run history, scroll horizontally">
    <table className="benchmark-table" data-testid="benchmark-run-history">
      <caption className="sr-only">Dated arm and construct history for the fixed canary release</caption>
      <thead><tr><th scope="col">Arm</th><th scope="col">Date</th><th scope="col">Admission</th><th scope="col">Construct</th><th scope="col">Result</th><th scope="col">Run</th><th scope="col">Policy</th></tr></thead>
      {rows.map((row, armIndex) => {
        const results = constructRows(asRows(row.results));
        const rendered = results.length > 0 ? results : [null];
        const policy = executionPolicy(row.policy);
        const admission = asText(row.admission_status, "unknown");
        const wall = asFinite(row.wall_seconds);
        const calls = asNumber(row.model_calls);
        const finished = row.finished_at ?? row.started_at;
        return <tbody key={`${asText(row.comparison_id, "comparison")}-${asText(row.arm_id, String(armIndex))}`}>
          {rendered.map((result, resultIndex) => <tr key={`${asText(result?.construct, "gap")}-${resultIndex}`}>
            {resultIndex === 0 && <th scope="rowgroup" rowSpan={rendered.length}><strong>{asText(row.label ?? row.arm_id, `Arm ${armIndex + 1}`)}</strong><span>{asText(row.comparison_id, "Comparison ID unavailable")} · {asText(row.arm_id, "Arm ID unavailable")}</span></th>}
            {resultIndex === 0 && <td rowSpan={rendered.length}>{dateLabel(finished)}<small>{asText(row.week, "Week not reported")}</small></td>}
            {resultIndex === 0 && <td rowSpan={rendered.length}><span className={`benchmark-chip benchmark-chip--${statusTone(admission)}`}>{label(admission)}</span><small>{label(row.observed_terminal_status)}</small></td>}
            <td>{result === null ? <strong>Admission gap</strong> : <><strong title={`Construct key: ${constructKey(result)}`}>{constructLabel(constructKey(result))}</strong><small>{label(result.domain)} · {label(result.panel)}</small></>}</td>
            <td>{result === null ? gapLabel(admission, row.observed_terminal_status) : <><strong>{metricValue(result.value, result.unit)}</strong><small>{asNumber(result.successful_units) ?? "—"} / {asNumber(result.planned_units) ?? "—"} units · {label(result.metric)}</small></>}</td>
            {resultIndex === 0 && <td rowSpan={rendered.length}>{wall === null ? "Evaluation wall not reported" : `${wall.toFixed(1)} s evaluation wall`}<small>{calls === null ? "Model calls not reported" : `${calls} model calls`}</small></td>}
            {resultIndex === 0 && <td rowSpan={rendered.length}><details><summary>{policy.summary}</summary>{policy.detail.length > 0 && <ul>{policy.detail.map((item) => <li key={item}>{item}</li>)}</ul>}</details></td>}
          </tr>)}
        </tbody>;
      })}
    </table>
  </div>;
}

interface MeasurementReviewView {
  status: "commissioning_only" | "unavailable";
  title: string;
  summary: string;
  interpretation: string | null;
  nextAction: string | null;
  affectedTaskIds: string[];
  sourcePath: string | null;
  reviewedAt: string | null;
}

function measurementReviewView(value: unknown): MeasurementReviewView | null {
  if (!isRecord(value)) return null;
  if (value.status !== "commissioning_only" && value.status !== "unavailable") return null;
  if (value.comparative_quality_allowed !== false) return null;
  const affectedTaskIds = Array.isArray(value.affected_task_ids)
    ? value.affected_task_ids.filter((item): item is string => typeof item === "string" && item.trim() !== "").slice(0, 24)
    : [];
  return {
    status: value.status,
    title: asText(value.title, "Measurement review required"),
    summary: asText(value.summary, "This release is not eligible for comparative quality interpretation."),
    interpretation: typeof value.interpretation === "string" && value.interpretation.trim() !== "" ? value.interpretation : null,
    nextAction: typeof value.next_action === "string" && value.next_action.trim() !== "" ? value.next_action : null,
    affectedTaskIds,
    sourcePath: typeof value.source_path === "string" && value.source_path.trim() !== "" ? value.source_path : null,
    reviewedAt: typeof value.reviewed_at === "string" && value.reviewed_at.trim() !== "" ? value.reviewed_at : null,
  };
}

function MeasurementReviewNotice({ review }: { review: MeasurementReviewView }) {
  return <aside className="benchmark-measurement-review" aria-labelledby="benchmark-measurement-review-title" data-testid="benchmark-measurement-review">
    <div>
      <span className="benchmark-chip benchmark-chip--warn">{label(review.status)}</span>
      <h3 id="benchmark-measurement-review-title">{review.title}</h3>
    </div>
    <p>{review.summary}</p>
    {review.interpretation !== null && <p><strong>Interpretation:</strong> {review.interpretation}</p>}
    {review.nextAction !== null && <p><strong>Next:</strong> {review.nextAction}</p>}
    {(review.affectedTaskIds.length > 0 || review.sourcePath !== null) && <details>
      <summary>{review.affectedTaskIds.length} affected task{review.affectedTaskIds.length === 1 ? "" : "s"} and review provenance</summary>
      {review.affectedTaskIds.length > 0 && <ul>{review.affectedTaskIds.map((taskId) => <li key={taskId}><code>{taskId}</code></li>)}</ul>}
      {review.sourcePath !== null && <p>Review source: <code>{review.sourcePath}</code>{review.reviewedAt === null ? "" : ` · reviewed ${dateLabel(review.reviewedAt)}`}</p>}
    </details>}
  </aside>;
}

function ReferenceResults({
  row,
  diagnosticOnly,
}: {
  row: Record<string, unknown>;
  diagnosticOnly: boolean;
}) {
  const results = constructRows(asRows(row.results));
  const policy = executionPolicy(row.policy);
  const wall = asFinite(row.wall_seconds);
  const calls = asNumber(row.model_calls);
  const finished = row.finished_at ?? row.started_at;
  const admission = asText(row.admission_status, "unknown");
  return <section className="benchmark-program-section benchmark-reference" aria-labelledby="benchmark-reference-heading">
    <div className="benchmark-program-section-head">
      <div>
        <p className="benchmark-eyebrow">Admitted reference</p>
        <h3 id="benchmark-reference-heading">{asText(row.label ?? row.arm_id, "Reference arm")}</h3>
      </div>
      <span className={`benchmark-chip benchmark-chip--${statusTone(admission)}`}>{label(admission)}</span>
    </div>
    <div className="benchmark-reference-meta" aria-label="Reference evaluation context">
      <span><small>Window</small><strong>{dateLabel(finished)} · {asText(row.week, "week not reported")}</strong></span>
      <span><small>Evaluation wall</small><strong>{wall === null ? "Not reported" : `${wall.toFixed(1)} s`}</strong></span>
      <span><small>Model calls</small><strong>{calls ?? "Not reported"}</strong></span>
      <span><small>Policy</small><strong>{policy.summary}</strong></span>
    </div>
    {policy.detail.length > 0 && <p className="benchmark-reference-policy">{policy.detail.join(" · ")}</p>}
    <p className="benchmark-reference-boundary">{diagnosticOnly
      ? "These receipt-bound counts are recorded diagnostics. The measurement review does not admit them as trusted quality scores or evidence for a comparative quality claim."
      : "Each construct stays separate. These small-sample canary signals are descriptive, not benchmark proof or an automatic winner decision."}</p>
    {results.length === 0 ? <p>No construct results are recorded for this admitted reference.</p> : <div className="benchmark-table-wrap" role="region" tabIndex={0} aria-label="Admitted reference construct results, scroll horizontally">
      <table className="benchmark-table benchmark-reference-table" data-testid="benchmark-reference-results">
        <caption className="sr-only">Per-construct admitted reference {diagnosticOnly ? "diagnostics" : "results"}</caption>
        <thead><tr><th scope="col">Construct</th><th scope="col">Layer</th><th scope="col">Successful units</th><th scope="col">{diagnosticOnly ? "Recorded diagnostic" : "Result"}</th></tr></thead>
        <tbody>{results.map((result, index) => {
          const construct = constructKey(result);
          return <tr key={`${construct}-${index}`}>
          <th scope="row"><strong title={`Construct key: ${construct}`}>{constructLabel(construct)}</strong></th>
          <td>{label(result.domain)}<small>{label(result.panel)}</small></td>
          <td>{asNumber(result.successful_units) ?? "—"} / {asNumber(result.planned_units) ?? "—"}</td>
          <td><strong>{metricValue(result.value, result.unit)}</strong><small>{label(result.metric)}</small></td>
        </tr>})}</tbody>
      </table>
    </div>}
  </section>;
}

function releasePresentation(status: string): { tone: "ok" | "warn" | "idle"; summary: string } {
  if (status === "frozen") {
    return {
      tone: "ok",
      summary: "This public definition is frozen for prospective matched evaluation.",
    };
  }
  if (status === "review_required") {
    return {
      tone: "warn",
      summary: "This release reached its review date. New runs require an explicit review or replacement release.",
    };
  }
  if (status === "draft") {
    return {
      tone: "warn",
      summary: "This definition remains a draft until the API records its public publication witness.",
    };
  }
  return {
    tone: "idle",
    summary: "The release state is not recognized. No freeze or run readiness is inferred.",
  };
}

export default function BenchmarkProgramOverview({
  initial,
  release: requestedRelease,
  initialServedModels,
  initialServedModelsRefreshFailed = false,
}: {
  initial?: BenchmarkProgramResponse | null;
  release?: string | null;
  initialServedModels?: Record<string, ServedModel> | null;
  /** Fixture seam mirroring pollhub's stale-while-revalidate failure state. */
  initialServedModelsRefreshFailed?: boolean;
}) {
  const selectedRelease = typeof requestedRelease === "string" && requestedRelease.trim() !== ""
    ? requestedRelease.trim()
    : null;
  const [data, setData] = useState<BenchmarkProgramResponse | null>(initial ?? null);
  const [loaded, setLoaded] = useState(initial !== undefined);
  const [error, setError] = useState<string | null>(null);
  const servedPoll = usePolled("served_models", getServedModels, {
    enabled: initial === undefined && initialServedModels === undefined,
    intervalMs: 30_000,
    initialDelayMs: 100,
    deadlineMs: 20_000,
  });
  const servedModels = initialServedModels === undefined ? servedPoll.data : initialServedModels;
  const servedRefreshFailing = initialServedModels === undefined
    ? servedPoll.failing
    : initialServedModelsRefreshFailed;

  useEffect(() => {
    if (initial !== undefined) return;
    let current = true;
    let inFlight = false;
    const refresh = () => {
      if (inFlight) return;
      inFlight = true;
      getBenchmarkProgram(selectedRelease).then((value) => {
        if (!current) return;
        setData(value);
        setLoaded(true);
        setError(null);
      }).catch((reason) => {
        if (!current) return;
        setLoaded(true);
        setError(String(reason));
      }).finally(() => {
        inFlight = false;
      });
    };
    refresh();
    const interval = window.setInterval(refresh, 30_000);
    return () => {
      current = false;
      window.clearInterval(interval);
    };
  }, [initial, selectedRelease]);

  const categories = useMemo(() => categoryRows(data?.design?.categories), [data?.design?.categories]);
  const releases = releaseOptions(data?.available_releases);
  const layers = data?.layers && isRecord(data.layers)
    ? (["model", "system", "runtime", "applied"] as const).map((id) => ({ id, value: data.layers?.[id] as BenchmarkProgramLayer | null | undefined }))
    : [];
  const warnings = warningText(data?.warnings);
  const completed = asNumber(data?.progress?.completed_units);
  const total = asNumber(data?.progress?.total_units);
  const meterValue = completed !== null && total !== null && total > 0 ? Math.min(total, completed) : null;
  const arms = comparisonRows(data?.comparison?.arms);
  const history = comparisonRows(data?.comparison?.history ?? data?.comparison?.arms);
  const matched = comparisonRows(data?.comparison?.matched_results);
  const blockers = Array.isArray(data?.progress?.blockers)
    ? data.progress.blockers.filter((item): item is string => typeof item === "string" && item.trim() !== "")
    : [];
  const progressPhase = typeof data?.progress?.phase === "string" && data.progress.phase.trim() !== ""
    ? data.progress.phase
    : null;
  const progressRunId = typeof data?.progress?.run_id === "string" && data.progress.run_id.trim() !== ""
    ? data.progress.run_id
    : null;

  if (!loaded) {
    return <section className="benchmark-source-empty" aria-label="Stable benchmark program"><h2>Loading stable benchmark definition…</h2><p>Waiting for the versioned program projection.</p></section>;
  }
  if (data === null || data.schema_version !== "benchmark-program/v1") {
    return <section className="benchmark-source-empty" aria-label="Stable benchmark program" role="status"><h2>Stable benchmark program unavailable</h2><p>{error ?? "The versioned program projection has not been published by this backend."} No run or comparison is inferred.</p></section>;
  }
  if (data.release == null || data.design == null) {
    return <section className="benchmark-source-empty" aria-label="Stable benchmark program" role="status">
      <h2>Stable benchmark definition unavailable</h2>
      <p>{warningText(data.warnings)[0] ?? "The versioned definition is missing or invalid."} Scores, run readiness, and comparisons are withheld.</p>
    </section>;
  }

  const releaseStatus = asText(data.release?.status, "status unknown");
  const release = releasePresentation(releaseStatus);
  const capabilityUnits = asNumber(data.design?.capability_units_per_arm);
  const systemMissions = asNumber(data.design?.system_missions_per_arm);
  const callsPerArm = asNumber(data.design?.model_calls_per_arm);
  const pairedCap = asNumber(data.design?.paired_model_call_cap);
  const completedCalls = asNumber(data.progress?.completed_calls);
  const totalCalls = asNumber(data.progress?.total_calls);
  const reportedBaseline = isRecord(data.comparison?.baseline) ? data.comparison.baseline : null;
  const isAdmittedReference = (row: Record<string, unknown> | null): row is Record<string, unknown> =>
    row !== null
    && row.role === "reference"
    && row.admission_status === "admitted"
    && asRows(row.results).length > 0;
  const historyReference = history.find((row) => isAdmittedReference(row)) ?? null;
  const reference = isAdmittedReference(reportedBaseline) ? reportedBaseline : historyReference;
  const baselineMissing = reference === null;
  const unitsPerArm = capabilityUnits !== null && systemMissions !== null
    ? capabilityUnits + systemMissions
    : null;
  const currentComparisonId = asText(data.progress?.comparison_id, "");
  const currentCohort = currentComparisonId === ""
    ? []
    : history.filter((row) => row.comparison_id === currentComparisonId);
  const currentArms = currentComparisonId === ""
    ? []
    : arms.filter((row) => row.comparison_id === currentComparisonId);
  const currentReferences = currentCohort.filter((row) => isAdmittedReference(row) &&
    row.observed_terminal_status === "complete");
  const currentUnissuedCandidates = currentCohort.filter((row) => row.role === "candidate" &&
    row.admission_status === "not_evaluated" && row.observed_terminal_status === "unissued" &&
    asRows(row.results).length === 0 && asNumber(row.model_calls) === 0);
  const currentReference = currentReferences.length === 1 ? currentReferences[0] : null;
  const currentUnissuedCandidate = currentUnissuedCandidates.length === 1
    ? currentUnissuedCandidates[0]
    : null;
  const currentReferenceCompletedUnits = currentReference === null
    ? null
    : asNumber(currentReference.completed_units);
  const currentReferenceArmId = currentReference === null ? "" : asText(currentReference.arm_id, "");
  const currentCandidateArmId = currentUnissuedCandidate === null
    ? ""
    : asText(currentUnissuedCandidate.arm_id, "");
  const currentArmIds = new Set(currentArms.map((row) => asText(row.arm_id, "")));
  const terminalReferenceSplit = unitsPerArm !== null && unitsPerArm > 0 &&
    currentCohort.length === 2 && currentReferenceCompletedUnits === unitsPerArm &&
    currentUnissuedCandidate !== null && currentArms.length === 2 && currentArmIds.size === 2 &&
    currentReferenceArmId !== "" && currentCandidateArmId !== "" &&
    currentArmIds.has(currentReferenceArmId) && currentArmIds.has(currentCandidateArmId) &&
    completed === unitsPerArm &&
    total === unitsPerArm * 2 && data.progress?.status === "partial" &&
    progressPhase === null && progressRunId === null && error === null;
  const coverageDetail = completed === null || total === null
    ? "Completion counts unavailable"
    : terminalReferenceSplit
      ? `Reference ${unitsPerArm}/${unitsPerArm} complete · candidate 0/${unitsPerArm} unissued${completedCalls === null || totalCalls === null ? "" : ` · ${completedCalls} / ${totalCalls} calls`}`
      : `${completed} of ${total} registered units${completedCalls === null || totalCalls === null ? "" : ` · ${completedCalls} / ${totalCalls} calls`}`;
  const review = measurementReviewView(data.measurement_review);
  const reviewPayloadPresent = data.measurement_review !== undefined && data.measurement_review !== null;
  const measurementReviewRequired = review !== null || data.comparison?.status === "measurement_review_required";
  const comparisonGaps = history.filter((row) => asRows(row.results).length === 0);
  const currentResident = verifiedProductionResident(servedModels, servedRefreshFailing);
  const servingContextUnavailable = currentResident === null
    && hasClaimedProductionResident(servedModels);
  const residentIdentifierAdmissionKnown = currentResident !== null
    && data.release.version === "1.1.0"
    && Array.isArray(data.comparison?.history);
  const residentIdentifierAdmitted = currentResident !== null && history.some((row) =>
    row.admission_status === "admitted"
    && asRows(row.results).length > 0
    && armUsesModelIdentifier(row, currentResident.configured_model));

  return <section className="benchmark-hero benchmark-program-overview" data-testid="benchmark-program" aria-labelledby="benchmark-program-heading">
    <header className="benchmark-program-head">
      <div className="benchmark-program-title">
        <div className="benchmark-program-release">
          <span className={`benchmark-chip benchmark-chip--${release.tone}`}>{label(releaseStatus)}</span>
          <p className="benchmark-eyebrow">Versioned benchmark · v{asText(data.release?.version)}</p>
        </div>
        {releases.length > 1 && <nav className="benchmark-release-selector" aria-label="Benchmark release">
          {releases.map((option) => <a
            key={option.version}
            href={option.href}
            aria-current={option.selected ? "page" : undefined}
            title={option.label}
          >v{option.version}{option.active ? " · active" : ""}</a>)}
        </nav>}
        <h2 id="benchmark-program-heading">Fixed regression canary</h2>
        <p>{release.summary}</p>
      </div>
      <dl className="benchmark-program-status" aria-label="Release and run status">
        <div><dt>Run</dt><dd>{terminalReferenceSplit ? "Reference complete" : label(data.progress?.status)}</dd>{progressPhase !== null
          ? <small data-testid="benchmark-program-phase">Phase: {label(progressPhase)}{progressRunId === null ? "" : ` · ${progressRunId}`}</small>
          : terminalReferenceSplit ? <small>Cohort partial · candidate unissued</small> : null}</div>
        <div><dt>Coverage</dt><dd>{completed === null || total === null ? "Not reported" : `${completed} / ${total}`}</dd><small>{coverageDetail}</small></div>
        <div><dt>Comparison</dt><dd>{label(data.comparison?.status)}</dd><small>{baselineMissing ? "No admitted reference" : `${arms.length} registered arms · ${matched.length} matched rows`}</small></div>
        <div><dt>Review date</dt><dd>{dateLabel(data.release?.expires_at)}</dd><small>Generated {dateLabel(data.generated_at)}</small></div>
      </dl>
    </header>

    {meterValue !== null && total !== null && <div className="benchmark-budget-track benchmark-program-meter" role="meter" aria-label="Stable benchmark registered units completed" aria-valuemin={0} aria-valuemax={total} aria-valuenow={meterValue} aria-valuetext={terminalReferenceSplit ? `Reference ${unitsPerArm} of ${unitsPerArm} complete; candidate 0 of ${unitsPerArm} unissued` : undefined}><span style={{ width: `${(meterValue / total) * 100}%` }} /></div>}

    <div className="benchmark-program-next">
      <p><strong>Next:</strong> {asText(data.progress?.next_action, "No next action reported")}</p>
      {blockers.map((blocker) => <p key={blocker}><strong>Boundary:</strong> {blocker}</p>)}
    </div>

    {currentResident !== null && <aside
      className="benchmark-evidence-note benchmark-current-resident"
      aria-label="Current serving context"
      data-testid="benchmark-current-resident"
    >
      <strong>Currently served</strong>
      <span><code>{currentResident.configured_model}</code> is the verified online production resident. This live serving observation is separate from the frozen historical reference below.
        {residentIdentifierAdmissionKnown
          ? residentIdentifierAdmitted
            ? " This model identifier appears in an admitted v1.1 arm; inspect its dated configuration and results below. This does not establish a match to the current weights or runtime."
            : " This model identifier is not yet admitted on v1.1, so no v1.1 quality score or comparison is inferred."
          : " Its admission status on the selected release is not established by the available projection."}
      </span>
    </aside>}

    {servingContextUnavailable && <aside
      className="benchmark-evidence-note benchmark-current-resident"
      aria-label="Current serving context unavailable"
      data-testid="benchmark-current-resident-unavailable"
      role="status"
    >
      <strong>Serving context unavailable</strong>
      <span>{servedRefreshFailing
        ? "The endpoint inventory refresh failed. Its retained payload is not presented as current online evidence."
        : "The production-resident claim does not have a fresh, identity-matched endpoint probe. No current online identity is inferred."}
      </span>
    </aside>}

    {review !== null && <MeasurementReviewNotice review={review} />}
    {reviewPayloadPresent && review === null && <aside className="benchmark-measurement-review" role="status">
      <h3>Measurement review metadata unavailable</h3>
      <p>The review payload is not internally admissible. Comparative quality interpretation and matched changes are withheld.</p>
    </aside>}

    {error !== null && <p className="benchmark-stale" role="status">The latest stable-program refresh failed: {error}. Showing the last successful projection.</p>}
    {warnings.length > 0 && <aside className="benchmark-warnings" aria-label="Stable benchmark qualifications">{warnings.map((warning, index) => <p key={`${warning}-${index}`}>{warning}</p>)}</aside>}

    {reference !== null ? <ReferenceResults row={reference} diagnosticOnly={measurementReviewRequired} /> : <section className="benchmark-program-section benchmark-reference" aria-labelledby="benchmark-reference-heading">
      <p className="benchmark-eyebrow">Admitted reference</p>
      <h3 id="benchmark-reference-heading">Baseline not established</h3>
      <p>A prospective admitted run is required before any construct result, delta, or trend can be shown.{history.length ? ` ${history.length} registered attempt${history.length === 1 ? " is" : "s are"} retained in run history with pending or withheld gaps.` : ""}</p>
    </section>}

    <section className="benchmark-program-section benchmark-matched" aria-labelledby="benchmark-matched-heading">
      <div className="benchmark-program-section-head">
        <div><p className="benchmark-eyebrow">Candidate versus reference</p><h3 id="benchmark-matched-heading">Matched changes</h3></div>
        <span className={`benchmark-chip benchmark-chip--${matched.length > 0 && !measurementReviewRequired ? "ok" : "idle"}`}>{matched.length > 0 && !measurementReviewRequired ? `${matched.length} recorded` : "none admitted"}</span>
      </div>
      {measurementReviewRequired ? <p>Matched quality changes are withheld while this release is under measurement review. Historical receipt counts remain visible only as recorded diagnostics.</p>
        : baselineMissing ? <p>No baseline is admitted, so matched scores and deltas are withheld.</p>
        : matched.length > 0 ? <><p>These small matched constructs are descriptive canary signals, not benchmark proof or an automatic winner decision.</p><MatchedResultsTable rows={matched} /></>
        : <><p>No matched candidate result is admitted. No winner, upgrade, or trend is inferred.</p>{comparisonGaps.length > 0 && <ul className="benchmark-comparison-gaps">{comparisonGaps.map((row, index) => <li key={`${asText(row.arm_id, "arm")}-${index}`}><strong>{asText(row.label ?? row.arm_id, `Arm ${index + 1}`)}</strong><span>{gapLabel(row.admission_status, row.observed_terminal_status)}</span></li>)}</ul>}</>}
    </section>

    <details className="benchmark-details benchmark-run-history-details">
      <summary>Run history · {history.length} registered arm{history.length === 1 ? "" : "s"}</summary>
      <p>Each construct remains separate. The program does not compute an across-construct score.</p>
      <BenchmarkHistoryTable rows={history} />
    </details>

    <details className="benchmark-details benchmark-definition-details">
      <summary>Definition, evidence layers and provenance</summary>
      <dl className="benchmark-summary-grid benchmark-definition-summary">
        <div><dt>Capability units / arm</dt><dd>{capabilityUnits ?? "—"}</dd><small>{categories.length ? categories.map((item) => `${item.label} ${item.count ?? "—"}`).join(" · ") : "Category counts not reported"}</small></div>
        <div><dt>Harness workflows / arm</dt><dd>{systemMissions ?? "—"}</dd><small>SYSTEM harness work, separate from capability units</small></div>
        <div><dt>Call ceiling</dt><dd>{callsPerArm ?? "—"} / arm</dd><small>{pairedCap === null ? "Paired ceiling not reported" : `${pairedCap} paired calls maximum`}</small></div>
        <div><dt>Definition SHA-256</dt><dd className="benchmark-definition-hash">{asText(data.release?.definition_sha256)}</dd><small>Public witness {data.release?.public_witness == null ? "not recorded" : "recorded by the program API"}</small></div>
      </dl>
      <div className="benchmark-details-grid">
        <section><h3>Panel definition</h3>{categories.length ? <ul>{categories.map((item) => <li key={item.id}><strong>{item.label}</strong> · {item.count ?? "count unavailable"}{item.detail ? ` · ${item.detail}` : ""}</li>)}</ul> : <p>Category detail is not reported.</p>}</section>
        <section><h3>Evidence layers</h3>{layers.length > 0 ? <dl className="benchmark-layer-list">{layers.map(({ id, value }) => <div key={id}><dt>{id}</dt><dd><strong>{label(value?.status)}</strong><span>{asText(value?.summary, "No layer summary reported")}</span></dd></div>)}</dl> : <p>Evidence layers are not reported.</p>}</section>
      </div>
      <p className="benchmark-footnote">Source: <code>{BENCHMARK_PROGRAM_ENDPOINT}</code> · schema {data.schema_version}</p>
    </details>
  </section>;
}
