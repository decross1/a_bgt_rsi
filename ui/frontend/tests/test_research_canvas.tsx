import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import ResearchCanvas from "../src/components/ladder/ResearchCanvas";
import { buildThesisFamilies } from "../src/components/ladder/thesisModel";
import type { FamilyRecord, ThesisModel } from "../src/components/ladder/thesisModel";
import type { LadderCluster } from "../src/types/schemas";

const claims = [
  {
    id: "iter-2026-08-16-003",
    claim: "In a liquid democracy model, a smaller spectral gap in the delegation transition matrix results in higher transient variance of the Gini coefficient during the convergence phase towards the stationary distribution.",
    topic: "Representation in Peer Selection: A Liquid Democracy Perspective",
    label: "Spectral gap → transient Gini variance",
  },
  {
    id: "iter-2026-08-17-014",
    claim: "In liquid democracy networks, high local clustering coefficients decrease the effective representation of minority nodes by concentrating delegated weight through reinforced transitive paths, rather than diluting it through redundancy.",
    topic: "Representation in Peer Selection: A Liquid Democracy Perspective",
    label: "Clustering → minority representation",
  },
  {
    id: "iter-2026-08-24-006",
    claim: "In liquid democracy networks, an increase in the eigenvector centrality of a subset of delegates leads to higher systemic volatility because the rapid convergence of delegated weights reduces the time-to-equilibrium following stochastic preference shifts.",
    topic: "Power in Liquid Democracy: A Network Centrality Approach",
    label: "Centrality → convergence → volatility",
  },
] as const;

const clusters: LadderCluster[] = claims.map((claim, index) => ({
  cluster_id: `cl-${claim.id}`,
  stem: claim.claim,
  status: "open",
  evidence_level: "L1",
  origin: "consolidation",
  members: [claim.id],
  last_event_ts: `2026-08-${String(16 + index).padStart(2, "0")}T05:00:14Z`,
}));

const rows = claims.map((claim, index) => ({
  iteration_id: claim.id,
  ended_at: `2026-08-${String(16 + index).padStart(2, "0")}T04:39:17Z`,
  seed: { topic: claim.topic },
  gate_status: "pending",
  hypothesis: { text: claim.claim },
  retrieval: { relevance: { reason: `Recorded retrieval review ${index + 1}` } },
  critique: { verdict: "survives", rationale: `Recorded critic review ${index + 1}` },
  experiment_outcome: null,
}));

function liquidModel(): ThesisModel {
  return buildThesisFamilies(clusters, rows);
}

function renderCanvas(model: ThesisModel, nextOwed: Record<string, string> = { L1: "experiment_outcome with trials >= 30" }) {
  return render(
    <MemoryRouter>
      <ResearchCanvas model={model} nextOwed={nextOwed} />
    </MemoryRouter>,
  );
}

describe("ResearchCanvas", () => {
  it("leads with the three exact source-bound Liquid Democracy claims and truthful selected context", () => {
    renderCanvas(liquidModel());

    expect(screen.getByTestId("research-canvas-family-select")).toHaveDisplayValue(
      "Liquid democracy — collection · 3 records",
    );
    const buttons = screen.getAllByRole("button", { name: /Select source-bound claim/ });
    expect(buttons).toHaveLength(3);
    claims.forEach((claim, index) => expect(within(buttons[index]).getByText(claim.label)).toBeVisible());
    expect(buttons[0]).toHaveAttribute("aria-pressed", "true");

    const initialContext = screen.getByTestId("research-canvas-context");
    expect(within(initialContext).getByTestId("research-canvas-evidence-state")).toHaveTextContent(
      "No compatible test recorded in the dated source assessment.",
    );
    expect(initialContext).toHaveTextContent("not an adopted protocol");
    expect(within(initialContext).getByRole("link", { name: /Open full dossier/ })).toHaveAttribute(
      "href",
      "/dossier/iter-2026-08-16-003",
    );

    fireEvent.click(buttons[2]);
    expect(buttons[2]).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("research-canvas")).toHaveAttribute("data-mobile-view", "context");
    expect(screen.getByTestId("research-canvas-context")).toHaveTextContent(
      "Whether concentrated delegate centrality shortens settling time",
    );

    fireEvent.click(screen.getByText("Source qualification and recorded fields"));
    const details = screen.getByTestId("research-canvas-source-details");
    expect(details).toHaveTextContent(claims[2].claim);
    expect(details).toHaveTextContent("Collection membership is association only");
    expect(details).toHaveTextContent("Evidence validity");
    expect(details).toHaveTextContent("Unknown");

    fireEvent.click(screen.getByTestId("research-canvas-back"));
    expect(screen.getByTestId("research-canvas")).toHaveAttribute("data-mobile-view", "membership");
  });

  it("reports a supplied raw outcome without replacing it with a universal no-test claim", () => {
    const model = buildThesisFamilies(
      [{
        cluster_id: "cl-outcome",
        stem: "A separately recorded outcome",
        status: "surfaced",
        evidence_level: "L4",
        members: ["iter-outcome"],
        last_event_ts: "2026-09-01T01:02:03Z",
      }],
      [{
        iteration_id: "iter-outcome",
        ended_at: "2026-09-01T01:00:00Z",
        seed: { topic: "Separate recorded topic" },
        hypothesis: { text: "A separate recorded hypothesis." },
        experiment_outcome: {
          experiment_id: "exp-recorded",
          metric: "score",
          value: 0.7,
          trials: 12,
          summary: "Raw producer summary",
        },
      }],
    );
    renderCanvas(model, { L4: "human validity verdict" });

    const state = screen.getByTestId("research-canvas-evidence-state");
    expect(state).toHaveTextContent("Recorded outcome supplied");
    expect(state).toHaveTextContent("validity remain unverified");
    expect(state).not.toHaveTextContent("No compatible test recorded");
    fireEvent.click(screen.getByText("Source qualification and recorded fields"));
    expect(screen.getByTestId("research-canvas-source-details")).toHaveTextContent("exp-recorded");
    expect(screen.getByTestId("research-canvas-source-details")).toHaveTextContent("Raw producer summary");
  });

  it("follows a newly arrived preferred collection until the user chooses, then drops stale selections safely", () => {
    const transient = buildThesisFamilies(
      [{ cluster_id: "cl-transient", stem: "Transient record", status: "open", evidence_level: null, members: [] }],
      [],
    );
    const result = renderCanvas(transient);
    expect(screen.getByTestId("research-canvas-family-select")).toHaveDisplayValue(
      "Transient record — individual source record cl-transient",
    );

    result.rerender(
      <MemoryRouter>
        <ResearchCanvas model={liquidModel()} nextOwed={{ L1: "run comparison" }} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("research-canvas-family-select")).toHaveDisplayValue(
      "Liquid democracy — collection · 3 records",
    );
    expect(screen.getAllByRole("button", { name: /Select source-bound claim/ })).toHaveLength(3);
    expect(screen.queryByText("Transient record")).not.toBeInTheDocument();
  });

  it("distinguishes same-title source records from unverified snapshots in selector and claim names", () => {
    const model = buildThesisFamilies(
      [
        { cluster_id: "cl-unique", stem: "Same title", status: "open", evidence_level: null, members: [] },
        { cluster_id: "cl-duplicate", stem: "Same title", status: "open", evidence_level: null, members: [] },
        { cluster_id: "cl-duplicate", stem: "Same title", status: "killed", evidence_level: null, members: [] },
      ],
      [],
    );
    renderCanvas(model);
    const select = screen.getByTestId("research-canvas-family-select");
    const options = within(select).getAllByRole("option");
    expect(options.map((option) => option.textContent)).toContain(
      "Same title — individual source record cl-unique",
    );
    expect(options.some((option) => option.textContent?.includes("individual unverified snapshot 1"))).toBe(true);
    expect(options.some((option) => option.textContent?.includes("individual unverified snapshot 2"))).toBe(true);

    const killedFamily = model.families.find((family) => family.records[0]?.cluster.status === "killed")!;
    const killedRecord = killedFamily.records[0];
    const snapshot = options.find((option) => option.textContent?.includes(`unverified snapshot ${killedRecord.unverifiedSnapshotNumber}`))!;
    fireEvent.change(select, { target: { value: (snapshot as HTMLOptionElement).value } });
    expect(screen.getByRole("button", { name: new RegExp(`Select recorded entry, unverified snapshot ${killedRecord.unverifiedSnapshotNumber}`) })).toBeVisible();
    expect(screen.getByTestId("research-canvas-standing")).toHaveTextContent("killed");
    expect(screen.getByTestId("research-canvas-evidence-state")).toHaveTextContent("Recorded negative history");
  });

  it("bounds family options, rendered claims and source reads", () => {
    let sourceReads = 0;
    const records: FamilyRecord[] = Array.from({ length: 10_000 }, (_, index) => ({
      cluster: {
        cluster_id: `cl-${index}`,
        stem: `Recorded history ${index}`,
        status: "open",
        evidence_level: "L0",
        members: [`iter-${index}`],
      },
      id: `cl-${index}`,
      key: `record-${index}`,
      hasUniqueSourceId: true,
      title: `Recorded history ${index}`,
      topics: ["Large topic"],
      iterations: [{
        id: `iter-${index}`,
        topic: "Large topic",
        hypothesis: `Recorded hypothesis ${index}`,
        paperText: [],
        evidenceText: [],
        source: {
          get experiment_outcome() {
            sourceReads += 1;
            return null;
          },
        },
      }],
      association: "exact-topic",
      reason: "exact iteration seed.topic",
      missingMembers: [],
    }));
    const otherFamilies = Array.from({ length: 60 }, (_, index) => ({
      id: `record:other-${index}`,
      title: `Other thesis ${index}`,
      basis: "individual",
      topicLabels: [],
      records: [] as FamilyRecord[],
    }));
    const model: ThesisModel = {
      families: [{ id: "topic:large", title: "Large topic", basis: "exact iteration seed.topic", topicLabels: ["Large topic"], records }, ...otherFamilies],
      records,
      issues: [],
    };
    renderCanvas(model);

    expect(within(screen.getByTestId("research-canvas-family-select")).getAllByRole("option")).toHaveLength(40);
    expect(screen.getAllByRole("button", { name: /Select recorded entry/ })).toHaveLength(3);
    expect(screen.getByTestId("research-canvas-bounded-note")).toHaveTextContent("Showing 3 of 10000");
    expect(sourceReads).toBeGreaterThan(0);
    expect(sourceReads).toBeLessThanOrEqual(24);
  });
  it("retains an explicit thesis and claim through source reorder and a thesis round trip", () => {
    const model = liquidModel();
    const other = buildThesisFamilies([{ cluster_id: "cl-other", stem: "Other thesis", status: "open", evidence_level: "L0", members: [] }], []);
    const combined = { ...model, families: [...model.families, ...other.families], records: [...model.records, ...other.records] };
    const result = renderCanvas(combined);
    const select = screen.getByTestId("research-canvas-family-select");
    fireEvent.click(screen.getAllByRole("button", { name: /Select source-bound claim/ })[2]);
    fireEvent.change(select, { target: { value: other.families[0].id } });
    expect(select).toHaveValue(other.families[0].id);
    result.rerender(<MemoryRouter><ResearchCanvas model={{ ...combined, families: [...combined.families].reverse() }} nextOwed={{}} /></MemoryRouter>);
    expect(select).toHaveValue(other.families[0].id);
    fireEvent.change(select, { target: { value: model.families[0].id } });
    expect(screen.getAllByRole("button", { name: /Select source-bound claim/ })[2]).toHaveAttribute("aria-pressed", "true");
  });

  it("does not hide unknown outcome shapes or retain dated pinning after hypothesis drift", () => {
    const supplied = rows.map((row, index) => index === 0 ? { ...row, experiment_outcome: { future_result: "unverified" } } : row);
    const result = renderCanvas(buildThesisFamilies(clusters, supplied));
    expect(screen.getByTestId("research-canvas-evidence-state")).toHaveTextContent("Recorded outcome supplied");
    const drifted = supplied.map((row) => ({ ...row, hypothesis: { text: row.hypothesis.text + " changed" } }));
    result.rerender(<MemoryRouter><ResearchCanvas model={buildThesisFamilies(clusters, drifted)} nextOwed={{}} /></MemoryRouter>);
    expect(screen.queryByRole("button", { name: /Select source-bound claim/ })).toBeNull();
    expect(screen.getByTestId("research-canvas-evidence-state")).not.toHaveTextContent("No compatible test recorded");
  });

  it("makes no-match search explicit and transfers narrow-pane focus in both directions", () => {
    const originalWidth = window.innerWidth;
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 500 });
    try {
      renderCanvas(liquidModel());
      const search = screen.getByTestId("research-canvas-family-search");
      fireEvent.change(search, { target: { value: "no such thesis" } });
      expect(screen.getByRole("status")).toHaveTextContent("No matching thesis. Your selected thesis is retained.");
      const claim = screen.getAllByRole("button", { name: /Select source-bound claim/ })[1];
      fireEvent.click(claim);
      const back = screen.getByTestId("research-canvas-back");
      expect(back).toHaveFocus();
      fireEvent.click(back);
      expect(claim).toHaveFocus();
    } finally {
      Object.defineProperty(window, "innerWidth", { configurable: true, value: originalWidth });
      vi.restoreAllMocks();
    }
  });

  it("finds a grouped thesis through exact child identity and claim text", () => {
    const model = liquidModel();
    const other = buildThesisFamilies([{ cluster_id: "cl-first", stem: "Another thesis", members: [], status: "open", evidence_level: "L0" }], []);
    renderCanvas({ ...model, families: [...other.families, ...model.families] });
    const search = screen.getByTestId("research-canvas-family-search");
    const select = screen.getByTestId("research-canvas-family-select");
    fireEvent.change(select, { target: { value: other.families[0].id } });
    for (const query of [claims[0].id, "spectral gap"]) {
      fireEvent.change(search, { target: { value: query } });
      expect(within(select).getByRole("option", { name: /Liquid democracy/ })).toBeInTheDocument();
      expect(screen.getByRole("status")).not.toHaveTextContent("No matching thesis");
    }
  });

  it("drops an explicitly selected missing family rather than resurrecting it", () => {
    const model = liquidModel();
    const other = buildThesisFamilies([{ cluster_id: "cl-other", stem: "Other thesis", members: [], status: "open", evidence_level: "L0" }], []);
    const combined = { ...model, families: [...model.families, ...other.families] };
    const result = renderCanvas(combined);
    const select = screen.getByTestId("research-canvas-family-select");
    fireEvent.change(select, { target: { value: other.families[0].id } });
    expect(select).toHaveValue(other.families[0].id);
    result.rerender(<MemoryRouter><ResearchCanvas model={model} nextOwed={{}} /></MemoryRouter>);
    expect(select).toHaveValue(model.families[0].id);
    result.rerender(<MemoryRouter><ResearchCanvas model={combined} nextOwed={{}} /></MemoryRouter>);
    expect(select).toHaveValue(model.families[0].id);
  });

  it("retains selected claim identity when members of one record reorder", () => {
    const cluster = { cluster_id: "cl-many", stem: "Multiple exact entries", status: "open", evidence_level: "L0", members: ["iter-a", "iter-b"] };
    const iterations = ["a", "b"].map((letter) => ({ iteration_id: `iter-${letter}`, seed: { topic: "One topic" }, hypothesis: { text: `Hypothesis ${letter}` } }));
    const result = renderCanvas(buildThesisFamilies([cluster], iterations));
    const button = screen.getByRole("button", { name: /iteration iter-b:/ });
    fireEvent.click(button);
    result.rerender(<MemoryRouter><ResearchCanvas model={buildThesisFamilies([{ ...cluster, members: ["iter-b", "iter-a"] }], iterations)} nextOwed={{}} /></MemoryRouter>);
    expect(screen.getByRole("button", { name: /iteration iter-b:/ })).toBe(button);
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(within(screen.getByTestId("research-canvas-context")).getByRole("link", { name: /Open full dossier/ })).toHaveAttribute("href", "/dossier/iter-b");
  });

});
