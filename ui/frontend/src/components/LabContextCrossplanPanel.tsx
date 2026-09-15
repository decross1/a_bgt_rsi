import type { ReactNode } from "react";

type Arm = {
  declared: 12;
  attempted: 12;
  passed: number;
  returned: number;
  timeout: number;
  error: number;
  cancelled: number;
  measured_prompt_tokens_max: number | null;
};
type Categories = {
  qwen_only: number;
  mia_only: number;
  both_pass: number;
  neither_pass: number;
};
type Lane = {
  resident_qwen: Arm;
  flash_next_mia: Arm;
  matched_cell_pass_categories: Categories;
};
type Admitted = {
  by_capacity: Record<"8192" | "16384", Lane>;
};

const sha = (value: unknown): value is string =>
  typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const obj = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);
const keys = (value: Record<string, unknown>, expected: string[]) =>
  Object.keys(value).sort().join() === [...expected].sort().join();
const whole = (value: unknown, max: number): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= max;
const observed = (value: unknown) => typeof value === "string" &&
  Number.isFinite(Date.parse(value)) && Date.now() - Date.parse(value) >= 0 &&
  Date.now() - Date.parse(value) <= 180_000;

function arm(value: unknown, capacity: number): Arm | null {
  if (!obj(value) || !keys(value, [
    "declared", "attempted", "passed", "returned", "timeout", "error",
    "cancelled", "measured_prompt_tokens_max",
  ])) return null;
  if (value.declared !== 12 || value.attempted !== 12 ||
      !whole(value.passed, 12) || !whole(value.returned, 12) ||
      !whole(value.timeout, 12) || !whole(value.error, 12) ||
      !whole(value.cancelled, 12) ||
      (value.measured_prompt_tokens_max !== null &&
        !whole(value.measured_prompt_tokens_max, capacity - 2048)) ||
      value.passed > value.returned ||
      value.returned + value.timeout + value.error + value.cancelled !== 12) return null;
  return value as Arm;
}

function lane(value: unknown, capacity: number): Lane | null {
  if (!obj(value) || !keys(value, [
    "resident_qwen", "flash_next_mia", "matched_cell_pass_categories",
  ])) return null;
  const qwen = arm(value.resident_qwen, capacity);
  const flash = arm(value.flash_next_mia, capacity);
  const categories = value.matched_cell_pass_categories;
  if (!qwen || !flash || !obj(categories) || !keys(categories, [
    "qwen_only", "mia_only", "both_pass", "neither_pass",
  ]) || !whole(categories.qwen_only, 12) || !whole(categories.mia_only, 12) ||
      !whole(categories.both_pass, 12) || !whole(categories.neither_pass, 12) ||
      categories.qwen_only + categories.mia_only +
        categories.both_pass + categories.neither_pass !== 12 ||
      categories.qwen_only + categories.both_pass !== qwen.passed ||
      categories.mia_only + categories.both_pass !== flash.passed) return null;
  return { resident_qwen: qwen, flash_next_mia: flash,
    matched_cell_pass_categories: categories as Categories };
}

function admitted(data: unknown): Admitted | null {
  if (!obj(data) || data.schema_version !== "lab-context-crossplan-progress/v1" ||
      data.publication_id !== "qfn-context-qwen-mia-20260915-a" ||
      data.status !== "complete_cross_plan_diagnostic" ||
      !observed(data.observed_at) ||
      data.matched_cells !== 24 ||
      data.grade_replay !== "private_sse_and_all_24_qwen_all_36_mia_objective_grades" ||
      data.same_plan_pair !== false || data.promotion_authorized !== false ||
      data.private_content_exported !== false ||
      !sha(data.publication_index_raw_sha256) || !sha(data.overlap_receipts_sha256) ||
      data.qwen_window_id !== "qfn-ab-lab-context-qwen-20260915-a" ||
      data.mia_window_id !== "qfn-ab-lab-context-20260915-a" ||
      !obj(data.configured_total_tokens) ||
      !keys(data.configured_total_tokens, ["resident_qwen", "flash_next_mia"]) ||
      data.configured_total_tokens.resident_qwen !== 16384 ||
      data.configured_total_tokens.flash_next_mia !== 32768 ||
      !obj(data.by_capacity) || !keys(data.by_capacity, ["8192", "16384"])) return null;
  const eight = lane(data.by_capacity["8192"], 8192);
  const sixteen = lane(data.by_capacity["16384"], 16384);
  return eight && sixteen ? { by_capacity: { "8192": eight, "16384": sixteen } } : null;
}

const prompt = (value: number | null) =>
  value === null ? "Not recorded" : value.toLocaleString();
const count = (value: number) => value + " / 12";

export function LabContextCrossplanPanel({ data, pollingFailed = false }: {
  data: unknown; pollingFailed?: boolean;
}): ReactNode {
  const proof = !pollingFailed ? admitted(data) : null;
  const pending = obj(data) && data.schema_version === "lab-context-crossplan-progress/v1" &&
    data.publication_id === "qfn-context-qwen-mia-20260915-a" &&
    observed(data.observed_at) &&
    data.status === "pending_publication" && data.by_capacity === null &&
    data.publication_index_raw_sha256 === null &&
    data.grade_replay === "not_available" &&
    data.promotion_authorized === false && data.private_content_exported === false;
  return <section className="research-pipeline local-model-research"
    aria-labelledby="lab-qwen-context-heading">
    <header className="research-pipeline-head"><div>
      <p className="benchmark-eyebrow">Separate context study</p>
      <h2 id="lab-qwen-context-heading">Qwen and Flash at 8K and 16K</h2>
      <p>A matched 24-cell public development diagnostic across two independently frozen plans. The Flash rows use the first 24 cells of its admitted 36-cell context run.</p>
    </div><span className="benchmark-chip benchmark-chip--info">Cross-plan diagnostic</span></header>
    {proof ? <>
      <p className="benchmark-empty-inline">Both windows and private grades were admitted. Qwen was configured at 16,384 total tokens; optimized Flash at 32,768. Each measured lane reserves 2,048 output tokens.</p>
      <div className="benchmark-table-wrap" role="region" tabIndex={0}
        aria-label="Qwen and Flash matched context quality, scroll horizontally">
        <table className="benchmark-table">
          <caption className="sr-only">Admitted matched answer quality by total context lane</caption>
          <thead><tr><th scope="col">Total lane</th>
            <th scope="col">Qwen passed</th><th scope="col">Flash passed</th>
            <th scope="col">Qwen timeouts</th><th scope="col">Flash timeouts</th>
            <th scope="col">Largest Qwen prompt token count reported</th>
            <th scope="col">Largest Flash prompt token count reported</th></tr></thead>
          <tbody>{(["8192", "16384"] as const).map(cap => {
            const row = proof.by_capacity[cap];
            return <tr key={cap}><th scope="row">{Number(cap).toLocaleString()} tokens</th>
              <td>{count(row.resident_qwen.passed)}</td>
              <td>{count(row.flash_next_mia.passed)}</td>
              <td>{row.resident_qwen.timeout}</td><td>{row.flash_next_mia.timeout}</td>
              <td>{prompt(row.resident_qwen.measured_prompt_tokens_max)}</td>
              <td>{prompt(row.flash_next_mia.measured_prompt_tokens_max)}</td></tr>;
          })}</tbody>
        </table>
      </div>
      <p className="benchmark-evidence-note">Matched answers by lane:{" "}
        {(["8192", "16384"] as const).map((cap, index) => {
          const categories = proof.by_capacity[cap].matched_cell_pass_categories;
          return <span key={cap}>{index ? "; " : ""}
            {Number(cap).toLocaleString()} tokens — both {categories.both_pass},
            Qwen only {categories.qwen_only}, Flash only {categories.mia_only},
            neither {categories.neither_pass}</span>;
        })}. These are correlated fixture placements, not independent held-out tasks.
        No Qwen 32K result or standalone Flash arm of the Qwen plan was measured.
        This diagnostic does not authorize a primary-model change.</p>
    </> : <p className="benchmark-empty-inline">{pending && !pollingFailed
      ? "Qwen–Flash 24-cell publication pending; matched quality is unknown."
      : "Qwen–Flash cross-plan source or admission unavailable; all scores are withheld."}</p>}
  </section>;
}
