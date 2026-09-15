import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  BENCHMARK_PROGRESS_ENDPOINT,
  BENCHMARK_PROGRESS_POLL_KEY,
  getBenchmarkProgress,
} from "../api/benchmarkProgress";
import {
  refreshPoll,
  usePolled,
  usePollActivity,
} from "../api/pollhub";
import { SkeletonCard } from "../design/Skeleton";
import { admittedPair, LocalModelResearchPanel } from "../components/LocalModelResearchPanel";
import { LabModelEvaluationPanel } from "../components/LabModelEvaluationPanel";
import { LabModelSupplementPanel } from "../components/LabModelSupplementPanel";
import { LabContextCrossplanPanel } from "../components/LabContextCrossplanPanel";
import { LabDiversityCapPanel } from "../components/LabDiversityCapPanel";
import { FollowonResultsPanel } from "../components/FollowonResultsPanel";
import { AppliedMarketResearchPanel } from "../components/AppliedMarketResearchPanel";
import { getLabDiversityCapProgress, getLabModelContextCrossplanProgress, getLabModelEvalProgress,
  getLabModelSupplementProgress } from "../api/http";
import type {
  BenchmarkArm,
  BenchmarkComparisonPoint,
  BenchmarkFamily,
  BenchmarkProgressWarning,
  BenchmarkProgressResponse,
  BenchmarkWeek,
  ResearchPipelineCoverage,
  ResearchPipelineProgress,
  ResearchPipelineRecord,
  ResearchPipelineSource,
  ResearchPipelineStage,
} from "../types/benchmarkProgress";
import "./benchmarkProgress.css";

interface Props {
  /** A test/story seam. `undefined` uses the live endpoint; null is a real empty source. */
  initial?: BenchmarkProgressResponse | null;
  /** Independent lab publication seam; weekly history may be unavailable. */
  initialLab?: unknown;
  /** Independent fresh/context publication seam. */
  initialSupplement?: unknown;
  /** Separate matched-24 Qwen/Flash cross-plan publication seam. */
  initialCrossplan?: unknown;
  /** Five reused-task cap diagnostic, independent of all paired model scores. */
  initialCap?: unknown;
}

type FamilyFilter = "all" | "measured" | "comparable" | "incomplete";

const text = (value: unknown, fallback = "Not recorded"): string =>
  typeof value === "string" && value.trim() ? value : fallback;
const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const wholeCount = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= 0;
const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const rows = <T,>(value: unknown): T[] =>
  Array.isArray(value) ? (value.filter((item) => item && typeof item === "object") as T[]) : [];
const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.length > 0) : [];

function fmtNumber(value: unknown, digits = 1): string {
  return finite(value) ? value.toFixed(digits) : "—";
}

function fmtCount(value: unknown): string {
  return finite(value) ? String(value) : "—";
}

function fmtPercent(value: unknown): string {
  return finite(value) && value >= 0 && value <= 1
    ? `${(value * 100).toFixed(0)}%`
    : "—";
}

function fmtSignedPoints(value: unknown): string {
  if (!finite(value)) return "—";
  const points = value * 100;
  return `${points > 0 ? "+" : ""}${points.toFixed(0)} pp`;
}

function fmtTimestamp(value: unknown): string {
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) return "Not reported";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value)) + " UTC";
}

function humanize(value: unknown): string {
  return text(value).toLowerCase().replaceAll("_", " ");
}

function toneFor(value: unknown): "ok" | "warn" | "bad" | "idle" | "info" {
  const normalized = typeof value === "string" ? value.toLowerCase() : "";
  if (/fail|error|reject|invalid|regress/.test(normalized)) return "bad";
  if (/incomplete|ineligible|non.?comparable|unverified|revision|watch|partial|timeout|held|not verified|no gain/.test(normalized)) return "warn";
  if (/complete|eligible|pass|established/.test(normalized) && !/not |no /.test(normalized)) return "ok";
  if (/review|trial|active|recorded/.test(normalized)) return "info";
  return "idle";
}

function StatusChip({ value, tone }: { value: unknown; tone?: ReturnType<typeof toneFor> }) {
  const label = humanize(value);
  return <span className={`benchmark-chip benchmark-chip--${tone ?? toneFor(value)}`}>{label}</span>;
}

function Missing({ label = "Not measured" }: { label?: string }) {
  return <span className="benchmark-missing" title="This source did not report a value">{label}</span>;
}

function MetricValue({ value, formatter, suffix }: {
  value: unknown;
  formatter?: (value: unknown) => string;
  suffix?: string;
}) {
  if (!finite(value)) return <Missing />;
  return <>{formatter ? formatter(value) : value}{suffix}</>;
}

function ArmTable({ arms }: { arms: BenchmarkArm[] }) {
  if (arms.length === 0) {
    return <p className="benchmark-empty-inline">No measured arms were recorded for this family.</p>;
  }
  return <div className="benchmark-table-wrap">
    <table className="benchmark-table">
      <caption className="sr-only">Measured benchmark arms</caption>
      <thead><tr>
        <th scope="col">Arm</th><th scope="col">Graded result</th><th scope="col">Planned attempts</th>
        <th scope="col">Timeouts</th><th scope="col">Success rate</th><th scope="col"><abbr title="Correct Task Throughput">CTT</abbr> / hour</th>
        <th scope="col"><abbr title="Reliable Success Rate: succeeds in at least two of three repeats">RSR 2 of 3</abbr></th><th scope="col">Recorded wall</th><th scope="col">Mean / planned attempt</th>
      </tr></thead>
      <tbody>{arms.map((arm, index) => {
        const metrics = arm.metrics ?? { success_rate: null, ctt_per_hour: null, rsr_2of3: null, recorded_wall_seconds: null, mean_recorded_seconds_per_transport_attempt: null, repair_rate: null, protocol_valid_rate: null, annotation_disagreements: null };
        const hasObjective = finite(arm.objective_successes) && finite(arm.objective_total);
        const hasRepair = finite(arm.repair_successes) && finite(arm.repair_total);
        return <tr key={text(arm.id, `arm-${index}`)}>
          <th scope="row"><strong>{text(arm.label, `Arm ${index + 1}`)}</strong><span>{text(arm.configuration, text(arm.id, "Configuration not recorded"))}</span></th>
          <td>{hasObjective ? <>{fmtCount(arm.objective_successes)} / {fmtCount(arm.objective_total)}<small> objective tasks</small></> : hasRepair ? <>{fmtCount(arm.repair_successes)} / {fmtCount(arm.repair_total)}<small> repair cases</small></> : <Missing label="Not graded" />}</td>
          <td>{finite(arm.transport_returned) && finite(arm.transport_expected) ? <>{fmtCount(arm.transport_returned)} / {fmtCount(arm.transport_expected)}<small> returned / planned</small></> : <Missing />}</td>
          <td>{finite(arm.timeouts) ? fmtCount(arm.timeouts) : <Missing />}</td>
          <td>{finite(metrics.success_rate) ? fmtPercent(metrics.success_rate) : <Missing />}</td>
          <td>{finite(metrics.ctt_per_hour) ? fmtNumber(metrics.ctt_per_hour, 1) : <Missing />}</td>
          <td>{finite(metrics.rsr_2of3) ? fmtPercent(metrics.rsr_2of3) : <Missing />}</td>
          <td>{finite(metrics.recorded_wall_seconds) ? `${fmtNumber(metrics.recorded_wall_seconds, 1)} s` : <Missing />}</td>
          <td>{finite(metrics.mean_recorded_seconds_per_transport_attempt) ? `${fmtNumber(metrics.mean_recorded_seconds_per_transport_attempt, 1)} s` : <Missing />}</td>
        </tr>;
      })}</tbody>
    </table>
  </div>;
}

function HashRow({ label, value }: { label: string; value: unknown }) {
  const hash = typeof value === "string" && value ? value : null;
  return <div className="benchmark-provenance-row"><dt>{label}</dt><dd title={hash ?? undefined}>{hash ?? <Missing label="Not recorded" />}</dd></div>;
}

function HashList({ label, value }: { label: string; value: unknown }) {
  const hashes = Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.length > 0) : [];
  return <div className="benchmark-provenance-row"><dt>{label}</dt><dd>{hashes.length ? hashes.map((hash) => <span key={hash} title={hash}>{hash}</span>) : <Missing label="Not recorded" />}</dd></div>;
}

function ResearchPipelinePanel({ pipeline }: { pipeline?: ResearchPipelineProgress }) {
  if (!record(pipeline)) {
    return <section className="research-pipeline research-pipeline--unavailable" aria-labelledby="research-pipeline-heading">
      <header className="research-pipeline-head"><div><p className="benchmark-eyebrow">Research system</p><h2 id="research-pipeline-heading">Research follow-through</h2></div><StatusChip value="Unavailable" tone="warn" /></header>
      <p className="research-pipeline-empty">This snapshot does not include the research-pipeline projection. No topic progression is inferred.</p>
    </section>;
  }

  const stages = rows<ResearchPipelineStage>(pipeline.stages);
  const coverage = rows<ResearchPipelineCoverage>(pipeline.coverage);
  const attempts = rows<ResearchPipelineRecord>(pipeline.records);
  const qualifications = rows<{ code: string; detail: string }>(pipeline.qualifications);
  const sources = record(pipeline.provenance) ? rows<ResearchPipelineSource>(pipeline.provenance.sources) : [];
  const joinContract = record(pipeline.provenance) ? strings(pipeline.provenance.join_contract) : [];
  const lineage = record(pipeline.provenance) && record(pipeline.provenance.campaign_lineage) ? pipeline.provenance.campaign_lineage : null;
  const window = record(pipeline.window) ? pipeline.window : null;
  const scope = record(pipeline.scope) ? pipeline.scope : null;
  const cohort = record(pipeline.cohort) ? pipeline.cohort : null;
  const campaign = record(pipeline.campaign) ? pipeline.campaign : null;
  const question = campaign && record(campaign.research_question) ? campaign.research_question : null;
  const campaignEvidence = campaign && record(campaign.evidence) ? campaign.evidence : null;
  const campaignRuntime = campaign && record(campaign.runtime) ? campaign.runtime : null;
  const runtimeStatus = text(campaignRuntime?.status, "unknown");
  const runtimeLabel = runtimeStatus === "active" ? "Active"
    : runtimeStatus === "closed" ? "Closed"
    : runtimeStatus === "inactive" ? "Not activated"
    : runtimeStatus === "invalid" ? "Invalid lifecycle"
    : "Not reported";
  const runtimeDetail = runtimeStatus === "active" ? `Activated ${fmtTimestamp(campaignRuntime?.activated_at)}`
    : runtimeStatus === "closed" ? `Closed ${fmtTimestamp(campaignRuntime?.closed_at)}`
    : runtimeStatus === "inactive" ? "No runtime pointer recorded"
    : runtimeStatus === "invalid" ? "Activation or closure receipt is invalid"
    : "Lifecycle receipt unavailable";
  const modelStudyStatus = campaignEvidence?.model_trial_status;
  const modelStudyLabel = modelStudyStatus === "not_registered" ? "No study registered"
    : modelStudyStatus === "registered_no_bound_result" ? "No bound result"
    : modelStudyStatus === "bound_result_observed" ? "Bound result observed"
    : modelStudyStatus === "invalid_bound_result" ? "Invalid bound result"
    : "Not reported";
  const bottleneck = record(pipeline.bottleneck) ? pipeline.bottleneck : null;
  const recordsWindow = record(pipeline.records_window) ? pipeline.records_window : null;
  const pipelineTone = pipeline.status === "observed" ? "info"
    : pipeline.status === "unavailable" ? "warn"
    : pipeline.status === "partial" ? "warn" : "idle";

  return <section className={`research-pipeline research-pipeline--${text(pipeline.status, "unavailable")}`} aria-labelledby="research-pipeline-heading">
    <header className="research-pipeline-head">
      <div><p className="benchmark-eyebrow">Research system · {window?.mode === "campaign_to_date" ? "Campaign to date" : text(window?.week, "Current week")}</p><h2 id="research-pipeline-heading">Research follow-through</h2><p>Track explicitly linked campaign records from dispatch through evidence, skeptic review, and human validation.</p></div>
      <StatusChip value={pipeline.status} tone={pipelineTone} />
    </header>

    {campaign ? <section className="research-campaign" aria-labelledby="research-campaign-heading">
      <div className="research-campaign-main">
        <div className="research-campaign-title"><div><p className="benchmark-eyebrow">Selected V2 campaign</p><h3 id="research-campaign-heading">{text(campaign.title, "Campaign title unavailable")}</h3></div><StatusChip value={`Declaration · ${text(campaign.status, "unknown")}`} tone="idle" /></div>
        <p className="research-campaign-id">{text(campaign.campaign_id)}</p>
        <div className="research-question"><span>Research question</span><p>{text(question?.text, "Research question not recorded")}</p></div>
      </div>
      <dl className="research-campaign-evidence">
        <div><dt>Runtime lifecycle</dt><dd>{runtimeLabel}<small>{runtimeDetail}</small></dd></div>
        <div><dt>CPU calibration</dt><dd>{campaignEvidence?.cpu_calibration_registered === true ? "Manifest registered" : "Not registered"}<small>{campaignEvidence?.cpu_calibration_verified === true ? "Bound result verified" : "Execution not verified here"}</small></dd></div>
        <div><dt>Model study</dt><dd>{modelStudyLabel}<small>{modelStudyStatus === "not_registered" ? "No campaign model evidence admitted" : "CPU controls are not model evidence"}</small></dd></div>
      </dl>
    </section> : <p className="research-campaign-missing">Campaign identity is unavailable in this snapshot. No record should be interpreted as V2 campaign progress.</p>}

    <div className="research-pipeline-intro">
      <div><h3>{text(pipeline.headline, "Research-pipeline state unavailable")}</h3><p>{text(bottleneck?.explanation, "No observation boundary was reported.")}</p></div>
      <dl><div><dt>Observation window</dt><dd>{fmtTimestamp(window?.start_at)} – {fmtTimestamp(window?.end_at)}</dd></div>{window?.dispatch_closed === true ? <div><dt>Dispatch window closed</dt><dd>{fmtTimestamp(window?.dispatch_end_at)}</dd></div> : null}<div><dt>Scope</dt><dd>{text(scope?.label)}</dd></div><div><dt>Runtime boundary</dt><dd>{fmtTimestamp(cohort?.cutoff_at)}</dd></div></dl>
    </div>

    {stages.length > 0 ? <ol className="research-funnel" aria-label="Research follow-through stages">
      {stages.map((stage, index) => <li key={text(stage.id, `stage-${index}`)} className={`research-funnel-stage research-funnel-stage--${text(stage.status, "unavailable")}`}>
        <span className="research-funnel-index" aria-hidden="true">{index + 1}</span>
        <span><small>{humanize(stage.status)}</small><strong>{text(stage.label, "Unnamed stage")}</strong></span>
        <b>{finite(stage.count) ? fmtCount(stage.count) : <Missing label="Unavailable" />}</b>
      </li>)}
    </ol> : <p className="research-pipeline-empty">No trustworthy funnel stages are available in this snapshot.</p>}

    <div className="research-pipeline-lower">
      <section aria-labelledby="research-coverage-heading"><div className="research-subhead"><h3 id="research-coverage-heading">Linkage coverage</h3><span>Missing is distinct from zero</span></div>
        {coverage.length ? <div className="research-coverage-list">{coverage.map((item, index) => {
          const validRate = finite(item.rate) && item.rate >= 0 && item.rate <= 1;
          return <div key={text(item.id, `coverage-${index}`)} className="research-coverage-row">
            <div><strong>{text(item.label, "Unnamed link")}</strong><span>{validRate && finite(item.covered) && finite(item.total) ? `${fmtCount(item.covered)} / ${fmtCount(item.total)}` : item.status === "unavailable" ? "Source unavailable" : "Awaiting observations"}</span></div>
            <div className="research-coverage-track" role={validRate ? "meter" : undefined} aria-label={validRate ? text(item.label) : undefined} aria-valuemin={validRate ? 0 : undefined} aria-valuemax={validRate ? 100 : undefined} aria-valuenow={validRate ? Math.round(item.rate! * 100) : undefined}><span style={{ width: validRate ? `${item.rate! * 100}%` : "0%" }} /></div>
            <b>{validRate ? fmtPercent(item.rate) : "—"}</b>
          </div>;
        })}</div> : <p className="research-pipeline-empty">Coverage cannot be calculated until linked stage records exist.</p>}
      </section>
      <aside className="research-bottleneck"><p className="benchmark-eyebrow">Current observation boundary</p><h3>{humanize(bottleneck?.stage)}</h3><StatusChip value={bottleneck?.status} /><p>{text(bottleneck?.explanation)}</p></aside>
    </div>

    <section className="research-attempts" aria-labelledby="research-attempts-heading"><div className="research-subhead"><h3 id="research-attempts-heading">Campaign topic attempts</h3><span>{attempts.length ? recordsWindow?.truncated === true && finite(recordsWindow.total) ? `${attempts.length} of ${recordsWindow.total} receipt rows shown` : `${attempts.length} receipt ${attempts.length === 1 ? "row" : "rows"}` : "Awaiting first dispatch"}</span></div>
      {attempts.length ? <div className="benchmark-table-wrap"><table className="benchmark-table research-attempt-table"><caption className="sr-only">Sanitized explicitly linked campaign research attempt receipts</caption><thead><tr><th scope="col">Attempt</th><th scope="col">Dispatch</th><th scope="col">Iteration</th><th scope="col">Scope</th><th scope="col">Evidence</th><th scope="col">Skeptic</th><th scope="col">Human validation</th></tr></thead><tbody>{attempts.map((attempt, index) => <tr key={`${text(attempt.attempt_id, "attempt")}-${index}`}><th scope="row"><strong>{text(attempt.attempt_id, `Attempt ${index + 1}`)}</strong><span>{fmtTimestamp(attempt.recorded_at)} · {humanize(attempt.topic_source)}</span><small>{text(attempt.topic_id, "Topic ID unavailable")}</small></th><td><StatusChip value={attempt.dispatch_status} /></td><td><span title={text(attempt.iteration_id)}>{text(attempt.iteration_id, humanize(attempt.iteration_status))}</span></td><td>{humanize(attempt.scope_status)}</td><td>{text(attempt.evidence_level, attempt.iteration_status === "recorded" ? "Level unavailable" : "Not assessed")}</td><td>{humanize(attempt.skeptic_status)}</td><td>{humanize(attempt.human_validation_status)}</td></tr>)}</tbody></table></div>
        : <p className="research-pipeline-empty">No explicitly linked campaign dispatch receipt has been observed. Downstream stages remain not yet observed.</p>}
    </section>

    <details className="benchmark-details research-provenance"><summary>Measurement boundary and source provenance</summary><div className="benchmark-details-grid">
      <section><h4>Campaign and cohort contract</h4><dl><HashRow label="Campaign manifest SHA-256" value={campaign?.manifest_sha256} /><HashRow label="Research question SHA-256" value={question?.text_sha256} /><HashRow label="Cohort ID" value={cohort?.id} /><HashRow label="Cutoff receipt SHA-256" value={cohort?.cutoff_receipt_sha256} /><HashRow label="Canonical source commit" value={cohort?.canonical_head} /></dl><p>{text(cohort?.membership_rule, "Exact campaign linkage is required.")}</p><p>{text(cohort?.cutoff_reason, "No verified runtime cutoff was reported.")}</p></section>
      <section><h4>Identifier joins</h4>{joinContract.length ? <ul>{joinContract.map((rule) => <li key={rule}>{rule}</li>)}</ul> : <p>No join contract was reported.</p>}<p>Only the selected research question is public. Topic or hypothesis text from result ledgers is neither exposed nor used to guess lineage.</p></section>
      <section><h4>Campaign lineage classifications</h4>{lineage ? <dl className="benchmark-provenance">{Object.entries(lineage).map(([sourceId, rawCounts]) => { const counts: Record<string, unknown> = record(rawCounts) ? rawCounts : {}; const explicit = finite(counts.explicit_match) ? counts.explicit_match : null; const excluded = ["unlinked_legacy", "malformed_campaign_link", "different_campaign", "campaign_link_mismatch", "malformed_record"].reduce((total, key) => total + (finite(counts[key]) ? counts[key] : 0), 0); return <div className="benchmark-provenance-row" key={sourceId}><dt>{humanize(sourceId)}</dt><dd>{explicit === null ? "Not recorded" : `${explicit} explicit · ${excluded} excluded`}</dd></div>; })}</dl> : <p>Campaign lineage classifications were not reported.</p>}</section>
      <section><h4>Source windows</h4><dl className="benchmark-provenance">{sources.map((source, index) => <div className="benchmark-provenance-row" key={text(source.id, `source-${index}`)}><dt>{humanize(source.id)}</dt><dd title={text(source.window_sha256)}>{source.available ? <>{fmtCount(source.parsed_rows)} rows · {text(source.window_sha256, "hash unavailable")}</> : "Unavailable"}</dd></div>)}</dl></section>
      <section><h4>Qualifications</h4>{qualifications.length ? <ul>{qualifications.map((item, index) => <li key={`${text(item.code)}-${index}`}>{text(item.detail)}</li>)}</ul> : <p>No source qualifications were reported for this bounded window.</p>}</section>
    </div></details>
  </section>;
}

function FamilyCard({ family }: { family: BenchmarkFamily }) {
  const arms = rows<BenchmarkArm>(family.arms);
  const comparison = family.comparison ?? { eligible: false, explanation: "Comparison state not reported", history_points: 0, fingerprint: null, basis: [], break_reasons: [], points: [] };
  const uncertainty = family.uncertainty ?? { kind: "none", metric: null, low: null, high: null, n: null };
  const provenance = family.provenance ?? { trial_ids: [], manifest_sha256: [], run_sha256: [], evaluation_sha256: [], summary_sha256: [], source_commits: [] };
  const evidence = family.evidence ?? { class: "NONE", candidate_benefit_verified: null };
  const details = family.details ?? { note: null, fixture_count: null, repeat_count: 0, grader_bound: false };
  const completeness = family.completeness ?? { expected: null, returned: null, protocol_valid: null, timeouts: null };
  const points = rows<BenchmarkComparisonPoint>(comparison.points);
  const hasContractBreak = strings(comparison.break_reasons).length > 0;
  const intervalValid = uncertainty.metric === "failure_inclusive_delta_candidate_minus_baseline" && finite(uncertainty.low) && finite(uncertainty.high) && uncertainty.low >= -1 && uncertainty.high <= 1 && uncertainty.low <= uncertainty.high;

  const executionTone = /fail|error/i.test(text(family.execution_status, "")) ? "bad" : /incomplete|timeout|partial|mixed/i.test(text(family.execution_status, "")) ? "warn" : "info";
  const evidenceTone = family.evaluation_status === "invalid" ? "bad" : family.evaluation_status === "partial" ? "warn" : family.evaluation_status === "recorded" ? "info" : "idle";
  return <article className="benchmark-family" data-testid={`benchmark-family-${text(family.id, "unknown")}`}>
    <header className="benchmark-family-head">
      <div><p className="benchmark-eyebrow">{text(family.kind, "Unclassified family")} · {humanize(family.status)}</p><h3>{text(family.label, "Unnamed benchmark")}</h3></div>
      <div className="benchmark-state-row">
        <span><small>Execution</small><StatusChip value={family.execution_status} tone={executionTone} /></span>
        <span><small>Evidence</small><StatusChip value={family.evaluation_status} tone={evidenceTone} /></span>
      </div>
    </header>
    <div className={`benchmark-comparison ${comparison.eligible ? "benchmark-comparison--eligible" : ""}`}>
      <div><span className="benchmark-comparison-label">Week-over-week comparison</span><strong>{comparison.eligible ? "Comparable" : comparison.history_points === 1 && !hasContractBreak ? "Baseline only" : comparison.history_points > 1 ? "Not comparable" : "Comparison unavailable"}</strong></div>
      <p>{text(comparison.explanation, "Comparison eligibility was not reported.")} <span>{fmtCount(comparison.history_points)} history {comparison.history_points === 1 ? "point" : "points"}.</span></p>
    </div>
    <p className="benchmark-verdict"><span>Semantic conclusion</span>{family.semantic_verdict === "candidate_benefit_not_verified" ? "Candidate benefit not verified" : "Unknown"}</p>
    {typeof family.interpretation_note === "string" && family.interpretation_note.trim() && <p className="benchmark-interpretation-note"><strong>Interpretation limit</strong><span>{family.interpretation_note}</span></p>}
    {!comparison.eligible || points.length <= 1 ? <p className="benchmark-history-note">{comparison.eligible ? "More comparable measurements are needed before a trend can be drawn." : points.length === 1 ? "First cohort point recorded. A trend is not drawn from one week." : "No eligible comparable series is available."}</p>
      : <div className="benchmark-table-wrap benchmark-history"><table className="benchmark-table"><caption>Comparable cohort history</caption><thead><tr><th scope="col">Week</th><th scope="col">Baseline</th><th scope="col">Candidate</th><th scope="col">Candidate delta</th><th scope="col">Trials</th></tr></thead><tbody>{points.map((point, index) => <tr key={`${text(point.week)}-${index}`}><th scope="row">{text(point.week)}</th><td>{finite(point.baseline?.success_rate) ? fmtPercent(point.baseline.success_rate) : <Missing />} <small>{text(point.baseline?.arm_id)} · {finite(point.baseline?.successes) && finite(point.baseline?.success_denominator) ? `${point.baseline.successes}/${point.baseline.success_denominator}` : "denominator not measured"}</small></td><td>{finite(point.candidate?.success_rate) ? fmtPercent(point.candidate.success_rate) : <Missing />} <small>{text(point.candidate?.arm_id)} · {finite(point.candidate?.successes) && finite(point.candidate?.success_denominator) ? `${point.candidate.successes}/${point.candidate.success_denominator}` : "denominator not measured"}</small></td><td>{finite(point.delta_success_rate) ? `${point.delta_success_rate >= 0 ? "+" : ""}${(point.delta_success_rate * 100).toFixed(0)} pp` : <Missing />}</td><td>{fmtCount(point.trial_count)}</td></tr>)}</tbody></table></div>}
    <ArmTable arms={arms} />
    <details className="benchmark-details">
      <summary>Evidence, uncertainty and provenance</summary>
      <div className="benchmark-details-grid">
        <section><h4>Interpretation</h4>
          <p>{text(details.note, "No additional interpretation was recorded.")}</p>
          <dl><div><dt>Fixtures</dt><dd>{finite(details.fixture_count) ? fmtCount(details.fixture_count) : <Missing />}</dd></div>
          <div><dt>Repeats</dt><dd>{fmtCount(details.repeat_count)}</dd></div>
          <div><dt>Grader bound</dt><dd>{details.grader_bound ? "Yes" : "No"}</dd></div>
          <div><dt>Planned / returned / protocol-valid</dt><dd>{fmtCount(completeness.expected)} / {fmtCount(completeness.returned)} / {fmtCount(completeness.protocol_valid)}</dd></div>
          <div><dt>Recorded timeouts</dt><dd>{fmtCount(completeness.timeouts)}</dd></div>
          <div><dt>Evidence class</dt><dd>{humanize(evidence.class)}</dd></div>
          <div><dt>Candidate benefit verified</dt><dd>{evidence.candidate_benefit_verified === false ? "No" : "Not reported"}</dd></div></dl>
        </section>
        <section><h4>Uncertainty</h4>
          {intervalValid ? <p>{humanize(uncertainty.kind)} candidate-minus-baseline failure-inclusive delta: {fmtSignedPoints(uncertainty.low)} to {fmtSignedPoints(uncertainty.high)}{finite(uncertainty.n) ? ` · n=${uncertainty.n}` : ""}</p>
            : <p>No valid paired delta interval was reported. No confidence band is inferred.</p>}
        </section>
        <section><h4>Immutable provenance</h4><dl className="benchmark-provenance">
          <HashList label="Trial IDs" value={provenance.trial_ids} />
          <HashList label="Manifest SHA-256" value={provenance.manifest_sha256} />
          <HashList label="Run SHA-256" value={provenance.run_sha256} />
          <HashList label="Evaluation SHA-256" value={provenance.evaluation_sha256} />
          <HashList label="Summary SHA-256" value={provenance.summary_sha256} />
          <HashList label="Source commits" value={provenance.source_commits} />
          <HashRow label="Cohort fingerprint" value={comparison.fingerprint} />
        </dl></section>
        <section><h4>Comparison contract</h4>
          <p>{strings(comparison.basis).length ? `Bound on: ${strings(comparison.basis).join(", ")}.` : "Comparison basis not reported."}</p>
          {strings(comparison.break_reasons).length > 0 && <ul>{strings(comparison.break_reasons).map((reason) => <li key={reason}>{reason}</li>)}</ul>}
        </section>
      </div>
    </details>
  </article>;
}

function WeekButton({ week, selected, onSelect }: { week: BenchmarkWeek; selected: boolean; onSelect: () => void }) {
  return <button type="button" className="benchmark-week" aria-pressed={selected} onClick={onSelect}>
    <span><strong>{text(week.week)}</strong><small>{humanize(week.status)}</small></span>
    <span><small>Review</small><b>{humanize(week.review?.status)}</b></span>
    <span><small>Terminal trials</small><b>{fmtCount(week.terminal_trials)} recorded</b></span>
  </button>;
}

export default function BenchmarkProgress({ initial, initialLab, initialSupplement,
  initialCrossplan, initialCap }: Props) {
  const live = initial === undefined;
  const poll = usePolled(BENCHMARK_PROGRESS_POLL_KEY, getBenchmarkProgress, {
    intervalMs: 60_000,
    deadlineMs: 16_000,
    enabled: live,
  });
  const labPoll = usePolled("lab-model-eval:progress", getLabModelEvalProgress, {
    intervalMs: 90_000,
    deadlineMs: 20_000,
    enabled: live,
    initialDelayMs: 2500,
  });
  const supplementPoll = usePolled("lab-model-supplement:progress", getLabModelSupplementProgress, {
    intervalMs: 120_000,
    deadlineMs: 20_000,
    enabled: live,
    initialDelayMs: 5000,
  });
  const crossplanPoll = usePolled("lab-context-crossplan:progress",
    getLabModelContextCrossplanProgress, {
      intervalMs: 150_000,
      deadlineMs: 20_000,
      enabled: live,
      initialDelayMs: 6500,
    });
  const capPoll = usePolled("lab-diversity-cap:progress", getLabDiversityCapProgress, {
    intervalMs: 180_000,
    deadlineMs: 20_000,
    enabled: live,
    initialDelayMs: 8000,
  });
  const refreshing = usePollActivity(BENCHMARK_PROGRESS_POLL_KEY);
  const data = initial === undefined ? poll.data : initial;
  const labData = initialLab === undefined ? labPoll.data : initialLab;
  const supplementData = initialSupplement === undefined ? supplementPoll.data : initialSupplement;
  const crossplanData = initialCrossplan === undefined ? crossplanPoll.data : initialCrossplan;
  const capData = initialCap === undefined ? capPoll.data : initialCap;
  const showLab = live || initialLab !== undefined;
  const showSupplement = live || initialSupplement !== undefined;
  const showCrossplan = live || initialCrossplan !== undefined;
  const showCap = live || initialCap !== undefined;
  const [selectedWeek, setSelectedWeek] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FamilyFilter>("all");
  const weeks = rows<BenchmarkWeek>(data?.weeks);
  const currentWeek = selectedWeek && weeks.some((week) => week.week === selectedWeek)
    ? selectedWeek : text(data?.summary?.latest_week, text(data?.current_week, weeks[0]?.week ?? ""));
  const week = weeks.find((entry) => entry.week === currentWeek) ?? weeks[0] ?? null;
  const families = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return rows<BenchmarkFamily>(week?.families).filter((family) => {
      const haystack = [family.id, family.kind, family.label, family.status, family.execution_status, family.evaluation_status, family.semantic_verdict].filter((value) => typeof value === "string").join(" ").toLowerCase();
      if (normalizedQuery && !haystack.includes(normalizedQuery)) return false;
      if (filter === "comparable") return family.comparison?.eligible === true;
      if (filter === "measured") return rows(family.arms).length > 0;
      if (filter === "incomplete") return /incomplete|partial|failed|timeout|invalid|mixed/i.test(`${family.status} ${family.execution_status} ${family.evaluation_status}`);
      return true;
    });
  }, [filter, query, week]);

  if (data === undefined && !poll.failing) {
    return <section className="page-full benchmark-progress" aria-labelledby="benchmark-progress-title">
      <header className="benchmark-page-head"><div><p className="benchmark-eyebrow">Operations</p><h1 id="benchmark-progress-title">Benchmark Progress</h1><p>Review decisions and benchmark results, week by week.</p></div></header>
      <SkeletonCard lines={7} />
      {showLab && <LabModelEvaluationPanel data={labData} pollingFailed={labPoll.failing} />}
      {showSupplement && <LabModelSupplementPanel data={supplementData} pollingFailed={supplementPoll.failing} />}
      {showCrossplan && <LabContextCrossplanPanel data={crossplanData} pollingFailed={crossplanPoll.failing} />}
      {showCap && <LabDiversityCapPanel data={capData} pollingFailed={capPoll.failing} />}
    </section>;
  }

  if (data == null) {
    return <section className="page-full benchmark-progress" aria-labelledby="benchmark-progress-title">
      <header className="benchmark-page-head"><div><p className="benchmark-eyebrow">Operations</p><h1 id="benchmark-progress-title">Benchmark Progress</h1><p>Review decisions and benchmark results, week by week.</p></div></header>
      <section className="benchmark-source-empty" role="status"><h2>Unable to load benchmark history</h2>
        <p>{poll.failing ? `The latest read failed: ${String(poll.error)}. Missing history is withheld rather than shown as zero.` : "The weekly upgrade sources have not produced a progress record yet."}</p>
        {live && <button type="button" onClick={() => refreshPoll(BENCHMARK_PROGRESS_POLL_KEY)}>Retry</button>}
      </section>
      {showLab && <LabModelEvaluationPanel data={labData} pollingFailed={labPoll.failing} />}
      {showSupplement && <LabModelSupplementPanel data={supplementData} pollingFailed={supplementPoll.failing} />}
      {showCrossplan && <LabContextCrossplanPanel data={crossplanData} pollingFailed={crossplanPoll.failing} />}
      {showCap && <LabDiversityCapPanel data={capData} pollingFailed={capPoll.failing} />}
    </section>;
  }

  const summaryMissing = !record(data.summary);
  const summary = data.summary ?? { headline: "Progress summary unavailable", upgrade_established: null, weeks_seen: null, latest_week: null, terminal_trials: null, recorded_evaluations: null, complete_executions: null, comparable_transitions: null, current_week_budget: null };
  const automation = data.automation ?? { mode: "unknown", status: null, activated_at: null, schedule: null, promotion_enabled: null };
  const trialsUnavailable = data.availability?.trials === false;
  const evaluationsUnavailable = data.availability?.evaluations === false;
  const completionUnavailable = data.availability?.completion === false;
  const benchmarkSourcesUnavailable = trialsUnavailable && evaluationsUnavailable;
  const budget = summary.current_week_budget;
  const upgradeLabel = summary.upgrade_established === true ? "Upgrade established"
    : summary.upgrade_established === false ? "Baseline recorded" : "More comparable measurements needed";
  const upgradeTone = summary.upgrade_established === true ? "ok" : summary.upgrade_established === false ? "idle" : "warn";
  const usedRatio = finite(budget?.charged_minutes) && finite(budget?.limit_minutes) && budget.limit_minutes > 0
    ? Math.min(1, Math.max(0, budget.charged_minutes / budget.limit_minutes)) : null;
  const budgetMeterNow = usedRatio !== null && finite(budget?.charged_minutes) && finite(budget?.limit_minutes)
    ? Math.min(budget.limit_minutes, Math.max(0, budget.charged_minutes)) : null;
  const budgetOverrun = finite(budget?.charged_minutes) && finite(budget?.limit_minutes) && budget.charged_minutes > budget.limit_minutes
    ? budget.charged_minutes - budget.limit_minutes : null;
  const localPair = data.local_model_research?.comparisons.find(row =>
    row.status === "complete" && row.comparison_eligible === true && admittedPair(row));
  const localObjective = localPair?.families.find(row => row.family === "objective" && row.comparison_eligible);
  const localTopic = localPair?.families.find(row => row.family === "topic" && row.comparison_eligible);
  const pairCountsBound = [localObjective, localTopic].every(row => row &&
    [row.cohorts.resident.declared, row.cohorts.resident.attempted,
      row.cohorts.resident.passed, row.cohorts.flash.declared,
      row.cohorts.flash.attempted, row.cohorts.flash.passed].every(wholeCount) &&
    row.cohorts.resident.declared > 0 &&
    row.cohorts.resident.attempted === row.cohorts.resident.declared &&
    row.cohorts.flash.attempted === row.cohorts.flash.declared &&
    row.cohorts.resident.declared === row.cohorts.flash.declared &&
    row.cohorts.resident.passed <= row.cohorts.resident.declared &&
    row.cohorts.flash.passed <= row.cohorts.flash.declared);
  const weeklyHeadline = summary.upgrade_established === false
    ? "Weekly review: no week-over-week upgrade established"
    : text(summary.headline, upgradeLabel);

  return <section className="page-full benchmark-progress" aria-labelledby="benchmark-progress-title">
    <header className="benchmark-page-head">
      <div><p className="benchmark-eyebrow">Operations</p><h1 id="benchmark-progress-title">Benchmark Progress</h1>
        <p>Review decisions and benchmark results, week by week.</p></div>
      {live && <button type="button" className="benchmark-refresh" disabled={refreshing} onClick={() => refreshPoll(BENCHMARK_PROGRESS_POLL_KEY)}>{refreshing ? "Refreshing…" : "Refresh records"}</button>}
    </header>

    {poll.failing && <p className="benchmark-stale" role="status">Refresh failed: {String(poll.error)}. Showing the last successful snapshot; current state is unknown.</p>}

    <section className="benchmark-mode-strip" aria-label="Recorded automation state">
      <div><span className="benchmark-status-dot" aria-hidden="true" /><span><small>Recorded automation mode</small><strong>{humanize(automation.mode)}</strong></span></div>
      <div><small>Schedule</small><strong>{text(automation.schedule)}</strong></div>
      <div><small>Activated</small><strong>{fmtTimestamp(automation.activated_at)}</strong></div>
      <div><small>Automatic promotion</small><strong>{automation.promotion_enabled === null ? "Not reported" : automation.promotion_enabled ? "Enabled" : "Disabled"}</strong></div>
      <div><small>Projection generated</small><strong>{fmtTimestamp(data.generated_at)}</strong></div>
    </section>

    <section className="benchmark-hero" aria-labelledby="benchmark-outcome-heading">
      <div className="benchmark-outcome"><StatusChip value={upgradeLabel} tone={upgradeTone} />
        <h2 id="benchmark-outcome-heading">{weeklyHeadline}</h2>
        <p>{summary.upgrade_established === false ? "No maintenance upgrade has been established from the recorded weeks. " : ""}This weekly review does not grade the separate local-model study below.</p>
        <Link to="/ladder">Open campaign research <span aria-hidden="true">→</span></Link>
      </div>
      <dl className="benchmark-summary-grid">
        <div><dt>Weeks recorded</dt><dd>{fmtCount(summary.weeks_seen)}</dd><small>baseline {text(summary.latest_week)}</small></div>
        <div><dt>Terminal trials</dt><dd>{trialsUnavailable ? <Missing label="Unavailable" /> : fmtCount(summary.terminal_trials)}</dd><small>{evaluationsUnavailable ? "Evaluation source unavailable" : `${fmtCount(summary.recorded_evaluations)} recorded evaluations`}{" · "}{completionUnavailable ? "Execution source unavailable" : `${fmtCount(summary.complete_executions)} complete executions`}</small></div>
        <div><dt>Comparable transitions</dt><dd>{fmtCount(summary.comparable_transitions)}</dd><small>eligible week-over-week changes</small></div>
        <div className="benchmark-budget"><dt>Weekly Spark allowance</dt><dd><MetricValue value={budget?.charged_minutes} formatter={(value) => fmtNumber(value, 1)} /> <span>charged / {finite(budget?.limit_minutes) ? `${fmtNumber(budget.limit_minutes, 0)} min` : "limit not recorded"}</span></dd>
          {usedRatio !== null && budgetMeterNow !== null && <div className="benchmark-budget-track" role="meter" aria-label="Weekly Spark allowance charged" aria-valuemin={0} aria-valuemax={budget?.limit_minutes ?? 0} aria-valuenow={budgetMeterNow}><span style={{ width: `${usedRatio * 100}%` }} /></div>}
          <small>{finite(budget?.prior_import_minutes) && budget.prior_import_minutes > 0 ? `Includes ${fmtNumber(budget.prior_import_minutes, 1)} min prior-use debit · ` : ""}{budgetOverrun !== null ? `${fmtNumber(budgetOverrun, 1)} min over allowance` : finite(budget?.remaining_minutes) ? `${fmtNumber(budget.remaining_minutes, 1)} min remaining` : "Remaining allowance not recorded"}</small></div>
      </dl>
    </section>

    <aside className="benchmark-evidence-note" aria-labelledby="local-evidence-bridge-heading">
      <strong id="local-evidence-bridge-heading">Separate local-model evidence</strong>
      <span>{localPair && pairCountsBound && localObjective && localTopic
        ? <>The admitted original Flash/resident pair is mixed: objective tasks passed {localObjective.cohorts.flash.passed}/{localObjective.cohorts.flash.declared} with Flash versus {localObjective.cohorts.resident.passed}/{localObjective.cohorts.resident.declared} with residents, while topic output passed {localTopic.cohorts.flash.passed}/{localTopic.cohorts.flash.declared} versus {localTopic.cohorts.resident.passed}/{localTopic.cohorts.resident.declared}. The optimized MTP profile has separate follow-on studies and a newly frozen paired trial; this original pair does not establish a primary-model replacement. <a href="#local-model-research-heading">View original paired evidence</a>, <a href="#lab-model-eval-heading">optimized paired status</a>, and <a href="#followon-heading">optimized follow-ons</a>.</>
        : <>No complete, admitted local pair is available in this snapshot. Local-model scores are withheld here; <a href="#local-model-research-heading">view source status below</a>.</>}</span>
    </aside>

    <aside className="benchmark-evidence-note"><strong>Evidence boundary</strong><span>Operator-recorded summaries are not scientific ground truth. Review-only automation scans and critiques proposals; it does not automatically rerun benchmark panels or promote changes.</span></aside>

    {(summaryMissing || rows<BenchmarkProgressWarning>(data.warnings).length > 0) && <aside className="benchmark-warnings" aria-label="Data qualifications">{summaryMissing && <p><strong>Progress summary</strong> · The response shape is incomplete. Missing values are withheld rather than inferred as zero.</p>}{rows<BenchmarkProgressWarning>(data.warnings).map((warning, index) => <p key={`${String(warning.code)}-${index}`}><strong>{text(warning.scope, "Record")}</strong> · {text(warning.detail, "An unspecified source qualification was recorded.")}</p>)}</aside>}

    <LocalModelResearchPanel data={data.local_model_research} />
    {showLab && <LabModelEvaluationPanel data={labData} pollingFailed={labPoll.failing} />}
    {showSupplement && <LabModelSupplementPanel data={supplementData} pollingFailed={supplementPoll.failing} />}
    {showCrossplan && <LabContextCrossplanPanel data={crossplanData} pollingFailed={crossplanPoll.failing} />}
    {showCap && <LabDiversityCapPanel data={capData} pollingFailed={capPoll.failing} />}
    <FollowonResultsPanel data={data.local_followon_results} />
    <ResearchPipelinePanel pipeline={data.research_pipeline} />
    <AppliedMarketResearchPanel data={data.applied_market_research} />

    {weeks.length === 0 ? <section className="benchmark-source-empty" role="status"><h2>{benchmarkSourcesUnavailable ? "Benchmark sources unavailable" : "No measured weeks yet"}</h2><p>{benchmarkSourcesUnavailable ? "Trial and evaluation sources were unavailable when this projection was generated. No benchmark history or zero result is inferred." : "The source is available, but it has not recorded a benchmark week. Missing history is not a zero score."}</p></section> : <>
      <section className="benchmark-week-section" aria-labelledby="benchmark-week-heading"><div className="benchmark-section-heading"><div><p className="benchmark-eyebrow">Timeline</p><h2 id="benchmark-week-heading">Recorded weeks</h2></div>
        <label>Selected week<select value={week?.week ?? ""} onChange={(event) => setSelectedWeek(event.target.value)}>{weeks.map((entry) => <option key={entry.week} value={entry.week}>{entry.week}</option>)}</select></label></div>
        <div className="benchmark-week-list">{weeks.map((entry) => <WeekButton key={entry.week} week={entry} selected={entry.week === week?.week} onSelect={() => setSelectedWeek(entry.week)} />)}</div>
      </section>

      {week && <section className="benchmark-family-section" aria-labelledby="benchmark-family-heading">
        <div className="benchmark-section-heading"><div><p className="benchmark-eyebrow">{week.week}</p><h2 id="benchmark-family-heading">Benchmark families</h2>
          <p>{rows(week.families).length} recorded families · review status: {humanize(week.review?.status).replace(/^review /, "")} · decision: {humanize(week.review?.decision)}</p></div>
          <div className="benchmark-filters"><label>Search<input type="search" value={query} placeholder="Family, status or verdict" onChange={(event) => setQuery(event.target.value)} /></label>
            <label>Show<select value={filter} onChange={(event) => setFilter(event.target.value as FamilyFilter)}><option value="all">All families</option><option value="measured">With measured arms</option><option value="comparable">Comparable only</option><option value="incomplete">Incomplete or failed</option></select></label></div>
        </div>
        <div className="benchmark-review-measurement"><div><span>Frontier review</span><strong>{humanize(week.review?.status)}</strong><small>{finite(week.review?.experiment_proposals) ? `${week.review.experiment_proposals} experiment ${week.review.experiment_proposals === 1 ? "proposal" : "proposals"}` : "Proposal count not recorded"} · {finite(week.review?.frontier_calls) ? `${week.review.frontier_calls} frontier calls` : "Call count not recorded"}</small></div>
          <div><span>Recorded evaluation</span><strong>{fmtCount(week.recorded_evaluations)} summaries · {fmtCount(week.complete_executions)} complete executions</strong><small>{finite(week.budget?.charged_minutes) ? `${fmtNumber(week.budget.charged_minutes, 1)} allowance min charged` : "Charge not recorded"}</small></div></div>
        {families.length > 0 ? <div className="benchmark-family-list">{families.map((family, index) => <FamilyCard key={text(family.id, `family-${index}`)} family={family} />)}</div>
          : rows(week.families).length === 0
            ? <div className="benchmark-filter-empty" role="status"><strong>No benchmark measurements recorded this week</strong><p>Frontier review activity is recorded separately from benchmark measurement. No benchmark result or zero score is inferred.</p></div>
            : <div className="benchmark-filter-empty" role="status"><strong>No matching benchmark families</strong><p>Change the search or filter. No zero results are inferred.</p></div>}
      </section>}
    </>}

    <footer className="benchmark-footnote">Source: <code>{BENCHMARK_PROGRESS_ENDPOINT}</code> · schema {text(data.schema_version)}. Hashes identify evidence; this page does not expose private filesystem paths.</footer>
  </section>;
}
