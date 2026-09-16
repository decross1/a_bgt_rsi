import { useEffect, useMemo, useState } from "react";

import {
  BENCHMARK_PROGRAM_ENDPOINT,
  getBenchmarkProgram,
} from "../api/benchmarkProgram";
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

function comparisonRows(value: unknown): Record<string, unknown>[] {
  return asRows(value);
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
      <tbody>{rows.map((row, index) => {
        const construct = asText(row.construct ?? row.domain, `Construct ${index + 1}`);
        const mechanism = asText(row.mechanism, "");
        const unit = row.unit;
        return <tr key={asText(row.id, `${construct}-${index}`)}>
          <th scope="row"><strong>{label(construct)}</strong>{mechanism && mechanism !== construct && <span>{label(mechanism)}</span>}<small>{label(row.metric)}</small></th>
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
      reasoningEffort === "low" || reasoningEffort === "medium" || reasoningEffort === "xhigh"
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
        const results = asRows(row.results);
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
            <td>{result === null ? <strong>Admission gap</strong> : <><strong>{label(result.construct)}</strong><small>{label(result.domain)} · {label(result.panel)}</small></>}</td>
            <td>{result === null ? gapLabel(admission, row.observed_terminal_status) : <><strong>{metricValue(result.value, result.unit)}</strong><small>{asNumber(result.successful_units) ?? "—"} / {asNumber(result.planned_units) ?? "—"} units · {label(result.metric)}</small></>}</td>
            {resultIndex === 0 && <td rowSpan={rendered.length}>{wall === null ? "Evaluation wall not reported" : `${wall.toFixed(1)} s evaluation wall`}<small>{calls === null ? "Model calls not reported" : `${calls} model calls`}</small></td>}
            {resultIndex === 0 && <td rowSpan={rendered.length}><details><summary>{policy.summary}</summary>{policy.detail.length > 0 && <ul>{policy.detail.map((item) => <li key={item}>{item}</li>)}</ul>}</details></td>}
          </tr>)}
        </tbody>;
      })}
    </table>
  </div>;
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
}: {
  initial?: BenchmarkProgramResponse | null;
}) {
  const [data, setData] = useState<BenchmarkProgramResponse | null>(initial ?? null);
  const [loaded, setLoaded] = useState(initial !== undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initial !== undefined) return;
    let current = true;
    let inFlight = false;
    const refresh = () => {
      if (inFlight) return;
      inFlight = true;
      getBenchmarkProgram().then((value) => {
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
  }, [initial]);

  const categories = useMemo(() => categoryRows(data?.design?.categories), [data?.design?.categories]);
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

  const baselineMissing = data.comparison?.baseline == null;
  const releaseStatus = asText(data.release?.status, "status unknown");
  const release = releasePresentation(releaseStatus);
  const capabilityUnits = asNumber(data.design?.capability_units_per_arm);
  const systemMissions = asNumber(data.design?.system_missions_per_arm);
  const callsPerArm = asNumber(data.design?.model_calls_per_arm);
  const pairedCap = asNumber(data.design?.paired_model_call_cap);

  return <section className="benchmark-hero" data-testid="benchmark-program" aria-labelledby="benchmark-program-heading">
    <div className="benchmark-outcome">
      <span className={`benchmark-chip benchmark-chip--${release.tone}`}>{label(releaseStatus)}</span>
      <p className="benchmark-eyebrow">Versioned benchmark · version {asText(data.release?.version)}</p>
      <h2 id="benchmark-program-heading">Fixed regression canary</h2>
      <p>{release.summary}</p>
      <dl className="benchmark-summary-grid">
        <div><dt>Capability units / arm</dt><dd>{capabilityUnits ?? "—"}</dd><small>{categories.length ? categories.map((item) => `${item.label} ${item.count ?? "—"}`).join(" · ") : "Category counts not reported"}</small></div>
        <div><dt>Harness workflows / arm</dt><dd>{systemMissions ?? "—"}</dd><small>SYSTEM harness work, separate from capability units</small></div>
        <div><dt>Call ceiling</dt><dd>{callsPerArm ?? "—"} / arm</dd><small>{pairedCap === null ? "Paired ceiling not reported" : `${pairedCap} paired calls maximum`}</small></div>
        <div><dt>Definition expires</dt><dd>{dateLabel(data.release?.expires_at)}</dd><small>Generated {dateLabel(data.generated_at)}</small></div>
      </dl>
    </div>

    <div className="benchmark-outcome">
      <p className="benchmark-eyebrow">Prospective run</p>
      <h2>{label(data.progress?.status)}</h2>
      {progressPhase !== null && <p data-testid="benchmark-program-phase"><strong>Phase:</strong> {label(progressPhase)}{progressRunId === null ? "" : ` · ${progressRunId}`}</p>}
      <p>{completed === null || total === null ? "Completion counts are not reported." : `${completed} of ${total} registered units recorded across capability tasks and harness workflows.`}</p>
      {meterValue !== null && total !== null && <div className="benchmark-budget-track" role="meter" aria-label="Stable benchmark registered units completed" aria-valuemin={0} aria-valuemax={total} aria-valuenow={meterValue}><span style={{ width: `${(meterValue / total) * 100}%` }} /></div>}
      <p><strong>Next:</strong> {asText(data.progress?.next_action, "No next action reported")}</p>
      {blockers.map((blocker) => <p key={blocker}><strong>Blocker:</strong> {blocker}</p>)}
      <p><strong>Matched comparison:</strong> {baselineMissing
        ? `Baseline not established. A prospective admitted run is required before any delta or trend can be shown.${history.length ? ` ${history.length} registered attempt${history.length === 1 ? " is" : "s are"} visible below with pending or withheld gaps.` : ""}`
        : `${label(data.comparison?.status)} · ${arms.length} arms · ${matched.length} matched result rows.`}</p>
    </div>

    {layers.length > 0 && <dl className="benchmark-summary-grid" aria-label="Benchmark evidence layers">
      {layers.map(({ id, value }) => <div key={id}><dt>{id}</dt><dd>{label(value?.status)}</dd><small>{asText(value?.summary, "No layer summary reported")}</small></div>)}
    </dl>}

    {error !== null && <p className="benchmark-stale" role="status">The latest stable-program refresh failed: {error}. Showing the last successful projection.</p>}

    {warnings.length > 0 && <aside className="benchmark-warnings" aria-label="Stable benchmark qualifications">{warnings.map((warning, index) => <p key={`${warning}-${index}`}>{warning}</p>)}</aside>}

    <details className="benchmark-details">
      <summary>Definition and comparison evidence</summary>
      <div className="benchmark-details-grid">
        <section><h3>Panel definition</h3>{categories.length ? <ul>{categories.map((item) => <li key={item.id}><strong>{item.label}</strong> · {item.count ?? "count unavailable"}{item.detail ? ` · ${item.detail}` : ""}</li>)}</ul> : <p>Category detail is not reported.</p>}<p>Definition SHA-256: <code>{asText(data.release?.definition_sha256)}</code></p><p>Public witness: {data.release?.public_witness == null ? "not recorded" : "recorded by the program API"}</p></section>
        <section><h3>Matched canary signals</h3>{baselineMissing ? <p>No baseline is admitted. Scores and deltas are withheld.</p> : matched.length ? <><p>These small matched constructs are descriptive canary signals, not benchmark proof or an automatic winner decision.</p><MatchedResultsTable rows={matched} /></> : <p>No matched result rows are recorded.</p>}</section>
      </div>
      <section><h3>Versioned run history</h3><p>Each construct remains separate. The program does not compute an across-construct score.</p><BenchmarkHistoryTable rows={history} /></section>
      <p className="benchmark-footnote">Source: <code>{BENCHMARK_PROGRAM_ENDPOINT}</code> · schema {data.schema_version}</p>
    </details>
  </section>;
}
