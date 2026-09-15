/** Five reused-task Mia cap diagnostic, separate from the original 126 cells. */
const SHA = /^[0-9a-f]{64}$/;
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const count = (value: unknown, max: number): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= max;
const seconds = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100_000;
const observed = (value: unknown) => typeof value === "string" &&
  Number.isFinite(Date.parse(value)) && Date.now() - Date.parse(value) >= 0 &&
  Date.now() - Date.parse(value) <= 180_000;

type Cap = { cap_tokens: number; condition_cells: number; generator_calls: number;
  generator_returned: number; generator_timeout: number; empty_visible_final: number;
  length_reasoning_only_empty: number; valid_proposals: number;
  selector_calls: number; selector_returned: number; selector_timeout: number;
  underlying_objective_success: number; creditable_protocol_pass: number };
type Result = { caps: Record<string, Cap>; paired_task_protocol_differences: Record<string, number>;
  recorded_evaluator_elapsed_s: number; source_replay: "publication_time_only" };
type View = { status: string; results: Result | null; replay_raw_sha256: string | null };

function cap(value: unknown, tokens: number): Cap | null {
  if (!object(value) || value.cap_tokens !== tokens || value.condition_cells !== 5 ||
      value.generator_calls !== 15 || value.selector_calls !== 5 ||
      !count(value.generator_returned, 15) || !count(value.generator_timeout, 15) ||
      !count(value.empty_visible_final, 15) ||
      !count(value.length_reasoning_only_empty, 15) ||
      !count(value.valid_proposals, 15) || !count(value.selector_returned, 5) ||
      !count(value.selector_timeout, 5) ||
      !count(value.underlying_objective_success, 5) ||
      !count(value.creditable_protocol_pass, 5) ||
      value.generator_returned + value.generator_timeout > 15 ||
      value.selector_returned + value.selector_timeout > 5 ||
      value.length_reasoning_only_empty > value.empty_visible_final ||
      value.empty_visible_final > value.generator_returned ||
      value.creditable_protocol_pass > value.underlying_objective_success) return null;
  return value as Cap;
}

function result(value: unknown): Result | null {
  if (!object(value) || value.source_replay !== "publication_time_only" ||
      !seconds(value.recorded_evaluator_elapsed_s) || !object(value.caps) ||
      Object.keys(value.caps).sort().join() !== "1536,384" ||
      !cap(value.caps["384"], 384) || !cap(value.caps["1536"], 1536) ||
      !object(value.paired_task_protocol_differences)) return null;
  const differences = value.paired_task_protocol_differences;
  const names = ["cap1536_pass_cap384_fail", "cap384_pass_cap1536_fail",
    "both_pass", "neither_pass"];
  if (Object.keys(differences).sort().join() !== [...names].sort().join() ||
      names.some(key => !count(differences[key], 5)) ||
      names.reduce((sum, key) => sum + Number(differences[key]), 0) !== 5) return null;
  return value as Result;
}

function view(data: unknown): View | null {
  if (!object(data) || data.schema_version !== "lab-diversity-cap-ui-progress/v1" ||
      !observed(data.observed_at) ||
      data.window_id !== "qfn-ab-lab-diversity-cap-20260915-a" ||
      data.original_primary_scores_changed !== false ||
      data.private_content_exported !== false ||
      data.promotion_authorized !== false ||
      data.comparison_eligible !== false) return null;
  const status = data.status;
  if (status === "closed_replay_admitted") {
    if (!SHA.test(String(data.plan_raw_sha256)) ||
        !SHA.test(String(data.window_raw_sha256)) ||
        !SHA.test(String(data.replay_raw_sha256))) return null;
    const results = result(data.results);
    return results ? { status, results, replay_raw_sha256: String(data.replay_raw_sha256) } : null;
  }
  return ["prepared_unissued", "execution_pending", "awaiting_admission",
    "incomplete_terminal", "source_unavailable"].includes(String(status)) &&
    data.results === null && data.replay_raw_sha256 === null
    ? { status: String(status), results: null, replay_raw_sha256: null } : null;
}

const pending = (status: string) => status === "prepared_unissued"
  ? "Frozen plan and window are prepared; no cap-study result has been admitted."
  : status === "execution_pending"
    ? "The cap window has begun or is being checked; results are withheld."
    : status === "awaiting_admission"
      ? "A terminal run is awaiting independent raw-response and grade replay; results are withheld."
      : status === "incomplete_terminal"
        ? "The window closed incomplete or failed; cap-quality counts are withheld."
        : "The exact cap source, window or replay is unavailable; cap-quality counts are withheld.";

export function LabDiversityCapPanel({ data, pollingFailed = false }: {
  data: unknown; pollingFailed?: boolean;
}) {
  const current = pollingFailed ? null : view(data);
  const scores = current?.results;
  return <section className="research-pipeline local-model-research"
    aria-labelledby="lab-diversity-cap-heading">
    <header className="research-pipeline-head"><div>
      <p className="benchmark-eyebrow">Separate reused-task diagnostic</p>
      <h2 id="lab-diversity-cap-heading">Mia proposal cap · 384 vs 1,536 tokens</h2>
      <p>Five reused diversity tasks, paired across two cap conditions. Each condition budgets three generator calls at 60 seconds and one selector at 20 seconds. This does not rescore the original 126 cells.</p>
    </div><span className="benchmark-chip benchmark-chip--info">Development diagnostic</span></header>
    {!scores ? <p className="benchmark-empty-inline">{current
      ? pending(current.status) : "Cap observation unavailable; all diagnostic counts are withheld."}</p> : <>
      <p className="benchmark-empty-inline">Exact closed-window replay admitted 40 private call streams and the unchanged diversity grader at publication. This page hashes archived public refs; it does not replay private streams on each poll.</p>
      <div className="benchmark-table-wrap" role="region" tabIndex={0}
        aria-label="Mia diversity cap results, scroll horizontally"><table className="benchmark-table">
        <caption className="sr-only">Admitted five-pair Mia diversity cap counts</caption>
        <thead><tr><th scope="col">Generator cap</th><th scope="col">Generators returned / 15</th>
          <th scope="col">Generator timeouts</th><th scope="col">Empty visible finals</th>
          <th scope="col">Length stopped, reasoning only</th><th scope="col">Valid proposals</th>
          <th scope="col">Selectors returned / 5</th><th scope="col">Selector timeouts</th>
          <th scope="col">Underlying objective / 5</th><th scope="col">Creditable protocol pass / 5</th></tr></thead>
        <tbody>{(["384", "1536"] as const).map(name => {
          const arm = scores.caps[name];
          return <tr key={name}><th scope="row">{Number(name).toLocaleString()} tokens</th>
            <td>{arm.generator_returned}/15</td><td>{arm.generator_timeout}</td>
            <td>{arm.empty_visible_final}</td><td>{arm.length_reasoning_only_empty}</td>
            <td>{arm.valid_proposals}</td><td>{arm.selector_returned}/5</td>
            <td>{arm.selector_timeout}</td><td>{arm.underlying_objective_success}/5</td>
            <td>{arm.creditable_protocol_pass}/5</td></tr>;
        })}</tbody></table></div>
      <p className="benchmark-empty-inline">Five paired task outcomes by protocol pass: 1,536 only {scores.paired_task_protocol_differences.cap1536_pass_cap384_fail}; 384 only {scores.paired_task_protocol_differences.cap384_pass_cap1536_fail}; both {scores.paired_task_protocol_differences.both_pass}; neither {scores.paired_task_protocol_differences.neither_pass}.</p>
      <p className="benchmark-evidence-note">Evaluator time {scores.recorded_evaluator_elapsed_s.toFixed(1)} s. Timing comes from the producer's recorded clock; raw-response replay does not independently verify elapsed time. The original 384-token cells also had a shorter 20-second generator timeout, so this equal-60-second pair is a separate intervention. These reused tasks do not establish held-out, causal or portfolio benefit.</p>
    </>}
  </section>;
}
