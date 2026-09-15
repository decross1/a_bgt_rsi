/** Bounded historical reference and H1 forward status inside applied research. */
import type {
  AppliedReferenceProgress, HistoricalReferenceHorizon,
} from "../types/appliedReference";

const SHA = /^[0-9a-f]{64}$/;
const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const fmt = (value: number, digits = 2) =>
  finite(value) ? value.toFixed(digits) : "Unavailable";
const ci = (value: [number, number]) =>
  Array.isArray(value) && value.length === 2 && value.every(finite)
    ? `${fmt(value[0])} to ${fmt(value[1])}` : "Unavailable";

function admittedHistorical(data: AppliedReferenceProgress["historical_trade_only"]): boolean {
  return data.status === "recorded_reference_only" &&
    data.symbol === "BTCUSDT" && data.calendar_start === "2026-07-17" &&
    data.calendar_end === "2026-09-14" && data.source_days === 60 &&
    data.source_hours === 1440 && data.source_rehash_at_publication === true &&
    data.score_replay_at_publication === true &&
    ["not_performed", "verified", "unavailable"]
      .includes(data.current_source_replay ?? "") &&
    data.reference_roundtrip_cost_bps === 30 &&
    data.reference_doubled_roundtrip_cost_bps === 60 &&
    data.historical_executable_quotes_proven === false &&
    data.paper_forward_result === "not_tested" && data.orders_placed === 0 &&
    [data.publication_sha256, data.gate_sha256, data.result_sha256,
      data.private_predictions_sha256, data.runner_source_sha256,
      data.archive_adapter_source_sha256].every(value =>
      typeof value === "string" && SHA.test(value),
    ) &&
    Array.isArray(data.horizons) && data.horizons.length === 2 &&
    data.horizons[0].horizon_hours === 1 &&
    data.horizons[1].horizon_hours === 4 &&
    data.horizons.every(validHorizon);
}

function validHorizon(row: HistoricalReferenceHorizon): boolean {
  const n = row.horizon_hours === 1 ? 476 : 473;
  return row.validation_scored_rows === n &&
    [row.baseline_mse_bps2, row.flow_model_mse_bps2,
      row.mse_improvement_bps2, row.baseline_directional_accuracy,
      row.flow_model_directional_accuracy, row.directional_improvement,
      row.baseline_reference_net_bps_per_eligible_hour,
      row.flow_reference_net_bps_per_eligible_hour,
      row.baseline_doubled_reference_net_bps_per_eligible_hour,
      row.flow_doubled_reference_net_bps_per_eligible_hour].every(finite) &&
    row.baseline_mse_bps2 >= 0 && row.flow_model_mse_bps2 >= 0 &&
    row.baseline_directional_accuracy >= 0 && row.baseline_directional_accuracy <= 1 &&
    row.flow_model_directional_accuracy >= 0 && row.flow_model_directional_accuracy <= 1 &&
    [row.mse_improvement_95ci,
      row.directional_improvement_95ci].every(value =>
      Array.isArray(value) && value.length === 2 &&
      value.every(finite) && value[0] <= value[1],
    );
}

function recordedForward(data: AppliedReferenceProgress["forward_h1"]): boolean {
  return data.status === "rest_reference_recorded" &&
    data.rest_reference_plan_published === true &&
    data.rest_reference_result_published === true &&
    data.strict_paper_study_registered === false &&
    data.paper_supported === false && data.orders_placed === 0 &&
    data.nonexecutable_reference_only === true &&
    data.score_replay_at_publication === true &&
    data.external_plan_freeze_proof === "unverified" &&
    ["not_performed", "verified", "unavailable"]
      .includes(data.current_source_replay ?? "") &&
    typeof data.study_id === "string" &&
    /^h1-btcusdt-rest-[0-9]{8}-[a-z0-9]{3,16}$/.test(data.study_id) &&
    typeof data.scheduled_cells === "number" &&
    data.scheduled_cells >= 2 && data.scheduled_cells <= 5 &&
    typeof data.source_valid_cells === "number" &&
    data.source_valid_cells >= 0 &&
    data.source_valid_cells <= data.scheduled_cells &&
    data.unknown_outcome_cells === 0 &&
    [data.plan_publication_sha256, data.plan_sha256, data.topic_sha256,
      data.result_publication_sha256, data.result_sha256,
      data.private_cells_sha256].every(value =>
      typeof value === "string" && SHA.test(value)) &&
    data.all_scheduled_reference_net_bps != null &&
    finite(data.all_scheduled_reference_net_bps.candidate) &&
    finite(data.all_scheduled_reference_net_bps.baseline);
}

function recordedForwardStatus(data: AppliedReferenceProgress["forward_h1"],
                               stage: "rest_plan_published_local" |
                                      "closed_missing_source"): boolean {
  return data.status === stage &&
    data.rest_reference_plan_published === true &&
    data.rest_reference_result_published ===
      (stage === "closed_missing_source") &&
    data.strict_paper_study_registered === false &&
    data.paper_supported === false && data.orders_placed === 0 &&
    data.nonexecutable_reference_only === true &&
    data.external_plan_freeze_proof === "unverified" &&
    typeof data.study_id === "string" &&
    /^h1-btcusdt-rest-[0-9]{8}-[a-z0-9]{3,16}$/.test(data.study_id) &&
    [data.plan_publication_sha256, data.plan_sha256,
      data.topic_sha256].every(value =>
      typeof value === "string" && SHA.test(value)) &&
    (stage === "rest_plan_published_local" ||
      (typeof data.result_publication_sha256 === "string" &&
       SHA.test(data.result_publication_sha256) &&
       data.all_scheduled_reference_net_bps == null));
}

export function AppliedReferencePanel({ data }: { data?: AppliedReferenceProgress }) {
  if (!data || data.schema_version !== "applied-reference-progress/v1") return null;
  const historical = data.historical_trade_only;
  const accepted = admittedHistorical(historical);
  const forward = data.forward_h1;
  return <section className="research-pipeline" aria-labelledby="applied-reference-heading">
    <header className="research-pipeline-head"><div>
      <p className="benchmark-eyebrow">Application evidence</p>
      <h3 id="applied-reference-heading">Historical reference and forward H1</h3>
      <p>The trade-only baseline and REST displayed-quote study answer different questions.</p>
    </div><span className="benchmark-chip benchmark-chip--info">Reference only</span></header>
    <h4>Fixed 60-day trade-only baseline</h4>
    {!accepted ? <p className="benchmark-empty-inline">
      {historical.status === "source_unavailable"
        ? "The recorded source proof is unavailable; historical scores are withheld."
        : "The complete 60-day source gate and historical result have not been admitted. Forecast and reference-cost scores are withheld."}
    </p> : <>
      <p>BTCUSDT Spot · 2026-07-17 to 2026-09-14 · 60 complete days / 1,440 hours.
        The archived gate rehashed all 60 daily trade files and reran both scorers when published;
        {historical.current_source_replay === "verified"
          ? "current source replay is verified."
          : historical.current_source_replay === "unavailable"
            ? "current source replay is unavailable; archived admission remains recorded."
            : "current source replay has not been performed."}
        {" "}One hour is primary,
        four hours secondary. Historical last trades do not prove executable quotes or fills.</p>
      <div className="benchmark-table-wrap" role="region" tabIndex={0}
           aria-label="Historical trade-only horizons, scroll horizontally">
        <table className="benchmark-table"><caption className="sr-only">Admitted historical reference forecasts</caption>
          <thead><tr><th scope="col">Horizon</th><th scope="col">Validation hours</th>
            <th scope="col">MSE improvement · bps²</th><th scope="col">95% day CI · bps²</th>
            <th scope="col">Direction improvement</th><th scope="col">95% day CI</th>
            <th scope="col">Baseline reference · bps/hour</th>
            <th scope="col">Flow reference · bps/hour</th>
            <th scope="col">Doubled-cost baseline / flow</th></tr></thead>
          <tbody>{historical.horizons.map(row => <tr key={row.horizon_hours}>
            <th scope="row">{row.horizon_hours}h {row.horizon_hours === 1 ? "primary" : "secondary"}</th>
            <td>{row.validation_scored_rows}</td>
            <td>{fmt(row.mse_improvement_bps2)}</td><td>{ci(row.mse_improvement_95ci)}</td>
            <td>{fmt(100 * row.directional_improvement)} percentage points</td>
            <td>{ci([100 * row.directional_improvement_95ci[0],
                      100 * row.directional_improvement_95ci[1]])} points</td>
            <td>{fmt(row.baseline_reference_net_bps_per_eligible_hour)}</td>
            <td>{fmt(row.flow_reference_net_bps_per_eligible_hour)}</td>
            <td>{fmt(row.baseline_doubled_reference_net_bps_per_eligible_hour)} / {fmt(row.flow_doubled_reference_net_bps_per_eligible_hour)}</td>
          </tr>)}</tbody></table>
      </div>
      <p className="benchmark-evidence-note">Reference costs assume 30 bps roundtrip and 60 bps doubled;
        each score uses last-trade prices and the full untouched validation denominator.
        These numbers are forecast and cost diagnostics, not realized returns or a trading edge.</p>
      <details className="benchmark-provenance"><summary>Archived source hashes</summary><dl>
        <dt>Publication SHA256</dt><dd>{historical.publication_sha256}</dd>
        <dt>60-day gate SHA256</dt><dd>{historical.gate_sha256}</dd>
        <dt>Result SHA256</dt><dd>{historical.result_sha256}</dd>
        <dt>Archive adapter SHA256</dt><dd>{historical.archive_adapter_source_sha256}</dd>
      </dl></details>
    </>}
    <h4>H1 forward study</h4>
    <p>Known strategic-liquidity prior; current topic transfer is a design record.
      Public capture receipts are source evidence. The separately typed REST L5 study
      is a displayed-quote reference diagnostic and needs its own prestart plan and later result.</p>
    {recordedForward(forward)
      ? <p className="benchmark-evidence-note">
          A {forward.scheduled_cells}-decision REST reference window closed with
          all scheduled return outcomes identified; {forward.source_valid_cells} source-valid.
          Candidate {fmt(forward.all_scheduled_reference_net_bps!.candidate)}
          {" "}bps per scheduled hour; matched momentum reference{" "}
          {fmt(forward.all_scheduled_reference_net_bps!.baseline)} bps.
          These are displayed-quote diagnostics, not executable or paper returns.
          The archived due publication reran the reference grader and private cell ledger.
          The local plan freeze has no external preregistration proof.
          {forward.current_source_replay === "verified"
            ? " Current source replay is verified."
            : forward.current_source_replay === "unavailable"
              ? " Current source replay is unavailable; archived admission remains recorded."
              : " Current source replay has not been performed."}
        </p>
      : forward?.status === "topic_design_only"
      ? <p className="benchmark-empty-inline">No forward REST plan or result has been published.
          Strict sequence-admitted paper evidence is not registered.</p>
      : recordedForwardStatus(forward, "rest_plan_published_local")
        ? <p className="benchmark-empty-inline">A local REST reference plan is recorded;
            no forward result is due or admitted yet. Its local exclusive write is not externally verified preregistration.</p>
      : recordedForwardStatus(forward, "closed_missing_source")
        ? <p className="benchmark-empty-inline">The REST window closed with evidence unavailable.
              All-scheduled return scores are withheld; this is a nonexecutable diagnostic.</p>
          : <p className="benchmark-empty-inline">Forward source or result admission is unavailable.
              Scores are withheld.</p>}
    <p className="benchmark-evidence-note">REST snapshots do not establish venue book sequence,
      queue position or executable fills. The strict paper trial has no accepted source gate;
      no order is authorized or reported.</p>
    {Array.isArray(data.warnings) && data.warnings.length > 0 &&
      <aside className="benchmark-warnings" aria-label="Applied reference limitations">
        {data.warnings.map((warning, index) => <p key={index}>{warning}</p>)}
      </aside>}
  </section>;
}
