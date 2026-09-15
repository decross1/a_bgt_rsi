import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppliedReferencePanel } from "../src/components/AppliedReferencePanel";
import type { AppliedReferenceProgress } from "../src/types/appliedReference";

const pending: AppliedReferenceProgress = {
  schema_version: "applied-reference-progress/v1",
  historical_trade_only: {
    status: "not_recorded", horizons: [],
    historical_executable_quotes_proven: false,
    paper_forward_result: "not_tested", orders_placed: 0,
  },
  forward_h1: {
    status: "topic_design_only",
    primary_horizon_hours: 1, secondary_horizon_hours: 4,
    rest_reference_plan_published: false,
    rest_reference_result_published: false,
    strict_paper_study_registered: false,
    paper_supported: false, orders_placed: 0,
  },
  warnings: [],
};

const score = (horizon: 1 | 4) => ({
  horizon_hours: horizon,
  validation_scored_rows: horizon === 1 ? 476 : 473,
  baseline_mse_bps2: 100, flow_model_mse_bps2: 90,
  mse_improvement_bps2: 10, mse_improvement_95ci: [-1, 20] as [number, number],
  baseline_directional_accuracy: 0.5, flow_model_directional_accuracy: 0.55,
  directional_improvement: 0.05,
  directional_improvement_95ci: [-0.1, 0.2] as [number, number],
  baseline_reference_net_bps_per_eligible_hour: -2,
  flow_reference_net_bps_per_eligible_hour: 1,
  baseline_doubled_reference_net_bps_per_eligible_hour: -4,
  flow_doubled_reference_net_bps_per_eligible_hour: -1,
});

const historical: AppliedReferenceProgress = {
  ...pending,
  historical_trade_only: {
    status: "recorded_reference_only", symbol: "BTCUSDT",
    calendar_start: "2026-07-17", calendar_end: "2026-09-14",
    source_days: 60, source_hours: 1440,
    source_rehash_at_publication: true,
    score_replay_at_publication: true,
    current_source_replay: "not_performed",
    reference_roundtrip_cost_bps: 30,
    reference_doubled_roundtrip_cost_bps: 60,
    horizons: [score(1), score(4)],
    publication_sha256: "a".repeat(64),
    gate_sha256: "b".repeat(64),
    result_sha256: "c".repeat(64),
    private_predictions_sha256: "d".repeat(64),
    runner_source_sha256: "e".repeat(64),
    archive_adapter_source_sha256: "f".repeat(64),
    historical_executable_quotes_proven: false,
    paper_forward_result: "not_tested", orders_placed: 0,
  },
};

describe("applied historical and forward evidence", () => {
  it("withholds scores before the 60-day gate and forward prestart plan", () => {
    render(<AppliedReferencePanel data={pending} />);
    expect(screen.getByText(/Forecast and reference-cost scores are withheld/))
      .toBeInTheDocument();
    expect(screen.getByText(/No forward REST plan or result/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("labels archived forecast and cost scores as trade-only references", () => {
    render(<AppliedReferencePanel data={historical} />);
    expect(screen.getByRole("region", {
      name: /Historical trade-only horizons, scroll horizontally/,
    })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("rowheader", { name: "1h primary" }))
      .toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "4h secondary" }))
      .toBeInTheDocument();
    expect(screen.getByText(/not realized returns or a trading edge/))
      .toBeInTheDocument();
    expect(screen.getByText(/current source replay has not been performed/))
      .toBeInTheDocument();
  });

  it("withholds a complete-looking baseline if its raw gate SHA is absent", () => {
    render(<AppliedReferencePanel data={{
      ...historical,
      historical_trade_only: {
        ...historical.historical_trade_only, gate_sha256: undefined,
      },
    }} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows the local H1 plan without implying a measured paper result", () => {
    render(<AppliedReferencePanel data={{
      ...pending,
      forward_h1: {
        ...pending.forward_h1, status: "rest_plan_published_local",
        rest_reference_plan_published: true,
        study_id: "h1-btcusdt-rest-20260915-abc",
        plan_publication_sha256: "a".repeat(64),
        plan_sha256: "b".repeat(64), topic_sha256: "c".repeat(64),
        external_plan_freeze_proof: "unverified",
        nonexecutable_reference_only: true,
      },
    }} />);
    expect(screen.getByText(/local REST reference plan is recorded/))
      .toBeInTheDocument();
    expect(screen.getByText(/not externally verified preregistration/))
      .toBeInTheDocument();
  });

  it("keeps a closed H1 source gap score-null", () => {
    render(<AppliedReferencePanel data={{
      ...pending,
      forward_h1: {
        ...pending.forward_h1, status: "closed_missing_source",
        rest_reference_plan_published: true,
        rest_reference_result_published: true,
        study_id: "h1-btcusdt-rest-20260915-abc",
        plan_publication_sha256: "a".repeat(64),
        plan_sha256: "b".repeat(64), topic_sha256: "c".repeat(64),
        result_publication_sha256: "d".repeat(64),
        external_plan_freeze_proof: "unverified",
        nonexecutable_reference_only: true,
        scheduled_cells: 3, unknown_outcome_cells: 3,
        all_scheduled_reference_net_bps: null,
      },
    }} />);
    expect(screen.getByText(/All-scheduled return scores are withheld/))
      .toBeInTheDocument();
    expect(screen.queryByText(/Candidate .*bps per scheduled hour/))
      .not.toBeInTheDocument();
  });

  it("labels a fully admitted H1 score as a displayed-quote reference", () => {
    render(<AppliedReferencePanel data={{
      ...pending,
      forward_h1: {
        ...pending.forward_h1, status: "rest_reference_recorded",
        rest_reference_plan_published: true,
        rest_reference_result_published: true,
        study_id: "h1-btcusdt-rest-20260915-abc",
        scheduled_cells: 3, source_valid_cells: 2,
        unknown_outcome_cells: 0,
        all_scheduled_reference_net_bps: {
          candidate: 1.25, baseline: -0.5,
        },
        plan_publication_sha256: "a".repeat(64),
        plan_sha256: "b".repeat(64), topic_sha256: "c".repeat(64),
        result_publication_sha256: "d".repeat(64),
        result_sha256: "e".repeat(64), private_cells_sha256: "f".repeat(64),
        score_replay_at_publication: true,
        current_source_replay: "not_performed",
        external_plan_freeze_proof: "unverified",
        nonexecutable_reference_only: true,
      },
    }} />);
    expect(screen.getByText(/Candidate 1.25/)).toBeInTheDocument();
    expect(screen.getByText(/not executable or paper returns/))
      .toBeInTheDocument();
    expect(screen.getByText(/2 source-valid/)).toBeInTheDocument();
  });
});
