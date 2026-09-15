const SHA = /^[0-9a-f]{64}$/;
const WINDOW_ID = "qfn-followon-payoff-tool-20260915-a";

const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const count = (value: unknown, max: number): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= max;
const seconds = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 600;

type Results = {
  declared_pairs: 6; declared_conditions_per_arm: 6; declared_slots: 18;
  issued_calls: number;
  direct: { strict_shape: number; strict_both_correct: number };
  tool: { native_calls_parsed: number; native_calls_executed: number;
    final_calls_issued: number; causal_final_skips: number;
    strict_shape: number; strict_both_correct: number };
  recorded_evaluator_elapsed_s: number; source_replay: "publication_time_only";
};
type View = { status: string; results: Results | null };

function results(value: unknown): Results | null {
  if (!object(value) || value.declared_pairs !== 6 ||
      value.declared_conditions_per_arm !== 6 || value.declared_slots !== 18 ||
      value.source_replay !== "publication_time_only" ||
      !count(value.issued_calls, 18) || !seconds(value.recorded_evaluator_elapsed_s) ||
      !object(value.direct) || !object(value.tool)) return null;
  const direct = value.direct;
  const tool = value.tool;
  if (!count(direct.strict_shape, 6) || !count(direct.strict_both_correct, 6) ||
      direct.strict_both_correct > direct.strict_shape ||
      !count(tool.native_calls_parsed, 6) || !count(tool.native_calls_executed, 6) ||
      !count(tool.final_calls_issued, 6) || !count(tool.causal_final_skips, 6) ||
      !count(tool.strict_shape, 6) || !count(tool.strict_both_correct, 6) ||
      tool.native_calls_executed > tool.native_calls_parsed ||
      tool.native_calls_executed !== tool.final_calls_issued ||
      tool.final_calls_issued + tool.causal_final_skips !== 6 ||
      value.issued_calls !== 12 + tool.final_calls_issued ||
      tool.strict_shape > tool.final_calls_issued ||
      tool.strict_both_correct > tool.strict_shape) return null;
  return value as Results;
}

function view(value: unknown): View | null {
  if (!object(value) || value.schema_version !== "payoff-tool-study-ui-progress/v1" ||
      value.window_id !== WINDOW_ID ||
      !Number.isFinite(Date.parse(String(value.observed_at))) ||
      value.private_content_exported !== false ||
      value.comparison_eligible !== false ||
      value.promotion_authorized !== false ||
      value.trading_claim_authorized !== false) return null;
  const status = value.status;
  if (status === "closed_admitted") {
    const result = results(value.results);
    return result && SHA.test(String(value.plan_raw_sha256)) &&
      SHA.test(String(value.window_raw_sha256)) &&
      SHA.test(String(value.admission_raw_sha256))
      ? { status, results: result } : null;
  }
  if (status !== "source_unavailable" &&
      (!SHA.test(String(value.plan_raw_sha256)) ||
       !SHA.test(String(value.window_raw_sha256)))) return null;
  return ["prepared_unissued", "execution_pending", "awaiting_admission",
    "aborted_unadmitted", "source_unavailable"].includes(String(status)) &&
    value.results === null && value.admission_raw_sha256 === null
    ? { status: String(status), results: null } : null;
}

function pending(status: string): string {
  if (status === "prepared_unissued")
    return "Frozen six-pair plan and resident window are prepared; no calls or arithmetic scores are admitted.";
  if (status === "execution_pending")
    return "The resident study is running or awaiting its supervisor; arithmetic scores are withheld.";
  if (status === "awaiting_admission")
    return "The window closed; exact restoration and private raw-response and grade replay are awaiting publication.";
  if (status === "aborted_unadmitted")
    return "The window closed incomplete or failed. No payoff-tool quality result is admitted.";
  return "The registered plan, window or admission source is unavailable. All arithmetic counts are withheld.";
}

export function PayoffToolStudyPanel({ data, pollingFailed = false }: {
  data: unknown; pollingFailed?: boolean;
}) {
  const current = pollingFailed ? null : view(data);
  const score = current?.results;
  return <section className="research-pipeline local-model-research"
    aria-labelledby="payoff-tool-study-heading">
    <header className="research-pipeline-head"><div>
      <p className="benchmark-eyebrow">Separate native-tool diagnostic</p>
      <h2 id="payoff-tool-study-heading">Gemma payoff arithmetic · direct vs calculator</h2>
      <p>Six fresh public-goods inputs are paired across direct answers and a native shared-return tool condition. The tool condition has a first call and, only after a valid tool request, a final answer call. All six conditions per arm remain in the denominator.</p>
    </div><span className="benchmark-chip benchmark-chip--info">Instrument study</span></header>
    {!score ? <p className="benchmark-empty-inline">{current ? pending(current.status) :
      "Payoff-tool observation unavailable; arithmetic counts are withheld."}</p> : <>
      <p className="benchmark-empty-inline">A one-time terminal admission checked exact resident restoration and replayed private tool calls, raw responses and arithmetic grades. This page rehashes bounded public files; it does not replay private streams on every poll.</p>
      <div className="benchmark-table-wrap" role="region" tabIndex={0}
        aria-label="Gemma direct and native-tool payoff arithmetic results, scroll horizontally">
        <table className="benchmark-table">
          <caption className="sr-only">Admitted six-pair payoff arithmetic counts</caption>
          <thead><tr><th scope="col">Condition</th><th scope="col">Strict JSON/rational shape / 6</th>
            <th scope="col">Strict focal and total correct / 6</th>
            <th scope="col">Native tool calls parsed / 6</th><th scope="col">Native tool calls executed / 6</th>
            <th scope="col">Final calls issued / 6</th><th scope="col">Causal final skips / 6</th></tr></thead>
          <tbody><tr><th scope="row">Direct answer</th>
            <td>{score.direct.strict_shape}/6</td><td>{score.direct.strict_both_correct}/6</td>
            <td>—</td><td>—</td><td>—</td><td>—</td></tr>
            <tr><th scope="row">Native shared-return tool</th>
              <td>{score.tool.strict_shape}/6</td><td>{score.tool.strict_both_correct}/6</td>
              <td>{score.tool.native_calls_parsed}/6</td>
              <td>{score.tool.native_calls_executed}/6</td>
              <td>{score.tool.final_calls_issued}/6</td>
              <td>{score.tool.causal_final_skips}/6</td></tr></tbody>
        </table></div>
      <p className="benchmark-evidence-note">{score.issued_calls} of 18 scheduled call slots were issued; skipped final slots remain accounted for. Evaluator time {score.recorded_evaluator_elapsed_s.toFixed(1)} s excludes setup and restoration and comes from the producer's clock. The calculator returns only the shared group return. These six inputs do not establish strategy quality, a causal model benefit, or trading value.</p>
    </>}
  </section>;
}
