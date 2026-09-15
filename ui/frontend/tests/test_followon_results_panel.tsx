import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FollowonResultsPanel } from "../src/components/FollowonResultsPanel";
import type { FollowonResultsProgress } from "../src/types/followonResults";

const admitted: FollowonResultsProgress = {
  schema_version: "local-followon-results-progress/v1",
  status: "available", warnings: [], promotion_authorized: false,
  windows: [{
    id: "qfn-followon-c0-pilot-20260915-a.resident", cohort: "resident",
    routes: ["resident_qwen"], status: "recorded_admitted",
    admission_class: "RECORDED_COMPLETED_WINDOW_ADMISSION",
    current_source_replay: "not_performed",
    report_schema: "flash-followon-content-free-report/v1",
    report_sha256: "a".repeat(64), admission_sha256: "b".repeat(64),
    recorded_controller_source_bundle_sha256: "f".repeat(64),
    window_plan_sha256: "c".repeat(64), result_sha256: "d".repeat(64),
    exact_restoration_verified: true, comparison_eligible: false,
    blocks: [{
      block_id: "thinking-71", kind: "thinking", run_sha256: "e".repeat(64),
      attempted: 2, passed: 1, timeouts: 1,
      groups: [{
        condition: ["off", "critic"], declared: 2, attempted: 2,
        passed: 1, timeouts: 1, errors: 0, supported: 0,
        unsupported: 0, wall_seconds: 123.4,
        calls: 2, recorded_timings: 1,
        mean_request_latency_seconds: 12.34,
        mean_first_token_seconds: 0.42,
        actual_input_tokens_min: null, actual_input_tokens_max: null,
      }],
    }],
  }],
};

describe("recorded follow-on studies", () => {
  it("shows admitted Qwen counts and transport timing apart from the paired benchmark", () => {
    render(<FollowonResultsPanel data={admitted} />);
    expect(screen.getByText(/Tested model: Qwen resident/)).toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    expect(screen.getByText("12.3 s")).toBeInTheDocument();
    expect(screen.getByText("0.4 s")).toBeInTheDocument();
    expect(screen.getByText(/current source replay has not been performed/)).toBeInTheDocument();
    expect(screen.getByRole("region", {
      name: /resident follow-on conditions, scroll horizontally/,
    })).toHaveAttribute("tabindex", "0");
  });

  it("withholds counts when a complete-looking row lacks archived source proof", () => {
    const row = admitted.windows[0];
    render(<FollowonResultsPanel data={{
      ...admitted, windows: [{ ...row, report_sha256: null }],
    }} />);
    expect(screen.getByText(/Task scores and timing are withheld/)).toBeInTheDocument();
    expect(screen.queryByText("1 / 2")).not.toBeInTheDocument();
  });

  it("does not turn a live unfinished window into a descriptive score", () => {
    render(<FollowonResultsPanel data={{ ...admitted, windows: [] }} />);
    expect(screen.getByText(/No restored follow-on window/)).toBeInTheDocument();
    expect(screen.queryByText("1 / 2")).not.toBeInTheDocument();
  });
});
