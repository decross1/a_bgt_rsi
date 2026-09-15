import type { LocalModelResearchProgress } from "../types/benchmarkProgress";

const number = (value: unknown, digits = 1) =>
  typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "Not recorded";
const label = (value: string) => value.replaceAll("_", " ");
const familyLabel = (value: string) => value === "topic" ? "Topic output protocol" : label(value);

export function LocalModelResearchPanel({ data }: { data?: LocalModelResearchProgress }) {
  if (!data || data.schema_version !== "local-model-research-progress/v1") return null;
  const qualifications = Array.isArray(data.qualification_runs) ? data.qualification_runs : [];
  const comparisons = Array.isArray(data.comparisons) ? data.comparisons : [];
  return <section className="research-pipeline local-model-research" aria-labelledby="local-model-research-heading">
    <header className="research-pipeline-head"><div>
      <p className="benchmark-eyebrow">Local model research</p>
      <h2 id="local-model-research-heading">Resident pair vs. {data.candidate}</h2>
      <p>Compare Gemma generation with Qwen criticism against Flash-Next in every local role.</p>
    </div><span className="benchmark-chip benchmark-chip--info">Evaluation only</span></header>
    <p>{data.accounting}</p>
    {data.status === "unavailable" ? <p className="benchmark-empty-inline">Local evaluation receipts are unavailable. No progress or result is inferred.</p> : <>
      <h3>Runtime qualification</h3>
      {qualifications.length === 0 ? <p className="benchmark-empty-inline">No qualification result recorded yet. Downloading the model does not establish that it runs reliably.</p> : <div className="benchmark-table-wrap" role="region" tabIndex={0} aria-label="Runtime qualification table, scroll horizontally"><table className="benchmark-table">
        <caption className="sr-only">Recorded Flash-Next runtime qualification</caption>
        <thead><tr><th scope="col">Run</th><th scope="col">Result</th><th scope="col">Candidate window</th><th scope="col">Host memory headroom</th><th scope="col">Probes</th><th scope="col">Resident restoration</th></tr></thead>
        <tbody>{qualifications.map(run => <tr key={run.id}>
          <th scope="row"><strong>{run.id}</strong><span>{run.finished_at ?? `Last recorded phase: ${label(run.phase)}`}</span></th>
          <td>{run.status === "unfinished_receipt" ? "Unfinished receipt · process state unverified" : run.status === "failed" && run.model_started === false ? "Setup failed · model not started" : label(run.status)}</td>
          <td>{run.model_started === false ? "Not started" : run.candidate_window_minutes === null ? "Not recorded" : `${number(run.candidate_window_minutes)} min maximum`}</td><td>{run.minimum_memory_gib === null ? "Not recorded" : `${number(run.minimum_memory_gib)} GiB minimum`}</td>
          <td>{number(run.probe_count, 0)}</td><td>{label(run.restoration)}</td>
        </tr>)}</tbody>
      </table></div>}
      {qualifications.length > 0 && <p className="benchmark-empty-inline">Candidate windows measure elapsed time, not GPU utilization. Host memory headroom includes setup and restoration.</p>}
      <h3>Paired benchmark evidence</h3>
      {comparisons.length === 0 ? <p className="benchmark-empty-inline">No validated paired run recorded yet. A runtime qualification pass is separate from a capability improvement.</p> : comparisons.map(comparison => <section key={comparison.id} aria-label={`Comparison ${comparison.id}`}>
        <h4>{comparison.id} · {label(comparison.status)}</h4>
        {(comparison.status !== "complete" || comparison.comparison_eligible !== true) && <p>Comparison incomplete or ineligible. Counts show recorded attempts; rates and gains are withheld.</p>}
        <div className="benchmark-table-wrap" role="region" tabIndex={0} aria-label={`Paired results for ${comparison.id}, scroll horizontally`}><table className="benchmark-table">
          <caption className="sr-only">Resident and Flash-Next task results</caption>
          <thead><tr><th scope="col">Family</th><th scope="col">Resident passed / planned</th><th scope="col">Flash passed / planned</th><th scope="col">Equal-source-task pass-rate delta (Flash − resident)</th><th scope="col">Resident successful runs/hour</th><th scope="col">Flash successful runs/hour</th></tr></thead>
          <tbody>{comparison.families.map(family => {
            const a = family.cohorts.resident, b = family.cohorts.flash;
            const eligible = comparison.status === "complete" && comparison.comparison_eligible === true && family.comparison_eligible === true;
            const delta = eligible ? family.equal_source_task_success_delta : null;
            const interval = eligible ? family.source_task_interval_95 : null;
            return <tr key={family.family}><th scope="row">{familyLabel(family.family)}</th>
              <td>{a.passed} / {a.declared}<small>{a.attempted} attempted</small></td><td>{b.passed} / {b.declared}<small>{b.attempted} attempted</small></td>
              <td>{typeof delta === "number" && Number.isFinite(delta) ? `${delta > 0 ? "+" : ""}${(delta * 100).toFixed(1)} pp` : "Withheld"}{Array.isArray(interval) && interval.length === 2 && interval.every(Number.isFinite) && <small>95% resampling interval: {(interval[0] * 100).toFixed(1)} to {(interval[1] * 100).toFixed(1)} pp</small>}</td>
              <td>{eligible ? number(a.successful_task_runs_per_hour) : "Withheld"}</td><td>{eligible ? number(b.successful_task_runs_per_hour) : "Withheld"}</td>
            </tr>;
          })}</tbody>
        </table></div>
        <details className="benchmark-provenance"><summary>Comparison provenance</summary><dl>
          <div className="benchmark-provenance-row"><dt>Frozen plan SHA256</dt><dd>{comparison.manifest_sha256}</dd></div>
          <div className="benchmark-provenance-row"><dt>Resident run SHA256</dt><dd>{comparison.run_sha256.resident}</dd></div>
          <div className="benchmark-provenance-row"><dt>Flash run SHA256</dt><dd>{comparison.run_sha256.flash}</dd></div>
        </dl></details>
      </section>)}
    </>}
    {data.warnings?.length > 0 && <aside className="benchmark-warnings" aria-label="Local model evidence qualifications">{data.warnings.map((warning, index) => <p key={index}>{warning}</p>)}</aside>}
    <p className="benchmark-evidence-note">{data.evidence_note} Task-run throughput includes failed attempts and grading time, and can include repeated tasks. Bundle differences include model, runtime, and inference policy.</p>
  </section>;
}
