import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ResearchOpsCard } from "../src/components/ResearchOpsCard";

const sha = (c: string) => c.repeat(64);
const receipt = () => ({
  schema: "research-ops-status/v1", observed_at: new Date().toISOString(),
  active_campaign: { campaign_id: "v2-campaign", manifest_sha256: sha("a") },
  campaign_queue: { status: "all_registered_topics_consumed", eligible_count: 0,
    consumed_count: 1, loop_source_sha256: sha("b") },
  next_registered_campaign: { campaign_id: "next-campaign", manifest_sha256: sha("c"),
    registered_topic_count: 12, activation_required: true },
  last_productive: { kind: "campaign_iteration_recorded", iteration_id: "iter-001",
    topic_id: "topic-001", at: new Date().toISOString(), loop_source_sha256: sha("b") },
  last_cycle: { run_id: "cycle-001", at: new Date().toISOString(), action_code: "noop",
    planned_count: 0, dispatched_count: 0, outcome_count: 1,
    raw_row_sha256: sha("d"), cycles_source_sha256: sha("e") },
  budget: { source_status: "available", spent_today: 3, daily_cap: 60,
    paced_allowance: 44, ledger_sha256: sha("f") },
  dispatch_gate: { operator_pause: false, other_actionable_work: "not_assessed" },
  ingestion: { source_status: "unknown", latest_attempt_status: "unknown",
    last_success_at: null as string | null, last_success_input_sha256: null as string | null,
    last_success_pointer_sha256: null as string | null },
});
const show = (data: unknown, failing = false) => render(<MemoryRouter><ResearchOpsCard data={data} failing={failing} /></MemoryRouter>);

describe("ResearchOpsCard", () => {
  it("separates exhausted campaign topics, recorded iterations, no-op plans, dispatch, and unknown ingestion", () => {
    show(receipt());
    expect(screen.getByText("All topics in this campaign have been used")).toBeInTheDocument();
    expect(screen.getByText(/Other useful research actions have not been assessed/)).toBeInTheDocument();
    expect(screen.getByText(/Next registered campaign next-campaign awaits activation/)).toBeInTheDocument();
    expect(screen.getByText(/iter-001/)).toBeInTheDocument();
    expect(screen.getByText(/No-op plan · 0 planned · 0 dispatched/)).toBeInTheDocument();
    expect(screen.getByText(/Today's coordinator allowance: 3\/60 used/)).toBeInTheDocument();
    expect(screen.getByText("Source attempt status unknown")).toBeInTheDocument();
    expect(screen.getByText(/Last receipt-bound success: not verified/)).toBeInTheDocument();
  });

  it("shows an eligible topic and a receipt-bound source success without treating a plan as dispatch", () => {
    const data = receipt();
    data.campaign_queue = { ...data.campaign_queue, status: "eligible", eligible_count: 2 };
    data.last_cycle = { ...data.last_cycle, action_code: "actions_planned", planned_count: 2,
      dispatched_count: 1 };
    data.ingestion = { ...data.ingestion, source_status: "available", latest_attempt_status: "succeeded",
      last_success_at: new Date().toISOString(), last_success_input_sha256: sha("1"),
      last_success_pointer_sha256: sha("2") };
    show(data);
    expect(screen.getByText("2 registered topics eligible")).toBeInTheDocument();
    expect(screen.getByText(/Plan recorded · 2 planned · 1 dispatched/)).toBeInTheDocument();
    expect(screen.getByText("Latest source attempt succeeded")).toBeInTheDocument();
    expect(screen.queryByText(/Last receipt-bound success: not verified/)).not.toBeInTheDocument();
  });

  it("withholds current work on stale, wrong-schema, or failed reads", () => {
    const stale = { ...receipt(), observed_at: new Date(Date.now() - 10 * 60_000).toISOString() };
    const { rerender } = show(stale);
    expect(screen.getByText("Current observation unavailable")).toBeInTheDocument();
    expect(screen.queryByText(/No-op plan · 0 planned/)).not.toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={{ ...receipt(), schema: "unknown" }} /></MemoryRouter>);
    expect(screen.getByText("Current observation unavailable")).toBeInTheDocument();
    rerender(<MemoryRouter><ResearchOpsCard data={receipt()} failing /></MemoryRouter>);
    expect(screen.getByText("Current observation unavailable")).toBeInTheDocument();
  });

  it("withholds tampered linked-iteration, cycle, and source-success details", () => {
    const data = receipt();
    data.last_productive = { ...data.last_productive, loop_source_sha256: "unbound" };
    data.last_cycle = { ...data.last_cycle, raw_row_sha256: "unbound" };
    data.ingestion = { ...data.ingestion, source_status: "available", latest_attempt_status: "succeeded",
      last_success_at: new Date().toISOString(), last_success_input_sha256: "unbound",
      last_success_pointer_sha256: sha("2") };
    show(data);
    expect(screen.getByText("No linked iteration verified in this observation")).toBeInTheDocument();
    expect(screen.getByText("No bound coordinator check")).toBeInTheDocument();
    expect(screen.getByText(/Last receipt-bound success: not verified/)).toBeInTheDocument();
  });
});
