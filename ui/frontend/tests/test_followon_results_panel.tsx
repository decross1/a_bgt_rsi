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

  it("labels measured original C0 context separately from configured capacity", () => {
    const row = admitted.windows[0];
    const group = row.blocks[0].groups[0];
    render(<FollowonResultsPanel data={{ ...admitted, windows: [{ ...row,
      blocks: [{ ...row.blocks[0], kind: "context", block_id: "context-8k",
        attempted: 8, passed: 8, timeouts: 0, groups: [
          { ...group, condition: ["2048", "early"], declared: 4,
            attempted: 4, passed: 4, supported: 4, timeouts: 0,
            actual_input_tokens_min: 2071, actual_input_tokens_max: 2105 },
          { ...group, condition: ["8192", "late"], declared: 4,
            attempted: 4, passed: 4, supported: 4, timeouts: 0,
            actual_input_tokens_min: 8195, actual_input_tokens_max: 8248 },
        ] }],
    }] }} />);
    expect(screen.getByText(/Measured context in these admitted original C0 windows/))
      .toHaveTextContent("2,048 and 8,192 input-token bands");
    expect(screen.getByText(/Measured context in these admitted original C0 windows/))
      .toHaveTextContent("actual prompts up to 8,248 tokens");
    expect(screen.getByText(/Measured context in these admitted original C0 windows/))
      .toHaveTextContent("do not qualify the optimized MTP profile");
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

  it("labels a decode timing block without inventing a task pass rate", () => {
    const row = admitted.windows[0];
    const timing = {
      ...row.blocks[0], block_id: "decode-17", kind: "mtp_decode_timing",
      attempted: 3, passed: null, timeouts: 0,
      groups: [{ ...row.blocks[0].groups[0],
        condition: ["fixed_decode_512"], declared: 3, attempted: 3,
        passed: 0, timeouts: 0, errors: 0,
      }],
    };
    render(<FollowonResultsPanel data={{
      ...admitted, windows: [{ ...row, blocks: [timing] }],
    }} />);
    expect(screen.getByText("Timing only")).toBeInTheDocument();
    expect(screen.queryByText("0 / 3")).not.toBeInTheDocument();
  });

  it("separates selected repair producer scores from an archived grade replay", () => {
    const row = admitted.windows[0];
    const block = {
      ...row.blocks[0], block_id: "repair-0", kind: "selected_repair",
      attempted: 22, passed: 8, timeouts: 1,
      groups: [{ ...row.blocks[0].groups[0],
        condition: ["resident_native"], declared: 22, attempted: 22,
        passed: 8, timeouts: 1,
      }],
      grader_replay: {
        schema: "flash-followon-selected-repair-grader-replay/v1" as const,
        run_sha256: row.blocks[0].run_sha256,
        replay_receipt_sha256: "f".repeat(64),
        source_replay_status: "available" as const,
        raw_private_calls_verified: 22, declared: 22, replayed: 20,
        producer_consistent: 20, producer_inconsistent: 0,
        grader_unavailable: 2,
        by_lane: { resident_native: {
          declared: 22, producer_passed: 8, replayed: 20,
          replayed_passed: 8, producer_consistent: 20,
          producer_inconsistent: 0, grader_unavailable: 2,
        } },
        comparison_eligible: false as const,
      },
    };
    render(<FollowonResultsPanel data={{ ...admitted,
      windows: [{ ...row, blocks: [block] }],
    }} />);
    expect(screen.getByText("8 / 22")).toBeInTheDocument();
    expect(screen.getByText(/20 of 22 recorded grades reproduced/)).toBeInTheDocument();
    expect(screen.getByText(/2 could not be rerun/)).toBeInTheDocument();
    expect(screen.queryByText(/private completion/)).not.toBeInTheDocument();
  });

  it("shows the closed four-task coding diagnostic with its own grader replay", () => {
    const row = admitted.windows[0];
    const group = row.blocks[0].groups[0];
    const family = (passed: number) => ({
      declared: 2, producer_passed: passed, replayed: 2,
      replayed_passed: passed, producer_consistent: 2,
      producer_inconsistent: 0, grader_unavailable: 0,
    });
    const block = {
      ...row.blocks[0], block_id: "coding-temp1-0", kind: "coding_temp1_medium",
      attempted: 4, passed: 1, timeouts: 0,
      groups: [
        { ...group, condition: ["temp1_medium", "portfolio"],
          declared: 2, attempted: 2, passed: 1, timeouts: 0 },
        { ...group, condition: ["temp1_medium", "historical"],
          declared: 2, attempted: 2, passed: 0, timeouts: 0 },
      ],
      grader_replay: {
        schema: "flash-followon-coding-temp1-grader-replay/v1" as const,
        run_sha256: row.blocks[0].run_sha256,
        replay_receipt_sha256: "f".repeat(64),
        source_replay_status: "available" as const,
        raw_private_calls_verified: 4, declared: 4, replayed: 4,
        producer_consistent: 4, producer_inconsistent: 0,
        grader_unavailable: 0,
        by_family: { portfolio: family(1), historical: family(0) },
        comparison_eligible: false as const,
      },
    };
    render(<FollowonResultsPanel data={{ ...admitted,
      windows: [{ ...row, cohort: "flash", routes: ["flash_next_mia"],
        blocks: [block] }],
    }} />);
    expect(screen.getAllByText("Coding sampling diagnostic")).toHaveLength(2);
    expect(screen.getByText(/4 of 4 recorded grades reproduced/)).toBeInTheDocument();
    expect(screen.getByText(/Sampling, reasoning effort, output cap, and timeout changed together/)).toBeInTheDocument();
    expect(screen.queryByText(/private completion/)).not.toBeInTheDocument();
  });
});
