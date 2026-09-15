import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppliedMarketResearchPanel } from "../src/components/AppliedMarketResearchPanel";
import type { AppliedMarketResearchProgress } from "../src/types/appliedMarketResearch";

const empty: AppliedMarketResearchProgress = {
  schema_version: "applied-market-research-progress/v1", observed_at: "2026-09-15T14:00:00Z",
  status: "not_started", research_focus: "flow", evidence_scope: "collection",
  paper_result: "not_tested", orders_placed: 0, scan_complete: true, max_recent_batches: 8,
  batches: [], warnings: [], stages: [
    { id: "capture", label: "Public data", status: "not_recorded" },
    { id: "forward_paper", label: "Forward paper outcomes", status: "not_recorded" },
  ],
};

describe("AppliedMarketResearchPanel", () => {
  it("separates a planned application from a measured strategy", () => {
    render(<AppliedMarketResearchPanel data={empty} />);
    expect(screen.getByText("No collection batch has been recorded yet.")).toBeTruthy();
    expect(screen.getByText("Strategy result: not tested.")).toBeTruthy();
    expect(screen.getAllByText("No accepted receipt yet")).toHaveLength(2);
  });
  it("shows failed requests and warmup gaps without inventing paper results", () => {
    render(<AppliedMarketResearchPanel data={{ ...empty, status: "data_recorded", batches: [{
      id: "spot-BTCUSDT-20260915T140000Z", symbol: "BTCUSDT", status: "incomplete",
      collector_source_verified: true, requests_attempted: 3, requests_succeeded: 2,
      requests_failed: 1, source_valid_frames: 2, trade_pages: 0,
      has_depth_snapshot: true, backlog_unresolved: true,
    }] }} />);
    expect(screen.getByText(/succeeded \/ attempted · 1 failed/)).toBeTruthy();
    expect(screen.getByText("Incomplete coverage")).toBeTruthy();
    expect(screen.getByText("Recorded at local receipt time")).toBeTruthy();
    expect(screen.getByText("Strategy result: not tested.")).toBeTruthy();
  });
  it("does not turn an invalid receipt into zero failures or a valid quote", () => {
    render(<AppliedMarketResearchPanel data={{ ...empty, status: "unavailable", batches: [{
      id: "spot-BTCUSDT-20260915T140000Z", status: "invalid_receipt",
    }] }} />);
    expect(screen.getAllByText("Unverified").length).toBeGreaterThan(0);
    expect(screen.getByText("Unknown")).toBeTruthy();
    expect(screen.queryByText("No gap inside this batch")).toBeNull();
  });
  it("keeps an initial warmup incomplete even without cursor or backlog flags", () => {
    render(<AppliedMarketResearchPanel data={{ ...empty, status: "data_recorded", batches: [{
      id: "spot-BTCUSDT-20260915T140000Z", status: "incomplete",
      collector_source_verified: true, cursor_gap: false, page_gap: false,
      backlog_unresolved: false,
    }] }} />);
    expect(screen.getByText("Incomplete coverage")).toBeTruthy();
    expect(screen.queryByText("No gap inside this batch")).toBeNull();
  });
  it("labels historical frames separately from verified collector code", () => {
    render(<AppliedMarketResearchPanel data={{ ...empty, status: "data_recorded", batches: [{
      id: "spot-BTCUSDT-20260915T140000Z", status: "complete_incremental_batch",
      collector_source_verified: false, collector_source_status: "historical_source_unavailable",
      source_valid_frames: 3,
    }] }} />);
    expect(screen.getByText("Sealed raw frames; collector code unavailable")).toBeTruthy();
    expect(screen.queryByText("No gap inside this batch")).toBeNull();
  });

});
