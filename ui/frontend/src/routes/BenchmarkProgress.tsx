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
import type {
  BenchmarkArm,
  BenchmarkComparisonPoint,
  BenchmarkFamily,
  BenchmarkProgressWarning,
  BenchmarkProgressResponse,
  BenchmarkWeek,
} from "../types/benchmarkProgress";
import "./benchmarkProgress.css";

interface Props {
  /** A test/story seam. `undefined` uses the live endpoint; null is a real empty source. */
  initial?: BenchmarkProgressResponse | null;
}

type FamilyFilter = "all" | "measured" | "comparable" | "incomplete";

const text = (value: unknown, fallback = "Not recorded"): string =>
  typeof value === "string" && value.trim() ? value : fallback;
const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
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
        <th scope="col">Arm</th><th scope="col">Graded result</th><th scope="col">Transport calls</th>
        <th scope="col">Timeouts</th><th scope="col">Success rate</th><th scope="col"><abbr title="Correct Task Throughput">CTT</abbr> / hour</th>
        <th scope="col"><abbr title="Reliable Success Rate: succeeds in at least two of three repeats">RSR 2 of 3</abbr></th><th scope="col">Recorded wall</th><th scope="col">Mean / transport attempt</th>
      </tr></thead>
      <tbody>{arms.map((arm, index) => {
        const metrics = arm.metrics ?? { success_rate: null, ctt_per_hour: null, rsr_2of3: null, recorded_wall_seconds: null, mean_recorded_seconds_per_transport_attempt: null, repair_rate: null, protocol_valid_rate: null, annotation_disagreements: null };
        const hasObjective = finite(arm.objective_successes) && finite(arm.objective_total);
        const hasRepair = finite(arm.repair_successes) && finite(arm.repair_total);
        return <tr key={text(arm.id, `arm-${index}`)}>
          <th scope="row"><strong>{text(arm.label, `Arm ${index + 1}`)}</strong><span>{text(arm.configuration, text(arm.id, "Configuration not recorded"))}</span></th>
          <td>{hasObjective ? <>{fmtCount(arm.objective_successes)} / {fmtCount(arm.objective_total)}<small> objective tasks</small></> : hasRepair ? <>{fmtCount(arm.repair_successes)} / {fmtCount(arm.repair_total)}<small> repair cases</small></> : <Missing label="Not graded" />}</td>
          <td>{finite(arm.transport_returned) && finite(arm.transport_expected) ? <>{fmtCount(arm.transport_returned)} / {fmtCount(arm.transport_expected)}<small> returned / expected</small></> : <Missing />}</td>
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
          <div><dt>Expected / returned / protocol-valid</dt><dd>{fmtCount(completeness.expected)} / {fmtCount(completeness.returned)} / {fmtCount(completeness.protocol_valid)}</dd></div>
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

export default function BenchmarkProgress({ initial }: Props) {
  const live = initial === undefined;
  const poll = usePolled(BENCHMARK_PROGRESS_POLL_KEY, getBenchmarkProgress, {
    intervalMs: 60_000,
    deadlineMs: 16_000,
    enabled: live,
  });
  const refreshing = usePollActivity(BENCHMARK_PROGRESS_POLL_KEY);
  const data = initial === undefined ? poll.data : initial;
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
    </section>;
  }

  if (data == null) {
    return <section className="page-full benchmark-progress" aria-labelledby="benchmark-progress-title">
      <header className="benchmark-page-head"><div><p className="benchmark-eyebrow">Operations</p><h1 id="benchmark-progress-title">Benchmark Progress</h1><p>Review decisions and benchmark results, week by week.</p></div></header>
      <section className="benchmark-source-empty" role="status"><h2>Unable to load benchmark history</h2>
        <p>{poll.failing ? `The latest read failed: ${String(poll.error)}. Missing history is withheld rather than shown as zero.` : "The weekly upgrade sources have not produced a progress record yet."}</p>
        {live && <button type="button" onClick={() => refreshPoll(BENCHMARK_PROGRESS_POLL_KEY)}>Retry</button>}
      </section>
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
        <h2 id="benchmark-outcome-heading">{text(summary.headline, upgradeLabel)}</h2>
        <p>{summary.upgrade_established === false ? "No upgrade has been established. " : ""}Operational review activity and measured capability are separate. More comparable measurements are needed to show progression.</p>
        <Link to="/ladder">Open Research for thesis evidence <span aria-hidden="true">→</span></Link>
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

    <aside className="benchmark-evidence-note"><strong>Evidence boundary</strong><span>Operator-recorded summaries are not scientific ground truth. Review-only automation scans and critiques proposals; it does not automatically rerun benchmark panels or promote changes.</span></aside>

    {(summaryMissing || rows<BenchmarkProgressWarning>(data.warnings).length > 0) && <aside className="benchmark-warnings" aria-label="Data qualifications">{summaryMissing && <p><strong>Progress summary</strong> · The response shape is incomplete. Missing values are withheld rather than inferred as zero.</p>}{rows<BenchmarkProgressWarning>(data.warnings).map((warning, index) => <p key={`${String(warning.code)}-${index}`}><strong>{text(warning.scope, "Record")}</strong> · {text(warning.detail, "An unspecified source qualification was recorded.")}</p>)}</aside>}

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
