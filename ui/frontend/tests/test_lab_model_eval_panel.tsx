import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LabModelEvaluationPanel } from "../src/components/LabModelEvaluationPanel";
import BenchmarkProgress from "../src/routes/BenchmarkProgress";

const sha = "a".repeat(64);
const pair = "qfn-ab-lab-primary-20260915-b";
const counts = { objective: 24, topic: 48, portfolio: 16, diversity: 10,
  role_effort: 18, historical: 6, context: 4 };
const families = Object.fromEntries(Object.entries(counts).map(([name, declared]) =>
  [name, { declared, attempted: declared, returned: declared, timeout: 0,
    error: 0, cancelled: 0, passed: declared, wall_s_including_failures: 60 } ]));
const cohort = (name: "resident" | "flash") => ({
  variant_id: name === "resident" ? "resident-role-bundle"
    : "mia-925d7be6-mtp3-reduced47k-v2opt-v1",
  declared: 126, attempted: 126, passed: 126, timeout: 0, elapsed_s: 600,
  families,
  configured_context_tokens_by_endpoint: name === "resident"
    ? { resident_qwen: 16384, resident_gemma: 32768 } : { flash_next_mia: 32768 },
  measured_prompt_tokens_max_by_endpoint: name === "resident"
    ? { resident_qwen: 12000, resident_gemma: 14400 } : { flash_next_mia: 14400 },
});
const admitted = {
  schema_version: "lab-model-eval-progress/v1", pair_id: pair,
  status: "complete_admitted_pair", denominator: 126, plan_raw_sha256: sha,
  source_status: "current_source_replay_verified",
  grade_replay: "raw_sse_and_all_126_primary_grades_per_cohort",
  promotion_authorized: false, registered_pair_ids: [pair, "qfn-ab-lab-primary-20260915-a"],
  cohorts: { resident: cohort("resident"), flash: cohort("flash") },
};
const pending = {
  ...admitted, status: "pending_admission", source_status: "prepared_sources_verified",
  grade_replay: "not_available", cohorts: null,
  provisional_execution: {
    resident: { schema_version: "lab-model-eval-execution/v1",
      cohort: "resident", plan_raw_sha256: sha,
      status: "recorded_prefix", recorded_cells: 13,
      checkpoint_raw_sha256: sha, run_raw_sha256: null },
    flash: { schema_version: "lab-model-eval-execution/v1",
      cohort: "flash", plan_raw_sha256: sha,
      status: "prepared", recorded_cells: null,
      checkpoint_raw_sha256: null, run_raw_sha256: null },
  },
};

describe("paired lab model publication", () => {
  it("shows only pending status for a frozen but incomplete pair", () => {
    render(<LabModelEvaluationPanel data={{ ...admitted, status: "pending_admission",
      source_status: "prepared_sources_verified", grade_replay: "not_available", cohorts: null }} />);
    expect(screen.getByText(/source-bound 126-task paired plan is frozen/)).toBeInTheDocument();
    expect(screen.queryByText("24 / 24")).not.toBeInTheDocument();
    expect(screen.getByText(/Earlier registered window IDs remain/)).toBeInTheDocument();
  });

  it("labels bound checkpoint order as provisional execution without grades", () => {
    const { rerender } = render(<LabModelEvaluationPanel data={pending} />);
    expect(screen.getByText(/Resident: 13\/126 cells recorded/)).toBeInTheDocument();
    expect(screen.getByText(/Flash: prepared/)).toBeInTheDocument();
    expect(screen.getByText(/A recorded cell may be a failed or skipped task/))
      .toBeInTheDocument();
    expect(screen.queryByText("24 / 24")).not.toBeInTheDocument();
    rerender(<LabModelEvaluationPanel data={{ ...pending, provisional_execution: {
      ...pending.provisional_execution,
      resident: { ...pending.provisional_execution.resident,
        status: "awaiting_verification", recorded_cells: null,
        checkpoint_raw_sha256: null, run_raw_sha256: sha },
    } }} />);
    expect(screen.getByText(/Resident: recorded run awaiting verification/)).toBeInTheDocument();
    expect(screen.queryByText(/Resident: 13\/126 cells recorded/)).not.toBeInTheDocument();
  });

  it("withholds provisional count on stale polling or unbound execution receipt", () => {
    const { rerender } = render(<LabModelEvaluationPanel data={pending} pollingFailed />);
    expect(screen.queryByText(/Resident: 13\/126 cells recorded/)).not.toBeInTheDocument();
    rerender(<LabModelEvaluationPanel data={{ ...pending, provisional_execution: {
      ...pending.provisional_execution,
      resident: { ...pending.provisional_execution.resident,
        checkpoint_raw_sha256: null },
    } }} />);
    expect(screen.queryByText(/Resident: 13\/126 cells recorded/)).not.toBeInTheDocument();
    rerender(<LabModelEvaluationPanel data={{ ...pending,
      source_status: "unverified" }} />);
    expect(screen.queryByText(/Resident: 13\/126 cells recorded/)).not.toBeInTheDocument();
    rerender(<LabModelEvaluationPanel data={{ ...pending, provisional_execution: {
      ...pending.provisional_execution,
      resident: { ...pending.provisional_execution.resident, cohort: "flash" },
    } }} />);
    expect(screen.queryByText(/Resident: 13\/126 cells recorded/)).not.toBeInTheDocument();
  });

  it("shows admitted family denominators, throughput and measured versus configured context", () => {
    render(<LabModelEvaluationPanel data={admitted} />);
    expect(screen.getByText(/Both windows restored the recorded services/)).toBeInTheDocument();
    expect(screen.getAllByText("24 / 24")).toHaveLength(2);
    expect(screen.getByRole("region", { name: /Optimized paired model families/ }))
      .toHaveAttribute("tabindex", "0");
    expect(screen.getByText(/Configured context is a server ceiling/)).toBeInTheDocument();
    expect(screen.getAllByText("32,768 tokens")).toHaveLength(2);
    expect(screen.getAllByText("14,400 tokens")).toHaveLength(2);
    expect(screen.getByText(/does not authorize model promotion/)).toBeInTheDocument();
  });

  it("withholds a re-sealed overcount or unbound source receipt", () => {
    const overcount = { ...admitted, cohorts: { ...admitted.cohorts,
      flash: { ...admitted.cohorts.flash, passed: 127 } } };
    const { rerender } = render(<LabModelEvaluationPanel data={overcount} />);
    expect(screen.getByText(/Scores are withheld/)).toBeInTheDocument();
    expect(screen.queryByText("24 / 24")).not.toBeInTheDocument();
    rerender(<LabModelEvaluationPanel data={{ ...admitted, plan_raw_sha256: null }} />);
    expect(screen.queryByText("24 / 24")).not.toBeInTheDocument();
    rerender(<LabModelEvaluationPanel data={{ ...admitted, grade_replay: "not_available" }} />);
    expect(screen.queryByText("24 / 24")).not.toBeInTheDocument();
  });

  it("keeps independent lab status visible when weekly history is unavailable", () => {
    render(<BenchmarkProgress initial={null} initialLab={{ ...admitted,
      status: "pending_admission", source_status: "prepared_sources_verified",
      grade_replay: "not_available", cohorts: null }} />);
    expect(screen.getByText("Unable to load benchmark history")).toBeInTheDocument();
    expect(screen.getByText("Optimized bundle paired evaluation")).toBeInTheDocument();
    expect(screen.getByText(/source-bound 126-task paired plan is frozen/)).toBeInTheDocument();
  });
});
