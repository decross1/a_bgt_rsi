// Page B detail tests. Render all three shapes from fixtures and assert the
// honest states render: per-opponent table + coop chart + "linkage absent"
// for json; markdown + trials for md; "no results yet" for empty.
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ExperimentDetail from "../src/routes/ExperimentDetail";
import {
  DETAIL_EMPTY_FIXTURE,
  DETAIL_JSON_FIXTURE,
  DETAIL_MD_FIXTURE,
} from "../src/fixtures/experiments";
import type { ExperimentDetail as ExperimentDetailT } from "../src/types/experiments";
import { describe, expect, it } from "vitest";

// recharts ResponsiveContainer needs a non-zero box in jsdom; stub it so the
// chart renders its children deterministically. (Same trick projects use to
// test recharts under jsdom.)
import { vi } from "vitest";
vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 800, height: 300 }}>{children}</div>
    ),
  };
});

function renderDetail(initial: typeof DETAIL_JSON_FIXTURE) {
  return render(
    <MemoryRouter>
      <ExperimentDetail initial={initial} expIdOverride={initial.id} />
    </MemoryRouter>,
  );
}

describe("ExperimentDetail", () => {
  it("renders per-opponent table + coop chart for json shape", () => {
    renderDetail(DETAIL_JSON_FIXTURE);
    expect(screen.getByTestId("opponent-table")).toBeInTheDocument();
    expect(screen.getByTestId("opp-row-tft")).toBeInTheDocument();
    expect(screen.getByTestId("opp-row-all_d")).toBeInTheDocument();
    expect(screen.getByTestId("coop-chart")).toBeInTheDocument();
  });

  it("surfaces the round->inspector linkage-absent note for json shape", () => {
    renderDetail(DETAIL_JSON_FIXTURE);
    const note = screen.getByTestId("linkage-absent");
    expect(note).toHaveTextContent(/linkage is not available/);
    expect(note).toHaveTextContent(/task_id/);
  });

  it("renders the outcome headline (exploited verdict) for json shape", () => {
    renderDetail(DETAIL_JSON_FIXTURE);
    const hl = screen.getByTestId("outcome-headline");
    expect(hl).toHaveTextContent(/EXPLOITED by all_d/);
    expect(hl).toHaveTextContent(/exploited 1\/2 opponents/);
  });

  it("renders the cumulative-payoff chart and C/D timeline for json shape", () => {
    renderDetail(DETAIL_JSON_FIXTURE);
    expect(screen.getByTestId("cumulative-chart")).toBeInTheDocument();
    expect(screen.getByTestId("move-timeline")).toBeInTheDocument();
  });

  it("defaults the round-chart focus to the exploited opponent", () => {
    renderDetail(DETAIL_JSON_FIXTURE);
    // worst opponent is all_d -> charts focus on it by default.
    expect(screen.getByTestId("cumulative-chart")).toHaveTextContent(
      /vs all_d/,
    );
  });

  it("re-focuses the round charts when an opponent row is clicked", () => {
    renderDetail(DETAIL_JSON_FIXTURE);
    fireEvent.click(screen.getByTestId("opp-row-tft"));
    expect(screen.getByTestId("cumulative-chart")).toHaveTextContent(/vs tft/);
    expect(screen.getByTestId("move-timeline")).toHaveTextContent(/vs tft/);
  });

  it("renders markdown + trials sample for md shape", () => {
    renderDetail(DETAIL_MD_FIXTURE);
    expect(screen.getByTestId("markdown-summary")).toBeInTheDocument();
    expect(screen.getByTestId("mini-markdown")).toHaveTextContent(
      /Vickrey rediscovery/,
    );
    const trials = screen.getByTestId("trials-sample");
    expect(trials).toHaveTextContent(/showing 2 of 50/);
    // The md verdict surfaces as the outcome headline.
    expect(screen.getByTestId("outcome-headline")).toHaveTextContent(
      /Verdict: YES/,
    );
    // No json table / chart for the md shape.
    expect(screen.queryByTestId("opponent-table")).toBeNull();
    expect(screen.queryByTestId("cumulative-chart")).toBeNull();
  });

  it("marks the no-results experiment honestly for empty shape", () => {
    renderDetail(DETAIL_EMPTY_FIXTURE);
    expect(screen.getByTestId("detail-no-results")).toBeInTheDocument();
    expect(screen.queryByTestId("opponent-table")).toBeNull();
    expect(screen.queryByTestId("markdown-summary")).toBeNull();
    expect(screen.queryByTestId("trials-sample")).toBeNull();
    expect(screen.queryByTestId("outcome-headline")).toBeNull();
    expect(screen.queryByTestId("cumulative-chart")).toBeNull();
  });

  // ─── focus fallback when headline.worst is absent ────────────────────

  it("falls back to the first round opponent when headline.worst is absent", () => {
    // Strip the worst-opponent hint; focus must default to roundOpponents[0]
    // (tft, the first key), not crash or stay null.
    const noWorst: ExperimentDetailT = {
      ...DETAIL_JSON_FIXTURE,
      headline: {
        ...DETAIL_JSON_FIXTURE.headline!,
        worst: null,
      },
    };
    renderDetail(noWorst);
    expect(screen.getByTestId("cumulative-chart")).toHaveTextContent(/vs tft/);
    expect(screen.getByTestId("move-timeline")).toHaveTextContent(/vs tft/);
  });

  // ─── linkage PRESENT branch (task_id carried) suppresses the note ────

  it("suppresses the linkage-absent note when round_inspector_linkage is true", () => {
    const linked: ExperimentDetailT = {
      ...DETAIL_JSON_FIXTURE,
      per_round: {
        ...DETAIL_JSON_FIXTURE.per_round!,
        round_inspector_linkage: true,
      },
    };
    renderDetail(linked);
    expect(screen.queryByTestId("linkage-absent")).toBeNull();
  });

  // ─── per_round truncation note renders the scan-cap warning ──────────

  it("shows the series-truncated note when per_round is truncated", () => {
    const truncated: ExperimentDetailT = {
      ...DETAIL_JSON_FIXTURE,
      per_round: {
        ...DETAIL_JSON_FIXTURE.per_round!,
        truncated: true,
        round_inspector_linkage: false,
      },
    };
    renderDetail(truncated);
    expect(screen.getByTestId("linkage-absent")).toHaveTextContent(
      /truncated at the scan cap/,
    );
  });

  // ─── warn-tone headline (payoff-absent) renders amber, not green ─────

  it("renders a warn-tone headline for the payoff-undetermined verdict", () => {
    const undetermined: ExperimentDetailT = {
      ...DETAIL_JSON_FIXTURE,
      headline: {
        verdict: "Payoff data absent — exploitation undetermined",
        tone: "warn",
        n_exploited: 0,
        n_opponents: 2,
        worst: null,
        exploited: [],
      },
    };
    renderDetail(undetermined);
    const hl = screen.getByTestId("outcome-headline");
    expect(hl).toHaveTextContent(/exploitation undetermined/);
    // amber tone class, never the emerald (green) ok box.
    expect(hl.className).toMatch(/amber/);
    expect(hl.className).not.toMatch(/emerald/);
  });

  // ─── exploited tint honors the backend threshold (single source) ─────

  it("tints the exploited payoff cell using the backend exploit_gap_threshold", () => {
    // Raise the threshold so the all_d gap (1.75) no longer counts as
    // exploited; the red tint must follow the backend value, not a hardcode.
    const highThreshold: ExperimentDetailT = {
      ...DETAIL_JSON_FIXTURE,
      headline: {
        ...DETAIL_JSON_FIXTURE.headline!,
        exploit_gap_threshold: 5.0,
      },
    };
    const { container } = renderDetail(highThreshold);
    // No payoff cell should be tinted red now.
    expect(container.querySelector("td.text-red-400")).toBeNull();
  });
});
