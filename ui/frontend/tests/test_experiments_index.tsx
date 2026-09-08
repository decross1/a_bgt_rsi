import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import Experiments from "../src/routes/Experiments";
import {
  RESEARCH_FIXTURE,
  RESEARCH_UNAVAILABLE,
} from "../src/fixtures/experiments";
import type { ResearchResponse } from "../src/types/experiments";

function renderPage(
  initial: ResearchResponse = RESEARCH_FIXTURE,
  entry = "/experiments",
) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Experiments initial={initial} />
    </MemoryRouter>,
  );
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="catalog-location">{location.search}</output>;
}

describe("Experiments source catalog", () => {
  it("renders one calm source list with mapped and unmapped entries", () => {
    renderPage();
    const list = screen.getByTestId("source-entry-list");
    expect(within(list).getAllByRole("article")).toHaveLength(5);
    expect(screen.getByTestId("research-card-exp003_vickrey_rediscovery"))
      .toHaveTextContent(/Synthetic/);
    expect(screen.getByTestId("research-card-exp002_loop_v0_robustness"))
      .toHaveTextContent(/Unmapped source/);
    expect(screen.queryByTestId("tier-section-synthetic")).toBeNull();
  });

  it("keeps adverse producer text while labeling it as a scoped report", () => {
    renderPage();
    const card = screen.getByTestId("research-card-exp001_repeated_pd");
    expect(card).toHaveTextContent(/Reported label/);
    expect(card).toHaveTextContent(/EXPLOITED by all_d/);
    expect(card).toHaveTextContent(
      /Claim binding and independent validity are not reported/,
    );
    expect(screen.getByTestId("verdict-exp001_repeated_pd"))
      .toHaveAttribute("data-tone", "bad");
  });

  it("preserves exact bridge identities and values in source evidence", () => {
    renderPage();
    const bridge = screen.getByTestId("bridge-exp003_vickrey_rediscovery");
    expect(bridge).toHaveTextContent("iter-2026-05-27-028");
    expect(bridge).toHaveTextContent("truthful_bid_fraction = 1");
  });

  it("does not infer not-run from absent bridge or verdict fields", () => {
    renderPage();
    expect(screen.getByTestId("bridge-exp001_repeated_pd"))
      .toHaveTextContent(/No bridge records are present in this response/);
    expect(screen.getByTestId("research-card-exp002_loop_v0_robustness"))
      .toHaveTextContent(/Results directory reported absent/);
    expect(screen.getByTestId("research-card-exp007_polymarket"))
      .toHaveTextContent(/Results directory reported empty/);
    expect(screen.getByTestId("experiments-page")).not.toHaveTextContent(
      /design-only — not run|no results yet — not run/i,
    );
  });

  it("searches title, id, reported label and bridge text", () => {
    renderPage();
    const search = screen.getByRole("searchbox", {
      name: /Search source entries/i,
    });
    fireEvent.change(search, { target: { value: "truthful_bid_fraction" } });
    expect(screen.getByText(/Showing 1 of 5/)).toBeInTheDocument();
    expect(screen.getByTestId("research-card-exp003_vickrey_rediscovery"))
      .toBeInTheDocument();
    expect(screen.queryByTestId("research-card-exp001_repeated_pd")).toBeNull();
  });

  it("filters immediately and syncs the completed search to the URL", () => {
    vi.useFakeTimers();
    try {
      render(
        <MemoryRouter initialEntries={["/experiments"]}>
          <Experiments initial={RESEARCH_FIXTURE} />
          <LocationProbe />
        </MemoryRouter>,
      );
      const search = screen.getByRole("searchbox", {
        name: /Search source entries/i,
      });
      fireEvent.change(search, { target: { value: "all_d" } });

      expect(screen.getByText(/Showing 1 of 5/)).toBeInTheDocument();
      expect(screen.getByTestId("catalog-location")).toHaveTextContent(/^$/);

      act(() => vi.advanceTimersByTime(180));
      expect(screen.getByTestId("catalog-location")).toHaveTextContent(
        "?q=all_d",
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("retains query search and filters by the supplied tier", () => {
    renderPage(RESEARCH_FIXTURE, "/experiments?q=exp&tier=semi_synthetic");
    expect(screen.getByRole("searchbox")).toHaveValue("exp");
    expect(screen.getByRole("combobox", { name: /Source tier/i }))
      .toHaveValue("semi_synthetic");
    expect(screen.getByText(/Showing 1 of 5/)).toBeInTheDocument();
    expect(screen.getByTestId("research-card-exp006_mechanism_design"))
      .toBeInTheDocument();
  });

  it("preserves exact detail and trace-history links", () => {
    renderPage();
    expect(
      within(screen.getByTestId("research-card-exp001_repeated_pd")).getByRole(
        "link",
        { name: /exp001 repeated pd/i },
      ),
    ).toHaveAttribute("href", "/experiments/exp001_repeated_pd");
    expect(screen.getByRole("link", { name: /View trace history/i }))
      .toHaveAttribute("href", "/cycles");
  });

  it("distinguishes unavailable, empty and filtered-empty catalog states", () => {
    const unavailable = renderPage(RESEARCH_UNAVAILABLE);
    expect(screen.getByTestId("experiments-unavailable")).toHaveTextContent(
      /unavailable/i,
    );
    unavailable.unmount();

    const empty: ResearchResponse = {
      available: true,
      tiers: [],
      untiered: [],
    };
    const emptyView = renderPage(empty);
    expect(screen.getByTestId("catalog-empty")).toBeInTheDocument();
    emptyView.unmount();

    renderPage(RESEARCH_FIXTURE, "/experiments?q=does-not-exist");
    expect(screen.getByTestId("catalog-filtered-empty")).toBeInTheDocument();
  });

  it("removes the coordinator-cycle tail even when old fixture data is passed", () => {
    render(
      <MemoryRouter>
        <Experiments
          initial={RESEARCH_FIXTURE}
          initialCoordinatorCycles={[{ run_id: "old-cycle" }]}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByTestId("coordinator-cycles-section")).toBeNull();
    expect(screen.queryByTestId("coordinator-cycle-card")).toBeNull();
    expect(screen.getByText(/does not load coordinator cycles/i))
      .toBeInTheDocument();
  });

  it("labels malformed catalog arrays without converting them to empty success", () => {
    const malformed = {
      available: true,
      tiers: "wrong shape",
      untiered: [],
    } as unknown as ResearchResponse;
    renderPage(malformed);
    expect(screen.getByTestId("catalog-malformed")).toBeInTheDocument();
    expect(screen.getByTestId("catalog-empty")).toBeInTheDocument();
  });
});
