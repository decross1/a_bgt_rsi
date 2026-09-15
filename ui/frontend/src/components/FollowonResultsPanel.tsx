/** Content-free follow-on studies, admitted only after each supervisor restores. */
import type {
  FollowonResultsProgress, RecordedFollowonWindow,
} from "../types/followonResults";

const SHA256 = /^[0-9a-f]{64}$/;
const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0;
const number = (value: unknown, digits = 1) =>
  finite(value) ? value.toFixed(digits) : "Unavailable";
const words = (value: string) => value.replaceAll("_", " ");
const routeLabel = (value: RecordedFollowonWindow["routes"][number]) => ({
  resident_qwen: "Qwen resident",
  resident_gemma: "Gemma resident",
  flash_next_mia: "Mia Flash candidate",
})[value];

function isRecorded(window: RecordedFollowonWindow): boolean {
  const routes = Array.isArray(window.routes) ? window.routes : [];
  const allowedRoutes = window.cohort === "flash"
    ? ["flash_next_mia"] : ["resident_qwen", "resident_gemma"];
  return window.status === "recorded_admitted" &&
    window.admission_class === "RECORDED_COMPLETED_WINDOW_ADMISSION" &&
    window.report_schema === "flash-followon-content-free-report/v1" &&
    window.exact_restoration_verified === true &&
    window.comparison_eligible === false &&
    routes.length > 0 && routes.length <= 2 &&
    routes.every(route => allowedRoutes.includes(route)) &&
    [window.report_sha256, window.admission_sha256,
      window.recorded_controller_source_bundle_sha256,
      window.window_plan_sha256, window.result_sha256].every(
      value => typeof value === "string" && SHA256.test(value),
    ) &&
    ["not_performed", "verified", "unavailable"].includes(window.current_source_replay);
}

export function FollowonResultsPanel({ data }: { data?: FollowonResultsProgress }) {
  if (!data || data.schema_version !== "local-followon-results-progress/v1") return null;
  const windows = Array.isArray(data.windows) ? data.windows : [];
  return <section className="research-pipeline local-model-research" aria-labelledby="followon-heading">
    <header className="research-pipeline-head"><div>
      <p className="benchmark-eyebrow">Local model research</p>
      <h2 id="followon-heading">Follow-on thinking, validity, and context studies</h2>
      <p>Each block is reported after its supervised window closes and the recorded service state is restored.</p>
    </div><span className="benchmark-chip benchmark-chip--info">Descriptive studies</span></header>
    {windows.length === 0
      ? <p className="benchmark-empty-inline">No restored follow-on window has a recorded admission receipt. Live task results and gains are withheld.</p>
      : windows.map(window => {
        const admitted = isRecorded(window);
        return <section key={window.id} aria-label={`${window.cohort} follow-on ${window.id}`}>
          <h3>{window.cohort === "flash" ? "Flash candidate" : "Resident models"} · {window.id}</h3>
          {!admitted ? <p className="benchmark-empty-inline">Window incomplete or source proof unavailable. Task scores and timing are withheld.</p> : <>
            <p><span className="benchmark-chip benchmark-chip--info">Restored window admitted</span>{" "}
              Tested model: {window.routes.map(routeLabel).join(", ")}. {" "}
              {window.current_source_replay === "verified"
                ? "Its recorded evidence passes source replay now."
                : window.current_source_replay === "unavailable"
                  ? "Its recorded bytes remain verified; current source replay is unavailable."
                  : "Its recorded bytes remain verified; current source replay has not been performed."}
            </p>
            <div className="benchmark-table-wrap" role="region" tabIndex={0}
                 aria-label={`${window.cohort} follow-on conditions, scroll horizontally`}>
              <table className="benchmark-table"><caption className="sr-only">Admitted follow-on condition outcomes</caption>
                <thead><tr><th scope="col">Block / condition</th><th scope="col">Passed / planned</th>
                  <th scope="col">Attempted</th><th scope="col">Timeouts</th>
                  <th scope="col">Errors</th><th scope="col">Context support</th>
                  <th scope="col">Recorded wall</th><th scope="col">Request latency</th>
                  <th scope="col">First token</th><th scope="col">Context input</th></tr></thead>
                <tbody>{window.blocks.flatMap(block => block.groups.map((group, index) =>
                  <tr key={`${block.block_id}-${index}`}><th scope="row"><strong>{words(block.kind)}</strong>
                    <span>{group.condition.map(words).join(" · ")}</span></th>
                    <td>{block.passed === null ? "Timing only" : `${group.passed} / ${group.declared}`}</td><td>{group.attempted}</td>
                    <td>{group.timeouts}</td><td>{group.errors}</td>
                    <td>{block.kind === "context" ? `${group.supported} / ${group.declared}` : "—"}</td>
                    <td>{number(group.wall_seconds)} s</td>
                    <td>{group.recorded_timings > 0 && group.mean_request_latency_seconds !== null
                      ? `${number(group.mean_request_latency_seconds)} s` : "Unavailable"}</td>
                    <td>{group.mean_first_token_seconds === null ? "Unavailable" : `${number(group.mean_first_token_seconds)} s`}</td>
                    <td>{group.actual_input_tokens_min === null || group.actual_input_tokens_max === null
                      ? "—" : `${group.actual_input_tokens_min.toLocaleString()}–${group.actual_input_tokens_max.toLocaleString()} tokens`}</td>
                  </tr>,
                ))}</tbody></table></div>
            {window.blocks.filter(block => block.kind === "selected_repair").map(block => {
              const replay = block.grader_replay;
              const bound = replay?.schema === "flash-followon-selected-repair-grader-replay/v1" &&
                replay.run_sha256 === block.run_sha256 &&
                SHA256.test(replay.replay_receipt_sha256) &&
                replay.comparison_eligible === false;
              return <p key={`${block.block_id}-grader-check`} className="benchmark-evidence-note">
                <strong>Independent repair grade check:</strong>{" "}
                {!bound || !replay
                  ? "Not recorded for this restored window. The table shows recorded producer grades only."
                  : replay.source_replay_status === "unavailable"
                    ? `Original grader replay unavailable for ${replay.declared} attempted repairs; recorded grades are shown separately.`
                    : `${replay.producer_consistent} of ${replay.declared} recorded grades reproduced; ${replay.grader_unavailable} could not be rerun; ${replay.producer_inconsistent} differed. This check was recorded at report publication.`}
              </p>;
            })}
            <details className="benchmark-provenance"><summary>Recorded sources</summary><dl>
              <dt>Admission SHA256</dt><dd>{window.admission_sha256}</dd>
              <dt>Recorded controller code SHA256</dt><dd>{window.recorded_controller_source_bundle_sha256}</dd>
              <dt>Report SHA256</dt><dd>{window.report_sha256}</dd>
              <dt>Frozen window SHA256</dt><dd>{window.window_plan_sha256}</dd>
              <dt>Result SHA256</dt><dd>{window.result_sha256}</dd>
            </dl></details>
          </>}
        </section>;
      })}
    {Array.isArray(data.warnings) && data.warnings.length > 0 &&
      <aside className="benchmark-warnings" aria-label="Follow-on evidence limitations">
        {data.warnings.map((warning, index) => <p key={index}>{warning}</p>)}
      </aside>}
    <p className="benchmark-evidence-note">These block counts include timeouts in the planned denominator.
      Request latency and first-token timing are shown only when recorded by the transport.
      Shared blocks describe this selected study; they are separate from the original paired benchmark and do not authorize promotion.</p>
  </section>;
}
