import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LocalModelResearchPanel } from "../src/components/LocalModelResearchPanel";
import type { LocalModelResearchProgress } from "../src/types/benchmarkProgress";

const base: LocalModelResearchProgress = {
  schema_version: "local-model-research-progress/v1", status: "available",
  candidate: "Qwen3.8 Flash-Next", accounting: "Outside the weekly maintenance allowance.",
  evidence_note: "Public development evidence only.", promotion_authorized: false,
  qualification_runs: [], comparisons: [], warnings: [],
};

describe("local model research", () => {
  it("shows pending work without invented scores", () => {
    render(<LocalModelResearchPanel data={base} />);
    expect(screen.getByText(/No qualification result recorded/)).toBeInTheDocument();
    expect(screen.getByText(/No validated paired run/)).toBeInTheDocument();
    expect(screen.getByText(/Outside the weekly/)).toBeInTheDocument();
  });
  it("does not interpret an orphan state as a live process", () => {
    render(<LocalModelResearchPanel data={{ ...base, qualification_runs: [{
      id: "qfn-c0-old", status: "unfinished_receipt", phase: "readiness", finished_at: null,
      candidate_window_minutes: null, minimum_memory_gib: null, probe_count: null,
      model_started: null,
      restoration: "unverified", source_sha256: "a".repeat(64),
    }] }} />);
    expect(screen.getByText(/Unfinished receipt · process state unverified/)).toBeInTheDocument();
    expect(screen.getByText(/Last recorded phase: readiness/)).toBeInTheDocument();
  });
  it("withholds gains from incomplete pairs even if a bad payload has numbers", () => {
    const arm = { declared: 2, attempted: 1, passed: 1, success_rate: 1, successful_task_runs_per_hour: 99 };
    render(<LocalModelResearchPanel data={{ ...base, comparisons: [{
      id: "pair", status: "incomplete", manifest_sha256: "a".repeat(64),
      comparison_eligible: false,
      run_sha256: { resident: "b".repeat(64), flash: "c".repeat(64) }, promotion_authorized: false,
      families: [{ family: "historical", comparison_eligible: false, paired_success_delta: 0.5, equal_source_task_success_delta: 0.5, source_task_interval_95: [0.3, 0.8], cohorts: { resident: arm, flash: arm } }],
    }] }} />);
    expect(screen.getAllByText("Withheld")).toHaveLength(3);
    expect(screen.queryByText("+50.0 pp")).not.toBeInTheDocument();
    expect(screen.getByText(/Comparison incomplete/)).toBeInTheDocument();
  });
  it("shows source errors and no result when unavailable", () => {
    render(<LocalModelResearchPanel data={{ ...base, status: "unavailable", warnings: ["Source invalid"] }} />);
    expect(screen.getByText(/No progress or result is inferred/)).toBeInTheDocument();
    expect(screen.getByText("Source invalid")).toBeInTheDocument();
  });
});
