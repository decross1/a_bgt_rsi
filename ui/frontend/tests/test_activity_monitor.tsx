// PAGE A — AgentMonitorPanel tests. Asserts the active-worker cross-ref
// renders cpu/rss, and that the synthetic-inference block carries the
// visible "synthetic — needs worker_activity.jsonl" marker so its numbers
// are never read as measured.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AgentMonitorPanel from "../src/components/AgentMonitorPanel";
import {
  MONITOR_FIXTURE,
  MONITOR_FIXTURE_UNAVAILABLE,
} from "../src/fixtures/activity";

describe("AgentMonitorPanel", () => {
  it("renders active workers with cpu/rss from telemetry", () => {
    render(<AgentMonitorPanel data={MONITOR_FIXTURE} />);
    const row = screen.getByTestId("worker-seq-1");
    expect(row).toHaveTextContent("summarize_paper");
    expect(row).toHaveTextContent("12.5%");
    expect(row).toHaveTextContent("660 MB");
  });

  it("shows the synthetic-inference marker prominently", () => {
    render(<AgentMonitorPanel data={MONITOR_FIXTURE} />);
    const marker = screen.getByTestId("synthetic-marker");
    expect(marker).toHaveTextContent(/synthetic/i);
    expect(marker).toHaveTextContent(/worker_activity\.jsonl/);
    expect(marker).toHaveTextContent(/primary-session/);
    // The synthetic numbers live inside the flagged block.
    const block = screen.getByTestId("synthetic-inference");
    expect(block).toHaveTextContent("312/512");
  });

  it("renders the synthetic worker row", () => {
    render(<AgentMonitorPanel data={MONITOR_FIXTURE} />);
    expect(screen.getByTestId("synthetic-worker-seq-1")).toBeInTheDocument();
  });

  it("renders an unavailable notice when the monitor is absent", () => {
    render(<AgentMonitorPanel data={MONITOR_FIXTURE_UNAVAILABLE} />);
    expect(screen.getByText(/unavailable/i)).toBeInTheDocument();
  });
});
