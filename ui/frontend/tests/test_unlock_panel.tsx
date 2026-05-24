// UnlockPanel renders the five Week-2-unlock prerequisite sections from
// /api/unlock_status (ui_plan.md §11.3). Read-only: attest/rollback
// commands appear as copy-paste text, never as actions the UI takes.
import { render, screen, waitFor } from "@testing-library/react";
import UnlockPanel from "../src/components/UnlockPanel";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { UnlockStatus } from "../src/types/schemas";

const responses: Record<string, unknown> = {};

beforeEach(() => {
  vi.stubGlobal("fetch", (url: string) => {
    for (const [key, value] of Object.entries(responses)) {
      if (url.endsWith(key)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          statusText: "OK",
          json: () => Promise.resolve(value),
        } as Response);
      }
    }
    return Promise.resolve({
      ok: false,
      status: 404,
      statusText: "not found",
      json: () => Promise.resolve({ detail: "missing" }),
    } as Response);
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  for (const key of Object.keys(responses)) delete responses[key];
});

function payload(overrides: Partial<UnlockStatus> = {}): UnlockStatus {
  return {
    milestone: "ui_v1_week2_unlock",
    current_day: "day_8",
    run_log_integrity: {
      available: true,
      ok: true,
      total_lines: 137,
      malformed_lines: [],
      rolling_window_days: 7,
      rolling_count: 135,
    },
    soft_gate_queue: { available: true, pending: [] },
    hard_gates_pending: { available: true, pending: [] },
    metric_log: {
      day1_tokens_per_sec: 32.03,
      day7_coop_rate_vs_tft: 1.0,
    },
    fallbacks_taken: {},
    ...overrides,
  };
}

describe("UnlockPanel", () => {
  it("renders the all-clear state — five sections, no pending gates", async () => {
    responses["/api/unlock_status"] = payload();
    render(<UnlockPanel />);
    await waitFor(() =>
      expect(screen.getByText("Run-log integrity")).toBeInTheDocument(),
    );
    expect(screen.getByText("Soft-gate queue")).toBeInTheDocument();
    expect(screen.getByText("Hard gates pending")).toBeInTheDocument();
    expect(screen.getByText("metric_log (drift check)")).toBeInTheDocument();
    expect(screen.getByText("fallbacks_taken")).toBeInTheDocument();
    // Per-day grouping: day 1 and day 7 buckets surface from the keys.
    expect(screen.getByText("day 1")).toBeInTheDocument();
    expect(screen.getByText("day 7")).toBeInTheDocument();
    // Apparatus-day breadcrumb sourced from current_day.
    expect(screen.getByText(/apparatus day_8/)).toBeInTheDocument();
  });

  it("flags malformed run-log lines and surfaces fallback reasons", async () => {
    responses["/api/unlock_status"] = payload({
      run_log_integrity: {
        available: true,
        ok: false,
        total_lines: 50,
        malformed_lines: [12, 33],
        rolling_window_days: 7,
        rolling_count: 50,
      },
      fallbacks_taken: { day5_ml_intern: "direct_api" },
    });
    render(<UnlockPanel />);
    await waitFor(() =>
      expect(screen.getByText(/malformed lines: 12, 33/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/day5_ml_intern:/)).toBeInTheDocument();
    expect(screen.getByText(/direct_api/)).toBeInTheDocument();
  });

  it("renders pending soft-gate rollback as copy-paste text, never as a button", async () => {
    responses["/api/unlock_status"] = payload({
      soft_gate_queue: {
        available: true,
        pending: [
          {
            task_id: "day8_some_soft_gate",
            agent_id: "claude-track-b",
            summary: "claim a tools/* path",
            ts: "2026-05-24T11:00:00Z",
            sla_hours: 48,
            rollback_command:
              "python tools/rollback_attestation.py --task-id day8_some_soft_gate",
          },
        ],
      },
    });
    render(<UnlockPanel />);
    await waitFor(() =>
      expect(screen.getByText("day8_some_soft_gate")).toBeInTheDocument(),
    );
    // The rollback command is rendered as text — assert no <button> exists
    // for the rollback affordance (read-only UI; rule 8).
    expect(screen.queryByRole("button", { name: /rollback/i })).toBeNull();
    expect(
      screen.getByText(
        /python tools\/rollback_attestation\.py --task-id day8_some_soft_gate/,
      ),
    ).toBeInTheDocument();
  });

  it("renders pending hard-gates with attest command and a fail badge", async () => {
    responses["/api/unlock_status"] = payload({
      hard_gates_pending: {
        available: true,
        pending: [
          {
            task_id: "some_publication_gate",
            attest_command:
              "python tools/attest_gate.py --task-id some_publication_gate",
          },
        ],
      },
    });
    render(<UnlockPanel />);
    await waitFor(() =>
      expect(screen.getByText("some_publication_gate")).toBeInTheDocument(),
    );
    expect(screen.getByText(/1 pending/)).toBeInTheDocument();
    expect(
      screen.getByText(
        /python tools\/attest_gate\.py --task-id some_publication_gate/,
      ),
    ).toBeInTheDocument();
  });

  it("shows a backend error rather than rendering empty when /api/unlock_status fails", async () => {
    // No matching response → fetch returns 404 → http.ts throws "404 not found".
    render(<UnlockPanel />);
    await waitFor(() =>
      expect(screen.getByText(/404/)).toBeInTheDocument(),
    );
  });
});
