// Page B detail tests. Render all three shapes from fixtures and assert the
// honest states render: per-opponent table + coop chart + "linkage absent"
// for json; markdown + trials for md; "no results yet" for empty.
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ExperimentDetail from "../src/routes/ExperimentDetail";
import {
  DETAIL_EMPTY_FIXTURE,
  DETAIL_FLAT_FIXTURE,
  DETAIL_JSON_FIXTURE,
  DETAIL_MD_FIXTURE,
  DETAIL_PER_MECHANISM_ALL_NO_FIXTURE,
  DETAIL_PER_MECHANISM_EFFICIENCY_FIXTURE,
  DETAIL_PER_MECHANISM_MIXED_FIXTURE,
  DETAIL_PER_MECHANISM_RESIDUAL_FIXTURE,
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

  // ─── per_mechanism shape (exp004): efficiency + revenue columns ──────

  it("renders the per-mechanism table with efficiency+revenue for exp004 shape", () => {
    renderDetail(DETAIL_PER_MECHANISM_EFFICIENCY_FIXTURE);
    const table = screen.getByTestId("mechanism-table");
    expect(table).toBeInTheDocument();
    expect(screen.getByTestId("mech-row-first_price")).toBeInTheDocument();
    expect(screen.getByTestId("mech-row-vcg")).toBeInTheDocument();
    // exp004 carries efficiency + revenue -> those columns appear.
    expect(table).toHaveTextContent(/efficiency/i);
    expect(table).toHaveTextContent(/revenue/i);
    // ...and NOT the signed-residual column (exp005-only).
    expect(table).not.toHaveTextContent(/signed resid/i);
    // No exp001 opponent table for this shape.
    expect(screen.queryByTestId("opponent-table")).toBeNull();
  });

  it("shows YES verdict chips + the structured per-mechanism headline for exp004", () => {
    const { container } = renderDetail(
      DETAIL_PER_MECHANISM_EFFICIENCY_FIXTURE,
    );
    const hl = screen.getByTestId("outcome-headline");
    expect(hl).toHaveTextContent(/YES on all 3 mechanisms/);
    expect(hl).toHaveTextContent(/YES on 3\/3/);
    expect(hl.className).toMatch(/emerald/);
    // Verdict chips read YES (emerald), one per mechanism row.
    const greenChips = container.querySelectorAll(
      "[data-testid^='mech-row-'] .text-emerald-300",
    );
    expect(greenChips.length).toBe(3);
  });

  // ─── per_mechanism shape (exp005): signed-residual column ────────────

  it("renders the signed-residual column (and no efficiency/revenue) for exp005 shape", () => {
    renderDetail(DETAIL_PER_MECHANISM_RESIDUAL_FIXTURE);
    const table = screen.getByTestId("mechanism-table");
    expect(table).toHaveTextContent(/signed resid/i);
    // exp005 has neither efficiency nor revenue columns.
    expect(table).not.toHaveTextContent(/efficiency/i);
    expect(table).not.toHaveTextContent(/revenue/i);
    expect(screen.getByTestId("mech-row-vcg")).toHaveTextContent(/-4.9/);
  });

  // ─── flat shape (exp006): scalar metrics card + red NO verdict ───────

  it("renders the flat scalar metrics card and a red NO verdict for exp006 shape", () => {
    renderDetail(DETAIL_FLAT_FIXTURE);
    const metrics = screen.getByTestId("json-header");
    // Flat scalars render generically — feasibility_rate as a percentage,
    // n_trials raw. The verdict key is NOT shown here (it's in the headline).
    expect(metrics).toHaveTextContent(/feasibility rate/);
    expect(metrics).toHaveTextContent(/52.5%/);
    expect(metrics).toHaveTextContent(/n trials/);
    expect(metrics).not.toHaveTextContent(/verdict/);
    // NO verdict tones red, never the emerald ok box.
    const hl = screen.getByTestId("outcome-headline");
    expect(hl).toHaveTextContent("NO");
    expect(hl.className).toMatch(/red/);
    expect(hl.className).not.toMatch(/emerald/);
    // No mechanism table / opponent table for the flat shape.
    expect(screen.queryByTestId("mechanism-table")).toBeNull();
    expect(screen.queryByTestId("opponent-table")).toBeNull();
  });

  // ─── BOTH-present: markdown does NOT clobber the structured headline ──
  // Every real exp004/005/006 dir ships a summary.md alongside summary.json.
  // The fixtures carry an ADVERSARIAL md verdict (toned the OTHER way) so this
  // pins, at the layer the user actually sees, that the structured JSON
  // headline survives and the markdown renders as prose BELOW it, never as the
  // outcome verdict. This is the #1 historical honesty risk.

  it("keeps the structured per_mechanism headline and does NOT let the markdown verdict clobber it", () => {
    renderDetail(DETAIL_PER_MECHANISM_EFFICIENCY_FIXTURE);
    // Structured headline still reads YES-on-all-3, emerald (ok).
    const hl = screen.getByTestId("outcome-headline");
    expect(hl).toHaveTextContent(/YES on all 3 mechanisms/);
    expect(hl.className).toMatch(/emerald/);
    expect(hl.className).not.toMatch(/red/);
    // The adversarial "Verdict: NO" markdown did NOT become the headline.
    expect(hl).not.toHaveTextContent(/Verdict: NO/);
    // The full markdown prose renders in its own card, below the headline.
    const md = screen.getByTestId("markdown-summary");
    expect(md).toBeInTheDocument();
    expect(md).toHaveTextContent(/Verdict: NO/);
  });

  it("keeps the structured flat NO headline and does NOT let the markdown YES clobber it", () => {
    renderDetail(DETAIL_FLAT_FIXTURE);
    const hl = screen.getByTestId("outcome-headline");
    // Structured flat verdict stays NO / red despite the adversarial md YES.
    expect(hl).toHaveTextContent("NO");
    expect(hl.className).toMatch(/red/);
    expect(hl.className).not.toMatch(/emerald/);
    expect(hl).not.toHaveTextContent(/Verdict: YES/);
    // Markdown prose still renders below.
    const md = screen.getByTestId("markdown-summary");
    expect(md).toHaveTextContent(/Verdict: YES/);
  });

  // ─── non-all-YES per_mechanism tones (warn / bad), not green ─────────

  it("tones a MIXED per_mechanism headline amber and renders a red NO chip", () => {
    const { container } = renderDetail(DETAIL_PER_MECHANISM_MIXED_FIXTURE);
    const hl = screen.getByTestId("outcome-headline");
    expect(hl).toHaveTextContent(/Mixed: YES on 1\/2 mechanisms/);
    expect(hl.className).toMatch(/amber/);
    expect(hl.className).not.toMatch(/emerald/);
    // The NO row's verdict chip reads red; exactly one row is YES (emerald).
    const greenChips = container.querySelectorAll(
      "[data-testid^='mech-row-'] .text-emerald-300",
    );
    const redChips = container.querySelectorAll(
      "[data-testid^='mech-row-'] .text-red-300",
    );
    expect(greenChips.length).toBe(1);
    expect(redChips.length).toBe(1);
  });

  it("tones an ALL-NO per_mechanism headline red", () => {
    renderDetail(DETAIL_PER_MECHANISM_ALL_NO_FIXTURE);
    const hl = screen.getByTestId("outcome-headline");
    expect(hl).toHaveTextContent(/NO on all 2 mechanisms/);
    expect(hl.className).toMatch(/red/);
    expect(hl.className).not.toMatch(/emerald/);
  });

  // ─── dash, not a fabricated value, for an absent mechanism metric cell ─

  it("renders a dash (not 0 or a fabricated value) for an absent mechanism metric cell", () => {
    renderDetail(DETAIL_PER_MECHANISM_MIXED_FIXTURE);
    // The vcg row carries no truthful_fraction -> its truthful cell is a dash.
    const vcgRow = screen.getByTestId("mech-row-vcg");
    expect(vcgRow).toHaveTextContent("—");
    // The first_price row DOES carry truthful_fraction -> renders a percent.
    expect(screen.getByTestId("mech-row-first_price")).toHaveTextContent(
      /96\.5%/,
    );
  });

  // ─── scalar card threshold/floor rendering is PINNED (cosmetic but fixed) ─
  // The flat exp006 summary carries pre-registered knobs (efficiency_threshold,
  // feasibility_threshold, feasibility_floor) alongside the MEASURED rates. The
  // generic ScalarMetricsCard renders ratio-keyed values in [0,1] as percents
  // and other scalars raw. This pins the current behavior so it can't silently
  // drift: thresholds matching the ratio heuristic show as %, floor shows raw.

  it("pins the flat scalar card threshold/floor rendering", () => {
    renderDetail(DETAIL_FLAT_FIXTURE);
    const metrics = screen.getByTestId("json-header");
    // efficiency_threshold (key matches /efficiency/, value 0.9 in [0,1]) -> %.
    expect(metrics).toHaveTextContent(/efficiency threshold: .*90\.0%/);
    // feasibility_floor (no rate/fraction/efficiency in key) -> raw value.
    expect(metrics).toHaveTextContent(/feasibility floor: .*0\.5/);
    // The MEASURED designer_mean_efficiency renders as a percent too.
    expect(metrics).toHaveTextContent(/designer mean efficiency: .*71\.0%/);
  });
});
