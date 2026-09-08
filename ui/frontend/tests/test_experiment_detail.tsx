import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ExperimentDetail from "../src/routes/ExperimentDetail";
import {
  DETAIL_EMPTY_FIXTURE,
  DETAIL_FLAT_FIXTURE,
  DETAIL_JSON_FIXTURE,
  DETAIL_MD_FIXTURE,
  DETAIL_PER_MECHANISM_EFFICIENCY_FIXTURE,
  DETAIL_PER_MECHANISM_MIXED_FIXTURE,
} from "../src/fixtures/experiments";
import type { ExperimentDetail as ExperimentDetailT } from "../src/types/experiments";

vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 800, height: 300 }}>{children}</div>
    ),
  };
});

function renderDetail(
  initial: ExperimentDetailT,
  route:
    | string
    | { pathname: string; state?: Record<string, unknown> } =
      `/experiments/${initial.id}`,
) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <ExperimentDetail initial={initial} expIdOverride={initial.id} />
    </MemoryRouter>,
  );
}

describe("ExperimentDetail evidence workspace", () => {
  it("keeps the opponent diagnostic separate from four unknown qualification axes", () => {
    renderDetail(DETAIL_JSON_FIXTURE);

    expect(screen.getByTestId("opponent-diagnostic")).toHaveTextContent(
      /EXPLOITED by all_d/,
    );
    const qualification = screen.getByRole("region", {
      name: /Result qualification/i,
    });
    for (const label of [
      "Claim binding",
      "Evidence validity",
      "Evaluation mode",
      "Application fit",
    ]) {
      expect(qualification).toHaveTextContent(label);
    }
    expect(within(qualification).getAllByText("Unknown")).toHaveLength(4);
    expect(qualification).toHaveTextContent(/No market is assumed/);
  });

  it("shows a conflicting authored conclusion without promoting it over the diagnostic", () => {
    const conflict: ExperimentDetailT = {
      ...DETAIL_JSON_FIXTURE,
      has_summary_md: true,
      summary_md:
        "# Authored experiment conclusion\n\n**Verdict=NO** — author supplied conclusion.",
    };
    renderDetail(conflict);

    const diagnostic = screen.getByTestId("opponent-diagnostic");
    expect(diagnostic).toHaveTextContent(/EXPLOITED by all_d/);
    expect(diagnostic).not.toHaveTextContent(/Verdict=NO/);
    const authored = screen.getByTestId("markdown-summary");
    expect(authored).toHaveTextContent(/Verdict=NO/);
    expect(authored).toHaveTextContent(/not promoted here/i);
    expect(authored).toHaveTextContent(/independently validated scientific verdict/i);
  });

  it("supports pointer and keyboard selection with a single source-bound comparison", () => {
    renderDetail(DETAIL_JSON_FIXTURE);

    const tft = screen.getByRole("radio", { name: /tft/i });
    const allD = screen.getByRole("radio", { name: /all_d/i });
    expect(allD).toHaveAttribute("aria-checked", "true");
    expect(tft).toHaveAttribute("aria-checked", "false");
    expect(screen.getByTestId("cumulative-chart")).toHaveTextContent(
      /against all_d/,
    );

    fireEvent.keyDown(allD, { key: "ArrowLeft" });
    expect(tft).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("cumulative-chart")).toHaveTextContent(
      /against tft/,
    );

    fireEvent.keyDown(allD, { key: "Enter" });
    expect(allD).toHaveAttribute("aria-checked", "true");
    fireEvent.click(tft);
    expect(tft).toHaveAttribute("aria-checked", "true");
  });

  it("provides one payoff graph and an exact accessible data equivalent", () => {
    renderDetail(DETAIL_JSON_FIXTURE);

    expect(screen.getAllByTestId("cumulative-chart")).toHaveLength(1);
    expect(screen.queryByTestId("coop-chart")).toBeNull();
    expect(screen.queryByTestId("move-timeline")).toBeNull();
    const data = screen.getByTestId("round-data");
    expect(data).toHaveTextContent(/View exact plotted and move values \(4\)/);
    expect(data).toHaveTextContent(/Opponent cumulative/);
    expect(data).toHaveTextContent(/16/);
    expect(screen.getByText(/Final reported cumulative payoff/)).toHaveTextContent(
      /LLM 2\.00; opponent 16\.00/,
    );
  });

  it("reports absent inspector linkage and source truncation without inventing links", () => {
    const truncated: ExperimentDetailT = {
      ...DETAIL_JSON_FIXTURE,
      per_round: {
        ...DETAIL_JSON_FIXTURE.per_round!,
        truncated: true,
      },
    };
    renderDetail(truncated);

    const note = screen.getByTestId("linkage-absent");
    expect(note).toHaveTextContent(/linkage is not available/i);
    expect(note).toHaveTextContent(/task_id/);
    expect(note).toHaveTextContent(/truncated at the source scan cap/i);
    expect(within(note).queryByRole("link")).toBeNull();
  });

  it("keeps markdown-only evidence and trial sampling explicit", () => {
    renderDetail(DETAIL_MD_FIXTURE);

    expect(screen.getByTestId("outcome-headline")).toHaveTextContent(
      /Verdict: YES/,
    );
    expect(screen.getByTestId("markdown-summary")).toHaveTextContent(
      /Vickrey rediscovery/,
    );
    expect(screen.getByTestId("trials-sample")).toHaveTextContent(
      /2 of 50 · truncated/,
    );
    expect(screen.queryByTestId("opponent-table")).toBeNull();
    expect(screen.queryByTestId("cumulative-chart")).toBeNull();
  });

  it("distinguishes absent, present-empty, and unreadable result inventories", () => {
    const absent = renderDetail(DETAIL_EMPTY_FIXTURE);
    expect(screen.getByTestId("detail-no-results")).toHaveTextContent(
      /directory reported absent/i,
    );
    absent.unmount();

    const presentEmpty: ExperimentDetailT = {
      ...DETAIL_EMPTY_FIXTURE,
      id: "exp_empty",
      has_results_dir: true,
    };
    const empty = renderDetail(presentEmpty);
    expect(screen.getByTestId("detail-empty-results")).toHaveTextContent(
      /present and empty/i,
    );
    empty.unmount();

    const unreadable: ExperimentDetailT = {
      ...presentEmpty,
      id: "exp_unreadable",
      n_results_files: 2,
    };
    renderDetail(unreadable);
    expect(screen.getByTestId("detail-unreadable-results")).toHaveTextContent(
      /no supported evidence shape was readable/i,
    );
    expect(screen.getByTestId("detail-unreadable-results")).toHaveTextContent(
      /unknown rather than zero, empty or NO/i,
    );
  });

  it("retains independent JSON and markdown read errors", () => {
    const readErrors: ExperimentDetailT = {
      ...DETAIL_EMPTY_FIXTURE,
      id: "exp_read_errors",
      has_results_dir: true,
      n_results_files: 2,
      summary_json_error: "invalid JSON at byte 9",
      summary_md_error: "permission denied",
    };
    renderDetail(readErrors);

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent(/summary\.json: invalid JSON at byte 9/);
    expect(status).toHaveTextContent(/summary\.md: permission denied/);
  });

  it("distinguishes a reported empty authored summary from an absent file", () => {
    const emptyMarkdown: ExperimentDetailT = {
      ...DETAIL_EMPTY_FIXTURE,
      id: "exp_empty_markdown",
      has_results_dir: true,
      has_summary_md: true,
      n_results_files: 1,
      summary_md: "",
    };
    renderDetail(emptyMarkdown);

    expect(screen.getByTestId("markdown-summary-empty")).toHaveTextContent(
      /reported present and empty/i,
    );
    expect(screen.getByTestId("markdown-summary-empty")).toHaveTextContent(
      /No conclusion is inferred/i,
    );
    expect(screen.queryByTestId("detail-unreadable-results")).toBeNull();
  });

  it("retains malformed fields without converting them into a result", () => {
    const malformed = {
      ...DETAIL_EMPTY_FIXTURE,
      id: "exp_malformed",
      has_results_dir: true,
      n_results_files: 3,
      has_summary_json: true,
      has_per_round: true,
      summary_json: {
        per_opponent: "wrong shape",
        per_mechanism: [{ mechanism: "vcg", verdict: { value: "NO" } }, null],
      },
      per_round: { by_opponent: [], total_rows: 0, truncated: false },
      headline: { verdict: { value: "NO" }, tone: "bad" },
    } as unknown as ExperimentDetailT;
    renderDetail(malformed);

    expect(screen.getByTestId("detail-malformed")).toHaveTextContent(
      /per-opponent results are malformed/i,
    );
    expect(screen.getByTestId("detail-malformed")).toHaveTextContent(
      /per-round opponent groups are malformed/i,
    );
    expect(screen.getByTestId("detail-malformed")).toHaveTextContent(
      /reported result label is malformed/i,
    );
    expect(screen.queryByTestId("outcome-headline")).toBeNull();
  });

  it("preserves mechanism outcomes and missing metrics as producer supplied", () => {
    renderDetail(DETAIL_PER_MECHANISM_MIXED_FIXTURE);

    const firstPrice = screen.getByTestId("mech-row-first_price");
    const vcg = screen.getByTestId("mech-row-vcg");
    expect(firstPrice).toHaveTextContent(/0\.965/);
    expect(firstPrice).toHaveTextContent(/YES/);
    expect(vcg).toHaveTextContent(/NO/);
    expect(vcg).toHaveTextContent(/Not reported/);
    expect(within(vcg).getByText("NO")).toHaveAttribute("data-tone", "bad");
  });

  it("keeps the structured headline separate from adversarial authored prose", () => {
    renderDetail(DETAIL_PER_MECHANISM_EFFICIENCY_FIXTURE);

    const headline = screen.getByTestId("outcome-headline");
    expect(headline).toHaveTextContent(/YES on all 3 mechanisms/);
    expect(headline).toHaveAttribute("data-tone", "ok");
    expect(headline).not.toHaveTextContent(/Verdict: NO/);
    expect(screen.getByTestId("markdown-summary")).toHaveTextContent(
      /Verdict: NO/,
    );
  });

  it("displays flat scalar values raw without inferring percentage units", () => {
    renderDetail(DETAIL_FLAT_FIXTURE);

    const scalars = screen.getByTestId("json-header");
    expect(scalars).toHaveTextContent(/feasibility rate/);
    expect(scalars).toHaveTextContent(/0\.525/);
    expect(scalars).toHaveTextContent(/efficiency threshold/);
    expect(scalars).toHaveTextContent(/0\.9/);
    expect(scalars).not.toHaveTextContent(/52\.5%|90\.0%/);
  });

  it("keeps raw source payloads and the preserved catalog return location", () => {
    renderDetail(DETAIL_JSON_FIXTURE, {
      pathname: "/experiments/exp001_repeated_pd",
      state: {
        experimentsReturnTo: "/experiments?q=all_d&tier=synthetic",
      },
    });

    expect(screen.getByRole("link", { name: /Experiments/i })).toHaveAttribute(
      "href",
      "/experiments?q=all_d&tier=synthetic",
    );
    expect(screen.getByText("Original summary.json payload")).toBeInTheDocument();
    expect(screen.getByText("Original detail response")).toBeInTheDocument();
    expect(screen.getByText("Original detail response").parentElement).toHaveTextContent(
      /exp001_repeated_pd/,
    );
  });
});
