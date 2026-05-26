// CriticPanel renders /api/critic_summary (Day-9 W2-01). Read-only:
// no execute buttons, just the latest invocations + flag-rate +
// per-fixture matchup table. Stubs fetch behind the same vi.stubGlobal
// pattern as test_unlock_panel.tsx.
import { render, screen, waitFor } from "@testing-library/react";
import CriticPanel from "../src/components/CriticPanel";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  CriticMatchupRow,
  CriticRecentRun,
  CriticSummary,
} from "../src/types/schemas";

const responses: Record<string, unknown> = {};

beforeEach(() => {
  vi.stubGlobal("fetch", (url: string) => {
    for (const [key, value] of Object.entries(responses)) {
      if (url.endsWith(key) || url.includes(key)) {
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

function makeRow(overrides: Partial<CriticRecentRun> = {}): CriticRecentRun {
  return {
    timestamp: "2026-05-25T10:00:00Z",
    hypothesis_id: "001_flaw_a",
    flag_decision: "flawed",
    ground_truth_label: "flawed",
    domain: "game_theory",
    severity: "moderate",
    injected_flaw_type: "spurious_causation",
    critique_excerpt: "A substantive critique.",
    target_hits: [],
    target_count: 2,
    model: null,
    latency_ms: null,
    ...overrides,
  };
}

function makeMatchupRow(
  overrides: Partial<CriticMatchupRow> = {},
): CriticMatchupRow {
  return {
    fixture_id: "001_flaw_a",
    ground_truth_label: "flawed",
    injected_flaw_type: "spurious_causation",
    severity: "moderate",
    domain: "game_theory",
    decision: "flawed",
    outcome: "TP",
    target_hits: [],
    target_count: 2,
    latest_run_ts: "2026-05-25T10:00:00Z",
    ...overrides,
  };
}

function payload(overrides: Partial<CriticSummary> = {}): CriticSummary {
  return {
    milestone: "critic_invocations",
    fixtures: { available: true, total: 0 },
    recent_runs: {
      available: true,
      limit: 50,
      rows: [],
      malformed_lines: [],
      total_runs: 0,
    },
    flag_rate: {
      available: true,
      window_days: 7,
      total: 0,
      flawed_count: 0,
      sound_count: 0,
      flag_rate: null,
    },
    fixture_matchup: {
      available: false,
      rows: [],
      counts: { TP: 0, FP: 0, TN: 0, FN: 0, unrun: 0, unknown_fixture: 0 },
      accuracy: null,
      scored: 0,
      total_fixtures: 0,
    },
    ...overrides,
  };
}

describe("CriticPanel", () => {
  it("renders all-flag state — every recent run flagged 'flawed', matchup is all TP", async () => {
    const rows: CriticRecentRun[] = [
      makeRow({ hypothesis_id: "003_misspecified_payoff" }),
      makeRow({
        hypothesis_id: "010_circular_reasoning",
        critique_excerpt: "Circular: assumes what it claims to prove.",
      }),
    ];
    const matchup: CriticMatchupRow[] = [
      makeMatchupRow({ fixture_id: "003_misspecified_payoff", outcome: "TP" }),
      makeMatchupRow({ fixture_id: "010_circular_reasoning", outcome: "TP" }),
    ];
    responses["/api/critic_summary"] = payload({
      fixtures: { available: true, total: 2 },
      recent_runs: {
        available: true,
        limit: 50,
        rows,
        malformed_lines: [],
        total_runs: 2,
      },
      flag_rate: {
        available: true,
        window_days: 7,
        total: 2,
        flawed_count: 2,
        sound_count: 0,
        flag_rate: 1.0,
      },
      fixture_matchup: {
        available: true,
        rows: matchup,
        counts: { TP: 2, FP: 0, TN: 0, FN: 0, unrun: 0, unknown_fixture: 0 },
        accuracy: 1.0,
        scored: 2,
        total_fixtures: 2,
      },
    });
    render(<CriticPanel />);
    // Each fixture id appears in both the recent-runs row and the
    // matchup table row → assert multiple matches rather than uniqueness.
    await waitFor(() =>
      expect(
        screen.getAllByText("003_misspecified_payoff").length,
      ).toBeGreaterThan(0),
    );
    expect(screen.getAllByText("010_circular_reasoning").length).toBeGreaterThan(0);
    // The "flawed" badge is the decision tag — present per-row + as a
    // matchup table column; just confirm at least one renders.
    expect(screen.getAllByText("flawed").length).toBeGreaterThan(0);
    // Rate-as-text "100 %" and "flagged · …" live in adjacent nodes
    // (see CriticPanel:FlagRateHeader). Assert each separately.
    expect(screen.getByText("100 %")).toBeInTheDocument();
    expect(screen.getByText(/flagged · 2\/2 in last 7 d/)).toBeInTheDocument();
    expect(screen.getByText(/accuracy 100 %/)).toBeInTheDocument();
    // Strictly read-only: no execute / attest / rerun buttons.
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("renders all-sound state — every run flagged 'sound', matchup mixes TN + FN", async () => {
    const rows: CriticRecentRun[] = [
      makeRow({
        hypothesis_id: "020_sound_baseline",
        flag_decision: "sound",
        ground_truth_label: "sound",
        injected_flaw_type: "none",
        critique_excerpt: "No substantive flaw to flag.",
      }),
      makeRow({
        hypothesis_id: "003_misspecified_payoff",
        flag_decision: "sound",
        ground_truth_label: "flawed",
        critique_excerpt: "Looks fine to me.",
      }),
    ];
    const matchup: CriticMatchupRow[] = [
      makeMatchupRow({
        fixture_id: "020_sound_baseline",
        ground_truth_label: "sound",
        injected_flaw_type: "none",
        decision: "sound",
        outcome: "TN",
      }),
      makeMatchupRow({
        fixture_id: "003_misspecified_payoff",
        decision: "sound",
        outcome: "FN",
      }),
    ];
    responses["/api/critic_summary"] = payload({
      fixtures: { available: true, total: 2 },
      recent_runs: {
        available: true,
        limit: 50,
        rows,
        malformed_lines: [],
        total_runs: 2,
      },
      flag_rate: {
        available: true,
        window_days: 7,
        total: 2,
        flawed_count: 0,
        sound_count: 2,
        flag_rate: 0.0,
      },
      fixture_matchup: {
        available: true,
        rows: matchup,
        counts: { TP: 0, FP: 0, TN: 1, FN: 1, unrun: 0, unknown_fixture: 0 },
        accuracy: 0.5,
        scored: 2,
        total_fixtures: 2,
      },
    });
    render(<CriticPanel />);
    await waitFor(() =>
      expect(screen.getByText("0 %")).toBeInTheDocument(),
    );
    expect(screen.getByText(/flagged · 0\/2 in last 7 d/)).toBeInTheDocument();
    expect(screen.getByText(/accuracy 50 %/)).toBeInTheDocument();
    // FN count should surface — it's the dangerous one (critic missed
    // a flaw). The header reads "FN 1".
    expect(screen.getByText(/FN 1/)).toBeInTheDocument();
    // Outcome badges render inside the matchup table.
    expect(screen.getAllByText("TN").length).toBeGreaterThan(0);
    expect(screen.getAllByText("FN").length).toBeGreaterThan(0);
  });

  it("renders mixed state — recent runs + matchup with TP/FP/TN/FN/unrun", async () => {
    const rows: CriticRecentRun[] = [
      makeRow({
        hypothesis_id: "003_misspecified_payoff",
        flag_decision: "flawed",
        ground_truth_label: "flawed",
        target_hits: ["rationality requires the agent know the objective"],
        target_count: 2,
      }),
      makeRow({
        hypothesis_id: "020_sound_baseline",
        flag_decision: "flawed",
        ground_truth_label: "sound",
        injected_flaw_type: "none",
        critique_excerpt: "(false alarm)",
      }),
    ];
    const matchup: CriticMatchupRow[] = [
      makeMatchupRow({
        fixture_id: "003_misspecified_payoff",
        target_hits: ["rationality requires the agent know the objective"],
        target_count: 2,
        outcome: "TP",
      }),
      makeMatchupRow({
        fixture_id: "020_sound_baseline",
        ground_truth_label: "sound",
        injected_flaw_type: "none",
        outcome: "FP",
      }),
      makeMatchupRow({
        fixture_id: "010_circular_reasoning",
        decision: null,
        outcome: "unrun",
      }),
    ];
    responses["/api/critic_summary"] = payload({
      fixtures: { available: true, total: 3 },
      recent_runs: {
        available: true,
        limit: 50,
        rows,
        malformed_lines: [],
        total_runs: 2,
      },
      flag_rate: {
        available: true,
        window_days: 7,
        total: 2,
        flawed_count: 2,
        sound_count: 0,
        flag_rate: 1.0,
      },
      fixture_matchup: {
        available: true,
        rows: matchup,
        counts: { TP: 1, FP: 1, TN: 0, FN: 0, unrun: 1, unknown_fixture: 0 },
        accuracy: 0.5,
        scored: 2,
        total_fixtures: 3,
      },
    });
    render(<CriticPanel />);
    await waitFor(() =>
      expect(screen.getByText(/1\/2 targets hit/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/FP 1/)).toBeInTheDocument();
    expect(screen.getByText(/unrun 1/)).toBeInTheDocument();
    // 010 only appears in the matchup table (no recent_runs row) → unique.
    expect(screen.getByText("010_circular_reasoning")).toBeInTheDocument();
  });

  it("shows the absent-log empty state when /api/critic_summary returns available=false sections", async () => {
    responses["/api/critic_summary"] = payload(); // defaults: recent_runs.available=true but rows=[]; flag_rate.total=0
    render(<CriticPanel />);
    await waitFor(() =>
      expect(
        screen.getByText(/logs\/critic_eval\.jsonl is empty/),
      ).toBeInTheDocument(),
    );
  });

  it("shows a backend error rather than rendering empty when /api/critic_summary fails", async () => {
    render(<CriticPanel />);
    await waitFor(() =>
      expect(screen.getByText(/404/)).toBeInTheDocument(),
    );
  });
});
