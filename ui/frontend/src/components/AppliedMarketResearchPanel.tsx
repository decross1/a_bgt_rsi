import type { AppliedMarketResearchProgress } from "../types/appliedMarketResearch";

const count = (value: unknown) => typeof value === "number" && Number.isFinite(value) && value >= 0
  ? value.toLocaleString() : "Not recorded";
const label = (value: string) => value.replaceAll("_", " ");

export function AppliedMarketResearchPanel({ data }: { data?: AppliedMarketResearchProgress }) {
  if (!data || data.schema_version !== "applied-market-research-progress/v1") return null;
  const batches = Array.isArray(data.batches) ? data.batches : [];
  return <section className="research-pipeline" aria-labelledby="applied-market-research-heading">
    <header className="research-pipeline-head"><div>
      <p className="benchmark-eyebrow">Game theory → empirical application</p>
      <h2 id="applied-market-research-heading">Market research pipeline</h2>
      <p>Test whether measured liquidity and signed flow improve hourly decisions over a matched momentum baseline.</p>
    </div><span className="benchmark-chip benchmark-chip--info">Paper research</span></header>
    <p>Public data → as-of features → matched tests → forward paper outcomes. Known theory can motivate an application without claiming a new theorem.</p>
    <div className="benchmark-table-wrap" role="region" tabIndex={0} aria-label="Market research stages, scroll horizontally">
      <table className="benchmark-table"><caption className="sr-only">Recorded market research stages</caption>
        <thead><tr>{data.stages.map(stage => <th scope="col" key={stage.id}>{stage.label}</th>)}</tr></thead>
        <tbody><tr>{data.stages.map(stage => <td key={stage.id}>{stage.status === "recorded" ? "Source receipts recorded" : "No accepted receipt yet"}</td>)}</tr></tbody>
      </table>
    </div>
    <p><strong>Strategy result: not tested.</strong> Source collection and model benchmark scores do not establish a trading edge. Historical trade records do not prove executable order-book prices.</p>
    {data.status === "not_started" ? <p className="benchmark-empty-inline">No collection batch has been recorded yet.</p>
      : data.status === "unavailable" ? <p className="benchmark-empty-inline">Collection evidence is unavailable or failed verification.</p> : null}
    {batches.length > 0 && <div className="benchmark-table-wrap" role="region" tabIndex={0} aria-label="Recent public-data captures, scroll horizontally">
      <table className="benchmark-table"><caption>Recent public-data captures · up to {count(data.max_recent_batches)} batches</caption>
        <thead><tr><th scope="col">Batch</th><th scope="col">Source status</th><th scope="col">GET requests</th><th scope="col">Response frames</th><th scope="col">Quote snapshot</th><th scope="col">Gaps / backlog</th></tr></thead>
        <tbody>{batches.map(batch => <tr key={batch.id}>
          <th scope="row"><strong>{batch.symbol ?? "Source unavailable"}</strong><small>{batch.sealed_at ?? batch.id}</small>{batch.batch_sha256 && <details className="benchmark-provenance"><summary>Receipt hash</summary><p>{batch.batch_sha256}</p></details>}</th>
          <td>{label(batch.status)}{batch.collector_source_status === "historical_source_unavailable" && <small>Historical collector source unavailable</small>}</td>
          <td>{count(batch.requests_succeeded)} / {count(batch.requests_attempted)}<small>succeeded / attempted · {count(batch.requests_failed)} failed</small></td>
          <td>{count(batch.source_valid_frames)}<small>{batch.collector_source_verified === true ? "Source checked" : batch.collector_source_status === "historical_source_unavailable" ? "Sealed raw frames; collector code unavailable" : "Unverified"}</small><small>{count(batch.trade_pages)} trade pages</small></td>
          <td>{batch.collector_source_verified !== true ? "Unverified" : batch.has_depth_snapshot ? "Recorded at local receipt time" : "No valid snapshot"}</td>
          <td>{batch.collector_source_verified !== true ? "Unknown" : batch.status !== "complete_incremental_batch" || batch.cursor_gap || batch.page_gap || batch.backlog_unresolved ? "Incomplete coverage" : "No gap inside this batch"}</td>
        </tr>)}</tbody>
      </table>
    </div>}
    {data.warnings?.length > 0 && <aside className="benchmark-warnings" aria-label="Market research evidence qualifications">{data.warnings.map((warning, index) => <p key={index}>{warning}</p>)}</aside>}
    <p className="benchmark-evidence-note">An initial capture is a warmup. A complete incremental batch does not establish continuous history across batches. This view reports source collection; later stages need their own measured receipts.</p>
  </section>;
}
