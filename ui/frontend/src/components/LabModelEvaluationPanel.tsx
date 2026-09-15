/** Content-free, source-bound paired lab comparison. Live runs never supply scores. */

const SHA = /^[0-9a-f]{64}$/;
const PAIR = /^qfn-ab-lab-primary-20260915-[a-z]$/;
const FAMILIES = ["objective", "topic", "portfolio", "diversity", "role_effort", "historical", "context"] as const;
type Cohort = "resident" | "flash";
type Family = { declared: number; attempted: number; returned: number; timeout: number;
  error: number; cancelled: number; passed: number; wall_s_including_failures: number };
type CohortRow = { variant_id: string; declared: number; attempted: number; passed: number;
  timeout: number; elapsed_s: number; families: Record<string, Family>;
  configured_context_tokens_by_endpoint: Record<string, number>;
  measured_prompt_tokens_max_by_endpoint: Record<string, number | null> };
type Admitted = { resident: CohortRow; flash: CohortRow };

const whole = (value: unknown, max = 126): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= max;
const seconds = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100_000;
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

function admitted(data: unknown): Admitted | null {
  if (!object(data) || data.schema_version !== "lab-model-eval-progress/v1" ||
      typeof data.pair_id !== "string" || !PAIR.test(data.pair_id) ||
      data.status !== "complete_admitted_pair" ||
      data.source_status !== "current_source_replay_verified" ||
      data.grade_replay !== "raw_sse_and_all_126_primary_grades_per_cohort" ||
      data.promotion_authorized !== false || data.denominator !== 126 ||
      typeof data.plan_raw_sha256 !== "string" || !SHA.test(data.plan_raw_sha256) ||
      !object(data.cohorts) || Object.keys(data.cohorts).sort().join() !== "flash,resident") return null;
  const rows = data.cohorts as Record<Cohort, unknown>;
  for (const cohort of ["resident", "flash"] as const) {
    const row = rows[cohort];
    if (!object(row) || row.variant_id !== (cohort === "flash"
      ? "mia-925d7be6-mtp3-reduced47k-v2opt-v1" : "resident-role-bundle") ||
        row.declared !== 126 || !whole(row.attempted) || !whole(row.passed) ||
        !whole(row.timeout) || row.passed > row.attempted || !seconds(row.elapsed_s) ||
        !object(row.families) || FAMILIES.some(name => !Object.hasOwn(row.families as object, name)) ||
        Object.keys(row.families).length !== FAMILIES.length ||
        !object(row.configured_context_tokens_by_endpoint) ||
        !object(row.measured_prompt_tokens_max_by_endpoint)) return null;
    let declared = 0, attempted = 0, passed = 0;
    for (const name of FAMILIES) {
      const item = row.families[name];
      if (!object(item) || !whole(item.declared) || !whole(item.attempted) ||
          !whole(item.passed) || !whole(item.returned) || !whole(item.timeout) ||
          !whole(item.error) || !whole(item.cancelled) ||
          item.attempted > item.declared || item.passed > item.attempted ||
          !seconds(item.wall_s_including_failures)) return null;
      declared += item.declared; attempted += item.attempted; passed += item.passed;
    }
    if (declared !== 126 || attempted !== row.attempted || passed !== row.passed) return null;
    for (const [name, configured] of Object.entries(row.configured_context_tokens_by_endpoint)) {
      if (!["resident_qwen", "resident_gemma", "flash_next_mia"].includes(name) ||
          !whole(configured, 131_072)) return null;
    }
    for (const [name, measured] of Object.entries(row.measured_prompt_tokens_max_by_endpoint)) {
      if (!["resident_qwen", "resident_gemma", "flash_next_mia"].includes(name) ||
          (measured !== null && !whole(measured, 131_072))) return null;
    }
    if (Object.keys(row.configured_context_tokens_by_endpoint).sort().join() !==
        Object.keys(row.measured_prompt_tokens_max_by_endpoint).sort().join()) return null;
  }
  return rows as Admitted;
}

const labels: Record<(typeof FAMILIES)[number], string> = {
  objective: "Objective decisions", topic: "Topic output", portfolio: "Portfolio tasks",
  diversity: "Diversity repeats", role_effort: "Role and effort", historical: "Historical repairs",
  context: "Context tasks",
};
const throughput = (passed: number, wall_s: number) =>
  wall_s > 0 ? `${(passed * 3600 / wall_s).toFixed(1)} / h` : "Unavailable";
const contextLabel = (route: string) => ({resident_qwen: "Qwen", resident_gemma: "Gemma",
  flash_next_mia: "Optimized Mia Flash"})[route as "resident_qwen" | "resident_gemma" | "flash_next_mia"];

export function LabModelEvaluationPanel({ data, pollingFailed = false }: {
  data?: unknown; pollingFailed?: boolean;
}) {
  const proof = admitted(data);
  const prepared = object(data) && data.schema_version === "lab-model-eval-progress/v1" &&
    typeof data.pair_id === "string" && PAIR.test(data.pair_id) &&
    data.status === "pending_admission" &&
    data.source_status === "prepared_sources_verified" && data.denominator === 126 &&
    data.promotion_authorized === false && typeof data.plan_raw_sha256 === "string" &&
    SHA.test(data.plan_raw_sha256);
  const pairIds = object(data) && Array.isArray(data.registered_pair_ids)
    ? data.registered_pair_ids.filter((id): id is string => typeof id === "string" && PAIR.test(id))
    : [];
  return <section className="research-pipeline local-model-research" aria-labelledby="lab-model-eval-heading">
    <header className="research-pipeline-head"><div>
      <p className="benchmark-eyebrow">Local model research</p>
      <h2 id="lab-model-eval-heading">Optimized bundle paired evaluation</h2>
      <p>The reduced MTP3 Flash bundle and the resident Qwen/Gemma roles reuse the same 126 development tasks under newly declared policies.</p>
    </div><span className="benchmark-chip benchmark-chip--info">Separate paired study</span></header>
    {(proof || prepared) && object(data) && pairIds.length > 1 && pairIds[0] === data.pair_id &&
      <p className="benchmark-empty-inline">Showing newest registered pair {pairIds[0]}. Earlier registered window IDs remain in the research record; an unadmitted attempt is not a failed model score.</p>}
    {pollingFailed && <p className="benchmark-empty-inline" role="status">The latest source read failed. Previously displayed data may be stale.</p>}
    {proof ? <>
      <p><span className="benchmark-chip benchmark-chip--info">Completed pair admitted</span>{" "}
        Both windows restored the recorded services, and the publication reader rechecked current sources, exact runs, and 126 private grade-replay receipts per cohort. This is descriptive evidence; it does not authorize model promotion.</p>
      <div className="benchmark-table-wrap" role="region" tabIndex={0} aria-label="Optimized paired model families, scroll horizontally">
        <table className="benchmark-table"><caption className="sr-only">Admitted optimized Flash and resident family counts</caption>
          <thead><tr><th scope="col">Family</th><th scope="col">Resident passed / planned</th><th scope="col">Flash passed / planned</th>
            <th scope="col">Resident timeouts</th><th scope="col">Flash timeouts</th>
            <th scope="col">Resident successful task runs / hour</th><th scope="col">Flash successful task runs / hour</th></tr></thead>
          <tbody>{FAMILIES.map(name => {
            const resident = proof.resident.families[name], flash = proof.flash.families[name];
            return <tr key={name}><th scope="row">{labels[name]}</th>
              <td>{resident.passed} / {resident.declared}<small>{resident.attempted} attempted</small></td>
              <td>{flash.passed} / {flash.declared}<small>{flash.attempted} attempted</small></td>
              <td>{resident.timeout}</td><td>{flash.timeout}</td>
              <td>{throughput(resident.passed, resident.wall_s_including_failures)}</td>
              <td>{throughput(flash.passed, flash.wall_s_including_failures)}</td>
            </tr>;
          })}</tbody>
        </table>
      </div>
      <p className="benchmark-empty-inline">Whole run: residents {proof.resident.passed}/{proof.resident.declared} passed, {proof.resident.timeout} timeouts, {throughput(proof.resident.passed, proof.resident.elapsed_s)} successful runs/hour; optimized Flash {proof.flash.passed}/{proof.flash.declared} passed, {proof.flash.timeout} timeouts, {throughput(proof.flash.passed, proof.flash.elapsed_s)} successful runs/hour. Failed attempts remain in each planned denominator.</p>
      <div className="benchmark-table-wrap" role="region" tabIndex={0} aria-label="Configured and observed context, scroll horizontally"><table className="benchmark-table">
        <caption className="sr-only">Server capacity and actual measured prompt use</caption>
        <thead><tr><th scope="col">Route</th><th scope="col">Configured total context</th><th scope="col">Largest observed prompt</th></tr></thead>
        <tbody>{(["resident", "flash"] as Cohort[]).flatMap(cohort =>
          Object.entries(proof[cohort].configured_context_tokens_by_endpoint).map(([route, configured]) =>
            <tr key={route}><th scope="row">{contextLabel(route)}</th><td>{configured.toLocaleString()} tokens</td>
              <td>{proof[cohort].measured_prompt_tokens_max_by_endpoint[route] === null
                ? "Not recorded"
                : `${proof[cohort].measured_prompt_tokens_max_by_endpoint[route].toLocaleString()} tokens`}</td></tr>))}</tbody>
      </table></div>
      <p className="benchmark-evidence-note">Configured context is a server ceiling. Largest prompt use does not establish long-context answer quality; the separate context study must close before that claim. Task-run throughput includes time spent on failures, repeats, and grading. The 126 tasks are reused development fixtures, and model, runtime, and policies differ between bundles.</p>
    </> : prepared ? <p className="benchmark-empty-inline">A source-bound 126-task paired plan is frozen. The model windows are underway or awaiting completed admission; pass counts, throughput, and supported context are pending.</p>
      : <p className="benchmark-empty-inline">No current-source-admitted optimized pair is available. Scores are withheld when publication or source proof is missing. The earlier original pair and restored follow-on studies remain separate below.</p>}
  </section>;
}
