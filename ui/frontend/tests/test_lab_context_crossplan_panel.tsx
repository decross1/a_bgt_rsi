import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LabContextCrossplanPanel } from "../src/components/LabContextCrossplanPanel";

const sha = "a".repeat(64);
const row = () => ({
  resident_qwen: {
    declared: 12, attempted: 12, passed: 6, returned: 12,
    timeout: 0, error: 0, cancelled: 0, measured_prompt_tokens_max: 6000,
  },
  flash_next_mia: {
    declared: 12, attempted: 12, passed: 8, returned: 12,
    timeout: 0, error: 0, cancelled: 0, measured_prompt_tokens_max: 6000,
  },
  matched_cell_pass_categories: {
    qwen_only: 1, mia_only: 3, both_pass: 5, neither_pass: 3,
  },
});
const pending = () => ({
  schema_version: "lab-context-crossplan-progress/v1",
  observed_at: new Date().toISOString(),
  publication_id: "qfn-context-qwen-mia-20260915-a",
  status: "pending_publication",
  matched_cells: 24,
  publication_index_raw_sha256: null,
  grade_replay: "not_available",
  same_plan_pair: false,
  by_capacity: null, configured_total_tokens: null,
  promotion_authorized: false, private_content_exported: false,
});
const admitted = () => ({
  ...pending(),
  status: "complete_cross_plan_diagnostic",
  publication_index_raw_sha256: sha,
  grade_replay: "private_sse_and_all_24_qwen_all_36_mia_objective_grades",
  qwen_window_id: "qfn-ab-lab-context-qwen-20260915-a",
  mia_window_id: "qfn-ab-lab-context-20260915-a",
  overlap_receipts_sha256: sha,
  configured_total_tokens: {
    resident_qwen: 16384, flash_next_mia: 32768,
  },
  by_capacity: { "8192": row(), "16384": row() },
});

describe("LabContextCrossplanPanel", () => {
  it("withholds all matched quality before the independent publication", () => {
    render(<LabContextCrossplanPanel data={pending()} />);
    expect(screen.getByText(/24-cell publication pending/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows only admitted 8K/16K Qwen versus Flash counts and source limits", () => {
    render(<LabContextCrossplanPanel data={admitted()} />);
    expect(screen.getByRole("region", {
      name: /Qwen and Flash matched context quality/,
    })).toBeInTheDocument();
    expect(screen.getAllByText("6 / 12")).toHaveLength(2);
    expect(screen.getAllByText("8 / 12")).toHaveLength(2);
    expect(screen.getByText(/Qwen was configured at 16,384 total tokens/)).toBeInTheDocument();
    expect(screen.getByText(/No Qwen 32K result/)).toBeInTheDocument();
    expect(screen.getByText(/not independent held-out tasks/)).toBeInTheDocument();
    expect(screen.queryByText(/32,768 tokens/, {
      selector: "th",
    })).not.toBeInTheDocument();
  });

  it("rejects unbound, stale, or inconsistent counts before rendering a table", () => {
    const { rerender } = render(<LabContextCrossplanPanel data={admitted()} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    rerender(<LabContextCrossplanPanel data={{
      ...admitted(), publication_index_raw_sha256: "unbound",
    }} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const changed = admitted();
    changed.by_capacity["8192"].matched_cell_pass_categories.both_pass = 6;
    rerender(<LabContextCrossplanPanel data={changed} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    rerender(<LabContextCrossplanPanel data={{
      ...admitted(), observed_at: new Date(Date.now() - 10 * 60_000).toISOString(),
    }} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    rerender(<LabContextCrossplanPanel data={admitted()} pollingFailed />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
