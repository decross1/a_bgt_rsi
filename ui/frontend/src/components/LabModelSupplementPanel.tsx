/** Fresh and context development diagnostics, independent of the primary 126. */
const SHA = /^[0-9a-f]{64}$/;
const observed = (value: unknown) => typeof value === "string" &&
  Number.isFinite(Date.parse(value)) && Date.now() - Date.parse(value) >= 0 &&
  Date.now() - Date.parse(value) <= 180_000;
const obj = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const count = (value: unknown, max: number): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= max;
const seconds = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100_000;
type Score = { declared: number; attempted: number; returned: number; timeout: number;
  error: number; cancelled: number; passed: number; wall_s_including_failures: number };
type Arm = { variant_id: string; elapsed_s: number; scores: Record<string, unknown>;
  configured_context_tokens?: number; output_reserve_tokens?: number;
  normalization_diagnostic?: Record<string, unknown> };
type Pair = { kind: "fresh" | "context"; pair_id: string; status: string;
  denominator_per_cohort: number; cohorts: { resident: Arm; flash: Arm } | null };
const ids = {
  fresh: { pair: "qfn-ab-lab-fresh-20260915-a", denominator: 12,
    grade: "raw_sse_and_all_12_fresh_primary_grades_per_cohort", resident: "resident-role-bundle" },
  context: { pair: "qfn-ab-lab-context-20260915-a", denominator: 36,
    grade: "raw_sse_and_all_36_context_objective_grades_per_cohort", resident: "resident-gemma" },
} as const;
const flashVariant = "mia-925d7be6-mtp3-reduced47k-v2opt-v1";

function score(value: unknown, denominator: number): Score | null {
  if (!obj(value) || value.declared !== denominator || value.attempted !== denominator ||
      !count(value.returned, denominator) || !count(value.timeout, denominator) ||
      !count(value.error, denominator) || !count(value.cancelled, denominator) ||
      !count(value.passed, denominator) || !seconds(value.wall_s_including_failures) ||
      value.returned + value.timeout + value.error + value.cancelled !== denominator ||
      value.passed > value.returned) return null;
  return value as Score;
}

function group(value: unknown, names: readonly string[], denominator: number): Record<string, Score> | null {
  if (!obj(value) || Object.keys(value).sort().join() !== [...names].sort().join()) return null;
  const shown: Record<string, Score> = {};
  for (const name of names) {
    const row = score(value[name], denominator);
    if (!row) return null;
    shown[name] = row;
  }
  return shown;
}

function pair(value: unknown, kind: "fresh" | "context"): Pair | null {
  const expected = ids[kind];
  if (!obj(value) || value.kind !== kind || value.pair_id !== expected.pair ||
      value.denominator_per_cohort !== expected.denominator ||
      value.promotion_authorized !== false) return null;
  if (value.status === "pending_publication" || value.status === "source_unavailable") {
    return value.cohorts === null && value.grade_replay === "not_available"
      ? { kind, pair_id: expected.pair, status: String(value.status),
          denominator_per_cohort: expected.denominator, cohorts: null } : null;
  }
  if (value.status !== "complete_admitted_pair" || value.grade_replay !== expected.grade ||
      !SHA.test(String(value.plan_raw_sha256)) ||
      !SHA.test(String(value.publication_index_raw_sha256)) ||
      !obj(value.cohorts) || Object.keys(value.cohorts).sort().join() !== "flash,resident") return null;
  const arms: Record<string, Arm> = {};
  for (const cohort of ["resident", "flash"] as const) {
    const arm = value.cohorts[cohort];
    if (!obj(arm) || arm.variant_id !== (cohort === "flash" ? flashVariant : expected.resident) ||
        !seconds(arm.elapsed_s) || !obj(arm.scores) ||
        !score(arm.scores.total, expected.denominator)) return null;
    const scores = arm.scores as Record<string, unknown>;
    if (kind === "fresh") {
      if (!group(scores.by_kind, ["science", "coding"], 6)) return null;
      const diagnostic = arm.normalization_diagnostic;
      if (!obj(diagnostic) || diagnostic.never_replaces_primary_score !== true ||
          !count(diagnostic.coding_returned_attempted, 6) ||
          !count(diagnostic.sandbox_passes_after_predeclared_transform, 6) ||
          diagnostic.sandbox_passes_after_predeclared_transform >
          diagnostic.coding_returned_attempted) return null;
    } else {
      if (!group(scores.by_capacity, ["8192", "16384", "32768"], 12) ||
          !group(scores.by_placement, ["early", "middle", "late"], 12) ||
          !obj(scores.by_capacity_placement) ||
          Object.keys(scores.by_capacity_placement).sort().join() !== "16384,32768,8192" ||
          ![8192, 16384, 32768].every(cap =>
            group((scores.by_capacity_placement as Record<string, unknown>)[String(cap)],
                  ["early", "middle", "late"], 4)) ||
          arm.configured_context_tokens !== 32768 || arm.output_reserve_tokens !== 2048 ||
          !obj(scores.measured_prompt_tokens_max_by_capacity) ||
          Object.keys(scores.measured_prompt_tokens_max_by_capacity).sort().join() !== "16384,32768,8192" ||
          ![8192, 16384, 32768].every(cap => {
            const tokens = (scores.measured_prompt_tokens_max_by_capacity as Record<string, unknown>)[String(cap)];
            return tokens === null || count(tokens, cap);
          })) return null;
    }
    arms[cohort] = arm as Arm;
  }
  return { kind, pair_id: expected.pair, status: "complete_admitted_pair",
    denominator_per_cohort: expected.denominator,
    cohorts: arms as { resident: Arm; flash: Arm } };
}

const rate = (item: Score) => item.wall_s_including_failures > 0
  ? (item.passed * 3600 / item.wall_s_including_failures).toFixed(1) + " / h" : "Unavailable";
const countLabel = (item: Score) => item.passed + " / " + item.declared;

export function LabModelSupplementPanel({ data, pollingFailed = false }: {
  data: unknown; pollingFailed?: boolean;
}) {
  const view = !pollingFailed && obj(data) &&
    data.schema_version === "lab-model-supplement-progress/v1" &&
    observed(data.observed_at) && data.original_scores_rebased === false &&
    data.private_content_exported === false && data.promotion_authorized === false &&
    obj(data.pairs) && Object.keys(data.pairs).sort().join() === "context,fresh" ? data : null;
  const fresh = pair(view?.pairs && (view.pairs as Record<string, unknown>).fresh, "fresh");
  const context = pair(view?.pairs && (view.pairs as Record<string, unknown>).context, "context");
  const freshScores = fresh?.cohorts;
  const contextScores = context?.cohorts;
  return <section className="research-pipeline local-model-research"
    aria-labelledby="lab-supplement-heading">
    <header className="research-pipeline-head"><div>
      <p className="benchmark-eyebrow">Separate local model studies</p>
      <h2 id="lab-supplement-heading">Fresh tasks and context quality</h2>
      <p>The 12 new science/coding tasks and 36 public context cells have their own plans and admission. They do not replace the primary 126-task scores.</p>
    </div><span className="benchmark-chip benchmark-chip--info">Supplemental development evidence</span></header>
    {!view && <p className="benchmark-empty-inline">Supplemental source observation unavailable; all scores are withheld.</p>}
    {view && <>
      <h3>Fresh science and coding · 12 cells per cohort</h3>
      {freshScores ? <>
        <p className="benchmark-empty-inline">Completed paired publication and private grade replay admitted. These are new synthetic development tasks, with no held-out or trading claim.</p>
        <div className="benchmark-table-wrap" role="region" tabIndex={0}
          aria-label="Fresh science and coding results, scroll horizontally"><table className="benchmark-table">
          <caption className="sr-only">Admitted fresh task pass counts, timeouts and observed task throughput</caption>
          <thead><tr><th scope="col">Task kind</th><th scope="col">Resident passed</th><th scope="col">Flash passed</th>
            <th scope="col">Resident timeouts</th><th scope="col">Flash timeouts</th>
            <th scope="col">Resident successful runs / hour</th><th scope="col">Flash successful runs / hour</th></tr></thead>
          <tbody>{(["science", "coding"] as const).map(name => {
            const resident = (freshScores.resident.scores.by_kind as Record<string, Score>)[name];
            const flash = (freshScores.flash.scores.by_kind as Record<string, Score>)[name];
            return <tr key={name}><th scope="row">{name === "science" ? "New quantitative games" : "New one-file repairs"}</th>
              <td>{countLabel(resident)}</td><td>{countLabel(flash)}</td>
              <td>{resident.timeout}</td><td>{flash.timeout}</td>
              <td>{rate(resident)}</td><td>{rate(flash)}</td></tr>;
          })}</tbody></table></div>
        <p className="benchmark-empty-inline">All fresh cells: resident {countLabel(freshScores.resident.scores.total as Score)}, Flash {countLabel(freshScores.flash.scores.total as Score)}. Each score keeps all attempted cells in the denominator.</p>
        <p className="benchmark-empty-inline">Separate predeclared coding normalization diagnostic: resident{" "}
          {String((freshScores.resident.normalization_diagnostic as Record<string, unknown>).sandbox_passes_after_predeclared_transform)}/
          {String((freshScores.resident.normalization_diagnostic as Record<string, unknown>).coding_returned_attempted)} returned coding attempts passed the sandbox after the transform; Flash{" "}
          {String((freshScores.flash.normalization_diagnostic as Record<string, unknown>).sandbox_passes_after_predeclared_transform)}/
          {String((freshScores.flash.normalization_diagnostic as Record<string, unknown>).coding_returned_attempted)}.
          The strict coding grades above are unchanged. This diagnostic is not a primary pass or rescued count.</p>
      </> : <p className="benchmark-empty-inline">{fresh?.status === "pending_publication"
        ? "Fresh pair publication pending; no pass or timing scores admitted yet."
        : "Fresh pair source or admission unavailable; scores withheld."}</p>}
      <h3>Public context quality · 8K, 16K, 32K total lanes</h3>
      {contextScores ? <>
        <p className="benchmark-empty-inline">Completed paired publication admitted. Each lane has 12 planned cells across early, middle and late answer positions.</p>
        <div className="benchmark-table-wrap" role="region" tabIndex={0}
          aria-label="Context quality by total capacity, scroll horizontally"><table className="benchmark-table">
          <caption className="sr-only">Admitted context quality by declared total capacity</caption>
          <thead><tr><th scope="col">Declared total lane</th><th scope="col">Resident Gemma passed</th><th scope="col">Flash passed</th>
            <th scope="col">Largest Resident Gemma prompt observed</th><th scope="col">Largest Flash prompt observed</th></tr></thead>
          <tbody>{(["8192", "16384", "32768"] as const).map(cap => {
            const resident = (contextScores.resident.scores.by_capacity as Record<string, Score>)[cap];
            const flash = (contextScores.flash.scores.by_capacity as Record<string, Score>)[cap];
            const residentPrompt = (contextScores.resident.scores.measured_prompt_tokens_max_by_capacity as Record<string, number | null>)[cap];
            const flashPrompt = (contextScores.flash.scores.measured_prompt_tokens_max_by_capacity as Record<string, number | null>)[cap];
            return <tr key={cap}><th scope="row">{Number(cap).toLocaleString()} tokens</th>
              <td>{countLabel(resident)}</td><td>{countLabel(flash)}</td>
              <td>{residentPrompt === null ? "Not recorded" : residentPrompt.toLocaleString()}</td>
              <td>{flashPrompt === null ? "Not recorded" : flashPrompt.toLocaleString()}</td></tr>;
          })}</tbody></table></div>
        <div className="benchmark-table-wrap" role="region" tabIndex={0}
          aria-label="Context quality by capacity and answer position, scroll horizontally"><table className="benchmark-table">
          <caption className="sr-only">Admitted context answers by total lane and answer position</caption>
          <thead><tr><th scope="col">Lane</th><th scope="col">Answer position</th>
            <th scope="col">Resident Gemma passed / planned</th><th scope="col">Flash passed / planned</th></tr></thead>
          <tbody>{(["8192", "16384", "32768"] as const).flatMap(cap =>
            (["early", "middle", "late"] as const).map(place => {
              const resident = ((contextScores.resident.scores.by_capacity_placement as Record<string, Record<string, Score>>)[cap])[place];
              const flash = ((contextScores.flash.scores.by_capacity_placement as Record<string, Record<string, Score>>)[cap])[place];
              return <tr key={cap + place}><th scope="row">{Number(cap).toLocaleString()} tokens</th>
                <td>{place}</td><td>{countLabel(resident)}</td><td>{countLabel(flash)}</td></tr>;
            }))}</tbody></table></div>
        <p className="benchmark-evidence-note">This table compares Resident Gemma with optimized Mia Flash. Qwen results, when admitted, belong to a separate cross-plan study. Both servers were configured at 32,768 total tokens with a 2,048-token output reserve. The tables show answer quality and actual prompt use in these three lanes. A prepared 64K packet or server flag is not a 64K quality result.</p>
      </> : <p className="benchmark-empty-inline">{context?.status === "pending_publication"
        ? "Context pair publication pending; tested quality is unknown."
        : "Context pair source or admission unavailable; quality scores withheld."}</p>}
    </>}
  </section>;
}
